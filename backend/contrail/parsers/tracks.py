"""GPX / TCX / FIT - the sports-device formats.

No real sample files exist in this project yet, so the two documented traps are
handled defensively and covered by synthetic tests:

  FIT coordinates are semicircles -> degrees = semicircles * 180 / 2**31.
      Forgetting this yields absurd coordinates rather than an error.
  FIT timestamps use the Garmin epoch (1989-12-31T00:00:00Z), not Unix.
      fitparse normally converts these already; the guard below catches the
      case where it hands back a raw integer.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

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

GARMIN_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)
SEMICIRCLE_TO_DEG = 180.0 / (2**31)

# A GPS outage inside one <trk>: longer than this and it is two Tracks.
SEGMENT_SPLIT_GAP_S = 1800

# Declared activity strings are not standardised; match loosely.
_MODE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("hik", "walk", "foot", "trek", "徒步", "步行"), "walk"),
    (("run", "jog", "跑步"), "run"),
    (("cycl", "bike", "biking", "ride", "骑行", "自行车"), "bike"),
    (("driv", "car", "auto", "驾车", "汽车"), "car"),
    (("train", "bus", "subway", "transit", "地铁", "公交"), "transit"),
    (("fly", "flight", "plane", "飞行"), "flight"),
]


def declared_mode(value: str | None) -> str | None:
    if not value:
        return None
    low = value.strip().lower()
    for keywords, mode in _MODE_KEYWORDS:
        if any(k in low for k in keywords):
            return mode
    return None


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = dtparser.isoparse(value.strip())
    except (ValueError, OverflowError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class GpxParser:
    source_kind = "gpx"

    def __init__(self, variant: str = "gpx") -> None:
        self.variant = variant

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        if path.suffix.lower() not in {".gpx", ".xml"}:
            return None
        if b"<gpx" in head.lower():
            return ParserMatch(cls, 0.95, "gpx", cls.source_kind)
        return None

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        from lxml import etree

        declared: str | None = None
        segment: list[RawPointDTO] = []

        # iterparse keeps memory flat on multi-hour recordings.
        context = etree.iterparse(str(path), events=("end",))
        for _, elem in context:
            name = _localname(elem.tag)

            if name in {"type", "name"} and _localname(elem.getparent().tag) == "trk":
                declared = declared or declared_mode(elem.text)

            elif name == "trkpt":
                point = self._point(elem)
                if point is not None:
                    if segment and (point.ts_utc - segment[-1].ts_utc).total_seconds() > (
                        SEGMENT_SPLIT_GAP_S
                    ):
                        yield from self._flush(segment, declared)
                        segment = []
                    segment.append(point)
                elem.clear()

            elif name == "trkseg":
                # A new <trkseg> means the signal dropped. Split unless the gap
                # is short enough that merging is the honest reading.
                yield from self._flush(segment, declared)
                segment = []
                elem.clear()

            elif name == "wpt":
                # Waypoints are deliberate marks, so they become Places.
                point = self._point(elem)
                if point is not None:
                    label = elem.findtext("{*}name")
                    yield PlaceHint(
                        lat=point.lat,
                        lon=point.lon,
                        start_utc=point.ts_utc,
                        end_utc=point.ts_utc,
                        name=label,
                    )
                elem.clear()

            elif name == "rte":
                # A planned route, not an actual footprint. Never imported.
                yield SkipNote("gpx_route_skipped")
                elem.clear()

        yield from self._flush(segment, declared)

    def _flush(self, segment: list[RawPointDTO], declared: str | None) -> Iterator[ParsedItem]:
        if not segment:
            return
        yield from segment
        if len(segment) >= 2:
            yield TrackHint(
                start_utc=segment[0].ts_utc,
                end_utc=segment[-1].ts_utc,
                points=[(p.lat, p.lon) for p in segment],
                mode=declared or "unknown",
                mode_source="declared" if declared else None,
                mode_confidence=0.95 if declared else None,
                geom_quality="full",
            )

    def _point(self, elem) -> RawPointDTO | None:
        try:
            lat = float(elem.get("lat"))
            lon = float(elem.get("lon"))
        except (TypeError, ValueError):
            return None
        if not is_valid_coord(lat, lon):
            return None
        ts = _ts(elem.findtext("{*}time"))
        if ts is None:
            return None
        ele = elem.findtext("{*}ele")
        return RawPointDTO(
            ts_utc=ts,
            lat=lat,
            lon=lon,
            altitude_m=float(ele) if ele else None,
            confidence="measured",
        )


class TcxParser:
    source_kind = "tcx"

    def __init__(self, variant: str = "tcx") -> None:
        self.variant = variant

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        if path.suffix.lower() not in {".tcx", ".xml"}:
            return None
        if b"TrainingCenterDatabase" in head:
            return ParserMatch(cls, 0.95, "tcx", cls.source_kind)
        return None

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        from lxml import etree

        declared: str | None = None
        points: list[RawPointDTO] = []
        context = etree.iterparse(str(path), events=("end",))
        for _, elem in context:
            name = _localname(elem.tag)
            if name == "Activity":
                declared = declared or declared_mode(elem.get("Sport"))
                elem.clear()
            elif name == "Trackpoint":
                ts = _ts(elem.findtext("{*}Time"))
                lat_text = elem.findtext("{*}Position/{*}LatitudeDegrees")
                lon_text = elem.findtext("{*}Position/{*}LongitudeDegrees")
                if ts and lat_text and lon_text:
                    lat, lon = float(lat_text), float(lon_text)
                    if is_valid_coord(lat, lon):
                        alt = elem.findtext("{*}AltitudeMeters")
                        points.append(
                            RawPointDTO(
                                ts_utc=ts,
                                lat=lat,
                                lon=lon,
                                altitude_m=float(alt) if alt else None,
                            )
                        )
                elem.clear()

        if not points:
            raise UnknownFormatError("TCX contained no usable trackpoints")
        yield from points
        if len(points) >= 2:
            yield TrackHint(
                start_utc=points[0].ts_utc,
                end_utc=points[-1].ts_utc,
                points=[(p.lat, p.lon) for p in points],
                mode=declared or "unknown",
                mode_source="declared" if declared else None,
                mode_confidence=0.95 if declared else None,
                geom_quality="full",
            )


class FitParser:
    source_kind = "fit"

    def __init__(self, variant: str = "fit") -> None:
        self.variant = variant

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        # ".FIT" sits at byte offset 8 of the header.
        if head[8:12] == b".FIT":
            return ParserMatch(cls, 1.0, "fit", cls.source_kind)
        if path.suffix.lower() == ".fit":
            return ParserMatch(cls, 0.6, "fit", cls.source_kind)
        return None

    @staticmethod
    def _coord(value) -> float | None:
        """Semicircles -> degrees. fitparse hands back the raw integer."""
        if value is None:
            return None
        return float(value) * SEMICIRCLE_TO_DEG

    @staticmethod
    def _time(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        # Raw Garmin-epoch seconds, if the library did not convert them.
        try:
            return GARMIN_EPOCH + timedelta(seconds=int(value))
        except (TypeError, ValueError):
            return None

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        from fitparse import FitFile

        fit = FitFile(str(path))
        declared: str | None = None
        for msg in fit.get_messages("session"):
            declared = declared or declared_mode(str(msg.get_value("sport") or ""))

        points: list[RawPointDTO] = []
        for msg in fit.get_messages("record"):
            lat = self._coord(msg.get_value("position_lat"))
            lon = self._coord(msg.get_value("position_long"))
            ts = self._time(msg.get_value("timestamp"))
            if lat is None or lon is None or ts is None or not is_valid_coord(lat, lon):
                continue
            points.append(
                RawPointDTO(
                    ts_utc=ts,
                    lat=lat,
                    lon=lon,
                    altitude_m=msg.get_value("altitude"),
                    speed_mps=msg.get_value("speed"),
                )
            )

        if not points:
            raise UnknownFormatError("FIT file contained no record messages with a position")
        yield from points
        yield TrackHint(
            start_utc=points[0].ts_utc,
            end_utc=points[-1].ts_utc,
            points=[(p.lat, p.lon) for p in points],
            mode=declared or "unknown",
            mode_source="declared" if declared else None,
            mode_confidence=0.95 if declared else None,
            geom_quality="full",
        )
