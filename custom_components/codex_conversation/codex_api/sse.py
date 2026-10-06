"""
SSE transport layer — low-level parsing of the Codex streaming response.

Mirrors the responsibilities of:
  codex-client/src/sse_stream.rs   → raw byte-stream → SSE frames
  codex-api/src/sse/responses.rs   → SSE frames → typed ResponseEvent objects
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import aiohttp

from .errors import (
    CodexApiError,
    CodexContextWindowExceeded,
    CodexError,
    CodexQuotaExceeded,
    CodexRateLimited,
    CodexServerOverloaded,
    CodexStreamError,
    CodexUsageNotIncluded,
)
from .models import (
    FunctionCallAdded,
    FunctionCallArgumentsDelta,
    FunctionCallArgumentsDone,
    OutputItemAdded,
    OutputItemDone,
    OutputTextDelta,
    RateLimits,
    ReasoningContentDelta,
    ReasoningSummaryDelta,
    ResponseCompleted,
    ResponseCreated,
    ResponseEvent,
)

_LOGGER = logging.getLogger(__name__)


# ── Error classification ───────────────────────────────────────────────────────


def _classify_error(code: str, message: str) -> CodexError:
    """Map an API error code string to the correct exception subclass."""
    lc = code.lower()
    if "context_length_exceeded" in lc or "context_window" in lc:
        return CodexContextWindowExceeded(message)
    if "quota" in lc or "insufficient_quota" in lc:
        return CodexQuotaExceeded(message)
    if "usage_not_included" in lc:
        return CodexUsageNotIncluded(message)
    if "rate_limit" in lc:
        return CodexRateLimited(message)
    if "server_error" in lc or "overloaded" in lc:
        return CodexServerOverloaded(message)
    return CodexApiError(0, f"{code}: {message}")


# ── Event parsing ──────────────────────────────────────────────────────────────


def parse_event(data_str: str) -> ResponseEvent | None:
    """
    Parse a single SSE ``data:`` payload into a typed ResponseEvent.

    Returns ``None`` for unknown / empty / ``[DONE]`` events so that the caller
    can simply skip them; raises a ``CodexError`` subclass for fatal or
    retryable server-side conditions.
    """
    if not data_str or data_str == "[DONE]":
        return None

    try:
        evt: dict[str, Any] = json.loads(data_str)
    except json.JSONDecodeError:
        _LOGGER.debug("codex_api.sse: unparseable data payload: %.120s", data_str)
        return None

    if not isinstance(evt, dict):
        return None
    etype: str = evt.get("type", "")

    # ── lifecycle events ───────────────────────────────────────────────────────

    if etype == "response.created":
        resp = evt.get("response") or {}
        return ResponseCreated(response_id=resp.get("id", ""))

    if etype in ("response.completed", "response.failed", "response.incomplete"):
        resp = evt.get("response") or {}
        if etype == "response.failed" or resp.get("status") == "failed":
            err = resp.get("error") or {}
            raise _classify_error(
                err.get("code", "unknown_error"),
                err.get("message", "Response failed"),
            )
        if etype == "response.incomplete" or resp.get("status") == "incomplete":
            details = resp.get("incomplete_details") or {}
            raise CodexStreamError(
                f"Incomplete response: {details.get('reason', 'unknown')}"
            )
        return ResponseCompleted(usage=resp.get("usage") or {})

    # ── output items ───────────────────────────────────────────────────────────

    if etype == "response.output_item.added":
        item = evt.get("item") or {}
        if item.get("type") == "function_call":
            return FunctionCallAdded(
                call_id=item.get("call_id", ""),
                name=item.get("name", ""),
                item_id=item.get("id", ""),
            )
        return OutputItemAdded(item=item)

    if etype == "response.output_item.done":
        return OutputItemDone(item=evt.get("item") or {})

    # ── function call arguments ────────────────────────────────────────────────

    if etype == "response.function_call_arguments.delta":
        return FunctionCallArgumentsDelta(
            delta=evt.get("delta", ""),
            item_id=evt.get("item_id", ""),
        )

    if etype == "response.function_call_arguments.done":
        return FunctionCallArgumentsDone(
            arguments=evt.get("arguments", ""),
            item_id=evt.get("item_id", ""),
        )

    # ── text streaming ─────────────────────────────────────────────────────────

    if etype == "response.output_text.delta":
        return OutputTextDelta(
            delta=evt.get("delta", ""),
            content_index=evt.get("content_index", 0),
        )

    # ── reasoning ─────────────────────────────────────────────────────────────

    if etype in (
        "response.reasoning.delta",
        "response.reasoning_content.delta",
        "response.reasoning_text.delta",
    ):
        raw_delta = evt.get("delta") or {}
        text = (
            raw_delta.get("text", "") if isinstance(raw_delta, dict) else str(raw_delta)
        )
        return ReasoningContentDelta(delta=text)

    if etype in (
        "response.reasoning_summary.delta",
        "response.reasoning_summary_text.delta",
    ):
        return ReasoningSummaryDelta(
            delta=evt.get("delta", ""),
            summary_index=evt.get("summary_index", 0),
        )

    # ── rate limits ────────────────────────────────────────────────────────────

    if etype == "response.rate_limits.updated":
        return RateLimits(data=evt.get("rate_limits") or [])

    # ── server-side errors ─────────────────────────────────────────────────────

    if etype in ("error", "response.error"):
        err = evt.get("error") or evt
        raise _classify_error(
            err.get("code", "unknown_error"),
            err.get("message", "Streaming error"),
        )

    # ── known lifecycle events (no payload we care about) ─────────────────────

    if etype in (
        "response.in_progress",
        "response.content_part.added",
        "response.content_part.done",
        "response.output_text.done",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
        "response.reasoning_summary_text.done",
    ):
        return None

    _LOGGER.debug("codex_api.sse: unknown event type %r", etype)
    return None


# ── Async SSE iterator ─────────────────────────────────────────────────────────


async def sse_iter(resp: aiohttp.ClientResponse) -> AsyncIterator[ResponseEvent]:
    """
    Iterate over an aiohttp streaming response and yield typed ResponseEvents.

    Mirrors ``sse_stream`` (codex-client) + ``process_sse`` (codex-api).
    Skips non-``data:`` lines and ``None`` parse results transparently.
    """
    data_lines: list[str] = []
    completed = False
    async for raw_line in resp.content:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("data:"):
            data_lines.append(line[5:].removeprefix(" "))
        elif not line and data_lines:
            event = parse_event("\n".join(data_lines))
            data_lines.clear()
            if event is not None:
                completed = completed or isinstance(event, ResponseCompleted)
                yield event
    if data_lines:
        event = parse_event("\n".join(data_lines))
        if event is not None:
            completed = completed or isinstance(event, ResponseCompleted)
            yield event
    if not completed:
        raise CodexStreamError("Stream ended before response.completed")
