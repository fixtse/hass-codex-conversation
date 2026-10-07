"""Regression tests for the Codex 0.160.1 HTTP and streaming protocol."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.codex_conversation.codex_api import (
    CodexApiError,
    CodexAuth,
    CodexClient,
    CodexQuotaExceeded,
    CodexRequest,
    CodexStreamError,
    OutputTextDelta,
    ReasoningContentDelta,
    ResponseCompleted,
)
from custom_components.codex_conversation.codex_api.sse import parse_event, sse_iter
from custom_components.codex_conversation.codex_api.version import CODEX_HEADERS


@pytest.mark.parametrize(
    "model", ["gpt-5.3-codex", "gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "o3"]
)
def test_reasoning_parameters_for_current_models(model):
    body = CodexRequest(model=model, input=[], reasoning_effort="high").to_body()
    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert body["text"] == {"verbosity": "medium"}
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["store"] is False
    assert body["stream"] is True


def test_non_reasoning_model_omits_reasoning():
    body = CodexRequest(model="gpt-4.1", input=[]).to_body()
    assert "reasoning" not in body
    assert "include" not in body


@pytest.mark.parametrize(
    "summary,expected",
    [("short", "concise"), ("concise", "concise"), ("off", None), ("none", None)],
)
def test_summary_wire_values_and_legacy_settings(summary, expected):
    reasoning = CodexRequest(
        model="gpt-6.1-sol", input=[], reasoning_summary=summary
    ).to_body()["reasoning"]
    assert reasoning.get("summary") == expected
    if expected is None:
        assert "summary" not in reasoning


@pytest.mark.parametrize("account_id", ["account-123", ""])
async def test_authenticated_response_uses_chatgpt_account_routing(account_id):
    session = MagicMock()
    session.request = AsyncMock()
    auth = CodexAuth(
        session, "https://example.test/responses", "test-token", account_id
    )
    await auth.request(
        "post", headers={"Accept": "text/event-stream"}, json={"model": "gpt-6.1-sol"}
    )
    headers = session.request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["originator"] == CODEX_HEADERS["originator"]
    assert headers["User-Agent"] == CODEX_HEADERS["User-Agent"]
    assert headers["Accept"] == "text/event-stream"
    assert "openai-organization" not in headers
    assert headers.get("ChatGPT-Account-Id") == (account_id or None)


@pytest.mark.parametrize("event_type", ["response.failed", "response.completed"])
def test_failed_response_raises_error(event_type):
    with pytest.raises(CodexQuotaExceeded, match="quota exhausted"):
        parse_event(
            json.dumps(
                {
                    "type": event_type,
                    "response": {
                        "status": "failed",
                        "error": {
                            "code": "insufficient_quota",
                            "message": "quota exhausted",
                        },
                    },
                }
            )
        )


def test_incomplete_response_raises_error():
    with pytest.raises(CodexStreamError, match="max_output_tokens"):
        parse_event(
            json.dumps(
                {
                    "type": "response.incomplete",
                    "response": {"incomplete_details": {"reason": "max_output_tokens"}},
                }
            )
        )


def test_top_level_error_preserves_details():
    with pytest.raises(CodexApiError, match="invalid_request: bad model"):
        parse_event(
            json.dumps(
                {"type": "error", "code": "invalid_request", "message": "bad model"}
            )
        )


def test_current_reasoning_text_event():
    assert parse_event(
        '{"type":"response.reasoning_text.delta","delta":"thinking"}'
    ) == ReasoningContentDelta(delta="thinking")


async def _lines(*lines):
    for line in lines:
        yield line.encode()


async def test_stream_handles_multiline_frames_and_crlf():
    response = SimpleNamespace(
        content=_lines(
            ": heartbeat\r\n",
            "\r\n",
            "event: response.output_text.delta\r\n",
            'data: {"type":"response.output_text.delta",\r\n',
            'data: "delta":"Hello"}\r\n',
            "\r\n",
            'data: {"type":"response.completed","response":{"usage":{"output_tokens":1}}}\r\n',
            "\r\n",
        )
    )
    events = [event async for event in sse_iter(response)]
    assert events == [
        OutputTextDelta(delta="Hello"),
        ResponseCompleted(usage={"output_tokens": 1}),
    ]


async def test_truncated_stream_is_not_successful_and_releases_connection():
    response = MagicMock(status=200)
    response.content = _lines(
        'data: {"type":"response.output_text.delta","delta":"partial"}\n', "\n"
    )
    auth = MagicMock()
    auth.request = AsyncMock(return_value=response)
    client = CodexClient(auth)
    with pytest.raises(CodexStreamError, match="before response.completed"):
        _ = [
            event
            async for event in client.stream(
                CodexRequest(model="gpt-6.1-sol", input=[])
            )
        ]
    response.release.assert_called_once_with()


async def test_completion_without_final_frame_separator():
    response = SimpleNamespace(
        content=_lines('data: {"type":"response.completed","response":{}}\n')
    )
    assert [event async for event in sse_iter(response)] == [ResponseCompleted()]


def test_web_search_is_live_and_preserves_home_assistant_tools():
    """Hosted search must coexist with function tools without mutating inputs."""
    tools = [{"type": "function", "name": "get_time", "parameters": {}}]
    request = CodexRequest(model="gpt-6-luna", input=[], tools=tools, web_search=True)
    expected = [*tools, {"type": "web_search", "external_web_access": True}]
    assert request.to_body()["tools"] == expected
    assert request.to_body()["tools"] == expected
    assert len(tools) == 1


def test_disabling_web_search_omits_only_the_hosted_tool():
    tools = [{"type": "function", "name": "get_time", "parameters": {}}]
    body = CodexRequest(
        model="gpt-6-luna", input=[], tools=tools, web_search=False
    ).to_body()
    assert body["tools"] == tools
    assert (
        "tools"
        not in CodexRequest(model="gpt-6-luna", input=[], web_search=False).to_body()
    )
