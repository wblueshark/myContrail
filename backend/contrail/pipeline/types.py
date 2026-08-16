"""Intermediate structures shared by the pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Pt:
    """A raw point reduced to what the algorithms actually use."""

    ts: datetime
    lat: float
    lon: float
    accuracy_m: float | None = None
    altitude_m: float | None = None
    speed_mps: float | None = None
    source_kind: str = "google_timeline"


@dataclass(slots=True)
class Stay:
    lat: float
    lon: float
    start: datetime
    end: datetime
    radius_m: float = 0.0
    point_count: int = 0
    # P4: a dwell whose length was partly deduced from a data gap must say so
    # rather than present itself as measured.
    is_inferred_dwell: bool = False
    inferred_ratio: float = 0.0
    origin: str = "track"
    tz_name: str | None = None
    name: str | None = None
    google_place_id: str | None = None
    semantic_type: str | None = None
    source_kinds: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(slots=True)
class Move:
    start: datetime
    end: datetime
    points: list[tuple[float, float]]
    distance_m: float | None = None
    distance_unknown: bool = False
    duration_s: int = 0
    speed_median_mps: float | None = None
    speed_p95_mps: float | None = None
    elevation_gain_m: float | None = None
    mode: str = "unknown"
    mode_source: str | None = None
    mode_confidence: float | None = None
    geom_quality: str = "full"
    point_count: int = 0
    crosses_tz: bool = False
    source_kind: str = "google_timeline"
