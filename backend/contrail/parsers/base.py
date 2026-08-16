"""Parser contract.

A parser turns one file into a lazy stream of items:

  RawPointDTO - a measured position in time (the raw material)
  PlaceHint   - "the source already told us this was a stay"
  TrackHint   - "the source already told us this was a movement"
  SkipNote    - "this record was understood and deliberately not imported"

Hints matter because Google's semantic records hand us stays and travel modes
outright for 67% of the timeline. Re-deriving those with our own clustering
would be both slower and worse.

P6 (failures must be loud): an unrecognised structure raises
UnknownFormatError with a sample attached. It is never skipped silently.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


class UnknownFormatError(Exception):
    """Raised when sniffing or parsing meets a structure we do not understand.

    `sample` keeps the first bytes / the offending record so the failure can be
    diagnosed later without asking the user for the file again.
    """

    def __init__(self, message: str, sample: str | bytes | None = None) -> None:
        super().__init__(message)
        self.sample = sample[:200] if isinstance(sample, (str, bytes)) else sample


@dataclass(slots=True)
class RawPointDTO:
    ts_utc: datetime
    lat: float
    lon: float
    altitude_m: float | None = None
    accuracy_m: float | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    confidence: str = "measured"
    tz_name: str | None = None
    raw: dict | None = None


@dataclass(slots=True)
class PlaceHint:
    """A stay the source declared. Skips clustering entirely."""

    lat: float
    lon: float
    start_utc: datetime
    end_utc: datetime
    tz_name: str | None = None
    name: str | None = None
    google_place_id: str | None = None
    # 'Home' | 'Work' | 'Inferred Home' | 'Inferred Work' | 'Unknown' | ...
    semantic_type: str | None = None
    probability: float | None = None


@dataclass(slots=True)
class TrackHint:
    """A movement the source declared.

    `points` may hold only the two endpoints (semantic era). The pipeline later
    tries to fill in real geometry from overlapping timelinePath records.
    """

    start_utc: datetime
    end_utc: datetime
    points: list[tuple[float, float]] = field(default_factory=list)
    mode: str = "unknown"
    mode_source: str | None = None
    mode_confidence: float | None = None
    distance_m: float | None = None
    geom_quality: str = "endpoints_only"


@dataclass(slots=True)
class SkipNote:
    """Understood, intentionally not imported. Counted in source_file.stats."""

    reason: str
    count: int = 1


ParsedItem = RawPointDTO | PlaceHint | TrackHint | SkipNote


@dataclass(slots=True)
class ParserMatch:
    parser: type[Parser]
    confidence: float
    variant: str
    source_kind: str


@runtime_checkable
class Parser(Protocol):
    """Implemented by every parser. `source_kind` maps onto the source_type enum."""

    source_kind: str

    @classmethod
    def sniff(cls, path: Path, head: bytes) -> ParserMatch | None:
        """Decide from the first <= 64 KB whether this parser applies.

        Must not parse the whole file.
        """

    def parse(self, path: Path) -> Iterator[ParsedItem]:
        """Yield items lazily, in file order."""
