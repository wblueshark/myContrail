"""Parser tests, including every measured data-quality trap."""

from __future__ import annotations

import json

import pytest

from contrail.core.geo import parse_latlng
from contrail.parsers.base import PlaceHint, RawPointDTO, SkipNote, TrackHint, UnknownFormatError
from contrail.parsers.google_timeline import GoogleTimelineParser, map_activity_type
from contrail.parsers.registry import sniff
from contrail.parsers.tracks import SEMICIRCLE_TO_DEG, declared_mode


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _parse(path):
    match = sniff(path)
    return list(match.parser(match.variant).parse(path))


# ── coordinate parsing ────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("geo:35.681236,139.767125", (35.681236, 139.767125)),
        ("35.0116°, 135.7681°", (35.0116, 135.7681)),
        ("geo:-33.8688,151.2093", (-33.8688, 151.2093)),
    ],
)
def test_latlng_accepts_both_written_forms(text, expected):
    assert parse_latlng(text) == expected


def test_null_island_is_treated_as_no_fix():
    """0,0 is the Gulf of Guinea. Taken literally it piles points onto the west
    coast of Africa."""
    assert parse_latlng("geo:0,0") is None
    assert parse_latlng("geo:0.0000000,0.0000000") is None


# ── Google on-device timeline ─────────────────────────────
def test_records_are_dispatched_per_record_not_per_file(tmp_path):
    """Four record streams coexist in one file across the whole 13 years, so
    detection has to happen per record."""
    path = _write(
        tmp_path,
        "location-history.json",
        [
            {
                "startTime": "2015-10-09T00:53:01.938+09:00",
                "endTime": "2015-10-09T07:17:54.459+09:00",
                "visit": {
                    "hierarchyLevel": "0",
                    "probability": "0.810000",
                    "topCandidate": {
                        "placeID": "ChIJtest",
                        "placeLocation": "geo:35.681236,139.767125",
                        "semanticType": "Home",
                        "probability": "0.391526",
                    },
                },
            },
            {
                "startTime": "2015-10-09T00:28:59.299+09:00",
                "endTime": "2015-10-09T00:53:01.938+09:00",
                "activity": {
                    "start": "geo:35.689487,139.691711",
                    "end": "geo:35.681236,139.767125",
                    "distanceMeters": "16031.000000",
                    "topCandidate": {"type": "in passenger vehicle", "probability": "0.000000"},
                },
            },
            {
                "startTime": "2026-03-31T22:00:00.000Z",
                "endTime": "2026-04-01T00:00:00.000Z",
                "timelinePath": [
                    {
                        "point": "geo:35.733497,139.891426",
                        "durationMinutesOffsetFromStartTime": "47",
                    },
                    {
                        "point": "geo:35.733499,139.891425",
                        "durationMinutesOffsetFromStartTime": "85",
                    },
                ],
            },
            {
                "startTime": "2020-01-01T00:00:00.000Z",
                "endTime": "2020-01-02T00:00:00.000Z",
                "timelineMemory": {
                    "destinations": [{"identifier": "ChIJx"}],
                    "distanceFromOriginKms": "90",
                },
            },
        ],
    )

    items = _parse(path)

    assert sum(isinstance(i, PlaceHint) for i in items) == 1
    assert sum(isinstance(i, TrackHint) for i in items) == 1
    assert sum(isinstance(i, RawPointDTO) for i in items) == 2
    # timelineMemory is understood and skipped - counted, never silent.
    assert any(isinstance(i, SkipNote) and i.reason == "timeline_memory" for i in items)


def test_searched_address_is_excluded(tmp_path):
    """An address the user LOOKED UP, not one they visited. Importing it would
    poison "places you go most" and city coverage alike."""
    path = _write(
        tmp_path,
        "location-history.json",
        [
            {
                "startTime": "2020-01-01T10:00:00.000+09:00",
                "endTime": "2020-01-01T11:00:00.000+09:00",
                "visit": {
                    "hierarchyLevel": "0",
                    "topCandidate": {
                        "placeLocation": "geo:35.681236,139.767125",
                        "semanticType": "Searched Address",
                    },
                },
            }
        ],
    )
    items = _parse(path)
    assert not [i for i in items if isinstance(i, PlaceHint)]
    assert any(isinstance(i, SkipNote) and i.reason == "searched_address" for i in items)


