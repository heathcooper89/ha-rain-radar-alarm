"""Radar map loop for one location: recent radar frames, then forecast frames.

Everything is drawn in memory from frames the integration already holds and BoM's own map
layers (radar_transparencies on the same FTP service). Nothing is written to disk.

Forecast frames move the latest radar frame along the storm motion field (the same
semi-Lagrangian step the point forecast uses), so they show where today's rain is heading,
not rain that forms or fades.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .bom import PALETTE
from .geo import latlon_to_pixel

CROP_PX = 200            # source pixels across: 100 km at 128 km range, 200 km at 256 km range
SCALE = 2                # output is CROP_PX * SCALE square
PAST_WINDOW_MIN = 60     # recent frames shown
MAX_PAST_FRAMES = 6
FORECAST_LEADS_MIN = (10, 20, 30, 40, 50, 60)
FRAME_MS = 500
HOLD_MS = 1500           # the latest observation and the last forecast stay up longer
LAYERS_BELOW = ("background", "topography")
LAYERS_ABOVE = ("range", "locations")
SEA = (184, 204, 224)
MARKER = (226, 114, 91)  # coral
ATTRIBUTION = "© Bureau of Meteorology"

_RAIN_RGB = np.zeros((len(PALETTE) + 1, 3), dtype=np.uint8)
for _i, (_colour, _) in enumerate(PALETTE, start=1):
    _RAIN_RGB[_i] = _colour


@dataclass
class RadarLoop:
    """One rendered loop: an animated GIF, plus the same frames as JPEGs for live streaming."""

    gif: bytes
    jpegs: list[bytes]
    durations_ms: list[int]
    observed: dt.datetime


def crop_box(col: float, row: float, n: int, size: int = CROP_PX) -> tuple[int, int, int, int]:
    """A size x size window centred on (col, row), shifted to stay inside the image."""
    x0 = int(round(col - size / 2))
    y0 = int(round(row - size / 2))
    x0 = min(max(x0, 0), n - size)
    y0 = min(max(y0, 0), n - size)
    return x0, y0, x0 + size, y0 + size


def _interp(field: np.ndarray, centres: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of a tile field at many pixel positions (vectorised velocity_at)."""
    def index(p):
        p = np.clip(p, centres[0], centres[-1])
        i = np.clip(np.searchsorted(centres, p, side="right") - 1, 0, len(centres) - 2)
        t = (p - centres[i]) / (centres[i + 1] - centres[i])
        return i, t

    i, tx = index(xs)
    j, ty = index(ys)
    return ((1 - tx) * (1 - ty) * field[j, i] + tx * (1 - ty) * field[j, i + 1]
            + (1 - tx) * ty * field[j + 1, i] + tx * ty * field[j + 1, i + 1])


def advect(latest: np.ndarray, motion: dict, lead_min: float, box: tuple[int, int, int, int]) -> np.ndarray:
    """Rain levels in `box`, lead_min minutes after `latest`, moved along the motion field."""
    n = latest.shape[0]
    x0, y0, x1, y1 = box
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    c = motion["centres"]
    vx = _interp(motion["vx"], c, xs, ys)
    vy = _interp(motion["vy"], c, xs, ys)
    # Midpoint step, as in the point forecast: velocity halfway back along the path.
    mx, my = xs - vx * lead_min / 2, ys - vy * lead_min / 2
    vx = _interp(motion["vx"], c, mx, my)
    vy = _interp(motion["vy"], c, mx, my)
    sx = np.rint(xs - vx * lead_min).astype(np.int32)
    sy = np.rint(ys - vy * lead_min).astype(np.int32)
    centre = n / 2.0
    inside = ((sx >= 0) & (sx < n) & (sy >= 0) & (sy < n)
              & ((sx - centre) ** 2 + (sy - centre) ** 2 <= (centre - 2) ** 2))
    out = np.zeros(xs.shape, dtype=np.uint8)
    out[inside] = latest[sy[inside], sx[inside]]
    return out


def _layer(png: bytes | None, box) -> Image.Image | None:
    if not png:
        return None
    try:
        img = Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception:  # noqa: BLE001 - a broken layer is skipped, not fatal
        return None
    if img.size[0] < box[2] or img.size[1] < box[3]:
        return None
    return img.crop(box).resize((CROP_PX * SCALE, CROP_PX * SCALE), Image.Resampling.NEAREST)


