"""Diagnostics download: radar state and a palette check on the latest frame.

Locations are rounded to about 10 km and person names left out, so the file is safe to share
in an issue.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import RainRadarConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant,
                                             entry: RainRadarConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    locations = []
    for i, coord in enumerate(data.coordinators.values()):
        d = coord.data or {}
        loc = coord.location
        locations.append({
            "location": "home" if coord.key == "home" else f"person {i}",
            "approx_lat_lon": [round(loc[0], 1), round(loc[1], 1)] if loc else None,
            "last_update_success": coord.last_update_success,
            "status": d.get("status"),
            "source": {k: v for k, v in (d.get("source") or {}).items()
                       if k in ("type", "radar_id", "distance_km", "data_age_minutes")},
        })
    return {
        "options": {k: v for k, v in entry.options.items() if k != "persons"},
        "people_tracked": len([k for k in data.coordinators if k != "home"]),
        "radar": await data.manager.async_diagnostics(),
        "locations": locations,
    }
