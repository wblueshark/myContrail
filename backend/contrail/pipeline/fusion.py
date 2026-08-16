"""Fusing the four Google record streams into complete Tracks and Places.

`activity` carries semantics but no path. `timelinePath` carries a path but no
semantics whatsoever. Measured: 91% of activities overlap at least one
timelinePath record, so joining them on the time window yields travel mode AND
real geometry at once.

Without this step every byte of data after 2016-11 loses half its information:
either the route is a straight line between endpoints, or the route exists but
nobody knows how it was travelled.

The second job here is coverage. `visit` alone accounts for 67.3% of the
13-year timeline and visit+activity for 75.6%. Those stretches must NOT be
re-clustered - Google already segmented them, and our clustering would be both
slower and worse. Only the remaining ~24% goes through clustering.py.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

from contrail.core.geo import haversine_m, path_length_m
from contrail.parsers.base import PlaceHint, TrackHint
from contrail.pipeline.types import Move, Pt, Stay

# Padding around a declared interval when deciding whether a raw point is
# already accounted for.
COVERAGE_PAD = timedelta(seconds=60)


def fuse_activity_geometry(hints: list[TrackHint], points: list[Pt]) -> list[Move]:
    """Turn declared movements into Moves, borrowing geometry where possible."""
    ordered = sorted(points, key=lambda p: p.ts)
    timestamps = [p.ts for p in ordered]
    moves: list[Move] = []

    for hint in hints:
        lo = bisect_left(timestamps, hint.start_utc)
        hi = bisect_right(timestamps, hint.end_utc)
        window = ordered[lo:hi]

        if len(window) >= 2:
            coords = [(p.lat, p.lon) for p in window]
            # Our own Haversine sum is more trustworthy than Google's figure,
            # which is missing or zero for a large share of segments.
            distance = path_length_m(coords)
            quality = "full"
            unknown = False
        else:
            coords = list(hint.points)
            distance = hint.distance_m
            quality = "endpoints_only"
            # A missing distance stays missing. Recording 0 would quietly fold
            # unknown mileage into the totals as though it had been measured.
            unknown = distance is None

        if len(coords) < 2:
            continue

        duration = max(int((hint.end_utc - hint.start_utc).total_seconds()), 1)
        speeds = _speeds(window) if len(window) >= 2 else None
        moves.append(
            Move(
                start=hint.start_utc,
                end=hint.end_utc,
                points=coords,
                distance_m=distance,
                distance_unknown=unknown,
                duration_s=duration,
                speed_median_mps=_percentile(speeds, 0.5) if speeds else _mean_speed(
                    distance, duration
                ),
                speed_p95_mps=_percentile(speeds, 0.95) if speeds else _mean_speed(
                    distance, duration
                ),
                mode=hint.mode,
                mode_source=hint.mode_source,
                mode_confidence=hint.mode_confidence,
                geom_quality=quality,
                point_count=len(coords),
                source_kind="google_timeline",
            )
        )
    return moves


def stays_from_hints(hints: list[PlaceHint]) -> list[Stay]:
    """Adopt declared stays verbatim: no clustering, no second-guessing."""
    return [
        Stay(
            lat=hint.lat,
            lon=hint.lon,
            start=hint.start_utc,
            end=hint.end_utc,
            point_count=1,
            tz_name=hint.tz_name,
            name=hint.name,
            google_place_id=hint.google_place_id,
            semantic_type=hint.semantic_type,
            origin="track",
            source_kinds=["google_timeline"],
        )
        for hint in hints
    ]


def covered_intervals(
    place_hints: list[PlaceHint], track_hints: list[TrackHint]
) -> list[tuple[datetime, datetime]]:
    """Merged time intervals for which the source already provided semantics."""
    spans = [(h.start_utc, h.end_utc) for h in place_hints]
    spans += [(h.start_utc, h.end_utc) for h in track_hints]
    if not spans:
        return []
    spans.sort()
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1] + COVERAGE_PAD:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def uncovered_points(points: list[Pt], intervals: list[tuple[datetime, datetime]]) -> list[Pt]:
    """Points that no declared stay or movement already explains.

    These are the only ones our own clustering has to look at.
    """
    if not intervals:
        return sorted(points, key=lambda p: p.ts)
    starts = [start for start, _ in intervals]
    out: list[Pt] = []
    for point in sorted(points, key=lambda p: p.ts):
        idx = bisect_right(starts, point.ts) - 1
        if idx >= 0 and intervals[idx][0] <= point.ts <= intervals[idx][1]:
            continue
        out.append(point)
    return out


def _speeds(points: list[Pt]) -> list[float]:
    speeds: list[float] = []
    for a, b in zip(points, points[1:], strict=False):
        dt = (b.ts - a.ts).total_seconds()
        if dt > 0:
            speeds.append(haversine_m(a.lat, a.lon, b.lat, b.lon) / dt)
    return speeds


def _mean_speed(distance_m: float | None, duration_s: int) -> float | None:
    if distance_m is None or duration_s <= 0:
        return None
    return distance_m / duration_s


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]