def test_hierarchy_level_one_is_skipped(tmp_path):
    """Level 1 is a parent container (a mall holding a shop); importing both
    produces two Places for one visit."""
    path = _write(
        tmp_path,
        "location-history.json",
        [
            {
                "startTime": "2020-01-01T10:00:00.000+09:00",
                "endTime": "2020-01-01T11:00:00.000+09:00",
                "visit": {
                    "hierarchyLevel": "1",
                    "topCandidate": {
                        "placeLocation": "geo:35.681236,139.767125",
                        "semanticType": "Unknown",
                    },
                },
            }
        ],
    )
    items = _parse(path)
    assert not [i for i in items if isinstance(i, PlaceHint)]


def test_zero_distance_becomes_unknown_not_zero(tmp_path):
    """7% of activities report 0 m (53% in early years). Storing 0 would fold
    unknown mileage into the totals as though it had been measured."""
    path = _write(
        tmp_path,
        "location-history.json",
        [
            {
                "startTime": "2015-10-09T00:28:59.299+09:00",
                "endTime": "2015-10-09T00:53:01.938+09:00",
                "activity": {
                    "start": "geo:35.689487,139.691711",
                    "end": "geo:35.681236,139.767125",
                    "distanceMeters": "0",
                    "topCandidate": {"type": "walking", "probability": "0.000000"},
                },
            }
        ],
    )
    hint = next(i for i in _parse(path) if isinstance(i, TrackHint))
    assert hint.distance_m is None


def test_broken_probability_field_is_not_used_as_confidence(tmp_path):
    """activity.topCandidate.probability is hardcoded "0.000000" in every single
    record measured (354/354). Driving mode_confidence from it would be
    inventing information."""
    path = _write(
        tmp_path,
        "location-history.json",
        [
            {
                "startTime": "2015-10-09T00:28:59.299+09:00",
                "endTime": "2015-10-09T00:53:01.938+09:00",
                "activity": {
                    "start": "geo:35.689487,139.691711",
                    "end": "geo:35.681236,139.767125",
                    "distanceMeters": "16031.000000",
                    "topCandidate": {"type": "in train", "probability": "0.000000"},
                },
            }
        ],
    )
    hint = next(i for i in _parse(path) if isinstance(i, TrackHint))
    assert hint.mode == "transit"
    assert hint.mode_confidence is None


def test_timeline_path_offsets_become_absolute_times(tmp_path):
    path = _write(
        tmp_path,
        "location-history.json",
        [
            {
                "startTime": "2026-03-31T22:00:00.000Z",
                "endTime": "2026-04-01T00:00:00.000Z",
                "timelinePath": [
                    {"point": "geo:35.7,139.8", "durationMinutesOffsetFromStartTime": "47"},
                    # Duplicate offsets genuinely occur (12 in the measured
                    # sample); dedup must absorb the collision, not raise.
                    {"point": "geo:35.7,139.8", "durationMinutesOffsetFromStartTime": "47"},
                ],
            }
        ],
    )
    points = [i for i in _parse(path) if isinstance(i, RawPointDTO)]
    assert len(points) == 2
    assert points[0].ts_utc.hour == 22 and points[0].ts_utc.minute == 47
    assert points[0].ts_utc == points[1].ts_utc
    # This source has no accuracy field at all.
    assert all(p.accuracy_m is None for p in points)


