"""Timezone resolution from coordinates.

timezonefinder is a required dependency, not an optional one: Google's
`timelinePath` records carry UTC-only timestamps ("...Z"), so the zone can only
come from the coordinates.

Do NOT look up zones for semantic-era records (`visit` / `activity`) - those
timestamps already carry an authoritative local offset.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

# Semantic-era Google records and EXIF OffsetTimeOriginal give an OFFSET, not a
# zone name, and it is authoritative. It is carried as "UTC+09:00", which is not
# an IANA name - resolving it must not silently degrade to UTC, or every day
# boundary shifts by the offset and cross-midnight stays land on the wrong day.
_FIXED_OFFSET_RE = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")


@lru_cache(maxsize=1)
def _finder():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder(in_memory=True)


@lru_cache(maxsize=100_000)
def _lookup(lat_q: float, lon_q: float) -> str | None:
    return _finder().timezone_at(lat=lat_q, lng=lon_q)


def tz_at(lat: float, lon: float) -> str | None:
    """IANA zone name for a coordinate, or an Etc/GMT fallback over open ocean.

    Coordinates are quantised to ~1 km before the lookup so the cache actually
    hits; zone polygons never change meaningfully at that scale.
    """
    name = _lookup(round(lat, 2), round(lon, 2))
    if name:
        return name
    # timezonefinder returns None mid-ocean. Fall back to a longitude estimate
    # rather than silently dropping the record.
    offset = int(math.floor(lon / 15.0 + 0.5))
    offset = max(-12, min(14, offset))
    # Etc/GMT signs are inverted relative to UTC offsets: Etc/GMT-9 is UTC+9.
    return f"Etc/GMT{-offset:+d}" if offset else "Etc/GMT"


@lru_cache(maxsize=1024)
def zone(name: str | None) -> ZoneInfo | timezone:
    """Resolve a zone name or a fixed-offset label to a tzinfo.

    Handles both IANA names ("Asia/Tokyo") and the fixed-offset form
    ("UTC+09:00") produced from a record's own UTC offset. Unknown input falls
    back to UTC so a malformed name cannot abort an import.
    """
    if not name:
        return UTC

    match = _FIXED_OFFSET_RE.match(name)
    if match:
        sign, hours, minutes = match.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes))
        return timezone(-delta if sign == "-" else delta, name)

    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - unknown zone names must not abort an import
        return UTC


def to_local(ts: datetime, tz_name: str | None) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(zone(tz_name))


def local_date(ts: datetime, tz_name: str | None) -> date:
    return to_local(ts, tz_name).date()


def local_midnight_utc(d: date, tz_name: str | None) -> datetime:
    """UTC instant of local midnight starting day `d`.

    `fold=0` resolves the ambiguous hour during a DST fall-back consistently.
    """
    naive = datetime(d.year, d.month, d.day, 0, 0, 0, fold=0)
    return naive.replace(tzinfo=zone(tz_name)).astimezone(UTC)
