"""Sensors per location: status, timings, intensity, and where the data came from."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime, UnitOfVolumetricFlux
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RainRadarConfigEntry
from .const import CATEGORIES, SOURCES, STATUSES
from .entity import RainRadarEntity


@dataclass(frozen=True, kw_only=True)
class RainSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any]


def _intensity(d: dict) -> str:
    part = d.get("peak") if d.get("status") == "rain_expected" else d.get("current")
    return (part or {}).get("category", "none")


SENSORS: tuple[RainSensorDescription, ...] = (
    RainSensorDescription(key="status", device_class=SensorDeviceClass.ENUM, options=STATUSES,
                          value_fn=lambda d: d.get("status")),
    RainSensorDescription(key="minutes_until_rain", native_unit_of_measurement=UnitOfTime.MINUTES,
                          value_fn=lambda d: d.get("minutes_until_rain")),
    RainSensorDescription(key="minutes_until_clear", native_unit_of_measurement=UnitOfTime.MINUTES,
                          value_fn=lambda d: d.get("minutes_until_clear")),
    RainSensorDescription(key="rain_start", device_class=SensorDeviceClass.TIMESTAMP,
                          value_fn=lambda d: d.get("rain_start_time")),
    RainSensorDescription(key="rain_clear", device_class=SensorDeviceClass.TIMESTAMP,
                          value_fn=lambda d: d.get("rain_clear_time")),
    RainSensorDescription(key="rain_rate", device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
                          native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
                          state_class=SensorStateClass.MEASUREMENT,
                          value_fn=lambda d: (d.get("current") or {}).get("rate")),
    RainSensorDescription(key="peak_rain_rate", device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
                          native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
                          value_fn=lambda d: (d.get("peak") or {}).get("rate", 0.0)),
    RainSensorDescription(key="intensity", device_class=SensorDeviceClass.ENUM, options=CATEGORIES,
                          value_fn=_intensity),
    RainSensorDescription(key="data_source", device_class=SensorDeviceClass.ENUM, options=SOURCES,
                          entity_category=EntityCategory.DIAGNOSTIC,
                          value_fn=lambda d: (d.get("source") or {}).get("type")),
    RainSensorDescription(key="data_age", native_unit_of_measurement=UnitOfTime.MINUTES,
                          entity_category=EntityCategory.DIAGNOSTIC,
                          value_fn=lambda d: (d.get("source") or {}).get("data_age_minutes")),
)


async def async_setup_entry(hass: HomeAssistant, entry: RainRadarConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(RainSensor(coord, desc)
                       for coord in entry.runtime_data.coordinators.values() for desc in SENSORS)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class RainSensor(RainRadarEntity, SensorEntity):
    entity_description: RainSensorDescription
    _unrecorded_attributes = frozenset({"timeline", "storm_speed_kmh", "storm_heading_deg"})

    def __init__(self, coordinator, description: RainSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.data) if self.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        d = self.data
        if not d:
            return None
        src = d.get("source") or {}
        key = self.entity_description.key
        if key == "data_source":
            return {k: src.get(k) for k in ("provider", "radar_id", "radar_name", "distance_km",
                                            "observed_at") if src.get(k) is not None}
        if key != "status":
            return None
        loc = self.coordinator.location
        return {
            "summary": d.get("summary"),
            "location_name": self.coordinator.display_name,
            "minutes_until_rain": d.get("minutes_until_rain"),
            "minutes_until_clear": d.get("minutes_until_clear"),
            "minutes_since_rain_cleared": d.get("minutes_since_rain_cleared"),
            "probability_now": (d.get("current") or {}).get("probability"),
            "peak_intensity": (d.get("peak") or {}).get("category"),
            "peak_time": _iso((d.get("peak") or {}).get("time")),
            "storm_speed_kmh": src.get("storm_speed_kmh"),
            "storm_heading_deg": src.get("storm_heading_deg"),
            "latitude": loc[0] if loc else None,
            "longitude": loc[1] if loc else None,
            "timeline": d.get("timeline"),
        }
