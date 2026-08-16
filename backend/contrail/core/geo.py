"""Geodesy helpers. Everything here is WGS-84; no datum shift exists anywhere
in this product (Mapbox basemaps are WGS-84 too, so nothing needs correcting).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

EARTH_RADIUS_M = 6371008.8

_GEOHASH_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"

# Accepts both "geo:35.0116,135.7681" and "35.0116°, 135.7681°".
_LATLNG_RE = re.compile(r"(?:geo:)?\s*(-?\d+\.?\d*)°?\s*,\s*(-?\d+\.?\d*)°?")


def parse_latlng(value: str | None) -> tuple[float, float] | None:
    """Parse a Google timeline coordinate string -> (lat, lon), or None."""
    if not value:
        return None
    m = _LATLNG_RE.search(value)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not is_valid_coord(lat, lon):
        return None
    return lat, lon


def is_valid_coord(lat: float, lon: float) -> bool:
    """(0, 0) is the Gulf of Guinea and always means "no fix" in this domain."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False
    return not (abs(lat) < 1e-9 and abs(lon) < 1e-9)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def path_length_m(points: Iterable[tuple[float, float]]) -> float:
    """Cumulative Haversine length of a (lat, lon) sequence."""
    total = 0.0
    prev: tuple[float, float] | None = None
    for lat, lon in points:
        if prev is not None:
            total += haversine_m(prev[0], prev[1], lat, lon)
        prev = (lat, lon)
    return total


def centroid(points: Iterable[tuple[float, float]]) -> tuple[float, float]:
    """Spherical mean; correct across the antimeridian, unlike averaging degrees."""
    x = y = z = 0.0
    n = 0
    for lat, lon in points:
        rlat, rlon = math.radians(lat), math.radians(lon)
        x += math.cos(rlat) * math.cos(rlon)
        y += math.cos(rlat) * math.sin(rlon)
        z += math.sin(rlat)
        n += 1
    if n == 0:
        raise ValueError("centroid of empty sequence")
    x, y, z = x / n, y / n, z / n
    lon = math.atan2(y, x)
    lat = math.atan2(z, math.hypot(x, y))
    return math.degrees(lat), math.degrees(lon)


def straightness(points: list[tuple[float, float]]) -> float:
    """Endpoint distance / along-path distance. Approaches 1.0 for flights."""
    if len(points) < 2:
        return 0.0
    along = path_length_m(points)
    if along <= 0:
        return 0.0
    direct = haversine_m(points[0][0], points[0][1], points[-1][0], points[-1][1])
    return min(1.0, direct / along)


def geohash(lat: float, lon: float, precision: int = 7) -> str:
    """Standard geohash. precision 7 ~ 153 m, precision 4 ~ 20 km."""
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    bits, ch, even = 0, 0, True
    out: list[str] = []
    while len(out) < precision:
        if even:
            mid = sum(lon_range) / 2
            if lon > mid:
                ch = (ch << 1) | 1
                lon_range[0] = mid
            else:
                ch <<= 1
                lon_range[1] = mid
        else:
            mid = sum(lat_range) / 2
            if lat > mid:
                ch = (ch << 1) | 1
                lat_range[0] = mid
            else:
                ch <<= 1
                lat_range[1] = mid
        even = not even
        bits += 1
        if bits == 5:
            out.append(_GEOHASH_ALPHABET[ch])
            bits, ch = 0, 0
    return "".join(out)


def bbox_of(points: Iterable[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    """-> (min_lon, min_lat, max_lon, max_lat)."""
    min_lat = min_lon = float("inf")
    max_lat = max_lon = float("-inf")
    seen = False
    for lat, lon in points:
        seen = True
        min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
        min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)
    return (min_lon, min_lat, max_lon, max_lat) if seen else None


def lerp_position(
    a: tuple[float, float], b: tuple[float, float], ratio: float
) -> tuple[float, float]:
    """Great-circle interpolation. Falls back to planar lerp for short hops,
    where the difference is far below GPS noise."""
    if haversine_m(a[0], a[1], b[0], b[1]) < 10_000:
        return (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(
        math.sqrt(
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
    )
    if d == 0:
        return a
    A = math.sin((1 - ratio) * d) / math.sin(d)
    B = math.sin(ratio * d) / math.sin(d)
    x = A * math.cos(lat1) * math.cos(lon1) + B * math.cos(lat2) * math.cos(lon2)
    y = A * math.cos(lat1) * math.sin(lon1) + B * math.cos(lat2) * math.sin(lon2)
    z = A * math.sin(lat1) + B * math.sin(lat2)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))
