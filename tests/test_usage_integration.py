"""Verify shared authentication, source isolation and native sensor discovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component
import pytest

from custom_components.codex_conversation import binary_sensor, sensor
from custom_components.codex_conversation.const import DOMAIN
from custom_components.codex_conversation.usage_client import (
    USAGE_ENDPOINTS,
    CodexUsageClient,
    UsageRequestError,
    retry_delay,
)
from custom_components.codex_conversation.usage_coordinator import CodexUsageCoordinator
from custom_components.codex_conversation.usage_diagnostic_sensor import (
    source_timestamp_entities,
)
from custom_components.codex_conversation.usage_models import parse_usage


def usage_payload(*, additional=False):
    now = datetime.now(UTC).timestamp()
    result = {
        "plan_type": "plus",
        "rate_limit": {
            "allowed": True,
            "limit_reached": False,
            "primary_window": {
                "used_percent": 25,
                "limit_window_seconds": 18000,
                "reset_at": now + 7200,
            },
            "secondary_window": {
                "used_percent": 50,
                "limit_window_seconds": 604800,
                "reset_at": now + 86400,
            },
        },
        "rate_limit_reset_credits": {"available_count": 0},
        "credits": {"balance": "0", "has_credits": False, "unlimited": False},
        "spend_control": {
            "reached": False,
            "individual_limit": {
                "used": 10,
                "limit": 100,
                "remaining": 90,
                "used_percent": 10,
                "reset_at": now + 86400,
            },
        },
    }
    if additional:
        result["additional_rate_limits"] = [
            {
                "metered_feature": "code_review",
                "limit_name": "Code review",
                "rate_limit": {
                    "allowed": True,
                    "limit_reached": False,
                    "primary_window": {
                        "used_percent": 5,
                        "limit_window_seconds": 604800,
                        "reset_at": now + 86400,
                    },
                },
            }
        ]
    return result


def fake_sources(payload=None):
    values = {
        "usage": payload or usage_payload(),
        "profile": {"stats": {"lifetime_tokens": 1000, "current_streak_days": 2}},
        "reset_details": {"available_count": 2, "credits": []},
        "workspace_discovery": {
            "accounts": {"private-account-id": {"email": "private@example.test"}}
        },
    }

    async def fetch(source):
        return values[source]

    return AsyncMock(side_effect=fetch)


async def test_usage_http_reuses_refreshed_oauth_and_account(mock_oauth_session):
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value=usage_payload())
    session = MagicMock()
    session.request = AsyncMock(return_value=response)
    client = CodexUsageClient(session, mock_oauth_session)
    await client.async_fetch("usage")
    args = session.request.call_args
    assert args.args == ("get", USAGE_ENDPOINTS["usage"])
    assert args.kwargs["headers"]["Authorization"] == "Bearer test_access_token"
    assert args.kwargs["headers"]["ChatGPT-Account-Id"] == "test_account_id"
    assert args.kwargs["timeout"].total == 20
    assert args.kwargs["allow_redirects"] is False
    mock_oauth_session.async_ensure_token_valid.assert_awaited_once()
    assert all(
        auth._oauth_session is mock_oauth_session for auth in client._auth.values()
    )
    response.release.assert_called_once()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "authentication"),
        (404, "http_error"),
        (429, "rate_limited"),
        (503, "http_error"),
    ],
)
async def test_http_errors_are_safe_and_release_response(
    mock_oauth_session, status, code
):
    response = MagicMock(status=status, headers={"Retry-After": "1200"})
    response.text = AsyncMock(return_value="private-token private-account-id")
    session = MagicMock(request=AsyncMock(return_value=response))
    with pytest.raises(UsageRequestError) as error:
        await CodexUsageClient(session, mock_oauth_session).async_fetch("usage")
    assert error.value.code == code
    assert "private" not in str(error.value)
    if status in (429, 503):
        assert error.value.retry_after == 1200
    response.text.assert_not_awaited()
    response.release.assert_called_once()


def test_retry_after_handles_dates_and_invalid_values():
    future = datetime.now(UTC) + timedelta(hours=1)
    assert 3590 < retry_delay(format_datetime(future)) <= 3600
    assert retry_delay("0") == 60
    assert retry_delay("invalid") == 300
    assert retry_delay("nan") == 300


async def test_coordinator_fetches_once_and_optional_sources_hourly(
    hass, mock_config_entry, mock_oauth_session
):
    coordinator = CodexUsageCoordinator(hass, mock_config_entry, mock_oauth_session)
    coordinator.client.async_fetch = fake_sources()
    await asyncio.gather(coordinator.async_initialize(), coordinator.async_initialize())
    assert coordinator.client.async_fetch.await_count == 4
    assert coordinator.data.profile.lifetime_tokens == 1000
    assert (
        coordinator.data.reset_summary.available_count == 0
    )  # Main zero beats stale/details count.
    assert coordinator.data.budgets["five_hour"].budget_pph == pytest.approx(
        37.5, rel=0.01
    )
    await coordinator.async_refresh()
    assert coordinator.client.async_fetch.await_count == 5
    assert coordinator.sources["workspace_discovery"].last_success is not None
    assert "private-account-id" not in repr(coordinator.data)
    await coordinator.async_shutdown()


async def test_optional_failures_do_not_break_usage_or_discard_profile(
    hass, mock_config_entry, mock_oauth_session
):
    coordinator = CodexUsageCoordinator(hass, mock_config_entry, mock_oauth_session)
    coordinator.client.async_fetch = fake_sources()
    await coordinator.async_initialize()
    previous_profile = coordinator.data.profile
    coordinator._next_attempt["profile"] = 0
    coordinator._next_attempt["reset_details"] = 0

    async def failing_optional(source):
        if source != "usage":
            raise UsageRequestError("authentication", status=403)
        return usage_payload()

    coordinator.client.async_fetch = AsyncMock(side_effect=failing_optional)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.profile == previous_profile
    assert coordinator.sources["profile"].state == "unsupported"
    assert coordinator.sources["reset_details"].state == "unsupported"
    assert coordinator.data.usage.five_hour_window.used_percent == 25
    await coordinator.async_shutdown()


async def test_provider_cooldown_applies_to_manual_refresh(
    hass, mock_config_entry, mock_oauth_session
):
    coordinator = CodexUsageCoordinator(hass, mock_config_entry, mock_oauth_session)
    coordinator.client.async_fetch = AsyncMock(
        side_effect=UsageRequestError("rate_limited", status=429, retry_after=1200)
    )
    await coordinator.async_initialize()
    assert not coordinator.last_update_success
    await coordinator.async_refresh()
    assert coordinator.client.async_fetch.await_count == 1
    with pytest.raises(UpdateFailed, match="cooling down"):
        await coordinator._async_update_data()
    assert coordinator.sources["usage"].error_code == "rate_limited"
    await coordinator.async_shutdown()


async def test_platforms_discover_late_windows_and_preserve_dynamic_identity(
    hass, mock_config_entry, mock_oauth_session
):
    mock_config_entry.add_to_hass(hass)
    coordinator = mock_config_entry.runtime_data = CodexUsageCoordinator(
        hass, mock_config_entry, mock_oauth_session
    )
    coordinator.client.async_fetch = AsyncMock(
        side_effect=UsageRequestError("connection")
    )
    entities = []
    binary_entities = []
    await sensor.async_setup_entry(
        hass, mock_config_entry, lambda values: entities.extend(values)
    )
    await binary_sensor.async_setup_entry(
        hass, mock_config_entry, lambda values: binary_entities.extend(values)
    )
    assert coordinator.client.async_fetch.await_count == 1
    assert len(binary_entities) == 5
    assert not binary_entities[0].available
    assert any(item.entity_description.key == "lifetime_tokens" for item in entities)
    assert not any(item.unique_id.endswith("five_hour_usage") for item in entities)
    coordinator._next_attempt["usage"] = 0
    coordinator.client.async_fetch = fake_sources(usage_payload(additional=True))
    await coordinator.async_refresh()
    values = {item.unique_id: item for item in entities}
    assert values[f"{mock_config_entry.entry_id}_five_hour_usage"].native_value == 25
    assert values[f"{mock_config_entry.entry_id}_weekly_remaining"].native_value == 50
    assert values[f"{mock_config_entry.entry_id}_spend_used"].native_value == 10
    assert values[f"{mock_config_entry.entry_id}_credit_balance"].native_value == 0
    assert values[f"{mock_config_entry.entry_id}_lifetime_tokens"].native_value == 1000
    dynamic = values[f"{mock_config_entry.entry_id}_code_review_primary_usage"]
    assert dynamic.native_value == 5
    assert dynamic.extra_state_attributes["allowed"] is True
    assert binary_entities[0].is_on is False
    count = len(entities)
    await coordinator.async_refresh()
    assert len(entities) == count
    coordinator.client.async_fetch = fake_sources(usage_payload())
    await coordinator.async_refresh()
    assert dynamic.native_value is None
    assert dynamic.unique_id in values
    coordinator.last_update_success = False
    assert not dynamic.available
    assert values[f"{mock_config_entry.entry_id}_lifetime_tokens"].available
    assert all(
        item.available
        for item in source_timestamp_entities(coordinator, mock_config_entry)
    )
    await coordinator.async_shutdown()


async def test_network_error_is_safe(mock_oauth_session):
    session = MagicMock(
        request=AsyncMock(side_effect=aiohttp.ClientError("private details"))
    )
    with pytest.raises(UsageRequestError, match="connection"):
        await CodexUsageClient(session, mock_oauth_session).async_fetch("usage")


def test_no_plan_matrix_infers_absent_windows():
    data = parse_usage({"plan_type": "pro", "rate_limit": {"allowed": True}})
    assert data.five_hour_window is None
    assert data.weekly_window is None


async def test_home_assistant_registers_and_unloads_native_sensors(
    hass, mock_config_entry, enable_custom_integrations
):
    """Exercise real platform loading and registry/state handling with mocked HTTP."""
    assert await async_setup_component(hass, "homeassistant", {})
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.codex_conversation.usage_client.CodexUsageClient.async_fetch",
        fake_sources(usage_payload(additional=True)),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        usage_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{mock_config_entry.entry_id}_five_hour_usage"
        )
        assert usage_id is not None
        assert hass.states.get(usage_id).state == "25.0"
        assert hass.states.get(usage_id).attributes["unit_of_measurement"] == "%"
        limit_id = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{mock_config_entry.entry_id}_limit_reached"
        )
        assert hass.states.get(limit_id).state == "off"
        profile_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{mock_config_entry.entry_id}_lifetime_tokens"
        )
        assert registry.async_get(profile_id).disabled
        coordinator = mock_config_entry.runtime_data
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert coordinator._shutdown_requested
        assert hass.states.get(usage_id).state == "unavailable"
