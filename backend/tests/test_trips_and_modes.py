"""Day-trip assignment, travel-mode inference, dedup and timezone handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contrail.core.timezones import local_date, local_midnight_utc, zone
from contrail.pipeline.dedup import point_dedup_key, prefer_more_accurate
from contrail.pipeline.modes import infer_mode
from contrail.pipeline.trips import build_day_trips, insert_implied_moves, make_title
from contrail.pipeline.types import Move, Stay

TOKYO = (35.6812, 139.7671)
NEW_YORK = (40.7128, -74.0060)


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


# ── timezone handling ─────────────────────────────────────
def test_fixed_offset_zone_names_are_honoured():
    """Semantic-era records carry an authoritative offset, not a zone name.

    Silently degrading "UTC+09:00" to UTC shifts every day boundary by nine
    hours and scatters cross-midnight stays onto the wrong days.
    """
    tz = zone("UTC+09:00")
    assert tz.utcoffset(None) == timedelta(hours=9)
    assert zone("UTC-04:00").utcoffset(None) == timedelta(hours=-4)
    assert zone("Asia/Tokyo") is not None
    assert zone("Not/AZone").utcoffset(None) == timedelta(0)


def test_local_date_uses_the_local_zone_not_utc():
    # 23:30 UTC is already the next day in Tokyo.
    instant = _utc(2024, 5, 3, 23, 30)
    assert local_date(instant, "UTC") == instant.date()
    assert local_date(instant, "Asia/Tokyo").day == 4
    assert local_date(instant, "UTC+09:00").day == 4


def test_local_midnight_round_trips():
    midnight = local_midnight_utc(_utc(2024, 5, 4).date(), "Asia/Tokyo")
    assert local_date(midnight, "Asia/Tokyo").day == 4
    assert midnight.hour == 15  # 00:00 JST is 15:00 UTC the previous day


# ── day assignment ────────────────────────────────────────
def test_stay_crossing_local_midnight_is_split():
    """A stay is spatially homogeneous, so cutting it at midnight loses nothing."""
    stay = Stay(
        lat=TOKYO[0],
        lon=TOKYO[1],
        start=_utc(2024, 5, 3, 12),  # 21:00 JST
        end=_utc(2024, 5, 4, 3),  # 12:00 JST next day
        tz_name="Asia/Tokyo",
        point_count=10,
    )
    trips = build_day_trips([stay], [])
    assert len(trips) == 2
    assert [t.local_date.day for t in trips] == [3, 4]


def test_track_crossing_local_midnight_is_never_split():
    """Cutting a journey in half destroys it. The whole segment belongs to the
    day it STARTED."""
    move = Move(
        start=_utc(2024, 5, 3, 12),
        end=_utc(2024, 5, 4, 3),
        points=[TOKYO, NEW_YORK],
        duration_s=54000,
        distance_m=10_800_000,
    )
    stay = Stay(
        lat=TOKYO[0], lon=TOKYO[1], start=_utc(2024, 5, 3, 6), end=_utc(2024, 5, 3, 11),
        tz_name="Asia/Tokyo", point_count=5,
    )
    trips = build_day_trips([stay], [move])
    holders = [t for t in trips if t.moves]
    assert len(holders) == 1, "a timezone-crossing track must live on exactly one day"
    assert holders[0].moves[0].start == move.start


def test_timezone_crossing_day_may_exceed_24_hours():
    """Measured worst case was 37 h. This is correct, not a bug: it is the price
    of keeping a flight whole."""
    stay_a = Stay(lat=TOKYO[0], lon=TOKYO[1], start=_utc(2024, 4, 28, 15),
                  end=_utc(2024, 4, 28, 20), tz_name="Asia/Tokyo", point_count=5)
    flight = Move(start=_utc(2024, 4, 29, 0, 53), end=_utc(2024, 4, 29, 14, 19),
                  points=[TOKYO, NEW_YORK], duration_s=48360, distance_m=10_874_000)
    stay_b = Stay(lat=NEW_YORK[0], lon=NEW_YORK[1], start=_utc(2024, 4, 30, 0, 46),
                  end=_utc(2024, 4, 30, 3, 59), tz_name="America/New_York", point_count=5)

    trips = build_day_trips([stay_a, stay_b], [flight])
    longest = max((t.end_utc - t.start_utc).total_seconds() for t in trips)
    assert longest > 24 * 3600


def test_track_crossing_timezones_is_flagged():
    move = Move(start=_utc(2024, 4, 29, 0), end=_utc(2024, 4, 29, 14),
                points=[TOKYO, NEW_YORK], duration_s=50400)
    build_day_trips([], [move])
    assert move.crosses_tz is True


def test_a_day_with_no_place_and_no_photo_is_not_a_trip():
    move = Move(start=_utc(2024, 5, 3, 1), end=_utc(2024, 5, 3, 2),
                points=[TOKYO, (35.7, 139.8)], duration_s=3600)
    assert build_day_trips([], [move]) == []


def test_photo_only_day_still_produces_a_trip():
    trips = build_day_trips([], [], photo_times=[_utc(2024, 5, 3, 10)])
    assert len(trips) == 1
    assert trips[0].photo_count == 1


def test_implied_moves_do_not_recreate_ghost_segments():
    a = Stay(lat=TOKYO[0], lon=TOKYO[1], start=_utc(2024, 5, 3, 8),
             end=_utc(2024, 5, 3, 9), tz_name="Asia/Tokyo", point_count=5)
    # Starts 10 s later: clustering noise, not a journey.
    b = Stay(lat=TOKYO[0], lon=TOKYO[1], start=_utc(2024, 5, 3, 9, 0, 10),
             end=_utc(2024, 5, 3, 10), tz_name="Asia/Tokyo", point_count=5)
    assert insert_implied_moves([a, b], []) == []

    c = Stay(lat=35.7, lon=139.8, start=_utc(2024, 5, 3, 10),
             end=_utc(2024, 5, 3, 11), tz_name="Asia/Tokyo", point_count=5)
    moves = insert_implied_moves([a, c], [])
    assert len(moves) == 1
    # Endpoints only, so the distance is unknown rather than invented.
    assert moves[0].distance_unknown is True and moves[0].distance_m is None


def test_title_degrades_through_the_template():
    trips = build_day_trips(
        [Stay(lat=TOKYO[0], lon=TOKYO[1], start=_utc(2024, 5, 3, 1),
              end=_utc(2024, 5, 3, 5), tz_name="Asia/Tokyo", point_count=5)],
        [],
    )
    trip = trips[0]
    assert make_title(trip, city_durations={"New York": 3600}) == "New York · 05-03"
    assert make_title(trip, countries=["Japan", "United States"]) == "Japan → United States · 05-03"
    assert make_title(trip) == "2024-05-03"
    assert make_title(trip, is_pure_commute=True).endswith("05-03")


# ── travel mode ───────────────────────────────────────────
@pytest.mark.parametrize(
    "v_med,v_p95,expected",
    [
        (0.1, 0.5, "unknown"),  # GPS drift
        (1.3, 2.5, "walk"),
        (3.0, 5.0, "run"),
        (5.5, 12.0, "bike"),
        (12.0, 25.0, "car"),
        (40.0, 50.0, "transit"),  # high-speed rail band, previously uncovered
    ],
)
def test_mode_rules_match_in_declared_order(v_med, v_p95, expected):
    assert infer_mode(v_med, v_p95).mode == expected


def test_gps_drift_is_dropped_not_labelled():
    verdict = infer_mode(0.1, 0.5)
    assert verdict.drop is True


def test_run_wins_over_bike_in_the_overlapping_band():
    """2.5-4.0 m/s matched both rules in v1.0 with no defined precedence."""
    assert infer_mode(3.0, 6.0).mode == "run"


def test_high_speed_rail_is_not_called_a_flight():
    """350 km/h ~ 97 m/s, straight and long. Without the altitude test this is
    labelled FLIGHT, which is the most visible possible misclassification for a
    product used in China."""
    verdict = infer_mode(97.0, 100.0, distance_m=800_000, straightness_ratio=0.95,
                         max_altitude_m=120.0)
    assert verdict.mode == "transit"


def test_flight_needs_altitude_evidence():
    high = infer_mode(250.0, 260.0, distance_m=9_000_000, straightness_ratio=0.99,
                      max_altitude_m=10_000.0)
    assert high.mode == "flight"

    # Google timelinePath has no altitude field, so a real flight degrades to
    # transit. Accepted under "unknown beats wrong".
    unknown_altitude = infer_mode(250.0, 260.0, distance_m=9_000_000,
                                  straightness_ratio=0.99, max_altitude_m=None)
    assert unknown_altitude.mode == "transit"


# ── dedup ─────────────────────────────────────────────────
def test_dedup_key_is_stable_and_position_sensitive():
    user = "11111111-1111-1111-1111-111111111111"
    ts = _utc(2024, 5, 3, 5, 20, 31)
    base = point_dedup_key(user, ts, 35.011600, 135.768100)

    assert base == point_dedup_key(user, ts, 35.011600, 135.768100)
    # Sub-metre jitter rounds to the same 5-decimal cell.
    assert base == point_dedup_key(user, ts, 35.0116001, 135.7681001)
    # ~2 m away is a different point.
    assert base != point_dedup_key(user, ts, 35.01162, 135.768100)
    assert base != point_dedup_key(user, ts + timedelta(seconds=1), 35.0116, 135.7681)


def test_cross_source_dedup_does_not_collide():
    """Measured: two sources never agree on the same second AND the same ~1 m
    cell. timelinePath resolves to whole minutes, EXIF to the second, and the
    same instant differs by 6-76 m in space. Cross-source overlap is handled by
    the Place association rules, never by L2."""
    user = "11111111-1111-1111-1111-111111111111"
    google = point_dedup_key(user, _utc(2024, 5, 3, 5, 20, 0), 35.01160, 135.76810)
    photo = point_dedup_key(user, _utc(2024, 5, 3, 5, 20, 31), 35.01175, 135.76835)
    assert google != photo


def test_more_accurate_reading_wins_a_collision():
    assert prefer_more_accurate(50.0, 5.0) is True
    assert prefer_more_accurate(5.0, 50.0) is False
    # Unknown loses to any measurement, and two unknowns keep what is stored -
    # so re-importing stays idempotent.
    assert prefer_more_accurate(None, 12.0) is True
    assert prefer_more_accurate(12.0, None) is False
    assert prefer_more_accurate(None, None) is False
