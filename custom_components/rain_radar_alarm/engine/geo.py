"""Geometry helpers: lat/lon <-> radar image pixels (local azimuthal approximation)."""
import math

EARTH_R_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def offset_km(lat0, lon0, lat, lon):
    """East/north offset (km) of (lat, lon) from (lat0, lon0)."""
    dy = math.radians(lat - lat0) * EARTH_R_KM
    dx = math.radians(lon - lon0) * EARTH_R_KM * math.cos(math.radians((lat + lat0) / 2))
    return dx, dy


def latlon_to_pixel(site, lat, lon, km_per_px, size):
    """Return (col, row) float pixel coordinates; image is centred on the radar, north up."""
    dx, dy = offset_km(site["lat"], site["lon"], lat, lon)
    c = size / 2.0
    return c + dx / km_per_px, c - dy / km_per_px
