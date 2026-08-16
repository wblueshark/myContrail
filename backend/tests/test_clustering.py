"""Stay clustering, including the rule the whole design turns on."""

from __future__ import annotations

from datetime import timedelta

from contrail.pipeline.clustering import (
    build_moves,
    cluster_photo_stays,
    cluster_stays,
    merge_adjacent_stays,
)
from contrail.pipeline.types import Pt
from tests.conftest import utc

HOME = (35.6812, 139.7671)
AWAY = (35.7100, 139.8100)  # ~4 km from HOME


def _walk(start, lat, lon, count, step_s=60, jitter=0.0):
    return [
        Pt(ts=start + timedelta(seconds=i * step_s), lat=lat + i * jitter, lon=lon)
        for i in range(count)
    ]


# Long enough to clear the 15-minute dwell threshold on its own, so tests about
# the gap rule are not silently testing the dwell rule instead.
DWELL_POINTS = 20


def test_long_gap_with_same_position_is_one_stay():
    """The core v2.0 correction.

    Google's timelinePath emits almost nothing while stationary, so a stay shows
    up as ABSENT data. 89.7% of measured >1h gaps had both ends within 150 m.
    Breaking on time alone reported 9.6% of the timeline as "somewhere"; the
    spacetime rule reports 82%.
    """
    start = utc(hour=8)
    points = _walk(start, *HOME, 5)
    # Six-hour hole, then the same place again: this is a stay, not a gap.
    points += _walk(start + timedelta(hours=6), *HOME, 5)

    stays, moving = cluster_stays(points)

    assert len(stays) == 1, "a long gap between two points in the same place must not split"
    assert stays[0].duration_s > 6 * 3600
    assert stays[0].is_inferred_dwell is True
    assert 0 < stays[0].inferred_ratio <= 1.0
    assert not moving


def test_long_gap_with_movement_breaks_the_stay():
    """The other half of the criterion: a gap whose ends genuinely moved IS
    missing data, and must break."""
    start = utc(hour=8)
    points = _walk(start, *HOME, DWELL_POINTS)
    points += _walk(start + timedelta(hours=6), *AWAY, DWELL_POINTS)

    stays, _ = cluster_stays(points)

    assert len(stays) == 2
    assert all(not s.is_inferred_dwell for s in stays)


def test_absurdly_long_gap_breaks_even_in_the_same_place():
    """A week with the phone off is not a week-long visit."""
    start = utc(hour=8)
    points = _walk(start, *HOME, DWELL_POINTS)
    points += _walk(start + timedelta(days=7), *HOME, DWELL_POINTS)

    stays, _ = cluster_stays(points, max_inferred_stay_s=86400)

    assert len(stays) == 2


def test_short_visit_below_threshold_is_movement_not_a_stay():
    start = utc(hour=8)
    points = _walk(start, *HOME, 3, step_s=60)  # 2 minutes

    stays, moving = cluster_stays(points, min_dwell_s=900)

    assert stays == []
    assert len(moving) == 3


def test_points_beyond_roaming_radius_do_not_join_the_cluster():
    start = utc(hour=8)
    # Drifts steadily away, past R after a while.
    points = _walk(start, *HOME, 60, step_s=60, jitter=0.0001)

    stays, _ = cluster_stays(points, r_m=150)

    for stay in stays:
        assert stay.radius_m <= 150.5


def test_merge_adjacent_removes_ghost_zero_km_segments():
    """Mandatory pass.

    Without it one location splits into two Places with a zero-displacement
    "movement" wedged between them. Measured: 218 stays before, 189 after, ghost
    segments down to zero.
    """
    start = utc(hour=8)
    # Two stays 20 m apart - the same place, seen twice.
    first = _walk(start, *HOME, 20)
    second = _walk(start + timedelta(hours=2), HOME[0] + 0.0002, HOME[1], 20)

    stays, moving = cluster_stays(first + second)
    moves = build_moves(moving, stays)

    assert len(stays) == 1
    assert not [m for m in moves if (m.distance_m or 0) < 1]


def test_merge_adjacent_keeps_genuinely_different_places():
    start = utc(hour=8)
    stays, _ = cluster_stays(
        _walk(start, *HOME, 20) + _walk(start + timedelta(hours=2), *AWAY, 20)
    )
    assert len(merge_adjacent_stays(stays, 150)) == 2


def test_accuracy_filter_drops_noisy_points():
    start = utc(hour=8)
    points = _walk(start, *HOME, DWELL_POINTS)
    points.append(
        Pt(ts=start + timedelta(minutes=21), lat=35.9, lon=139.9, accuracy_m=3000)
    )

    stays, moving = cluster_stays(points, accuracy_max_m=500)

    assert all(p.accuracy_m is None or p.accuracy_m <= 500 for p in moving)
    assert len(stays) == 1


def test_moves_drop_noise_and_keep_real_journeys():
    start = utc(hour=8)
    # A real 4 km journey sampled once a minute.
    journey = [
        Pt(
            ts=start + timedelta(minutes=i),
            lat=HOME[0] + (AWAY[0] - HOME[0]) * i / 20,
            lon=HOME[1] + (AWAY[1] - HOME[1]) * i / 20,
        )
        for i in range(21)
    ]
    moves = build_moves(journey, [])
    assert len(moves) == 1
    assert moves[0].distance_m > 1000
    assert moves[0].speed_median_mps is not None

    # Three points inside a 20 m circle is noise, not a journey.
    assert build_moves(_walk(start, *HOME, 3), []) == []


def test_photo_clustering_ignores_the_dwell_threshold():
    """Photos are sparse: a single frame is still a place, and T does not apply."""
    start = utc(hour=8)
    single = [Pt(ts=start, lat=HOME[0], lon=HOME[1], source_kind="photo")]

    stays = cluster_photo_stays(single)

    assert len(stays) == 1
    assert stays[0].point_count == 1
    assert stays[0].origin == "photo"


def test_photo_clustering_splits_distant_groups():
    start = utc(hour=8)
    points = [
        Pt(ts=start, lat=HOME[0], lon=HOME[1], source_kind="photo"),
        Pt(ts=start + timedelta(minutes=5), lat=HOME[0], lon=HOME[1], source_kind="photo"),
        Pt(ts=start + timedelta(hours=1), lat=AWAY[0], lon=AWAY[1], source_kind="photo"),
    ]
    stays = cluster_photo_stays(points)
    assert len(stays) == 2


def test_clustering_is_linear_enough_for_an_overnight_cluster():
    """A whole night in one cluster used to make the naive O(n*k**2) version
    explode. 2,000 points must stay comfortably fast."""
    import time

    start = utc(hour=20)
    points = _walk(start, *HOME, 2000, step_s=30)

    began = time.perf_counter()
    stays, _ = cluster_stays(points)
    elapsed = time.perf_counter() - began

    assert len(stays) == 1
    assert elapsed < 2.0, f"clustering 2000 co-located points took {elapsed:.2f}s"
