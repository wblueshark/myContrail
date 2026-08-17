"""Commute detection.

No large language model is involved, and that is a deliberate decision rather
than a cost saving. Every criterion below is a computable statistic - visit
frequency, weekday share, circular variance of departure hour, path similarity -
so the result is explainable, tunable and reproducible. More importantly,
sending a user's position sequence to a third-party model would overturn the
product's entire privacy premise. This runs fully offline with zero external
requests.

Marking happens at TRACK level and is only summarised at trip level. A workday
often looks like "commute in, work, concert, commute home". If the commute flag
lived on the Trip, "delete commute trips" would delete the concert too - an
irreversible loss of exactly the data the user cares about.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from contrail.core.geo import geohash
from contrail.core.timezones import to_local

# Cold start: below this the detector does not run at all. Sample/ is two months
# of mostly travel and WILL hit this branch - that is correct behaviour, and it
# also means commute detection cannot be validated with the current sample.
MIN_WORKDAYS = 30

MIN_OCCURRENCE = 10
MIN_DISTINCT_WORKDAYS = 8
MIN_WEEKDAY_RATIO = 0.8
MAX_DEPART_HOUR_CIRCSTD = 1.5
MIN_PATH_JACCARD = 0.6
PATH_GEOHASH_PRECISION = 6

# A trip is "pure commute" when almost nothing else happened that day.
PURE_OTHER_DWELL_SHARE = 0.15


@dataclass(slots=True)
class CommuteLeg:
    """One observed movement between two anchors."""

    track_id: str
    from_anchor: str
    to_anchor: str
    depart_utc: datetime
    tz_name: str | None
    path: list[tuple[float, float]]
    distance_m: float | None = None
    duration_s: int = 0


@dataclass(slots=True)
class ODResult:
    from_anchor: str
    to_anchor: str
    occurrence: int
    weekday_ratio: float
    depart_hour_mean: float
    depart_hour_circstd: float
    path_jaccard: float
    track_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def circular_hour_stats(hours: list[float]) -> tuple[float, float]:
    """Mean and standard deviation on a 24-hour circle.

    A plain average of 23:50 and 00:10 is 12:00, which would make a perfectly
    regular night commute look maximally irregular.
    """
    if not hours:
        return 0.0, 0.0
    angles = [h / 24.0 * 2 * math.pi for h in hours]
    sin_mean = sum(math.sin(a) for a in angles) / len(angles)
    cos_mean = sum(math.cos(a) for a in angles) / len(angles)
    r = math.hypot(sin_mean, cos_mean)
    mean_angle = math.atan2(sin_mean, cos_mean) % (2 * math.pi)
    mean_hour = mean_angle / (2 * math.pi) * 24.0
    if r <= 1e-12:
        return mean_hour, 24.0
    circstd_rad = math.sqrt(-2.0 * math.log(min(1.0, r)))
    return mean_hour, circstd_rad / (2 * math.pi) * 24.0


def path_similarity(paths: list[list[tuple[float, float]]]) -> float:
    """Median pairwise Jaccard similarity over the geohash6 cells traversed.

    Far cheaper than a Frechet distance and considerably more robust to GPS
    noise, which is what actually varies between two runs of the same route.
    """
    cell_sets = [
        {geohash(lat, lon, PATH_GEOHASH_PRECISION) for lat, lon in path} for path in paths if path
    ]
    if len(cell_sets) < 2:
        return 1.0 if cell_sets else 0.0
    scores: list[float] = []
    for i in range(len(cell_sets)):
        for j in range(i + 1, len(cell_sets)):
            union = cell_sets[i] | cell_sets[j]
            if union:
                scores.append(len(cell_sets[i] & cell_sets[j]) / len(union))
    if not scores:
        return 0.0
    scores.sort()
    return scores[len(scores) // 2]


def detect_commute_ods(
    legs: list[CommuteLeg],
    home_work_anchors: set[str] | None = None,
    workday_count: int | None = None,
    min_occurrence: int = MIN_OCCURRENCE,
) -> list[ODResult]:
    """Find directed anchor pairs that behave like a commute.

    All of these must hold:
      1. seen >= 10 times across >= 8 distinct weekdays
      2. weekday share >= 0.8
      3. departure hour is tight: circular stddev <= 1.5 h
      4. the route is stable: median geohash6 Jaccard > 0.6
      5. bonus - one end is the inferred home or work
    """
    if workday_count is not None and workday_count < MIN_WORKDAYS:
        return []

    grouped: dict[tuple[str, str], list[CommuteLeg]] = defaultdict(list)
    for leg in legs:
        if leg.from_anchor and leg.to_anchor and leg.from_anchor != leg.to_anchor:
            grouped[(leg.from_anchor, leg.to_anchor)].append(leg)

    results: list[ODResult] = []
    for (origin, destination), pair_legs in grouped.items():
        if len(pair_legs) < min_occurrence:
            continue

        locals_ = [to_local(leg.depart_utc, leg.tz_name) for leg in pair_legs]
        weekday_dates = {dt.date() for dt in locals_ if dt.weekday() < 5}
        if len(weekday_dates) < MIN_DISTINCT_WORKDAYS:
            continue

        weekday_ratio = sum(1 for dt in locals_ if dt.weekday() < 5) / len(locals_)
        if weekday_ratio < MIN_WEEKDAY_RATIO:
            continue

        mean_hour, circstd = circular_hour_stats([dt.hour + dt.minute / 60.0 for dt in locals_])
        if circstd > MAX_DEPART_HOUR_CIRCSTD:
            continue

        jaccard = path_similarity([leg.path for leg in pair_legs])
        anchors_are_home_work = bool(
            home_work_anchors and (origin in home_work_anchors or destination in home_work_anchors)
        )
        # Criterion 5 is a bonus, not a gate: it relaxes the path threshold for
        # a pair that already looks like home <-> work.
        threshold = MIN_PATH_JACCARD * (0.85 if anchors_are_home_work else 1.0)
        if jaccard < threshold:
            continue

        distances = [leg.distance_m for leg in pair_legs if leg.distance_m is not None]
        results.append(
            ODResult(
                from_anchor=origin,
                to_anchor=destination,
                occurrence=len(pair_legs),
                weekday_ratio=weekday_ratio,
                depart_hour_mean=mean_hour,
                depart_hour_circstd=circstd,
                path_jaccard=jaccard,
                track_ids=[leg.track_id for leg in pair_legs],
                evidence={
                    "sample_dates": sorted({dt.date().isoformat() for dt in locals_})[:5],
                    "median_distance_m": (
                        sorted(distances)[len(distances) // 2] if distances else None
                    ),
                    "distance_unknown_count": len(pair_legs) - len(distances),
                    # Sum of the KNOWN distances only. A leg with no distance
                    # contributes nothing here and is counted above instead -
                    # folding it in as zero would understate the total silently.
                    "total_distance_m": sum(distances) if distances else None,
                    "median_duration_s": (
                        sorted(leg.duration_s for leg in pair_legs)[len(pair_legs) // 2]
                    ),
                    # The span this pair covers, in local dates: the card reads
                    # "2024-03 ~ 2026-05" and nothing else can produce it.
                    "first_seen": min(locals_).date().isoformat(),
                    "last_seen": max(locals_).date().isoformat(),
                    "anchor_is_home_or_work": anchors_are_home_work,
                },
            )
        )
    return results


def classify_trip(
    commute_dwell_s: float,
    other_dwell_s: float,
    photo_count: int,
    has_commute_track: bool,
) -> str:
    """Summarise a day.

    pure  - nothing but the commute: other dwell < 15% and no photos that day
    mixed - a commute happened, but so did other things
    none  - no commute at all
    """
    if not has_commute_track:
        return "none"
    total = commute_dwell_s + other_dwell_s
    other_share = (other_dwell_s / total) if total > 0 else 0.0
    if other_share < PURE_OTHER_DWELL_SHARE and photo_count == 0:
        return "pure"
    return "mixed"
