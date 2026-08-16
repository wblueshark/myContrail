"""Legacy Google Takeout: Records.json and Semantic Location History.

No real sample of either exists in this project - the descriptions below come
from the documented structure, not from measurement. Both parsers therefore
fail loudly on anything unexpected instead of guessing (P6), and the import
report marks them as unverified.

Records.json can reach gigabytes, so it is parsed with ijson at
`locations.item`. json.load() on this file is not an option.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dateutil import parser as dtparser

from contrail.core.geo import is_valid_coord
from contrail.parsers.base import (
    ParsedItem,
    ParserMatch,
    PlaceHint,
    RawPointDTO,
    SkipNote,
    TrackHint,
    UnknownFormatError,
)

# Points worse than this are mostly cell-tower fixes and are pure noise.
DEFAULT_ACCURACY_LIMIT_M = 500.0

SEMANTIC_ACTIVITY_TO_MODE = {
    "WALKING": "walk",
    "ON_FOOT": "walk",
    "HIKING": "walk",
    "RUNNING": "run",
    "CYCLING": "bike",
    "IN_PASSENGER_VEHICLE": "car",
    "IN_VEHICLE": "car",
    "MOTORCYCLING": "car",
    "IN_BUS": "transit",
    "IN_TRAIN": "transit",
    "IN_SUBWAY": "transit",
    "IN_TRAM": "transit",
    "IN_FERRY": "transit",
    "FLYING": "flight",
    "STILL": "unknown",
    "UNKNOWN_ACTIVITY_TYPE": "unknown",
}


def _e7(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 1e7
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> datetime | None:
    if value is None:
        return None
    # Older exports used timestampMs (a millisecond string).
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    try:
        dt = dtparser.isoparse(str(value))
    except (ValueError, OverflowError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class GoogleRecordsParser:
    """Takeout `Records.json` - the raw point stream of the old export."""

    source_kind = "google_records"

    def __init__(
        self, variant: str = "records", accuracy_limit_m: float = DEFAULT_ACCURACY_LIMIT_M
    ):
        self.variant = variant
        self.accuracy_limit_m = accuracy_limit_m

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        if path.suffix.lower() != ".json":
            return None
        text = head.decode("utf-8", errors="replace")
        if '"locations"' in text and ("latitudeE7" in text or "timestampMs" in text):
            return ParserMatch(cls, 0.9, "records", cls.source_kind)
        return None

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        import ijson

        with path.open("rb") as fh:
            for rec in ijson.items(fh, "locations.item", use_float=True):
                if not isinstance(rec, dict):
                    continue
                lat = _e7(rec.get("latitudeE7"))
                lon = _e7(rec.get("longitudeE7"))
                ts = _ts(rec.get("timestamp") or rec.get("timestampMs"))
                if lat is None or lon is None or ts is None or not is_valid_coord(lat, lon):
                    yield SkipNote("records_incomplete")
                    continue
                accuracy = rec.get("accuracy")
                accuracy = float(accuracy) if accuracy is not None else None
                if accuracy is not None and accuracy > self.accuracy_limit_m:
                    yield SkipNote("accuracy_filtered")
                    continue
                altitude = rec.get("altitude")
                yield RawPointDTO(
                    ts_utc=ts,
                    lat=lat,
                    lon=lon,
                    altitude_m=float(altitude) if altitude is not None else None,
                    accuracy_m=accuracy,
                    confidence="measured",
                )


class GoogleSemanticParser:
    """Takeout `Semantic Location History/*.json` - placeVisit / activitySegment."""

    source_kind = "google_semantic"

    def __init__(self, variant: str = "semantic") -> None:
        self.variant = variant

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        if path.suffix.lower() != ".json":
            return None
        if b'"timelineObjects"' in head:
            return ParserMatch(cls, 0.95, "semantic", cls.source_kind)
        return None

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        import ijson

        with path.open("rb") as fh:
            for obj in ijson.items(fh, "timelineObjects.item", use_float=True):
                if not isinstance(obj, dict):
                    continue
                if "placeVisit" in obj:
                    item = self._visit(obj["placeVisit"])
                elif "activitySegment" in obj:
                    item = self._segment(obj["activitySegment"])
                else:
                    raise UnknownFormatError(
                        f"unknown timelineObject key: {sorted(obj)}",
                        json.dumps(obj, ensure_ascii=False)[:200],
                    )
                if item is not None:
                    yield item

    def _visit(self, visit: dict) -> ParsedItem | None:
        loc = visit.get("location") or {}
        lat, lon = _e7(loc.get("latitudeE7")), _e7(loc.get("longitudeE7"))
        duration = visit.get("duration") or {}
        start = _ts(duration.get("startTimestamp") or duration.get("startTimestampMs"))
        end = _ts(duration.get("endTimestamp") or duration.get("endTimestampMs"))
        if lat is None or lon is None or start is None or end is None:
            return SkipNote("place_visit_incomplete")
        if not is_valid_coord(lat, lon):
            return SkipNote("place_visit_invalid_coord")
        return PlaceHint(
            lat=lat,
            lon=lon,
            start_utc=start,
            end_utc=end,
            # A free place name: this saves one geocoding request per visit.
            name=loc.get("name"),
            google_place_id=loc.get("placeId"),
            probability=None,
        )

    def _segment(self, seg: dict) -> ParsedItem | None:
        duration = seg.get("duration") or {}
        start = _ts(duration.get("startTimestamp") or duration.get("startTimestampMs"))
        end = _ts(duration.get("endTimestamp") or duration.get("endTimestampMs"))
        if start is None or end is None:
            return SkipNote("segment_without_time")

        points: list[tuple[float, float]] = []
        for key in ("startLocation", "endLocation"):
            loc = seg.get(key) or {}
            lat, lon = _e7(loc.get("latitudeE7")), _e7(loc.get("longitudeE7"))
            if lat is not None and lon is not None and is_valid_coord(lat, lon):
                points.append((lat, lon))

        quality = "endpoints_only"
        waypoints = ((seg.get("waypointPath") or {}).get("waypoints")) or []
        path: list[tuple[float, float]] = []
        for wp in waypoints:
            lat, lon = _e7(wp.get("latE7")), _e7(wp.get("lngE7"))
            if lat is not None and lon is not None and is_valid_coord(lat, lon):
                path.append((lat, lon))
        if len(path) >= 2:
            # Waypoints are thinned relative to Records.json, but they are real
            # intermediate geometry, which beats a straight line.
            points = path
            quality = "full"

        if len(points) < 2:
            return SkipNote("segment_without_geometry")

        distance = seg.get("distance")
        distance = float(distance) if distance not in (None, "", 0) else None
        return TrackHint(
            start_utc=start,
            end_utc=end,
            points=points,
            mode=SEMANTIC_ACTIVITY_TO_MODE.get(str(seg.get("activityType") or ""), "unknown"),
            mode_source="google",
            mode_confidence=None,
            distance_m=distance,
            geom_quality=quality,
        )
