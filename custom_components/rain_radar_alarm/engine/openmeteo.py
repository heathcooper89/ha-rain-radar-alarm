"""Open-Meteo 15-minute precipitation forecast, used where no BoM radar covers a location.

Model-based, not radar: lower confidence. Free for non-commercial use, CC BY 4.0, no key.
The HTTP call is made by the integration (async); this module only builds and parses.
"""
from __future__ import annotations

import datetime as dt

from . import Settings

URL = "https://api.open-meteo.com/v1/forecast"


def params(lat: float, lon: float, s: Settings) -> dict:
    return {
        "latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}",
        "minutely_15": "precipitation", "hourly": "precipitation_probability",
        "past_minutely_15": 4, "forecast_minutely_15": max(1, s.horizon_min // 15 + 1),
        "forecast_hours": 4, "past_hours": 1, "timezone": "GMT",
    }


def _t(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)


def to_timeline(data: dict, now: dt.datetime, s: Settings):
    """Open-Meteo JSON -> (timeline, history) shaped like the radar nowcast."""
    m = data["minutely_15"]
    h = data.get("hourly", {})
    hour_prob = {_t(t).replace(minute=0): p
                 for t, p in zip(h.get("time", []), h.get("precipitation_probability", []))}
    timeline, history = [], []
    for t_s, mm in zip(m["time"], m["precipitation"]):
        t_end = _t(t_s)                       # value = total over the preceding 15 minutes
        rate = (mm or 0.0) * 4.0
        hp = hour_prob.get(t_end.replace(minute=0))
        hp = 0.5 if hp is None else hp / 100.0
        wet = rate >= s.rain_threshold
        prob = max(hp, s.alert_probability) if wet else min(hp, s.clear_probability - 0.05)
        minutes = round((t_end - now).total_seconds() / 60)
        entry = {"time": t_end, "probability": prob, "rate": rate if wet else 0.0, "peak_rate": rate}
        if minutes < 0:
            history.append(entry)
        elif minutes <= s.horizon_min:
            timeline.append({**entry, "minutes": minutes})
    return timeline, history
