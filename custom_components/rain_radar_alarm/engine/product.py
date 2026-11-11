"""A radar 'product': the recent rain frames for one radar plus the storm motion field.

Built once per new frame per radar; every location under that radar reuses it.
"""
from __future__ import annotations

import numpy as np

from . import Settings
from .bom import km_per_px, levels_to_rate
from .motion import estimate


def build_product(levels, times, site: dict, range_code: str, settings: Settings) -> dict:
    order = sorted(range(len(times)), key=lambda i: times[i])[-settings.history_frames:]
    times = [times[i] for i in order]
    stack = np.stack([levels[i] for i in order])
    kmpp = km_per_px(range_code)
    k = min(settings.frames_for_motion, len(times))
    t0 = times[0]
    rates = [levels_to_rate(lv) for lv in stack[-k:]]
    mins = [(t - t0).total_seconds() / 60 for t in times[-k:]]
    motion = estimate(rates, mins, settings.max_speed_kmh / 60.0 / kmpp)
    return {"levels": stack, "times": times, "site": site, "km_per_px": kmpp,
            "range_code": range_code, "motion": motion}
