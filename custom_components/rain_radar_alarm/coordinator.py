"""One coordinator per tracked location: home, or a person who moves around."""
from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .const import (
    ATTRIBUTION_MODEL, ATTRIBUTION_RADAR, COORD_DECIMALS, DOMAIN, EVENT, HOME_KEY,
    LOCATION_INTERVAL, MOVE_THRESHOLD_M,
)
from .engine import nowcast, openmeteo
from .engine.geo import latlon_to_pixel
from .engine.motion import velocity_at
from .radar import RadarManager

_LOGGER = logging.getLogger(__name__)


def home_location(hass: HomeAssistant) -> tuple[float, float]:
    zone = hass.states.get("zone.home")
    if zone and zone.attributes.get("latitude") is not None:
        return zone.attributes["latitude"], zone.attributes["longitude"]
    return hass.config.latitude, hass.config.longitude


def person_location(hass: HomeAssistant, state: State | None) -> tuple[float, float] | None:
    """GPS if the person has it, otherwise the centre of the zone they're in."""
    if state is None:
        return None
    lat, lon = state.attributes.get("latitude"), state.attributes.get("longitude")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    if state.state == "home":
        return home_location(hass)
    for zone in hass.states.async_all("zone"):
        if zone.name == state.state and zone.attributes.get("latitude") is not None:
            return zone.attributes["latitude"], zone.attributes["longitude"]
    return None


class RainLocationCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Forecast for one location, recomputed when radar frames arrive or the location moves."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager: RadarManager,
                 key: str, name: str, person: str | None, use_fallback: bool) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {name}",
                         update_interval=LOCATION_INTERVAL)
        self.manager = manager
        self.key = key                    # "home" or a person entity id
        self.display_name = name
        self.person = person
        self.use_fallback = use_fallback
        self.location: tuple[float, float] | None = None
        self.radar_site: int | None = None   # radar used for the latest forecast, if any

    def current_location(self) -> tuple[float, float] | None:
        if self.key == HOME_KEY:
            return home_location(self.hass)
        return person_location(self.hass, self.hass.states.get(self.person))

    def moved_enough(self) -> bool:
        new = self.current_location()
        if new is None or self.location is None:
            return new != self.location
        return distance(self.location[0], self.location[1], new[0], new[1]) > MOVE_THRESHOLD_M

    async def _async_update_data(self) -> dict[str, Any]:
        loc = self.current_location()
        if loc is None:
            # Normal for someone away without phone location: show unavailable, don't log errors.
            self.location = None
            return {"location_unknown": True}
        lat, lon = round(loc[0], COORD_DECIMALS), round(loc[1], COORD_DECIMALS)
        self.location = (lat, lon)
        now = dt_util.utcnow()
        settings = self.manager.settings

        result = await self._radar(lat, lon, now)
        self.radar_site = result[2]["site_id"] if result else None
        if result is None and self.use_fallback:
            try:
                raw = await self.manager.async_open_meteo(lat, lon)
            except Exception as err:  # noqa: BLE001 - network
                raise UpdateFailed(f"No radar data and Open-Meteo failed: {err}") from err
            timeline, history = openmeteo.to_timeline(raw, now, settings)
            result = (timeline, history, {"type": "model", "provider": "Open-Meteo"})
        if result is None:
            raise UpdateFailed("No BoM radar covers this location right now")

        timeline, history, source = result
        data = nowcast.derive_events(timeline, history, now, settings)
        data["timeline"] = nowcast.format_timeline(timeline, settings)
        data["source"] = source
        data["attribution"] = ATTRIBUTION_RADAR if source["type"] == "radar" else ATTRIBUTION_MODEL
        data["summary"] = summarise(data)

        previous = (self.data or {}).get("status")
        if previous and previous != data["status"]:
            self.hass.bus.async_fire(EVENT, {
                "location": self.key, "name": self.display_name, "person": self.person,
                "status": data["status"], "previous_status": previous,
                "minutes_until_rain": data["minutes_until_rain"],
                "minutes_until_clear": data["minutes_until_clear"],
                "intensity": ((data.get("peak") or data["current"]) or {}).get("category"),
                "summary": data["summary"],
            })
        return data

    async def async_radar_loop(self):
        """The radar map loop for this location, or None when no radar covers it right now."""
        if self.radar_site is None or self.location is None:
            return None
        return await self.manager.async_radar_loop(self.radar_site, *self.location)

    async def _radar(self, lat: float, lon: float, now: dt.datetime):
        for site in self.manager.radars_for(lat, lon):
            product = await self.manager.async_product(site["id"])
            if not self.manager.is_fresh(product):
                continue
            fc = await self.hass.async_add_executor_job(
                nowcast.radar_point_forecast, product, lat, lon, now, self.manager.settings)
            if not fc or not fc[0]:
                continue
            observed = product["times"][-1]
            return fc[0], fc[1], {
                "type": "radar",
                "provider": "Bureau of Meteorology",
                "site_id": site["id"],
                "radar_id": f"IDR{site['id']:02d}{product['range_code']}",
                "radar_name": site["name"],
                "distance_km": site["distance_km"],
                "observed_at": observed.isoformat(),
                "data_age_minutes": round((now - observed).total_seconds() / 60),
                **_motion(product, lat, lon),
            }
        return None


def _motion(product: dict, lat: float, lon: float) -> dict:
    col, row = latlon_to_pixel(product["site"], lat, lon, product["km_per_px"], product["levels"].shape[-1])
    vx, vy = velocity_at(product["motion"], col, row)
    kmh = math.hypot(vx, vy) * product["km_per_px"] * 60
    heading = (math.degrees(math.atan2(vx, -vy)) + 360) % 360
    return {"storm_speed_kmh": round(kmh, 1), "storm_heading_deg": None if kmh < 1 else round(heading)}


def _hm(t: dt.datetime | None) -> str | None:
    return f"{dt_util.as_local(t):%H:%M}" if t else None


def summarise(d: dict) -> str:
    """One plain sentence for notifications and dashboards."""
    status, cur, peak = d.get("status"), d.get("current") or {}, d.get("peak") or {}
    clear_at = _hm(d.get("rain_clear_time"))
    if status == "rain_expected":
        s = f"{peak.get('category', 'some').capitalize()} rain in about {d.get('minutes_until_rain')} min"
        return s + (f", clearing around {clear_at}" if clear_at else "")
    if status == "raining":
        return (f"{cur.get('category', 'some').capitalize()} rain now ({cur.get('rate')} mm/h), "
                f"not clearing in the next {d.get('horizon_minutes')} min")
    if status == "clearing":
        return (f"{cur.get('category', 'some').capitalize()} rain now, clearing in about "
                f"{d.get('minutes_until_clear')} min ({clear_at})")
    if status == "cleared":
        return f"Rain cleared about {d.get('minutes_since_rain_cleared')} min ago, none on the way"
    return f"No rain expected in the next {d.get('horizon_minutes') or 120} min"
