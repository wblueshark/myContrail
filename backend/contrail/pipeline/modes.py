"""Travel-mode inference.

Priority, highest wins:
    1. user override          mode_source = manual
    2. file declaration       mode_source = declared   (GPX type / FIT sport)
    3. Google activityType    mode_source = google
    4. speed + geometry       mode_source = inferred
    5. give up                mode = unknown

Level 3 never fires in the path era: `timelinePath` carries no semantics at all,
so stays and modes must be derived entirely by us there. The semantic era is the
mirror image - Google hands both over.

Rules are evaluated top to bottom and the FIRST match wins. v1.0 left this
undefined and 2.5-4.0 m/s matched both `run` and `bike` simultaneously.

Two rows exist specifically to avoid a very visible misclassification:
33-55 m/s (119-198 km/h) was uncovered in v1.0, and `v_med >= 55` alone labels a
Chinese high-speed train (350 km/h, straight, long) as a FLIGHT. Altitude is
what separates them. But timelinePath has no altitude field, so on that source
rule 7 can never fire and real flights (measured at 334 / 390 / 461 km/h) all
land on rule 8 as `transit`. That is an accepted downgrade under "unknown beats
wrong", not a bug to paper over.
"""

from __future__ import annotations

from dataclasses import dataclass

from contrail.core.geo import path_length_m, straightness
from contrail.pipeline.types import Move

FLIGHT_ALTITUDE_M = 3000.0
FLIGHT_MIN_DISTANCE_M = 100_000.0
FLIGHT_MIN_STRAIGHTNESS = 0.9

# Reference speeds (m/s): walking 1.4, running 3.0, cycling 5.5,
# city driving 8-15, motorway 30, airliner 250.
DRIFT = "drift"


@dataclass(slots=True)
class ModeVerdict:
    mode: str
    confidence: float | None
    source: str
    drop: bool = False


def infer_mode(
    v_med: float | None,
    v_p95: float | None,
    distance_m: float | None = None,
    straightness_ratio: float | None = None,
    max_altitude_m: float | None = None,
) -> ModeVerdict:
    if v_med is None or v_p95 is None:
        return ModeVerdict("unknown", None, "inferred")

    # 1. Barely moving in both statistics: GPS jitter, not a journey.
    if v_med < 0.3 and v_p95 < 1.0:
        return ModeVerdict("unknown", None, "inferred", drop=True)
    if v_med < 2.0 and v_p95 < 3.5:
        return ModeVerdict("walk", 0.9, "inferred")
    if 2.0 <= v_med < 4.0 and v_p95 < 6.5:
        return ModeVerdict("run", 0.8, "inferred")
    if 2.5 <= v_med < 8.5 and v_p95 < 14:
        return ModeVerdict("bike", 0.75, "inferred")
    if 8.5 <= v_med < 33:
        # car vs transit needs stop-pattern analysis; record the safer label.
        return ModeVerdict("car", 0.5, "inferred")
    if 33 <= v_med < 55:
        return ModeVerdict("transit", 0.6, "inferred")

    if v_med >= 55:
        long_and_straight = (
            (straightness_ratio or 0.0) > FLIGHT_MIN_STRAIGHTNESS
            and (distance_m or 0.0) > FLIGHT_MIN_DISTANCE_M
        )
        if long_and_straight:
            if max_altitude_m is not None and max_altitude_m > FLIGHT_ALTITUDE_M:
                return ModeVerdict("flight", 0.95, "inferred")
            # No altitude, or too low: could be high-speed rail. Say transit.
            return ModeVerdict("transit", 0.6, "inferred")
    return ModeVerdict("unknown", None, "inferred")


def apply_mode(move: Move, max_altitude_m: float | None = None) -> Move:
    """Fill in mode for one Move unless a higher-priority source already did."""
    if move.mode_source in {"manual", "declared", "google"} and move.mode != "unknown":
        return move

    distance = move.distance_m if move.distance_m is not None else path_length_m(move.points)
    verdict = infer_mode(
        move.speed_median_mps,
        move.speed_p95_mps,
        distance_m=distance,
        straightness_ratio=straightness(move.points),
        max_altitude_m=max_altitude_m if max_altitude_m is not None else move.elevation_gain_m,
    )
    move.mode = verdict.mode
    move.mode_source = verdict.source
    move.mode_confidence = verdict.confidence
    return move


def speeds_from_move(move: Move) -> tuple[float | None, float | None]:
    """Recover median / p95 speed from geometry when the source gave neither."""
    if move.speed_median_mps is not None:
        return move.speed_median_mps, move.speed_p95_mps
    if move.duration_s <= 0 or len(move.points) < 2:
        return None, None
    average = path_length_m(move.points) / move.duration_s
    return average, average
