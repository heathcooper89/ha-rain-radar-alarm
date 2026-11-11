"""Engine tests on synthetic radar frames: a textured rain band moving east at a known speed."""
import datetime as dt
import io
import struct

import numpy as np
from PIL import Image

from custom_components.rain_radar_alarm.engine import Settings, bom, nowcast, openmeteo, sites
from custom_components.rain_radar_alarm.engine.motion import velocity_at
from custom_components.rain_radar_alarm.engine.product import build_product

N = 512
S = Settings()
SITE = {"id": 2, "name": "Melbourne", "lat": -37.85, "lon": 144.75}
KMPP = bom.km_per_px("3")  # 0.5 km per pixel
T0 = dt.datetime(2026, 11, 7, 3, 0, tzinfo=dt.timezone.utc)
STEP = 6  # minutes between frames
SPEED_PX_MIN = 2.0  # 60 km/h east


def storm(n_frames=6, seed=1):
    rng = np.random.default_rng(seed)
    tex = rng.integers(3, 9, size=(N, N), dtype=np.uint8)
    levels, times = [], []
    for k in range(n_frames):
        x0 = int(150 + SPEED_PX_MIN * STEP * k)
        lv = np.zeros((N, N), dtype=np.uint8)
        lv[156:356, x0:x0 + 50] = tex[156:356, 150:200]  # texture travels with the band
        levels.append(lv)
        times.append(T0 + dt.timedelta(minutes=STEP * k))
    return build_product(levels, times, SITE, "3", S)


def point_at(col, row):
    dx, dy = (col - N / 2) * KMPP, (N / 2 - row) * KMPP
    lat = SITE["lat"] + np.degrees(dy / 6371.0)
    lon = SITE["lon"] + np.degrees(dx / (6371.0 * np.cos(np.radians(lat))))
    return float(lat), float(lon)


def events(product, col, row, now):
    tl, hist = nowcast.radar_point_forecast(product, *point_at(col, row), now, S)
    return nowcast.derive_events(tl, hist, now, S)


def test_motion_recovers_speed():
    p = storm()
    vx, vy = p["motion"]["global"]
    assert abs(vx - SPEED_PX_MIN) < 0.2 and abs(vy) < 0.2
    tvx, tvy = velocity_at(p["motion"], 260, 256)
    assert abs(tvx - SPEED_PX_MIN) < 0.3 and abs(tvy) < 0.3


def test_rain_approaching():
    p = storm()
    lead_edge = 150 + SPEED_PX_MIN * STEP * 5 + 50
    ev = events(p, lead_edge + 60, 256, p["times"][-1] + dt.timedelta(minutes=2))  # 30 km ahead
    assert ev["status"] == "rain_expected"
    assert 20 <= ev["minutes_until_rain"] <= 35
    assert 15 <= ev["minutes_until_clear"] - ev["minutes_until_rain"] <= 40  # 25 km wide band
    assert ev["peak"]["category"] in ("moderate", "heavy")


def test_raining_then_clearing():
    p = storm()
    ev = events(p, 150 + 60 + 40, 256, p["times"][-1])
    assert ev["raining_now"] and ev["status"] == "clearing"
    assert 15 <= ev["minutes_until_clear"] <= 30


def test_recently_cleared_and_dry():
    p = storm()
    assert events(p, 170, 256, p["times"][-1])["status"] == "cleared"
    assert events(p, 256, 60, p["times"][-1])["status"] == "dry"


def test_outside_radar_image():
    p = storm()
    assert nowcast.radar_point_forecast(p, SITE["lat"] + 3, SITE["lon"], p["times"][-1], S) is None


def test_png_decoding():
    rgba = np.zeros((N, N, 4), dtype=np.uint8)
    rgba[10, 10] = (*bom.PALETTE[0][0], 255)
    rgba[20, 20] = (*bom.PALETTE[7][0], 255)
    rgba[30, 30] = (255, 255, 255, 255)  # white text must not count as rain
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    lv = bom.decode_png(buf.getvalue())
    assert lv[10, 10] == 1 and lv[20, 20] == 8 and lv[30, 30] == 0
    rep = bom.palette_report(buf.getvalue())
    assert rep["opaque_pixels"] == 3 and rep["matched_pixels"] == 2
    assert rep["unmatched_colours"][0]["rgb"] == (255, 255, 255)


def test_frame_names():
    rid, rng, ts = bom.parse_frame_name("IDR023.T.202611070306.png")
    assert (rid, rng) == (2, "3") and ts == dt.datetime(2026, 11, 7, 3, 6, tzinfo=dt.timezone.utc)
    assert bom.parse_frame_name("IDR023.T.202611070306.gif") is None


def make_dbf(rows, fields):
    """Write a small dBase III file the way BoM's IDR00007.dbf is laid out."""
    rec_len = 1 + sum(length for _, length in fields)
    header_len = 32 + 32 * len(fields) + 1
    out = bytearray(struct.pack("<BBBBIHH20x", 3, 126, 1, 1, len(rows), header_len, rec_len))
    for name, length in fields:
        out += name.encode().ljust(11, b"\x00") + b"C" + b"\x00" * 4 + bytes([length, 0]) + b"\x00" * 14
    out += b"\x0d"
    for i, row in enumerate(rows):
        out += b"*" if i == 2 else b" "  # third record marked deleted
        for (_name, length), value in zip(fields, row):
            out += str(value).encode().ljust(length)[:length]
    out += b"\x1a"
    return bytes(out)


def test_radar_sites_from_dbf():
    fields = [("Name", 20), ("Longitude", 12), ("Latitude", 12), ("Radar_id", 4), ("Full_Name", 40)]
    data = make_dbf([
        ("Melbourne", "144.7554", "-37.8553", "2", "Melbourne (Laverton)"),
        ("Sydney", "151.2094", "-34.0062", "71", "Sydney (Terrey Hills)"),
        ("Old", "150.0", "-30.0", "99", "Deleted site"),
        ("Bad", "abc", "-30.0", "98", "Bad row"),
    ], fields)
    reg = sites.parse_sites(data)
    assert [s["id"] for s in reg] == [2, 71]
    assert reg[0] == {"id": 2, "name": "Melbourne (Laverton)", "lat": -37.8553, "lon": 144.7554}
    near = sites.candidates(reg, -37.81, 144.96, bom.RANGE_KM["3"])
    assert [s["id"] for s in near] == [2] and near[0]["distance_km"] < 25


def test_open_meteo_fallback_timeline():
    now = dt.datetime(2026, 11, 7, 3, 2, tzinfo=dt.timezone.utc)
    times = [f"2026-11-07T{h:02d}:{m:02d}" for h in (2, 3, 4) for m in (0, 15, 30, 45)]
    data = {"minutely_15": {"time": times, "precipitation": [0.5, 0, 0, 0, 0, 0, 0.3, 1.2, 0.8, 0, 0, 0]},
            "hourly": {"time": ["2026-11-07T02:00", "2026-11-07T03:00", "2026-11-07T04:00"],
                       "precipitation_probability": [40, 70, 60]}}
    tl, hist = openmeteo.to_timeline(data, now, S)
    ev = nowcast.derive_events(tl, hist, now, S)
    assert ev["status"] == "rain_expected" and 20 <= ev["minutes_until_rain"] <= 30
    assert ev["peak"]["rate"] == 4.8 and ev["peak"]["category"] == "moderate"
