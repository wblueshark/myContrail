"""Stay-point clustering: roaming-distance temporal clustering.

DBSCAN is deliberately NOT used here. DBSCAN ignores time, so two separate
visits to the same cafe collapse into one cluster and the product loses the
thing it exists to show - that these were two different events. (DBSCAN IS the
right tool one level up, in anchors.py, where merging across time is the goal.)

The one change that matters most, and the reason the v1.0 rule was thrown out:

    GAP is a SPACETIME criterion, not a time threshold.

Measured on a real 61-day subset containing only timelinePath records:

    1,450.8 h spanned, of which 686 h (47%) contain no points at all
      263 gaps longer than 1 h:
        236 gaps (1,078 h total) have endpoints < 150 m apart  <- these ARE stays
         27 gaps have endpoints that genuinely moved           <- real data loss

89.7% of long gaps have both ends in the same place, because Google's
timelinePath emits almost nothing while stationary. In this source a stay shows
up as the ABSENCE of data, not as a dense cluster of it.

    rule                         places   covered      share
    v1.0 (GAP always breaks)        188    138.7 h       9.6%
    v2.0 (spacetime criterion)      218  1,190.4 h      82.0%

Under the old rule a user importing two months of history would be told that in
61 days they were "somewhere" for 139 hours, and neither moving nor staying for
the other 91% - a map full of holes.

Scope: this only runs for stretches with no Google `visit` coverage (~24% of the
13-year timeline), plus GPX/TCX/FIT and photos. Where Google already declared a
stay, that segmentation is used as-is.
"""

from __future__ import annotations

import math
from datetime import timedelta

from contrail.core.geo import haversine_m, path_length_m
from contrail.pipeline.types import Move, Pt, Stay

DEFAULT_R = 150.0
DEFAULT_T = 900
DEFAULT_GAP = 3600
DEFAULT_MAX_INFERRED_STAY = 86400
MIN_MOVE_POINTS = 3
MIN_MOVE_DISTANCE_M = 100.0


class _Centroid:
    """O(1) incremental spherical mean with an upper-bounded radius check.

    The naive version recomputes max-distance-to-centroid over the whole
    candidate set on every step: O(n * k**2). Since v2.0 stopped breaking
    clusters at every gap, a single cluster can span a whole night, k reaches
    the hundreds, and the k**2 term dominates the entire import.

    Here the exact max distance is recomputed only when the centroid has
    drifted far enough that the cached bound could be stale.
    """

    __slots__ = ("_x", "_y", "_z", "_n", "_max_dist", "_drift", "_ref")

    def __init__(self) -> None:
        self._x = self._y = self._z = 0.0
        self._n = 0
        self._max_dist = 0.0
        self._drift = 0.0
        self._ref: tuple[float, float] | None = None

    @property
    def n(self) -> int:
        return self._n

    def _position(self) -> tuple[float, float]:
        x, y, z = self._x / self._n, self._y / self._n, self._z / self._n
        return (
            math.degrees(math.atan2(z, math.hypot(x, y))),
            math.degrees(math.atan2(y, x)),
        )

    def add(self, p: Pt) -> None:
        rlat, rlon = math.radians(p.lat), math.radians(p.lon)
        self._x += math.cos(rlat) * math.cos(rlon)
        self._y += math.cos(rlat) * math.sin(rlon)
        self._z += math.sin(rlat)
        self._n += 1
        pos = self._position()
        if self._ref is not None:
            self._drift += haversine_m(self._ref[0], self._ref[1], pos[0], pos[1])
        self._ref = pos

    def remove(self, p: Pt) -> None:
        rlat, rlon = math.radians(p.lat), math.radians(p.lon)
        self._x -= math.cos(rlat) * math.cos(rlon)
        self._y -= math.cos(rlat) * math.sin(rlon)
        self._z -= math.sin(rlat)
        self._n -= 1
        self._ref = self._position() if self._n else None

    def position(self) -> tuple[float, float]:
        return self._position()

    def within(self, points: list[Pt], radius_m: float) -> bool:
        """True if every point lies within radius_m of the current centroid.

        `_max_dist` was measured against an older centroid position, so
        `_max_dist + _drift` is a conservative upper bound for the current one.
        When that bound already proves containment, only the newly added point
        needs measuring and the O(k) sweep is skipped entirely.
        """
        lat, lon = self._position()
        newest = points[-1]
        d_new = haversine_m(lat, lon, newest.lat, newest.lon)
        if self._max_dist + self._drift <= radius_m and d_new <= radius_m:
            self._max_dist = max(self._max_dist, d_new)
            return True
        # The bound is stale or violated: settle it exactly and reset the drift.
        self._max_dist = max(haversine_m(lat, lon, p.lat, p.lon) for p in points)
        self._drift = 0.0
        return self._max_dist <= radius_m

    def radius(self, points: list[Pt]) -> float:
        lat, lon = self._position()
        return max((haversine_m(lat, lon, p.lat, p.lon) for p in points), default=0.0)


