"""Day-Trip generation.

v1.0's "group by a 6-hour gap" rule was discarded outright. A Trip is now
exactly one local day. Verified against 4,072 real points: 61 days produced 61
day-trips (56 spanning 12-24 h, 4 over 24 h - all timezone-crossing days, 1
under 12 h) and zero ghost 0 km segments.

Two choices carry the whole design:

    the zone comes from the DEPARTURE point, not the arrival point
    the day comes from the event's START instant, not its end

Together they keep a timezone-crossing flight whole. A flight leaving Tokyo at
09:53 JST lands in New York on a local date that may be a different day, but the
whole segment belongs to the day it STARTED. The price is that such a Trip can
exceed 24 hours - 37 h in the measured worst case - which is correct, not a bug.

Splitting rules at local midnight:
    Place -> split (a stay is spatially homogeneous, cutting it loses nothing)
    Track -> NEVER split (cutting a journey in half destroys it)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from contrail.core.timezones import local_date, local_midnight_utc, tz_at
from contrail.pipeline.types import Move, Stay

# Below this, two consecutive stays are treated as contiguous rather than as
# having a movement between them.
MIN_IMPLIED_MOVE_S = 60

# User-facing product copy, not a code string: this is the generated Trip title
# shown in the Chinese UI, in the same category as a geocoded place name.
# See docs/design/04-data-contract section 10.3.
COMMUTE_TITLE = "通勤"


@dataclass(slots=True)
class DayTrip:
    local_date: date
    anchor_tz: str
    stays: list[Stay] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)
    photo_count: int = 0

    @property
    def start_utc(self) -> datetime:
        return min(
            [s.start for s in self.stays] + [m.start for m in self.moves],
            default=datetime.min,
        )

    @property
    def end_utc(self) -> datetime:
        return max(
            [s.end for s in self.stays] + [m.end for m in self.moves],
            default=datetime.min,
        )


def build_day_trips(
    stays: list[Stay],
    moves: list[Move],
    photo_times: list[datetime] | None = None,
) -> list[DayTrip]:
    """Assign stays and moves to local days.

    A Trip only exists if it holds at least one Place or at least one photo -
    a day of nothing but a single unexplained movement is not a trip.
    """
    photo_times = photo_times or []
    buckets: dict[date, DayTrip] = {}
    # (start instant, is_stay) so the day's anchor zone comes from whichever
    # event genuinely happened first.
    ordered: list[tuple[datetime, str, object, str]] = []

    for stay in stays:
        tz_name = stay.tz_name or tz_at(stay.lat, stay.lon) or "UTC"
        for piece in _split_stay_at_local_midnight(stay, tz_name):
            ordered.append((piece.start, "stay", piece, tz_name))

    for move in moves:
        if not move.points:
            continue
        origin = move.points[0]
        destination = move.points[-1]
        # The zone of the DEPARTURE point decides the day.
        tz_name = tz_at(origin[0], origin[1]) or "UTC"
        end_tz = tz_at(destination[0], destination[1]) or tz_name
        move.crosses_tz = end_tz != tz_name
        ordered.append((move.start, "move", move, tz_name))

    ordered.sort(key=lambda item: item[0])

    for start, kind, obj, tz_name in ordered:
        day = local_date(start, tz_name)
        trip = buckets.get(day)
        if trip is None:
            trip = buckets[day] = DayTrip(local_date=day, anchor_tz=tz_name)
        if kind == "stay":
            obj.tz_name = obj.tz_name or tz_name
            trip.stays.append(obj)
        else:
            trip.moves.append(obj)

    for taken in photo_times:
        day = _day_for_photo(taken, buckets)
        trip = buckets.get(day)
        if trip is None:
            # A photo-only day: no track data at all for this date.
            trip = buckets[day] = DayTrip(local_date=day, anchor_tz="UTC")
        trip.photo_count += 1

    return [
        trip
        for _, trip in sorted(buckets.items())
        if trip.stays or trip.photo_count  # Step 4: a Trip needs a Place or a photo
    ]


def _day_for_photo(taken: datetime, buckets: dict[date, DayTrip]) -> date:
    """Place a photo on the day whose span contains it, else on its UTC date."""
    for day, trip in buckets.items():
        if (trip.stays or trip.moves) and trip.start_utc <= taken <= trip.end_utc:
            return day
    return taken.date()


def _split_stay_at_local_midnight(stay: Stay, tz_name: str) -> list[Stay]:
    """Cut a stay at each local midnight it crosses."""
    first_day = local_date(stay.start, tz_name)
    last_day = local_date(stay.end, tz_name)
    if first_day == last_day:
        stay.tz_name = stay.tz_name or tz_name
        return [stay]

    pieces: list[Stay] = []
    cursor = stay.start
    day = first_day
    while day < last_day:
        boundary = local_midnight_utc(day + timedelta(days=1), tz_name)
        if boundary <= cursor:
            day += timedelta(days=1)
            continue
        pieces.append(_slice_stay(stay, cursor, min(boundary, stay.end), tz_name))
        cursor = boundary
        day += timedelta(days=1)
    if cursor < stay.end:
        pieces.append(_slice_stay(stay, cursor, stay.end, tz_name))
    return pieces or [stay]


def _slice_stay(stay: Stay, start: datetime, end: datetime, tz_name: str) -> Stay:
    return Stay(
        lat=stay.lat,
        lon=stay.lon,
        start=start,
        end=end,
        radius_m=stay.radius_m,
        point_count=stay.point_count,
        is_inferred_dwell=stay.is_inferred_dwell,
        inferred_ratio=stay.inferred_ratio,
        origin=stay.origin,
        tz_name=tz_name,
        name=stay.name,
        google_place_id=stay.google_place_id,
        semantic_type=stay.semantic_type,
        source_kinds=list(stay.source_kinds),
    )


def insert_implied_moves(stays: list[Stay], moves: list[Move]) -> list[Move]:
    """Step 1: bridge consecutive stays that have no movement between them.

    Only gaps longer than MIN_IMPLIED_MOVE_S get a segment; anything shorter is
    clustering noise, and drawing it would recreate the ghost 0 km segments that
    merge_adjacent_stays exists to eliminate.
    """
    if len(stays) < 2:
        return moves
    covered = sorted((m.start, m.end) for m in moves)
    added: list[Move] = []
    for a, b in zip(stays, stays[1:], strict=False):
        gap = (b.start - a.end).total_seconds()
        if gap <= MIN_IMPLIED_MOVE_S:
            continue
        if any(start < b.start and end > a.end for start, end in covered):
            continue
        added.append(
            Move(
                start=a.end,
                end=b.start,
                points=[(a.lat, a.lon), (b.lat, b.lon)],
                distance_m=None,
                distance_unknown=True,
                duration_s=int(gap),
                geom_quality="endpoints_only",
                point_count=2,
            )
        )
    return sorted(moves + added, key=lambda m: m.start)


def make_title(
    trip: DayTrip,
    city_durations: dict[str, float] | None = None,
    countries: list[str] | None = None,
    is_pure_commute: bool = False,
) -> str:
    """Title template, degrading as information runs out (section 10.3).

    The title is metadata: the user may overwrite it at any time (P7).
    """
    stamp = trip.local_date.strftime("%m-%d")
    countries = [c for c in (countries or []) if c]
    if len(set(countries)) >= 2:
        return f"{countries[0]} → {countries[-1]} · {stamp}"
    if city_durations:
        # "Main city" = the city with the longest accumulated dwell.
        main = max(city_durations.items(), key=lambda kv: kv[1])[0]
        if main:
            return f"{main} · {stamp}"
    if is_pure_commute:
        return f"{COMMUTE_TITLE} · {stamp}"
    return trip.local_date.strftime("%Y-%m-%d")
