"""Read-only Codex account endpoints backed by Home Assistant OAuth."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
import math
from typing import Any

import aiohttp
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .oauth import CodexHAAuth

USAGE_ENDPOINTS = {
    "usage": "https://chatgpt.com/backend-api/wham/usage",
    "profile": "https://chatgpt.com/backend-api/wham/profiles/me",
    "reset_details": "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits",
    "workspace_discovery": "https://chatgpt.com/backend-api/wham/accounts/check",
}


class UsageRequestError(Exception):
    """A safe error code without credentials or backend response bodies."""

    def __init__(
        self, code: str, *, status: int = 0, retry_after: float | None = None
    ) -> None:
        self.code = code
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"Codex usage source: {code} (HTTP {status})")


def retry_delay(value: str | None) -> float:
    """Honor either Retry-After form, with a one-minute minimum cooldown."""
    if value:
        try:
            seconds = float(value)
            if math.isfinite(seconds):
                return max(60, seconds)
        except ValueError:
            try:
                deadline = parsedate_to_datetime(value)
                if deadline.tzinfo is not None:
                    return max(60, (deadline - datetime.now(UTC)).total_seconds())
            except ValueError, TypeError, OverflowError:
                pass
    return 300


class CodexUsageClient:
    """Reuse the integration's single OAuth2Session for every source."""

    def __init__(self, session: aiohttp.ClientSession, oauth_session: OAuth2Session):
        self._auth = {
            source: CodexHAAuth(session, oauth_session, endpoint=url)
            for source, url in USAGE_ENDPOINTS.items()
        }

    async def async_fetch(self, source: str) -> dict[str, Any]:
        """Fetch account data without redirects or unbounded HTTP waits."""
        try:
            response = await self._auth[source].request(
                "get",
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=False,
            )
            try:
                if response.status in (429, 503):
                    raise UsageRequestError(
                        "rate_limited" if response.status == 429 else "http_error",
                        status=response.status,
                        retry_after=retry_delay(response.headers.get("Retry-After")),
                    )
                if response.status in (401, 403):
                    raise UsageRequestError("authentication", status=response.status)
                if response.status < 200 or response.status >= 300:
                    raise UsageRequestError("http_error", status=response.status)
                payload = await response.json()
                if not isinstance(payload, dict):
                    raise UsageRequestError("invalid_response")
                return payload
            finally:
                response.release()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UsageRequestError("connection") from err
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise UsageRequestError("invalid_response") from err
