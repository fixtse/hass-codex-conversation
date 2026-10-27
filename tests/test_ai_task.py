"""Tests for the AI Task entity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from homeassistant.components import ai_task as ai_task_component
from homeassistant.components.conversation import AssistantContent
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
import voluptuous as vol

from custom_components.codex_conversation.ai_task import (
    CodexAITaskEntity,
    _format_structure_instruction,
)
from custom_components.codex_conversation.codex_api import OutputTextDelta
from custom_components.codex_conversation.const import (
    DOMAIN,
    RECOMMENDED_AI_TASK_OPTIONS,
)

from .conftest import make_chat_log


async def test_ai_tasks_register_separate_entities_and_devices(
    hass, mock_config_entry, enable_custom_integrations
):
    """Task subentries must register without taking over the account device."""
    assert await async_setup_component(hass, "homeassistant", {})
    mock_config_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    account = devices.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, mock_config_entry.entry_id)},
        name="OpenAI Codex",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    tasks = [
        ConfigSubentry(
            subentry_type="ai_task_data",
            title=f"Codex Task {index}",
            data=RECOMMENDED_AI_TASK_OPTIONS.copy(),
            unique_id=None,
        )
        for index in range(2)
    ]
    for task in tasks:
        hass.config_entries.async_add_subentry(mock_config_entry, task)

    with patch("custom_components.codex_conversation.PLATFORMS", [Platform.AI_TASK]):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        device_ids = {account.id}
        entity_ids = []
        for task in tasks:
            entity_id = registry.async_get_entity_id(
                "ai_task", DOMAIN, task.subentry_id
            )
            assert entity_id is not None
            assert hass.states.get(entity_id) is not None
            entity = registry.async_get(entity_id)
            assert entity.config_subentry_id == task.subentry_id
            device = devices.async_get(entity.device_id)
            assert device.identifiers == {(DOMAIN, task.subentry_id)}
            assert device.entry_type == dr.DeviceEntryType.SERVICE
            device_ids.add(device.id)
            entity_ids.append(entity_id)
        assert len(device_ids) == 3
        assert devices.async_get(account.id).config_subentry_id is None

        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        for task, entity_id in zip(tasks, entity_ids, strict=True):
            assert (
                registry.async_get_entity_id("ai_task", DOMAIN, task.subentry_id)
                == entity_id
            )
            assert hass.states.get(entity_id) is not None
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)


@pytest.fixture
def mock_ai_task_entity(
    hass, mock_config_entry, mock_oauth_session, mock_ai_task_subentry: SimpleNamespace
) -> CodexAITaskEntity:
    """A CodexAITaskEntity wired to hass but not added to the entity registry."""
    entity = CodexAITaskEntity(
        hass, mock_config_entry, mock_oauth_session, mock_ai_task_subentry
    )
    entity.entity_id = f"ai_task.{DOMAIN}"
    entity.hass = hass
    return entity


async def test_generate_data_returns_text_result(mock_ai_task_entity):
    """The entity should return plain text when no structure is requested."""
    chat_log = make_chat_log(
        [
            AssistantContent(
                agent_id="ai_task.codex", content="Result text", tool_calls=None
            )
        ]
    )
    chat_log.conversation_id = "conv-1"
    task = MagicMock(spec=ai_task_component.GenDataTask)
    task.structure = None
    task.name = "summarize"

    async def fake_stream(request):
        yield OutputTextDelta(delta="Result text", content_index=0)

    with patch(
        "custom_components.codex_conversation.ai_task.CodexClient"
    ) as MockClient:
        MockClient.return_value.stream = fake_stream
        result = await mock_ai_task_entity._async_generate_data(task, chat_log)

    assert result.conversation_id == "conv-1"
    assert result.data == "Result text"


async def test_generate_data_parses_json_result(mock_ai_task_entity):
    """Structured tasks should parse the assistant text as JSON."""
    chat_log = make_chat_log(
        [
            AssistantContent(
                agent_id="ai_task.codex", content='{"answer":"ok"}', tool_calls=None
            )
        ]
    )
    chat_log.conversation_id = "conv-2"
    task = MagicMock(spec=ai_task_component.GenDataTask)
    task.structure = vol.Schema({vol.Required("answer"): str})
    task.name = "extract"

    async def fake_stream(request):
        yield OutputTextDelta(delta='{"answer":"ok"}', content_index=0)

    with patch(
        "custom_components.codex_conversation.ai_task.CodexClient"
    ) as MockClient:
        MockClient.return_value.stream = fake_stream
        result = await mock_ai_task_entity._async_generate_data(task, chat_log)

    assert result.conversation_id == "conv-2"
    assert result.data == {"answer": "ok"}


def test_format_structure_instruction():
    """The structured output helper should request JSON-only output."""
    task = MagicMock(spec=ai_task_component.GenDataTask)
    task.structure = vol.Schema({vol.Required("name"): str, vol.Optional("age"): int})

    instruction = _format_structure_instruction(task)

    assert "Return only valid JSON." in instruction
    assert "name" in instruction
    assert "age" in instruction


@pytest.mark.parametrize(
    "setting,enabled", [(None, True), (True, True), (False, False)]
)
async def test_ai_task_web_search_setting(mock_ai_task_entity, setting, enabled):
    from custom_components.codex_conversation.const import CONF_WEB_SEARCH

    if setting is not None:
        mock_ai_task_entity._subentry.data[CONF_WEB_SEARCH] = setting
    else:
        mock_ai_task_entity._subentry.data.pop(CONF_WEB_SEARCH, None)
    captured = []

    async def stream(request):
        captured.append(request.to_body())
        yield OutputTextDelta(delta="Result", content_index=0)

    task = MagicMock(spec=ai_task_component.GenDataTask)
    task.structure = None
    chat_log = make_chat_log(
        [AssistantContent(agent_id="ai_task.codex", content="Result", tool_calls=None)]
    )
    with patch("custom_components.codex_conversation.ai_task.CodexClient") as client:
        client.return_value.stream = stream
        await mock_ai_task_entity._async_generate_data(task, chat_log)
    assert (
        any(t["type"] == "web_search" for t in captured[0].get("tools", [])) is enabled
    )
