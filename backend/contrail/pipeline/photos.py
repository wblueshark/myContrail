"""Photo handling: location inference and association with Trip Places.

The single easiest thing to get wrong in this product:

    a Trip's Place means  "I stopped here"
    a Photo's Place means "a photo of mine was taken here"

They are different entities and must never be merged into one record. If they
were, turning off the photo layer would make stay points vanish, undoing a photo
import would damage stay records derived from tracks, and "I was here two hours
and took no photos" would become indistinguishable from "I passed by and
snapped one frame".

The right relationship is a nullable association: the photo keeps its own place
intelligence, and photo.trip_place_id points at the Trip Place covering the same
time and location. That association is reliable - measured displacement between
a photo and the Google timeline at the same instant was 6 / 35 / 44 / 76 m, all
far below R = 150 m.

Two Places drawn at the same spot on the map is correct, not a duplicate bug:
they are two independent layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from contrail.core.geo import haversine_m, lerp_position
from contrail.pipeline.types import Pt

DEFAULT_TOLERANCE_S = 1800
# A one-sided neighbour is only trusted at a third of the tolerance: with a
# point on just one side there is no way to bound how far the user moved.
ONE_SIDED_DIVISOR = 3


@dataclass(slots=True)
class InferredLocation:
    lat: float
    lon: float
    confidence: str  # 'inferred'


def infer_photo_location(
    taken_at_utc: datetime,
    track_points: list[Pt],
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> InferredLocation | None:
    """Interpolate a position for a photo with no GPS.

    `track_points` must be sorted by timestamp. Inferred photos count towards
    "number of photos" but never towards mileage, and the UI must show them with
    a dashed border - a guess that looks like a measurement is worse than no
    answer at all.
    """
    before = after = None
    for point in track_points:
        if point.ts <= taken_at_utc:
            before = point
        else:
            after = point
            break

    if before is not None and after is not None:
        span = (after.ts - before.ts).total_seconds()
        if span <= tolerance_s * 2 and span > 0:
            ratio = (taken_at_utc - before.ts).total_seconds() / span
            lat, lon = lerp_position((before.lat, before.lon), (after.lat, after.lon), ratio)
            return InferredLocation(lat, lon, "inferred")

    for candidate in (before, after):
        if candidate is None:
            continue
        if abs((taken_at_utc - candidate.ts).total_seconds()) <= tolerance_s / ONE_SIDED_DIVISOR:
            return InferredLocation(candidate.lat, candidate.lon, "inferred")
    return None


@dataclass(slots=True)
class PlaceWindow:
    """The minimum a Trip Place needs to expose for photo association."""

    place_id: str
    lat: float
    lon: float
    start_utc: datetime
    end_utc: datetime


def associate_with_trip_place(
    photo_lat: float,
    photo_lon: float,
    taken_at_utc: datetime,
    places: list[PlaceWindow],
    radius_m: float = 150.0,
) -> str | None:
    """Find the Trip Place a photo belongs with. Association, never a merge.

    Criteria (04-data-contract section 8.5):
        taken_at_utc within [place.start_utc, place.end_utc]
        distance(photo, place.centroid) < R
    """
    best: tuple[float, str] | None = None
    for place in places:
        if not (place.start_utc <= taken_at_utc <= place.end_utc):
            continue
        distance = haversine_m(photo_lat, photo_lon, place.lat, place.lon)
        if distance < radius_m and (best is None or distance < best[0]):
            best = (distance, place.place_id)
    return best[1] if best else None


def resolve_missing_timezone(
    naive_local: datetime,
    track_points: list[Pt],
    default_tz: str,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
) -> tuple[datetime, str, str]:
    """Levels 4 and 5 of the photo time fallback chain.

    Level 4: adopt the zone of the nearest track point in time.
    Level 5: fall back to the user's default zone and flag the uncertainty.

    Returns (ts_utc, tz_name, tz_source).
    """
    from contrail.core.timezones import tz_at, zone

    nearest: Pt | None = None
    nearest_gap = float("inf")
    reference = naive_local.replace(tzinfo=UTC)
    for point in track_points:
        gap = abs((point.ts - reference).total_seconds())
        if gap < nearest_gap:
            nearest, nearest_gap = point, gap

    if nearest is not None and nearest_gap <= tolerance_s:
        tz_name = nearest.__dict__.get("tz_name") or tz_at(nearest.lat, nearest.lon) or default_tz
        source = "nearest_track"
    else:
        tz_name = default_tz
        source = "user_default"

    ts_utc = naive_local.replace(tzinfo=zone(tz_name)).astimezone(UTC)
    return ts_utc, tz_name, source
