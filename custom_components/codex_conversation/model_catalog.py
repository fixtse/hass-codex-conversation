"""Fetch the Codex models available to the authenticated ChatGPT account."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp

from .codex_api.version import CODEX_CLIENT_VERSION, CODEX_HEADERS

MODEL_CATALOG_ENDPOINT = "https://chatgpt.com/backend-api/codex/models"
MODEL_CATALOG_CLIENT_VERSION = CODEX_CLIENT_VERSION


class ModelCatalogError(Exception):
    """Raised when the Codex model catalog cannot be loaded or parsed."""


def parse_model_catalog(payload: Any) -> list[dict[str, str]]:
    """Return picker-visible models from a Codex model catalog response."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("models"), list):
        raise ModelCatalogError("The model catalog response has an invalid shape")

    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload["models"]:
        if not isinstance(item, Mapping) or item.get("visibility") != "list":
            continue

        slug = item.get("slug")
        if not isinstance(slug, str) or not slug or slug in seen:
            continue

        display_name = item.get("display_name")
        options.append(
            {
                "value": slug,
                "label": display_name
                if isinstance(display_name, str) and display_name
                else slug,
            }
        )
        seen.add(slug)

    if not options:
        raise ModelCatalogError("The model catalog contains no selectable models")

    return options


async def async_fetch_model_catalog(
    session: aiohttp.ClientSession,
    *,
    access_token: str,
    account_id: str = "",
    reasoning_levels: dict[str, list[str]] | None = None,
) -> list[dict[str, str]]:
    """Fetch picker-visible Codex models for an authenticated account."""
    headers = {
        **CODEX_HEADERS,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    response = await session.get(
        MODEL_CATALOG_ENDPOINT,
        params={"client_version": MODEL_CATALOG_CLIENT_VERSION},
        headers=headers,
    )
    try:
        response.raise_for_status()
        payload = await response.json()
        options = parse_model_catalog(payload)
        if reasoning_levels is not None:
            for item in payload["models"]:
                if not isinstance(item, Mapping) or not isinstance(
                    item.get("slug"), str
                ):
                    continue
                levels = item.get("supported_reasoning_levels")
                if isinstance(levels, list):
                    efforts = [
                        level["effort"]
                        for level in levels
                        if isinstance(level, Mapping)
                        and isinstance(level.get("effort"), str)
                    ]
                    if efforts:
                        reasoning_levels[item["slug"]] = efforts
        return options
    finally:
        response.release()
