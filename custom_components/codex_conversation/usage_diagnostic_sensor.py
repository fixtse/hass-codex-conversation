"""Diagnostic timestamp sensors for independently refreshed sources."""

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

from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry as CodexUsageConfigEntry
from homeassistant.helpers.entity import EntityCategory

from .usage_coordinator import CodexUsageCoordinator
from .usage_entity import CodexUsageEntity


@dataclass(frozen=True, kw_only=True)
class CodexSourceTimestampDescription(SensorEntityDescription):
    """Describe the last successful response for one data source."""

    source: str


SOURCE_TIMESTAMP_SENSORS: tuple[CodexSourceTimestampDescription, ...] = tuple(
    CodexSourceTimestampDescription(
        key=f"{source}_last_success",
        translation_key=f"{source}_last_success",
        source=source,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )
    for source in ("usage", "profile", "reset_details", "workspace_discovery")
)


def source_timestamp_entities(
    coordinator: CodexUsageCoordinator, entry: CodexUsageConfigEntry
) -> list[CodexSourceTimestampSensor]:
    """Create the four fixed diagnostic source timestamps."""
    return [
        CodexSourceTimestampSensor(coordinator, entry, item)
        for item in SOURCE_TIMESTAMP_SENSORS
    ]


class CodexSourceTimestampSensor(CodexUsageEntity, SensorEntity):
    """Expose a source timestamp even while the core coordinator is unavailable."""

    entity_description: CodexSourceTimestampDescription

    def __init__(
        self,
        coordinator: CodexUsageCoordinator,
        entry: CodexUsageConfigEntry,
        description: CodexSourceTimestampDescription,
    ) -> None:
        super().__init__(coordinator, entry)
        self.entity_description = description
        identity = entry.entry_id
        self._attr_unique_id = f"{identity}_{description.key}"

    @property
    def native_value(self) -> datetime | None:
        source = getattr(self.coordinator, "sources", {}).get(
            self.entity_description.source
        )
        return source.last_success if source is not None else None

    @property
    def available(self) -> bool:
        return True
