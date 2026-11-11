"""BoM radar sites, read from BoM's own radar locations table (IDR00007.dbf on the FTP service).

The table is a dBase III file; this module reads it with the standard library only.
"""
from __future__ import annotations

import struct

from .geo import haversine_km


def read_dbf(data: bytes) -> list[dict]:
    """Minimal dBase III reader: returns one dict per non-deleted record, values as stripped text."""
    if len(data) < 32:
        raise ValueError("not a dBase file")
    n_records, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while pos < header_len - 1 and data[pos] != 0x0D:
        raw = data[pos:pos + 32]
        name = raw[:11].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
        fields.append((name, chr(raw[11]), raw[16]))
        pos += 32
    rows = []
    for i in range(n_records):
        start = header_len + i * record_len
        rec = data[start:start + record_len]
        if len(rec) < record_len or rec[:1] == b"*":  # truncated or deleted
            continue
        off, row = 1, {}
        for name, _kind, length in fields:
            row[name] = rec[off:off + length].decode("latin-1", "replace").strip()
            off += length
        rows.append(row)
    return rows


def _get(row: dict, *names: str) -> str | None:
    lower = {k.lower(): v for k, v in row.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, ""):
            return v
    return None


def parse_sites(data: bytes) -> list[dict]:
    """[{id, name, lat, lon}] from the radar locations table, one entry per radar id."""
    out: dict[int, dict] = {}
    for row in read_dbf(data):
        rid = _get(row, "Radar_id", "LocationID", "id")
        lat, lon = _get(row, "Latitude", "lat"), _get(row, "Longitude", "lon")
        if not (rid and lat and lon):
            continue
        try:
            rid_i, lat_f, lon_f = int(float(rid)), float(lat), float(lon)
        except ValueError:
            continue
        if not (-45 <= lat_f <= -9 and 110 <= lon_f <= 160):  # sanity: Australian territory
            continue
        out[rid_i] = {"id": rid_i, "name": _get(row, "Full_Name", "Name") or f"Radar {rid_i}",
                      "lat": lat_f, "lon": lon_f}
    return sorted(out.values(), key=lambda s: s["id"])


def candidates(registry: list[dict], lat: float, lon: float, range_km: float) -> list[dict]:
    """Radars whose image covers the point, nearest first."""
    reach = range_km * 0.95
    found = []
    for s in registry:
        d = haversine_km(lat, lon, s["lat"], s["lon"])
        if d <= reach:
            found.append({**s, "distance_km": round(d, 1)})
    return sorted(found, key=lambda s: s["distance_km"])