def _rain(levels: np.ndarray, alpha: int) -> Image.Image:
    rgba = np.zeros((*levels.shape, 4), dtype=np.uint8)
    rgba[..., :3] = _RAIN_RGB[levels]
    rgba[..., 3] = np.where(levels > 0, alpha, 0)
    img = Image.fromarray(rgba, "RGBA")
    return img.resize((CROP_PX * SCALE, CROP_PX * SCALE), Image.Resampling.NEAREST)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # Pillow without FreeType
        return ImageFont.load_default()


def _text(draw: ImageDraw.ImageDraw, xy, text: str, font, colour=(255, 255, 255), anchor="la") -> None:
    left, top, right, bottom = draw.textbbox(xy, text, font=font, anchor=anchor)
    draw.rounded_rectangle((left - 5, top - 3, right + 5, bottom + 3), radius=4, fill=(20, 30, 45, 190))
    draw.text(xy, text, font=font, fill=colour, anchor=anchor)


def radar_loop(product: dict, layers: dict[str, bytes], lat: float, lon: float,
               tz: dt.tzinfo) -> RadarLoop | None:
    """Render the loop for a location, or None if it isn't on this radar's image."""
    levels, times = product["levels"], product["times"]
    n = levels.shape[-1]
    col, row = latlon_to_pixel(product["site"], lat, lon, product["km_per_px"], n)
    if not (0 <= col < n and 0 <= row < n):
        return None
    box = crop_box(col, row, n)
    x0, y0, x1, y1 = box
    size = CROP_PX * SCALE

    base = Image.new("RGBA", (size, size), (*SEA, 255))
    for name in LAYERS_BELOW:
        if (img := _layer(layers.get(name), box)) is not None:
            base.alpha_composite(img)
    above = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for name in LAYERS_ABOVE:
        if (img := _layer(layers.get(name), box)) is not None:
            above.alpha_composite(img)

    font, small = _font(15), _font(12)
    mx, my = (col - x0) * SCALE, (row - y0) * SCALE
    latest_t = times[-1]

    def frame(rain_levels: np.ndarray, label: str, forecast: bool) -> Image.Image:
        img = base.copy()
        img.alpha_composite(_rain(rain_levels, 200 if forecast else 235))
        img.alpha_composite(above)
        draw = ImageDraw.Draw(img)
        draw.ellipse((mx - 8, my - 8, mx + 8, my + 8), fill=(*MARKER, 255), outline=(255, 255, 255, 255), width=3)
        _text(draw, (8, 8), label, font, (255, 214, 102) if forecast else (255, 255, 255))
        _text(draw, (size - 8, size - 8), ATTRIBUTION, small, anchor="rd")
        return img.convert("RGB")

    frames: list[tuple[Image.Image, int]] = []
    recent = [i for i, t in enumerate(times)
              if (latest_t - t).total_seconds() <= PAST_WINDOW_MIN * 60][-MAX_PAST_FRAMES:]
    for i in recent:
        local = times[i].astimezone(tz)
        last = i == len(times) - 1
        frames.append((frame(levels[i, y0:y1, x0:x1], f"{local:%H:%M}" + (" latest" if last else ""), False),
                       HOLD_MS if last else FRAME_MS))
    for k, lead in enumerate(FORECAST_LEADS_MIN):
        local = (latest_t + dt.timedelta(minutes=lead)).astimezone(tz)
        frames.append((frame(advect(levels[-1], product["motion"], lead, box),
                             f"{local:%H:%M} forecast", True),
                       HOLD_MS if k == len(FORECAST_LEADS_MIN) - 1 else FRAME_MS))

    gif = io.BytesIO()
    pal = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=255) for f, _ in frames]
    pal[0].save(gif, "GIF", save_all=True, append_images=pal[1:],
                duration=[d for _, d in frames], loop=0, disposal=1)
    jpegs = []
    for f, _ in frames:
        buf = io.BytesIO()
        f.save(buf, "JPEG", quality=82)
        jpegs.append(buf.getvalue())
    return RadarLoop(gif=gif.getvalue(), jpegs=jpegs, durations_ms=[d for _, d in frames],
                     observed=latest_t)
