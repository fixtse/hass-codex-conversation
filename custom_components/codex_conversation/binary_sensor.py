"""Binary sensor platform for Codex Usage."""

# MIT License
#
# Copyright (c) 2026 Codex Usage contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry as CodexUsageConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .usage_coordinator import CodexUsageCoordinator
from .usage_entity import CodexUsageEntity
from .usage_models import CodexUsageData
from .usage_monitoring import restriction_summary


@dataclass(frozen=True, kw_only=True)
class CodexBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[CodexUsageData], bool | None]


def _limit_reached(data: CodexUsageData) -> bool | None:
    """Return an explicit limit state without inventing data when absent."""
    return restriction_summary(data).reached


BINARY_SENSORS: tuple[CodexBinarySensorDescription, ...] = (
    CodexBinarySensorDescription(
        key="limit_reached",
        translation_key="limit_reached",
        value_fn=_limit_reached,
    ),
    CodexBinarySensorDescription(
        key="credits_available",
        translation_key="credits_available",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.credits.has_credits if data.credits else None,
    ),
    CodexBinarySensorDescription(
        key="credits_unlimited",
        translation_key="credits_unlimited",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.credits.unlimited if data.credits else None,
    ),
    CodexBinarySensorDescription(
        key="credits_overage_limit_reached",
        translation_key="credits_overage_limit_reached",
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.credits.overage_limit_reached if data.credits else None
        ),
    ),
    CodexBinarySensorDescription(
        key="spend_limit_reached",
        translation_key="spend_limit_reached",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.spend_limit_reached,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CodexUsageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    await coordinator.async_initialize()
    async_add_entities(
        CodexUsageBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class CodexUsageBinarySensor(CodexUsageEntity, BinarySensorEntity):
    entity_description: CodexBinarySensorDescription

    def __init__(
        self,
        coordinator: CodexUsageCoordinator,
        entry: CodexUsageConfigEntry,
        description: CodexBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        identity = entry.entry_id
        self._attr_unique_id = f"{identity}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data.usage)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        if self.entity_description.key != "limit_reached":
            return None
        value = restriction_summary(self.coordinator.data.usage)
        attributes: dict[str, object] = {
            "reason": value.reason,
            "affected_limits": list(value.affected_limits),
            "affected_limits_truncated": value.affected_limits_truncated,
        }
        if value.fallback_limit_id:
            attributes["fallback_available"] = value.fallback_available
            attributes["fallback_limit_id"] = value.fallback_limit_id
        return attributes

    @property
    def available(self) -> bool:
        return super().available
