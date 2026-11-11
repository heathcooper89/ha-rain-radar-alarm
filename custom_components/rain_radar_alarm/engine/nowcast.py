"""Point nowcast from a radar product, and conversion of a timeline into alarm events.

Semi-Lagrangian advection: for each lead time, trace the air arriving at the point back along
the motion field and sample the latest radar frame there, in a circle that widens with lead
time to express growing uncertainty. About 2 ms per point.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np

from . import Settings
from .bom import LEVEL_RATE
from .geo import latlon_to_pixel
from .motion import velocity_at

SEVERITY = [  # (min mm/h, label, level)
    (50.0, "intense", 4),
    (10.0, "heavy", 3),
    (2.5, "moderate", 2),
]


def severity(rate: float, threshold: float) -> dict:
    for lo, label, lvl in SEVERITY:
        if rate >= lo:
            return {"category": label, "level": lvl}
    if rate >= threshold:
        return {"category": "light", "level": 1}
    return {"category": "none", "level": 0}


def _disk_sample(levels, col, row, radius_px, threshold):
    n = levels.shape[0]
    r = max(1.0, radius_px)
    c0, c1 = int(math.floor(col - r)), int(math.ceil(col + r)) + 1
    r0, r1 = int(math.floor(row - r)), int(math.ceil(row + r)) + 1
    cc0, cc1, rr0, rr1 = max(c0, 0), min(c1, n), max(r0, 0), min(r1, n)
    if cc0 >= cc1 or rr0 >= rr1:
        return None
    win = levels[rr0:rr1, cc0:cc1]
    yy, xx = np.mgrid[rr0:rr1, cc0:cc1]
    mask = (xx - col) ** 2 + (yy - row) ** 2 <= r * r
    vals = LEVEL_RATE[win[mask]]
    if vals.size == 0:
        return None
    rainy = vals >= threshold
    peak = float(np.percentile(vals[rainy], 90)) if rainy.any() else 0.0
    return float(rainy.mean()), float(vals.mean()), peak


def _inside(col, row, n, margin=2):
    c = n / 2.0
    return math.hypot(col - c, row - c) <= c - margin


def radar_point_forecast(product: dict, lat: float, lon: float, now: dt.datetime, s: Settings):
    """(timeline, history), or None if the point is outside this radar's image."""
    levels_hist, times = product["levels"], product["times"]
    n = levels_hist.shape[-1]
    kmpp = product["km_per_px"]
    col, row = latlon_to_pixel(product["site"], lat, lon, kmpp, n)
    if not _inside(col, row, n):
        return None
    latest, t_latest = levels_hist[-1], times[-1]
    age_min = max(0.0, (now - t_latest).total_seconds() / 60.0)

    history = []
    for lv, t in zip(levels_hist, times):
        smp = _disk_sample(lv, col, row, 1.0 / kmpp, s.rain_threshold)
        if smp:
            history.append({"time": t, "probability": smp[0], "rate": smp[1]})

    motion = product["motion"]
    timeline = []
    lead = int(math.ceil(age_min / s.step_min)) * s.step_min  # first step at or after now
    while lead - age_min <= s.horizon_min:
        vx, vy = velocity_at(motion, col, row)
        vx, vy = velocity_at(motion, col - vx * lead / 2, row - vy * lead / 2)
        sc, sr = col - vx * lead, row - vy * lead
        if not _inside(sc, sr, n):
            break  # the air arriving then is beyond radar range now
        smp = _disk_sample(latest, sc, sr, (s.radius_base_km + s.radius_growth_km * lead) / kmpp,
                           s.rain_threshold)
        if smp is None:
            break
        prob, mean_rate, peak = smp
        timeline.append({
            "minutes": round(lead - age_min),
            "time": t_latest + dt.timedelta(minutes=lead),
            "probability": prob,
            "rate": mean_rate if prob >= s.clear_probability else 0.0,
            "peak_rate": peak,
        })
        lead += s.step_min
    return timeline, history


def derive_events(timeline: list, history: list, now: dt.datetime, s: Settings) -> dict:
    """Alarm-friendly fields from a forecast timeline plus observed history at the point."""
    a, c = s.alert_probability, s.clear_probability
    current = timeline[0] if timeline else None
    raining_now = bool(current and current["probability"] >= a)

    start_idx = 0 if raining_now else next(
        (i for i, e in enumerate(timeline) if e["probability"] >= a), None)

    end_idx = None
    if start_idx is not None:
        for i in range(start_idx + 1, len(timeline)):
            nxt = timeline[i + 1]["probability"] if i + 1 < len(timeline) else 0.0
            if timeline[i]["probability"] < c and nxt < c:
                end_idx = i
                break

    window = timeline[start_idx:end_idx] if start_idx is not None else []
    peak_entry = max(window, key=lambda e: e["peak_rate"], default=None)

    since_cleared = None
    if not raining_now:
        for h in reversed(history[:-1] if history else []):
            if h["probability"] >= a:
                since_cleared = max(0, round((now - h["time"]).total_seconds() / 60))
                break

    if raining_now:
        status = "clearing" if end_idx is not None else "raining"
    elif start_idx is not None:
        status = "rain_expected"
    elif since_cleared is not None:
        status = "cleared"
    else:
        status = "dry"

    cur_rate = current["rate"] if raining_now else 0.0
    return {
        "status": status,
        "raining_now": raining_now,
        "rain_expected": start_idx is not None,
        "minutes_until_rain": None if raining_now or start_idx is None else timeline[start_idx]["minutes"],
        "rain_start_time": None if start_idx is None else timeline[start_idx]["time"],
        "minutes_until_clear": None if end_idx is None else timeline[end_idx]["minutes"],
        "rain_clear_time": None if end_idx is None else timeline[end_idx]["time"],
        "minutes_since_rain_cleared": since_cleared,
        "current": {"rate": round(cur_rate, 1),
                    "probability": round(current["probability"], 2) if current else None,
                    **severity(cur_rate, s.rain_threshold)},
        "peak": None if peak_entry is None else {
            "rate": round(peak_entry["peak_rate"], 1), "minutes": peak_entry["minutes"],
            "time": peak_entry["time"], **severity(peak_entry["peak_rate"], s.rain_threshold)},
        "horizon_minutes": timeline[-1]["minutes"] if timeline else 0,
    }


def format_timeline(timeline: list, s: Settings) -> list[dict]:
    return [{"minutes": e["minutes"], "time": e["time"].isoformat(),
             "probability": round(e["probability"], 2), "rate": round(e["rate"], 1),
             "category": severity(e["rate"], s.rain_threshold)["category"]} for e in timeline]
