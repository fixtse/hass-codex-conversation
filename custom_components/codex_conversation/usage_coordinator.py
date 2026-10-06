"""Independent usage polling that shares the conversation's OAuth session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, USAGE_UPDATE_INTERVAL
from .usage_budget import UsageBudget, collect_usage_budgets
from .usage_client import CodexUsageClient, UsageRequestError
from .usage_models import (
    CodexProfileStats,
    CodexUsageData,
    ResetCredits,
    parse_profile,
    parse_reset_credits,
    parse_usage,
)
from .usage_monitoring import (
    ResetSummary,
    SourceState,
    initial_sources,
    reset_context,
    reset_context_changed,
    reset_summary,
)

_LOGGER = logging.getLogger(__name__)
OPTIONAL_UPDATE_INTERVAL = 3600


@dataclass(frozen=True)
class CodexCoordinatorData:
    """Only normalized, non-sensitive account metrics are retained."""

    usage: CodexUsageData
    profile: CodexProfileStats | None = None
    reset_credits: ResetCredits | None = None
    refreshed_at: datetime | None = None
    reset_summary: ResetSummary | None = None
    budgets: dict[str, UsageBudget] = field(default_factory=dict)


class CodexUsageCoordinator(DataUpdateCoordinator[CodexCoordinatorData]):
    """Poll usage every five minutes and optional sources hourly."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, oauth: OAuth2Session):
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} usage",
            config_entry=entry,
            update_interval=timedelta(seconds=USAGE_UPDATE_INTERVAL),
        )
        self.client = CodexUsageClient(async_get_clientsession(hass), oauth)
        self.sources = initial_sources()
        self._next_attempt = dict.fromkeys(self.sources, 0.0)
        self._global_retry_at = 0.0
        self._initialize_lock = asyncio.Lock()
        self._initialized = False
        self._reset_context: tuple | None = None
        self._reset_context_changed_at: datetime | None = None
        # An unavailable usage service must not prevent the conversation loading.
        self.data = CodexCoordinatorData(usage=parse_usage({}))

    @property
    def last_success(self) -> datetime | None:
        return self.sources["usage"].last_success

    async def async_initialize(self) -> None:
        """Share the first refresh between concurrently loaded platforms."""
        async with self._initialize_lock:
            if not self._initialized:
                await self.async_refresh()
                self._initialized = True

    async def _async_fetch_source(self, source: str) -> dict:
        now = datetime.now(UTC)
        previous = self.sources[source]
        try:
            payload = await self.client.async_fetch(source)
            required = {
                "usage": {
                    "plan_type",
                    "rate_limit",
                    "credits",
                    "spend_control",
                    "additional_rate_limits",
                },
                "profile": {"stats"},
                "reset_details": {"available_count", "credits"},
                "workspace_discovery": {"accounts"},
            }[source]
            if not required.intersection(payload):
                raise UsageRequestError("invalid_response")
        except UsageRequestError as err:
            optional = source != "usage"
            unsupported = optional and err.status in (403, 404, 405)
            delay = err.retry_after or (
                OPTIONAL_UPDATE_INTERVAL if optional else USAGE_UPDATE_INTERVAL
            )
            self._next_attempt[source] = monotonic() + delay
            if err.retry_after is not None:
                self._global_retry_at = max(self._global_retry_at, monotonic() + delay)
            self.sources[source] = replace(
                previous,
                state="unsupported" if unsupported else "error",
                last_attempt=now,
                retry_at=now + timedelta(seconds=delay),
                error_code=err.code,
            )
            raise
        except HomeAssistantError as err:
            # Token refresh failures are isolated from otherwise usable conversation setup.
            self._next_attempt[source] = monotonic() + USAGE_UPDATE_INTERVAL
            self.sources[source] = replace(
                previous, state="error", last_attempt=now, error_code="authentication"
            )
            raise UsageRequestError("authentication") from err
        self.sources[source] = SourceState(
            "ok",
            now,
            now,
            refresh_mode="on_auth" if source == "workspace_discovery" else "poll",
            expected_interval_seconds=USAGE_UPDATE_INTERVAL
            if source == "usage"
            else OPTIONAL_UPDATE_INTERVAL,
        )
        self._next_attempt[source] = monotonic() + (
            USAGE_UPDATE_INTERVAL if source == "usage" else OPTIONAL_UPDATE_INTERVAL
        )
        return payload

    async def _async_update_data(self) -> CodexCoordinatorData:
        retry_at = max(self._global_retry_at, self._next_attempt["usage"])
        if self.sources["usage"].state == "ok":
            retry_at = self._global_retry_at
        if monotonic() < retry_at:
            raise UpdateFailed(
                "Codex usage polling is cooling down",
                retry_after=retry_at - monotonic(),
            )
        try:
            usage = parse_usage(await self._async_fetch_source("usage"))
        except UsageRequestError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        now = self.last_success
        assert now is not None
        profile = self.data.profile
        resets = self.data.reset_credits
        current_context = reset_context(usage)
        if self._reset_context is not None and reset_context_changed(
            self._reset_context, current_context
        ):
            self._reset_context_changed_at = now
            if self.sources["reset_details"].state == "ok":
                self._next_attempt["reset_details"] = 0
        self._reset_context = current_context

        for source in ("profile", "reset_details", "workspace_discovery"):
            if source == "workspace_discovery" and self.sources[source].last_success:
                continue
            if monotonic() < max(self._global_retry_at, self._next_attempt[source]):
                continue
            try:
                payload = await self._async_fetch_source(source)
            except UsageRequestError:
                continue  # Keep successful main data and previous optional values.
            if source == "profile":
                profile = parse_profile(payload)
            elif source == "reset_details":
                resets = parse_reset_credits(payload)

        return CodexCoordinatorData(
            usage=usage,
            profile=profile,
            reset_credits=resets,
            refreshed_at=now,
            reset_summary=reset_summary(
                usage,
                resets,
                now=now,
                usage_updated_at=now,
                details_updated_at=self.sources["reset_details"].last_success,
                context_changed_at=self._reset_context_changed_at,
            ),
            budgets=collect_usage_budgets(
                usage,
                now=now,
                last_success=now,
                update_interval_seconds=USAGE_UPDATE_INTERVAL,
                core_available=True,
            ),
        )