def cluster_stays(
    points: list[Pt],
    r_m: float = DEFAULT_R,
    min_dwell_s: int = DEFAULT_T,
    gap_s: int = DEFAULT_GAP,
    max_inferred_stay_s: int = DEFAULT_MAX_INFERRED_STAY,
    min_points: int = 2,
    accuracy_max_m: float | None = None,
) -> tuple[list[Stay], list[Pt]]:
    """Split a time-ordered point sequence into stays and leftover moving points.

    `points` must be sorted by timestamp. `min_points=1` is used for photos,
    where a single isolated frame is still a place.

    Returns (stays, moving_points); moving points are handed to build_moves().
    """
    if accuracy_max_m is not None:
        # Note: Google timeline records carry no accuracy at all, so this filter
        # is a no-op for that source. It matters for phone GPS and Records.json.
        points = [p for p in points if p.accuracy_m is None or p.accuracy_m <= accuracy_max_m]
    if not points:
        return [], []

    stays: list[Stay] = []
    moving: list[Pt] = []
    i, n = 0, len(points)

    while i < n:
        j = i
        inferred_s = 0.0
        centroid = _Centroid()
        centroid.add(points[i])

        while j + 1 < n:
            gap = (points[j + 1].ts - points[j].ts).total_seconds()
            pending_gap = 0.0
            if gap > gap_s:
                d = haversine_m(
                    points[j].lat, points[j].lon, points[j + 1].lat, points[j + 1].lon
                )
                # The spacetime criterion. A long gap only breaks the cluster if
                # the two ends are actually in different places - or if it is so
                # long that calling it one stay would be absurd (a week with the
                # phone off is not a week-long visit).
                if d >= r_m or gap > max_inferred_stay_s:
                    break
                pending_gap = gap

            candidate = points[i : j + 2]
            centroid.add(points[j + 1])
            if not centroid.within(candidate, r_m):
                centroid.remove(points[j + 1])
                break

            # Only count the gap once the extended cluster has been accepted.
            inferred_s += pending_gap
            j += 1

        window = points[i : j + 1]
        dwell = (points[j].ts - points[i].ts).total_seconds()
        if dwell >= min_dwell_s and len(window) >= min_points:
            lat, lon = centroid.position()
            stays.append(
                Stay(
                    lat=lat,
                    lon=lon,
                    start=points[i].ts,
                    end=points[j].ts,
                    radius_m=centroid.radius(window),
                    point_count=len(window),
                    is_inferred_dwell=inferred_s > 0,
                    inferred_ratio=inferred_s / max(dwell, 1.0),
                    source_kinds=sorted({p.source_kind for p in window}),
                )
            )
            i = j + 1
        else:
            moving.append(points[i])
            i += 1

    return merge_adjacent_stays(stays, r_m, max_inferred_stay_s), moving


def merge_adjacent_stays(
    stays: list[Stay],
    r_m: float = DEFAULT_R,
    max_gap_s: int = DEFAULT_MAX_INFERRED_STAY,
) -> list[Stay]:
    """Merge consecutive stays whose centroids are closer than R.

    Not optional. Without it the same location gets split into two Places with a
    zero-displacement "movement" wedged between them - a ghost 0 km segment.
    Measured: 218 stays before merging, 189 after, ghost segments down to zero.

    `max_gap_s` is what keeps this from undoing the point of the algorithm.
    Proximity alone is not enough: two visits to the same flat a week apart are
    two events, and merging them across that gap would reintroduce exactly the
    time-blindness that made DBSCAN the wrong tool here. The bound matches the
    threshold that broke the cluster in the first place, so the two rules cannot
    disagree.
    """
    if not stays:
        return []
    merged = [stays[0]]
    for stay in stays[1:]:
        prev = merged[-1]
        contiguous = (stay.start - prev.end).total_seconds() <= max_gap_s
        if contiguous and haversine_m(prev.lat, prev.lon, stay.lat, stay.lon) < r_m:
            total = prev.point_count + stay.point_count or 1
            weight = prev.point_count / total
            prev.lat = prev.lat * weight + stay.lat * (1 - weight)
            prev.lon = prev.lon * weight + stay.lon * (1 - weight)
            prev.end = max(prev.end, stay.end)
            prev.point_count = total
            prev.radius_m = max(prev.radius_m, stay.radius_m)
            prev.is_inferred_dwell = prev.is_inferred_dwell or stay.is_inferred_dwell
            prev.inferred_ratio = max(prev.inferred_ratio, stay.inferred_ratio)
            prev.source_kinds = sorted(set(prev.source_kinds) | set(stay.source_kinds))
        else:
            merged.append(stay)
    return merged


