"""Place anchors: merging repeated visits to one location.

This is a derived index, not a storage entity. It keeps aggregate statistics
only - never an individual visit - so deleting it loses nothing and it does not
violate "a Place is not stored twice". It is nonetheless the single landing
point for four features: home inference, work inference, commute OD detection
and geofence pre-fill. Without it, commute detection has nothing to stand on.

DBSCAN is the right algorithm HERE (the goal is to merge the same place across
time) and the wrong one in clustering.py (where separate visits must stay
separate). Both statements are true at once.

placeID cannot be used as the merge key on its own. Measured:

    276 visits -> 132 distinct placeIDs -> only 83 distinct coordinates
    same placeID  -> coordinate drift 0.0 m       (placeID -> coords is stable)
    same coords   -> many placeIDs                (28 "Inferred Home" visits
                                                   produced 28 different IDs)

Google mints a throwaway placeID for each visit to an inferred (non-POI) place.
So placeID is a strong merge HINT - equal IDs are certainly the same place - but
spatial clustering still has to run.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from contrail.core.geo import centroid as spherical_centroid
from contrail.core.geo import haversine_m
from contrail.core.timezones import to_local

ANCHOR_EPS_M = 150.0
ANCHOR_MIN_SAMPLES = 3
# A separate, coarser pass used when turning anchors into suggested fences:
# 24 measured "Home" coordinates are mostly the same address seen from the
# doorway, the car park and the shop downstairs.
FENCE_MERGE_EPS_M = 200.0

NIGHT_HOURS = set(range(22, 24)) | set(range(0, 6))
WORK_HOURS = set(range(9, 18))

GOOGLE_CONFIRMED = "google_confirmed"
GOOGLE_INFERRED = "google_inferred"
HEURISTIC = "heuristic"


@dataclass(slots=True)
class VisitRecord:
    """One stay, reduced to what anchor aggregation needs."""

    lat: float
    lon: float
    start_utc: datetime
    end_utc: datetime
    tz_name: str | None = None
    google_place_id: str | None = None
    semantic_type: str | None = None
    place_id: str | None = None


@dataclass(slots=True)
class Anchor:
    lat: float
    lon: float
    radius_m: float = 0.0
    visit_count: int = 0
    first_visit_utc: datetime | None = None
    last_visit_utc: datetime | None = None
    total_duration_s: int = 0
    hour_histogram: list[int] = field(default_factory=lambda: [0] * 24)
    weekday_ratio: float | None = None
    kind: str = "other"
    kind_source: str | None = None
    member_place_ids: list[str] = field(default_factory=list)


def _grid_key(lat: float, lon: float, cell_m: float) -> tuple[int, int]:
    lat_step = cell_m / 111_320.0
    lon_step = cell_m / max(1.0, 111_320.0 * math.cos(math.radians(lat)))
    return int(lat / lat_step), int(lon / lon_step)


def dbscan(
    visits: list[VisitRecord], eps_m: float = ANCHOR_EPS_M, min_samples: int = ANCHOR_MIN_SAMPLES
) -> list[list[int]]:
    """DBSCAN over visit centroids, indexed by a grid so it stays near-linear.

    Returns clusters as lists of indices into `visits`. Noise points become
    singleton clusters: a place visited twice is still a place, it just is not
    a "frequent" one.
    """
    if not visits:
        return []

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, v in enumerate(visits):
        grid[_grid_key(v.lat, v.lon, eps_m)].append(idx)

    def neighbours(idx: int) -> list[int]:
        v = visits[idx]
        key = _grid_key(v.lat, v.lon, eps_m)
        out: list[int] = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for other in grid.get((key[0] + dy, key[1] + dx), ()):
                    w = visits[other]
                    if haversine_m(v.lat, v.lon, w.lat, w.lon) <= eps_m:
                        out.append(other)
        return out

    labels: list[int] = [-1] * len(visits)
    visited = [False] * len(visits)
    clusters: list[list[int]] = []

    for idx in range(len(visits)):
        if visited[idx]:
            continue
        visited[idx] = True
        seeds = neighbours(idx)
        if len(seeds) < min_samples:
            clusters.append([idx])  # noise kept as its own place
            labels[idx] = len(clusters) - 1
            continue

        cluster_id = len(clusters)
        clusters.append([])
        queue = list(seeds)
        while queue:
            current = queue.pop()
            if labels[current] != -1:
                continue
            if not visited[current]:
                visited[current] = True
                expansion = neighbours(current)
                if len(expansion) >= min_samples:
                    queue.extend(expansion)
            labels[current] = cluster_id
            clusters[cluster_id].append(current)

    return [c for c in clusters if c]


def build_anchors(
    visits: list[VisitRecord],
    eps_m: float = ANCHOR_EPS_M,
    min_samples: int = ANCHOR_MIN_SAMPLES,
) -> list[Anchor]:
    """Aggregate visits into anchors, in LOCAL time throughout.

    Using UTC for the hour histogram would make "home" mean different clock
    hours in different countries, which defeats the whole purpose.
    """
    anchors: list[Anchor] = []
    for cluster in dbscan(visits, eps_m, min_samples):
        members = [visits[i] for i in cluster]
        lat, lon = spherical_centroid([(v.lat, v.lon) for v in members])
        anchor = Anchor(
            lat=lat,
            lon=lon,
            radius_m=max((haversine_m(lat, lon, v.lat, v.lon) for v in members), default=0.0),
            visit_count=len(members),
            first_visit_utc=min(v.start_utc for v in members),
            last_visit_utc=max(v.end_utc for v in members),
            member_place_ids=[v.place_id for v in members if v.place_id],
        )

        weekday_s = 0.0
        for visit in members:
            duration = (visit.end_utc - visit.start_utc).total_seconds()
            anchor.total_duration_s += int(duration)
            start_local = to_local(visit.start_utc, visit.tz_name)
            if start_local.weekday() < 5:
                weekday_s += duration
            # Spread the dwell across the local hours it actually covered.
            hours = max(1, int(duration // 3600))
            for offset in range(hours):
                anchor.hour_histogram[(start_local.hour + offset) % 24] += 1
        anchor.weekday_ratio = (
            weekday_s / anchor.total_duration_s if anchor.total_duration_s else None
        )
        _apply_semantic_kind(anchor, members)
        anchors.append(anchor)

    return anchors


def _apply_semantic_kind(anchor: Anchor, members: list[VisitRecord]) -> None:
    """Step 0: adopt Google's own labels where they exist.

    'Inferred Home' is NOT a synonym for 'Home'. Measured separation: 427 m for
    home, 795 m for work - different places. They are recorded with different
    kind_source values so the UI can present them as separate suggestions and
    the user confirms each one. Merging them would leave one real address
    completely unprotected.
    """
    types = [(v.semantic_type or "").strip().lower() for v in members]
    if any(t == "home" for t in types):
        anchor.kind, anchor.kind_source = "home", GOOGLE_CONFIRMED
    elif any(t == "work" for t in types):
        anchor.kind, anchor.kind_source = "work", GOOGLE_CONFIRMED
    elif any(t == "inferred home" for t in types):
        anchor.kind, anchor.kind_source = "home", GOOGLE_INFERRED
    elif any(t == "inferred work" for t in types):
        anchor.kind, anchor.kind_source = "work", GOOGLE_INFERRED
    elif anchor.visit_count >= ANCHOR_MIN_SAMPLES:
        anchor.kind = "frequent"


def infer_home_work(anchors: list[Anchor]) -> None:
    """Step 1: statistical fallback for anchors Google never labelled.

    home = highest share of dwell in 22:00-06:00 local
    work = highest weekday dwell in 09:00-18:00 local AND weekend/weekday < 0.2

    Anchors already labelled by Google keep their label; this only fills gaps,
    so a heuristic can never overwrite a confirmed address.
    """
    unlabelled = [a for a in anchors if a.kind_source is None]
    if not unlabelled:
        return

    def night_score(a: Anchor) -> int:
        return sum(a.hour_histogram[h] for h in NIGHT_HOURS)

    def work_score(a: Anchor) -> int:
        return sum(a.hour_histogram[h] for h in WORK_HOURS)

    if not any(a.kind == "home" for a in anchors):
        home = max(unlabelled, key=night_score, default=None)
        if home is not None and night_score(home) > 0:
            home.kind, home.kind_source = "home", HEURISTIC

    if not any(a.kind == "work" for a in anchors):
        candidates = [
            a
            for a in unlabelled
            if a.kind_source in (None, HEURISTIC)
            and a.kind != "home"
            and (a.weekday_ratio or 0.0) >= 0.8
        ]
        work = max(candidates, key=work_score, default=None)
        if work is not None and work_score(work) > 0:
            work.kind, work.kind_source = "work", HEURISTIC


def merge_for_fences(anchors: list[Anchor]) -> list[Anchor]:
    """Collapse home/work anchors into distinct addresses for fence suggestions.

    13 years of real data held 24 distinct Home coordinates and 37 Work
    coordinates - the user moved house and changed jobs. Every one of them
    becomes a fence (see geofence: no time windows, all always active), but the
    user should be shown the handful of real addresses, not 24 near-duplicate
    rows.
    """
    targets = [a for a in anchors if a.kind in {"home", "work"}]
    merged: list[Anchor] = []
    for anchor in sorted(targets, key=lambda a: a.visit_count, reverse=True):
        for existing in merged:
            same_kind = existing.kind == anchor.kind
            # Confirmed and inferred are never merged into each other: they were
            # measured hundreds of metres apart and are different addresses.
            same_source = existing.kind_source == anchor.kind_source
            if (
                same_kind
                and same_source
                and haversine_m(existing.lat, existing.lon, anchor.lat, anchor.lon)
                <= FENCE_MERGE_EPS_M
            ):
                total = existing.visit_count + anchor.visit_count
                weight = existing.visit_count / total
                existing.lat = existing.lat * weight + anchor.lat * (1 - weight)
                existing.lon = existing.lon * weight + anchor.lon * (1 - weight)
                existing.visit_count = total
                existing.total_duration_s += anchor.total_duration_s
                if anchor.first_visit_utc and (
                    existing.first_visit_utc is None
                    or anchor.first_visit_utc < existing.first_visit_utc
                ):
                    existing.first_visit_utc = anchor.first_visit_utc
                if anchor.last_visit_utc and (
                    existing.last_visit_utc is None
                    or anchor.last_visit_utc > existing.last_visit_utc
                ):
                    existing.last_visit_utc = anchor.last_visit_utc
                break
        else:
            merged.append(anchor)
    return merged
