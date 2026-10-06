"""Tests for account-scoped Codex model discovery."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.codex_conversation.codex_api.version import CODEX_HEADERS
from custom_components.codex_conversation.model_catalog import (
    MODEL_CATALOG_CLIENT_VERSION,
    MODEL_CATALOG_ENDPOINT,
    ModelCatalogError,
    async_fetch_model_catalog,
    parse_model_catalog,
)


def test_parse_model_catalog_returns_picker_visible_models() -> None:
    """Only unique picker-visible models should become selector options."""
    payload = {
        "models": [
            {
                "slug": "gpt-new",
                "display_name": "GPT New",
                "visibility": "list",
            },
            {
                "slug": "gpt-hidden",
                "display_name": "Hidden",
                "visibility": "hide",
            },
            {"slug": "gpt-fallback-label", "visibility": "list"},
            {
                "slug": "gpt-new",
                "display_name": "Duplicate",
                "visibility": "list",
            },
            {"display_name": "Missing slug", "visibility": "list"},
        ]
    }

    assert parse_model_catalog(payload) == [
        {"value": "gpt-new", "label": "GPT New"},
        {"value": "gpt-fallback-label", "label": "gpt-fallback-label"},
    ]


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"models": {}}, {"models": []}, {"models": [{"visibility": "hide"}]}],
)
def test_parse_model_catalog_rejects_unusable_responses(payload) -> None:
    """Malformed or empty catalogs should produce a recoverable flow error."""
    with pytest.raises(ModelCatalogError):
        parse_model_catalog(payload)


async def test_fetch_model_catalog_uses_account_credentials() -> None:
    """Discovery should call the Codex endpoint with the authenticated account."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(
        return_value={
            "models": [
                {
                    "slug": "gpt-account-model",
                    "display_name": "Account Model",
                    "visibility": "list",
                }
            ]
        }
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=response)

    result = await async_fetch_model_catalog(
        session,
        access_token="access-token",
        account_id="account-id",
    )

    assert result == [{"value": "gpt-account-model", "label": "Account Model"}]
    session.get.assert_awaited_once_with(
        MODEL_CATALOG_ENDPOINT,
        params={"client_version": MODEL_CATALOG_CLIENT_VERSION},
        headers={
            "Authorization": "Bearer access-token",
            "Accept": "application/json",
            **CODEX_HEADERS,
            "ChatGPT-Account-Id": "account-id",
        },
    )
    response.raise_for_status.assert_called_once_with()


async def test_fetch_model_catalog_releases_invalid_response() -> None:
    """A malformed catalog must not leak the HTTP connection."""
    response = MagicMock()
    response.json = AsyncMock(return_value={"models": []})
    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    with pytest.raises(ModelCatalogError):
        await async_fetch_model_catalog(session, access_token="token")
    response.release.assert_called_once_with()


async def test_catalog_exposes_model_specific_reasoning_levels() -> None:
    response = MagicMock()
    response.json = AsyncMock(
        return_value={
            "models": [
                {
                    "slug": "gpt-6-luna",
                    "visibility": "list",
                    "supported_reasoning_levels": [
                        {"effort": "low"},
                        {"effort": "medium"},
                        {"effort": "max"},
                        {},
                        None,
                    ],
                },
            ]
        }
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    levels = {}
    await async_fetch_model_catalog(
        session, access_token="token", reasoning_levels=levels
    )
    assert levels == {"gpt-6-luna": ["low", "medium", "max"]}