def build_moves(
    moving: list[Pt],
    stays: list[Stay],
    gap_s: int = DEFAULT_GAP,
    min_points: int = MIN_MOVE_POINTS,
    min_distance_m: float = MIN_MOVE_DISTANCE_M,
) -> list[Move]:
    """Turn leftover points into movement segments.

    1. cut into runs wherever the inter-point gap exceeds GAP
    2. attach the neighbouring stay centroids so the drawn path joins up
    3. drop runs that are too short or too small to be real movement
    """
    if not moving:
        return []

    runs: list[list[Pt]] = [[moving[0]]]
    for point in moving[1:]:
        if (point.ts - runs[-1][-1].ts).total_seconds() > gap_s:
            runs.append([point])
        else:
            runs[-1].append(point)

    moves: list[Move] = []
    for run in runs:
        if len(run) < min_points:
            continue
        coords = [(p.lat, p.lon) for p in run]
        before = _stay_ending_before(stays, run[0])
        after = _stay_starting_after(stays, run[-1])
        if before is not None:
            coords.insert(0, (before.lat, before.lon))
        if after is not None:
            coords.append((after.lat, after.lon))

        distance = path_length_m(coords)
        if distance < min_distance_m:
            continue
        duration = max(int((run[-1].ts - run[0].ts).total_seconds()), 1)
        speeds = _segment_speeds(run)
        moves.append(
            Move(
                start=run[0].ts,
                end=run[-1].ts,
                points=coords,
                distance_m=distance,
                duration_s=duration,
                speed_median_mps=_percentile(speeds, 0.5),
                speed_p95_mps=_percentile(speeds, 0.95),
                elevation_gain_m=_elevation_gain(run),
                geom_quality="full",
                point_count=len(coords),
                source_kind=run[0].source_kind,
            )
        )
    return moves


def _stay_ending_before(stays: list[Stay], point: Pt) -> Stay | None:
    candidates = [s for s in stays if s.end <= point.ts]
    return max(candidates, key=lambda s: s.end, default=None)


def _stay_starting_after(stays: list[Stay], point: Pt) -> Stay | None:
    candidates = [s for s in stays if s.start >= point.ts]
    return min(candidates, key=lambda s: s.start, default=None)


def _segment_speeds(points: list[Pt]) -> list[float]:
    speeds: list[float] = []
    for a, b in zip(points, points[1:], strict=False):
        dt = (b.ts - a.ts).total_seconds()
        if dt <= 0:
            continue
        speeds.append(haversine_m(a.lat, a.lon, b.lat, b.lon) / dt)
    return speeds


def _elevation_gain(points: list[Pt]) -> float | None:
    gain, prev = 0.0, None
    seen = False
    for p in points:
        if p.altitude_m is None:
            continue
        seen = True
        if prev is not None and p.altitude_m > prev:
            gain += p.altitude_m - prev
        prev = p.altitude_m
    return gain if seen else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def cluster_photo_stays(points: list[Pt], r_m: float = DEFAULT_R) -> list[Stay]:
    """Photos are sparse samples, so the dwell threshold does not apply.

    Consecutive photos within R become one Place regardless of time span, and a
    single isolated photo still produces a Place with point_count = 1 and an
    unknown duration.
    """
    if not points:
        return []
    stays: list[Stay] = []
    bucket: list[Pt] = [points[0]]
    for point in points[1:]:
        lat, lon = _mean(bucket)
        if haversine_m(lat, lon, point.lat, point.lon) <= r_m:
            bucket.append(point)
        else:
            stays.append(_photo_stay(bucket))
            bucket = [point]
    stays.append(_photo_stay(bucket))
    return stays


def _mean(points: list[Pt]) -> tuple[float, float]:
    return (
        sum(p.lat for p in points) / len(points),
        sum(p.lon for p in points) / len(points),
    )


def _photo_stay(bucket: list[Pt]) -> Stay:
    lat, lon = _mean(bucket)
    start, end = bucket[0].ts, bucket[-1].ts
    if start == end:
        end = start + timedelta(seconds=0)
    return Stay(
        lat=lat,
        lon=lon,
        start=start,
        end=end,
        radius_m=max((haversine_m(lat, lon, p.lat, p.lon) for p in bucket), default=0.0),
        point_count=len(bucket),
        origin="photo",
        source_kinds=["photo"],
    )
