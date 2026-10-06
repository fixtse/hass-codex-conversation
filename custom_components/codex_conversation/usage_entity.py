"""Shared account device for usage sensors using the existing Codex login."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .usage_coordinator import CodexUsageCoordinator


class CodexUsageEntity(CoordinatorEntity[CodexUsageCoordinator]):
    """Base entity for account-wide Codex monitoring."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CodexUsageCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="OpenAI Codex",
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="OpenAI",
        )