def test_unknown_record_type_raises_with_a_sample(tmp_path):
    """Google keeps changing this format. An unknown structure is an error with
    a preserved sample, never a guess (P6)."""
    path = _write(
        tmp_path,
        "location-history.json",
        [{"startTime": "2020-01-01T00:00:00Z", "endTime": "2020-01-01T01:00:00Z",
          "someNewThing": {"x": 1}}],
    )
    with pytest.raises(UnknownFormatError) as caught:
        _parse(path)
    assert caught.value.sample


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("walking", "walk"),
        ("WALKING", "walk"),
        ("in passenger vehicle", "car"),
        ("IN_PASSENGER_VEHICLE", "car"),
        ("in train", "transit"),
        ("cycling", "bike"),
        ("flying", "flight"),
        ("something new", "unknown"),
    ],
)
def test_activity_type_mapping_is_case_insensitive(raw, expected):
    assert map_activity_type(raw) == expected


def test_android_wrapper_is_detected(tmp_path):
    path = _write(
        tmp_path,
        "Timeline.json",
        {
            "semanticSegments": [
                {
                    "startTime": "2024-05-03T14:20:31.000+09:00",
                    "endTime": "2024-05-03T16:45:12.000+09:00",
                    "visit": {
                        "hierarchyLevel": "0",
                        "topCandidate": {
                            "placeLocation": "35.0116°, 135.7681°",
                            "semanticType": "Unknown",
                        },
                    },
                }
            ]
        },
    )
    match = sniff(path)
    assert match.parser is GoogleTimelineParser
    assert match.variant == "android"
    assert len([i for i in _parse(path) if isinstance(i, PlaceHint)]) == 1


# ── GPX ───────────────────────────────────────────────────
GPX = """<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="35.0116" lon="135.7681"><name>Kiyomizu</name>
    <time>2024-05-03T05:00:00Z</time></wpt>
  <trk><name>Kyoto Hike</name><type>hiking</type><trkseg>
    <trkpt lat="35.0116" lon="135.7681"><ele>128.4</ele>
      <time>2024-05-03T05:20:31Z</time></trkpt>
    <trkpt lat="35.0126" lon="135.7691"><ele>130.0</ele>
      <time>2024-05-03T05:21:31Z</time></trkpt>
    <trkpt lat="35.0136" lon="135.7701"><ele>140.0</ele>
      <time>2024-05-03T05:22:31Z</time></trkpt>
  </trkseg></trk>
  <rte><rtept lat="35.0" lon="135.0"/></rte>
</gpx>
"""


def test_gpx_points_waypoints_and_declared_mode(tmp_path):
    path = tmp_path / "hike.gpx"
    path.write_text(GPX, encoding="utf-8")

    items = _parse(path)
    points = [i for i in items if isinstance(i, RawPointDTO)]
    hints = [i for i in items if isinstance(i, TrackHint)]

    assert len(points) == 3
    assert points[0].altitude_m == 128.4
    assert hints[0].mode == "walk" and hints[0].mode_source == "declared"
    # A waypoint is a deliberate mark, so it becomes a Place.
    assert any(isinstance(i, PlaceHint) and i.name == "Kiyomizu" for i in items)
    # <rte> is a planned route, not a footprint - skipped, and reported.
    assert any(isinstance(i, SkipNote) and i.reason == "gpx_route_skipped" for i in items)


@pytest.mark.parametrize(
    "declared,expected",
    [("hiking", "walk"), ("Running", "run"), ("cycling", "bike"), ("driving", "car"),
     ("徒步", "walk"), ("骑行", "bike"), ("mystery", None)],
)
def test_declared_mode_matching_is_fuzzy(declared, expected):
    assert declared_mode(declared) == expected


def test_fit_semicircle_constant_is_right():
    """degrees = semicircles * 180 / 2**31. Getting this wrong yields absurd
    coordinates rather than an error."""
    semicircles = 424_000_000  # ~35.5 degrees
    assert abs(semicircles * SEMICIRCLE_TO_DEG - 35.53) < 0.01


def test_unrecognised_file_raises_with_the_first_bytes(tmp_path):
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"\x00\x01\x02not a format we know" * 10)
    with pytest.raises(UnknownFormatError) as caught:
        sniff(path)
    assert caught.value.sample
