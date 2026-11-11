"""Rain Radar Alarm: BoM radar rain nowcasts for your home and everyone in it, computed locally."""
from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_ALERT_PROBABILITY, CONF_FALLBACK, CONF_INCLUDE_HOME, CONF_PERSONS, CONF_RADAR_RANGE,
    CONF_RAIN_THRESHOLD, DEFAULTS, DOMAIN, HOME_KEY,
)
from .coordinator import RainLocationCoordinator
from .engine import Settings
from .radar import RadarManager

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CAMERA, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class RuntimeData:
    manager: RadarManager
    coordinators: dict[str, RainLocationCoordinator] = field(default_factory=dict)


type RainRadarConfigEntry = ConfigEntry[RuntimeData]


def option(entry: ConfigEntry, key: str):
    return entry.options.get(key, entry.data.get(key, DEFAULTS[key]))


def tracked_persons(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    chosen = option(entry, CONF_PERSONS)
    if chosen:
        return [p for p in chosen if hass.states.get(p) is not None]
    return sorted(s.entity_id for s in hass.states.async_all("person"))


def settings_for(entry: ConfigEntry) -> Settings:
    alert = option(entry, CONF_ALERT_PROBABILITY) / 100
    return Settings(alert_probability=alert, clear_probability=max(0.05, alert - 0.2),
                    rain_threshold=float(option(entry, CONF_RAIN_THRESHOLD)))


async def async_setup_entry(hass: HomeAssistant, entry: RainRadarConfigEntry) -> bool:
    manager = RadarManager(hass, settings_for(entry), option(entry, CONF_RADAR_RANGE))
    await manager.async_start()
    data = RuntimeData(manager)
    fallback = option(entry, CONF_FALLBACK)

    if option(entry, CONF_INCLUDE_HOME):
        data.coordinators[HOME_KEY] = RainLocationCoordinator(
            hass, entry, manager, HOME_KEY, hass.config.location_name or "Home", None, fallback)
    for pid in tracked_persons(hass, entry):
        state = hass.states.get(pid)
        data.coordinators[pid] = RainLocationCoordinator(
            hass, entry, manager, pid, state.name if state else pid, pid, fallback)

    entry.runtime_data = data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _first_refresh() -> None:
        # Network work happens here, after setup, so a slow or unreachable BoM never delays
        # Home Assistant starting. Entities show unavailable until their first forecast.
        await manager.async_ensure_sites()
        for coord in data.coordinators.values():
            await coord.async_refresh()

    entry.async_create_background_task(hass, _first_refresh(), f"{DOMAIN} first refresh")

    @callback
    def _new_frames() -> None:
        for coord in data.coordinators.values():
            hass.async_create_task(coord.async_request_refresh())

    entry.async_on_unload(manager.async_add_listener(_new_frames))

    people = [k for k in data.coordinators if k != HOME_KEY]

    @callback
    def _person_moved(event: Event[EventStateChangedData]) -> None:
        coord = data.coordinators.get(event.data["entity_id"])
        if coord and coord.moved_enough():
            hass.async_create_task(coord.async_request_refresh())

    if people:
        entry.async_on_unload(async_track_state_change_event(hass, people, _person_moved))

    @callback
    def _is_new_person(event_data: EventStateChangedData) -> bool:
        return (event_data["old_state"] is None and event_data["entity_id"].startswith("person.")
                and event_data["entity_id"] not in data.coordinators)

    @callback
    def _person_added(event: Event[EventStateChangedData]) -> None:
        if not option(entry, CONF_PERSONS):  # tracking everyone: pick up the new person
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_STATE_CHANGED, _person_added, event_filter=_is_new_person))
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    entry.async_on_unload(manager.async_stop)
    return True


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: RainRadarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the saved radar list when the integration is removed."""
    await RadarManager(hass, settings_for(entry), option(entry, CONF_RADAR_RANGE)).async_remove_stored()
