"""
Request model for the Codex Responses API.

Mirrors ``ResponsesApiRequest`` from codex-api/src/endpoint/responses.rs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass
class CodexRequest:
    """
    Typed request for the Codex ``/responses`` endpoint.

    ``input`` is a list of message dicts in the OpenAI Responses API format::

        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "..."}]}
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "..."}]}

    ``instructions`` maps to the top-level field of the same name (system prompt).

    Reasoning parameters (``reasoning``, ``text``, ``include``) are only
    included in the serialised body for models that support them
    (GPT-5 and later / ``o*`` series).
    """

    model: str
    input: list[dict[str, Any]]
    instructions: str = ""
    store: bool = False
    reasoning_effort: str = "medium"
    reasoning_summary: str = "auto"
    text_verbosity: str = "medium"
    tools: list[dict[str, Any]] = field(default_factory=list)
    web_search: bool = False

    def _is_reasoning_model(self) -> bool:
        match = re.match(r"gpt-(\d+)(?:[.\-]|$)", self.model)
        return (
            match is not None and int(match.group(1)) >= 5
        ) or self.model.startswith(("o1", "o3", "o4", "gpt-daybreak-"))

    def to_body(self) -> dict[str, Any]:
        """Serialise to the JSON body expected by the Codex endpoint."""
        body: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "store": self.store,
            "input": self.input,
        }
        if self.instructions:
            body["instructions"] = self.instructions
        tools = list(self.tools)
        if self.web_search:
            tools.append({"type": "web_search", "external_web_access": True})
        if tools:
            body["tools"] = tools
        if self._is_reasoning_model():
            body["reasoning"] = {"effort": self.reasoning_effort}
            # Keep existing subentry settings compatible with the current wire API.
            summary = {"short": "concise", "off": "none"}.get(
                self.reasoning_summary, self.reasoning_summary
            )
            if summary != "none":
                body["reasoning"]["summary"] = summary
            body["text"] = {"verbosity": self.text_verbosity}
            body["include"] = ["reasoning.encrypted_content"]
        return body
