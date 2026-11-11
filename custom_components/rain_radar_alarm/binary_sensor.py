"""Binary sensors per location: raining now, rain soon."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RainRadarConfigEntry, option
from .const import CONF_SOON_MINUTES
from .entity import RainRadarEntity


async def async_setup_entry(hass: HomeAssistant, entry: RainRadarConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    soon = int(option(entry, CONF_SOON_MINUTES))
    entities: list[BinarySensorEntity] = []
    for coord in entry.runtime_data.coordinators.values():
        entities += [Raining(coord), RainSoon(coord, soon)]
    async_add_entities(entities)


class Raining(RainRadarEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "raining")

    @property
    def is_on(self) -> bool | None:
        return bool(self.data.get("raining_now")) if self.data else None


class RainSoon(RainRadarEntity, BinarySensorEntity):
    def __init__(self, coordinator, minutes: int) -> None:
        super().__init__(coordinator, "rain_soon")
        self._minutes = minutes

    @property
    def is_on(self) -> bool | None:
        if not self.data:
            return None
        m = self.data.get("minutes_until_rain")
        return bool(self.data.get("raining_now")) or (m is not None and m <= self._minutes)

    @property
    def extra_state_attributes(self):
        return {"within_minutes": self._minutes}
