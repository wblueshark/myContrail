"""Google's on-device timeline export (2024-11 onwards).

Two shapes of the same thing:
  Android  Timeline.json          -> {"semanticSegments": [...]}
  iOS      location-history.json  -> a bare top-level array

Verified against 13 years of real data (49,654 records, 2013-09 .. 2026-07).

The single most important fact about this format: ONE FILE CONTAINS FOUR
PARALLEL RECORD STREAMS that coexist for the whole period. It is not "old
format vs new format". So format detection happens PER RECORD, not per file:

  visit          16,465   2013-09 .. 2026-07   stays: placeID + coords + type
  activity       18,159   2013-09 .. 2026-07   movement: mode + endpoints only
  timelinePath   14,975   2016-11 .. 2026-07   path geometry, no semantics at all
  timelineMemory     55   2016-11 .. 2024-06   trip summaries, no coordinates

Time coverage of the 13-year union: visit 67.3%, activity 8.3%,
visit+activity 75.6%, timelinePath 26.6%.

Consequences that shaped this parser:
  * Semantic-era timestamps carry a real local offset - never re-derive the
    zone for those. timelinePath timestamps are UTC ("Z") and MUST have their
    zone resolved from coordinates.
  * Every numeric value is a string ("16031.000000", "0").
  * activity.topCandidate.probability is always exactly "0.000000" (354/354).
    The field is broken; use `type` and ignore it.
  * 7% of activities report distance 0 (53% in early years). That is unknown,
    not zero.
  * `Searched Address` is an address the user LOOKED UP, not one they visited.
    Importing it would poison "places you go most" and city coverage.
  * hierarchyLevel 1 records are containers (a mall holding a shop); taking
    both would produce two Places for one visit.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dateutil import parser as dtparser

from contrail.core.geo import parse_latlng
from contrail.parsers.base import (
    ParsedItem,
    ParserMatch,
    PlaceHint,
    RawPointDTO,
    SkipNote,
    TrackHint,
    UnknownFormatError,
)

# Measured: these are all the values that actually occur. Matching is
# case-insensitive because the semantic era used upper case and the on-device
# era uses lower case for the same concepts.
ACTIVITY_TYPE_TO_MODE = {
    "walking": "walk",
    "on foot": "walk",
    "hiking": "walk",
    "running": "run",
    "cycling": "bike",
    "in passenger vehicle": "car",
    "in vehicle": "car",
    "motorcycling": "car",
    "in bus": "transit",
    "in train": "transit",
    "in subway": "transit",
    "in tram": "transit",
    "in ferry": "transit",
    "flying": "flight",
    "still": "unknown",
    "unknown": "unknown",
    "unknown activity type": "unknown",
}

# Not a visit. The user searched for this address; they were never there.
EXCLUDED_SEMANTIC_TYPES = {"searched address"}


def map_activity_type(value: str | None) -> str:
    if not value:
        return "unknown"
    return ACTIVITY_TYPE_TO_MODE.get(value.strip().lower().replace("_", " "), "unknown")


def _f(value: Any) -> float | None:
    """Every numeric in this format arrives as a string."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = dtparser.isoparse(str(value))
    except (ValueError, OverflowError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _offset_name(dt: datetime) -> str | None:
    """Semantic-era records carry an offset but not a zone name. Keep the offset
    as a fixed-offset label rather than guessing a zone from coordinates - the
    offset is authoritative for display, the guess would not be."""
    off = dt.utcoffset()
    if off is None:
        return None
    total = int(off.total_seconds())
    if total == 0:
        return "UTC"
    sign = "+" if total > 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


class GoogleTimelineParser:
    source_kind = "google_timeline"

    def __init__(self, variant: str = "ios") -> None:
        self.variant = variant

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        if path.suffix.lower() != ".json":
            return None
        text = head.decode("utf-8", errors="replace")
        if '"semanticSegments"' in text:
            return ParserMatch(cls, 0.95, "android", cls.source_kind)
        stripped = text.lstrip()
        if stripped.startswith("[") and (
            '"startTime"' in text or '"timelinePath"' in text or '"visit"' in text
        ):
            return ParserMatch(cls, 0.9, "ios", cls.source_kind)
        return None

    # ── streaming ─────────────────────────────────────────
    def _records(self, path: Path) -> Iterator[dict]:
        """Stream records without materialising the file.

        ijson is used for both shapes: the Android wrapper key and the iOS bare
        array. A 13-year export is tens of MB, but old Takeout files reach GB.
        """
        import ijson

        with path.open("rb") as fh:
            head = fh.read(65536)
            fh.seek(0)
            prefix = "semanticSegments.item" if b'"semanticSegments"' in head else "item"
            for record in ijson.items(fh, prefix, use_float=True):
                if isinstance(record, dict):
                    yield record

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        seen_kinds: set[str] = set()
        for record in self._records(path):
            start = _ts(record.get("startTime"))
            end = _ts(record.get("endTime"))
            # Per-record dispatch: the four streams interleave inside one file.
            if "visit" in record:
                seen_kinds.add("visit")
                item = self._parse_visit(record["visit"], start, end)
                if item is not None:
                    yield item
            elif "activity" in record:
                seen_kinds.add("activity")
                item = self._parse_activity(record["activity"], start, end)
                if item is not None:
                    yield item
            elif "timelinePath" in record:
                seen_kinds.add("timelinePath")
                yield from self._parse_path(record["timelinePath"], start)
            elif "timelineMemory" in record:
                # Coarse "trip memory" summaries: no coordinates, no path.
                # Skipped on purpose - but counted, never silently dropped.
                yield SkipNote("timeline_memory")
            else:
                keys = sorted(k for k in record if k not in {"startTime", "endTime"})
                if not keys:
                    yield SkipNote("empty_segment")
                    continue
                # Google keeps changing this format. An unknown structure is an
                # error with a preserved sample, not a guess (P6).
                raise UnknownFormatError(
                    f"unknown Google timeline record type: {keys}",
                    json.dumps(record, ensure_ascii=False)[:200],
                )

    # ── per-record handlers ───────────────────────────────
    def _parse_visit(
        self, visit: dict, start: datetime | None, end: datetime | None
    ) -> ParsedItem | None:
        if start is None or end is None:
            return SkipNote("visit_without_time")
        # hierarchyLevel 1 is a parent container; taking it too would double the
        # Places for a single visit.
        if str(visit.get("hierarchyLevel", "0")).strip() not in {"0", ""}:
            return SkipNote("visit_hierarchy_parent")

        top = visit.get("topCandidate") or {}
        semantic = (top.get("semanticType") or "").strip()
        if semantic.lower() in EXCLUDED_SEMANTIC_TYPES:
            return SkipNote("searched_address")

        coords = parse_latlng(top.get("placeLocation"))
        if coords is None:
            return SkipNote("visit_without_location")
        lat, lon = coords
        return PlaceHint(
            lat=lat,
            lon=lon,
            start_utc=start,
            end_utc=end,
            tz_name=_offset_name(start),
            google_place_id=top.get("placeID"),
            semantic_type=semantic or None,
            probability=_f(visit.get("probability")),
        )

    def _parse_activity(
        self, activity: dict, start: datetime | None, end: datetime | None
    ) -> ParsedItem | None:
        if start is None or end is None:
            return SkipNote("activity_without_time")
        a = parse_latlng(activity.get("start"))
        b = parse_latlng(activity.get("end"))
        if a is None or b is None:
            return SkipNote("activity_without_endpoints")

        top = activity.get("topCandidate") or {}
        distance = _f(activity.get("distanceMeters"))
        # 0 means "Google did not know", not "did not move". Recording 0 would
        # silently understate lifetime mileage as though it were measured.
        if distance is not None and distance <= 0:
            distance = None

        return TrackHint(
            start_utc=start,
            end_utc=end,
            points=[a, b],
            mode=map_activity_type(top.get("type")),
            mode_source="google",
            # topCandidate.probability is hardcoded "0.000000" in every record;
            # deriving confidence from it would be inventing information.
            mode_confidence=None,
            distance_m=distance,
            geom_quality="endpoints_only",
        )

    def _parse_path(self, path_points: Any, start: datetime | None) -> Iterator[ParsedItem]:
        if start is None or not isinstance(path_points, list):
            yield SkipNote("path_without_time")
            return
        for entry in path_points:
            if not isinstance(entry, dict):
                continue
            coords = parse_latlng(entry.get("point"))
            if coords is None:
                continue
            offset = _f(entry.get("durationMinutesOffsetFromStartTime")) or 0.0
            # Resolution is whole minutes; duplicate offsets do occur (12 in the
            # sample), so dedup must tolerate collisions rather than raise.
            yield RawPointDTO(
                ts_utc=start + timedelta(minutes=offset),
                lat=coords[0],
                lon=coords[1],
                # This stream has no accuracy field at all, so the accuracy
                # filter is a no-op here and L2's "keep the more accurate one"
                # has no input.
                accuracy_m=None,
                confidence="measured",
            )
