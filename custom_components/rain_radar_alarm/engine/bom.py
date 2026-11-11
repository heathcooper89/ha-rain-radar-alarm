"""Bureau of Meteorology radar images from the anonymous FTP service.

BoM publishes 512x512 radar PNGs at ftp://ftp.bom.gov.au/anon/gen/radar/, named
IDR<site><range>.T.<yyyymmddhhmm>.png (UTC), transparent where it's dry, centred on the radar.
Range codes: 1 = 512 km, 2 = 256 km, 3 = 128 km, 4 = 64 km.

Terms (BoM copyright notice, default terms for anonymous FTP products): material may be
downloaded and used for personal use or within your organisation; it may not be supplied to
anyone else or used commercially. This module only ever fetches for the Home Assistant instance
it runs in, keeps frames in memory, and never re-publishes them.
"""
from __future__ import annotations

import datetime as dt
import ftplib
import io
import re

import numpy as np
from PIL import Image

FTP_HOST = "ftp.bom.gov.au"
RADAR_DIR = "/anon/gen/radar"
SPATIAL_DIR = "/anon/home/adfd/spatial"
RADAR_SITES_FILE = "IDR00007.dbf"   # BoM's radar locations table (dBase)
FTP_TIMEOUT = 20
IMAGE_SIZE = 512
RANGE_KM = {"1": 512.0, "2": 256.0, "3": 128.0, "4": 64.0}

# BoM rain-rate legend: RGB -> lower bound of the band in mm/h, light to extreme.
PALETTE = [
    ((245, 245, 255), 0.2),
    ((180, 180, 255), 0.5),
    ((120, 120, 255), 1.5),
    ((20, 20, 255), 2.5),
    ((0, 216, 195), 4.0),
    ((0, 150, 144), 6.0),
    ((0, 102, 102), 10.0),
    ((255, 255, 0), 15.0),
    ((255, 200, 0), 20.0),
    ((255, 150, 0), 35.0),
    ((255, 100, 0), 50.0),
    ((255, 0, 0), 80.0),
    ((200, 0, 0), 120.0),
    ((120, 0, 0), 200.0),
    ((40, 0, 0), 300.0),
]
# Level 0 = dry; levels 1..15 index PALETTE. Representative rate = middle of each band.
LEVEL_RATE = np.array(
    [0.0] + [
        (PALETTE[i][1] + (PALETTE[i + 1][1] if i + 1 < len(PALETTE) else PALETTE[i][1] * 1.2)) / 2
        for i in range(len(PALETTE))
    ],
    dtype=np.float32,
)
# Tight, so white map text or labels never read as the lightest rain colour.
COLOUR_TOLERANCE = 6

FRAME_RE = re.compile(r"^IDR(\d{2})(\d)\.T\.(\d{12})\.png$")


def km_per_px(range_code: str) -> float:
    return 2 * RANGE_KM[range_code] / IMAGE_SIZE


def parse_frame_name(name: str):
    m = FRAME_RE.match(name.rsplit("/", 1)[-1])
    if not m:
        return None
    ts = dt.datetime.strptime(m.group(3), "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc)
    return int(m.group(1)), m.group(2), ts


def connect() -> ftplib.FTP:
    ftp = ftplib.FTP(FTP_HOST, timeout=FTP_TIMEOUT)
    ftp.login()  # anonymous
    return ftp


def list_frames(ftp: ftplib.FTP, radar_ids, range_code: str) -> dict[int, list]:
    """{radar_id: [(timestamp, filename), ...] oldest first} for just the radars asked for.

    One NLST per radar with a name pattern keeps listings tiny; if the server does not accept
    patterns, falls back to a single full directory listing.
    """
    ftp.cwd(RADAR_DIR)
    out: dict[int, list] = {}
    names: list[str] = []
    for rid in radar_ids:
        try:
            names += ftp.nlst(f"IDR{rid:02d}{range_code}.T.*.png")
        except ftplib.error_perm:  # "550 No files found", or patterns not supported
            continue
    if not names:
        names = ftp.nlst()  # one full listing, in case the server ignores name patterns
    wanted = set(radar_ids)
    for n in names:
        p = parse_frame_name(n)
        if p and p[1] == range_code and p[0] in wanted:
            out.setdefault(p[0], []).append((p[2], n.rsplit("/", 1)[-1]))
    for v in out.values():
        v.sort()
    return out


def fetch(ftp: ftplib.FTP, filename: str) -> bytes:
    buf = io.BytesIO()
    ftp.retrbinary(f"RETR {filename}", buf.write)
    return buf.getvalue()


def fetch_sites_table() -> bytes:
    ftp = connect()
    try:
        ftp.cwd(SPATIAL_DIR)
        return fetch(ftp, RADAR_SITES_FILE)
    finally:
        _quit(ftp)


def _quit(ftp: ftplib.FTP) -> None:
    try:
        ftp.quit()
    except Exception:  # noqa: BLE001 - closing a dead connection is not an error
        ftp.close()


def decode_png(data: bytes) -> np.ndarray:
    """PNG bytes -> uint8 grid of rain levels (0 = dry, 1..15 = legend band)."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    a = np.asarray(img, dtype=np.int16)
    rgb, alpha = a[..., :3], a[..., 3]
    levels = np.zeros(a.shape[:2], dtype=np.uint8)
    for i, (colour, _) in enumerate(PALETTE, start=1):
        match = np.all(np.abs(rgb - np.array(colour)) <= COLOUR_TOLERANCE, axis=-1) & (alpha > 0)
        levels[match] = i
    return levels


def levels_to_rate(levels: np.ndarray) -> np.ndarray:
    return LEVEL_RATE[levels]


def palette_report(data: bytes) -> dict:
    """How many opaque pixels match a legend colour; for the diagnostics download."""
    img = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"), dtype=np.int16)
    opaque = img[..., 3] > 0
    matched = (decode_png(data) > 0) & opaque
    other = img[opaque & ~matched][:, :3]
    top = []
    if len(other):
        colours, counts = np.unique(other, axis=0, return_counts=True)
        top = sorted(zip(counts.tolist(), [tuple(int(x) for x in c) for c in colours]), reverse=True)[:8]
    return {"opaque_pixels": int(opaque.sum()), "matched_pixels": int(matched.sum()),
            "unmatched_colours": [{"rgb": c, "pixels": n} for n, c in top]}
