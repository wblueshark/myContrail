"""Three-layer deduplication, coarse to fine.

L1  file level   SHA-256 of the whole file -> "already imported"
L2  point level  hash(user, second, lat5, lon5) -> unique index on raw_point
L3  trip level   same-day data from several sources lands in one day_trip;
                 mileage picks a primary source per time interval (section 10.2)

A correction that matters for expectations: L2's real reach is ONLY "the same
file imported twice" and "duplicates inside one file". Cross-source hit rate is
ZERO, measured:

    Google timelinePath time resolution = 60 s (whole-minute offsets)
    photo EXIF time resolution          =  1 s
    spatial offset between the two at the same instant = 6-76 m (4 samples)
                                     >> the 1.1 m that 5 decimals represents

Two sources will essentially never agree on the same second AND the same
1-metre cell. Cross-source overlap is handled by L3 and by the Place
association rules, never by L2.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

# 5 decimal places ~ 1.1 m.
COORD_PRECISION = 5


def point_dedup_key(user_id: UUID | str, ts_utc: datetime, lat: float, lon: float) -> bytes:
    """L2 key. Timestamps round to the second, coordinates to ~1.1 m."""
    payload = "|".join(
        (
            str(user_id),
            str(int(ts_utc.timestamp())),
            f"{round(lat, COORD_PRECISION):.5f}",
            f"{round(lon, COORD_PRECISION):.5f}",
        )
    )
    return hashlib.sha256(payload.encode()).digest()


def content_hash_bytes(data: bytes) -> bytes:
    """L1 key for content already in memory (uploads, photo bytes)."""
    return hashlib.sha256(data).digest()


def prefer_more_accurate(
    existing_accuracy_m: float | None, incoming_accuracy_m: float | None
) -> bool:
    """On a unique-index collision, keep the more accurate reading.

    NULL means "unknown", which loses to any real measurement - but two unknowns
    keep the row already stored, so re-importing is idempotent.
    """
    if incoming_accuracy_m is None:
        return False
    if existing_accuracy_m is None:
        return True
    return incoming_accuracy_m < existing_accuracy_m
