"""Base entity: one device per tracked location."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, HOME_KEY
from .coordinator import RainLocationCoordinator


class RainRadarEntity(CoordinatorEntity[RainLocationCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: RainLocationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        loc = coordinator.key.replace("person.", "")
        self._attr_unique_id = f"{entry_id}_{loc}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{loc}")},
            name=f"Rain radar {coordinator.display_name}",
            manufacturer="Rain Radar Alarm",
            model="Home" if coordinator.key == HOME_KEY else "Person",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        return super().available and "status" in self.data

    @property
    def data(self) -> dict:
        return self.coordinator.data or {}

    @property
    def attribution(self) -> str | None:
        return self.data.get("attribution")
