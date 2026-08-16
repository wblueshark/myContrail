"""Recomputing the derived layer for a time window.

P1 says raw_point is immutable and everything else is disposable, so this
function is allowed to delete and rebuild every Place, Track and Trip that
touches the window. That is what makes "undo an import" tractable: drop the
source_file (raw_point cascades), then recompute the affected window with a
+/-1 day buffer. There is no full rebuild.

Declared stays and movements (Google's `visit` / `activity`) are recovered by
RE-PARSING the retained original file rather than being cached in a side table.
That is precisely what keeping the originals buys (P5), and it means a parser
fix can be applied to already-imported data without asking the user for the file
again. Photos are different: their directory is never read a second time, so
photo-derived Places are rebuilt from the `photo` rows themselves.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.config import get_settings
from contrail.core.geo import bbox_of, haversine_m
from contrail.core.timezones import to_local
from contrail.models import Place, SourceFile, Track, Trip
from contrail.pipeline import clustering, fusion, modes, trips
from contrail.pipeline.types import Move, Pt, Stay
from contrail.storage import get_storage

log = logging.getLogger(__name__)

# Recomputing a window must include a little context on either side, otherwise a
# stay straddling the boundary gets cut in half.
WINDOW_BUFFER = timedelta(days=1)


async def rederive_window(
    session: AsyncSession,
    user_id: UUID,
    window_start: datetime,
    window_end: datetime,
    settings=None,
) -> dict:
    """Rebuild Places / Tracks / Trips covering [window_start, window_end]."""
    settings = settings or get_settings()
    start = window_start - WINDOW_BUFFER
    end = window_end + WINDOW_BUFFER

    await _delete_derived(session, user_id, start, end)

    points = await _load_points(session, user_id, start, end)
    place_hints, track_hints = await _load_hints(session, user_id, start, end)

    # 1. Adopt what the source already declared. Google's `visit` records cover
    #    67% of the timeline; re-clustering those would be slower and worse.
    stays: list[Stay] = fusion.stays_from_hints(place_hints)
    # 2. Give declared movements real geometry from overlapping path records.
    moves: list[Move] = fusion.fuse_activity_geometry(track_hints, points)

    # 3. Cluster only what nothing has explained yet.
    leftover = fusion.uncovered_points(points, fusion.covered_intervals(place_hints, track_hints))
    if leftover:
        clustered, moving = clustering.cluster_stays(
            leftover,
            r_m=settings.cluster_radius_m,
            min_dwell_s=settings.cluster_min_dwell_s,
            gap_s=settings.cluster_gap_s,
            max_inferred_stay_s=settings.cluster_max_inferred_stay_s,
            accuracy_max_m=settings.accuracy_max_m,
        )
        stays.extend(clustered)
        moves.extend(clustering.build_moves(moving, clustered, gap_s=settings.cluster_gap_s))

    # 4. Photo-only days: photos become Places when nothing else covers the day.
    photo_stays, photo_times = await _photo_stays(session, user_id, start, end, stays, settings)
    stays.extend(photo_stays)

    stays.sort(key=lambda s: s.start)
    moves.sort(key=lambda m: m.start)

    altitudes = _altitude_index(points)
    for move in moves:
        move.speed_median_mps, move.speed_p95_mps = modes.speeds_from_move(move)
        modes.apply_mode(move, max_altitude_m=altitudes.get(_bucket(move.start)))

    moves = trips.insert_implied_moves(stays, moves)
    day_trips = trips.build_day_trips(stays, moves, photo_times)

    written = await _persist(session, user_id, day_trips)
    await session.flush()
    return written


async def _delete_derived(
    session: AsyncSession, user_id: UUID, start: datetime, end: datetime
) -> None:
    """Trips are dropped last: place.trip_id / track.trip_id are SET NULL, so
    deleting a Trip must never take its contents with it."""
    await session.execute(
        delete(Place).where(
            Place.user_id == user_id, Place.start_utc <= end, Place.end_utc >= start
        )
    )
    await session.execute(
        delete(Track).where(
            Track.user_id == user_id, Track.start_utc <= end, Track.end_utc >= start
        )
    )
    await session.execute(
        delete(Trip).where(Trip.user_id == user_id, Trip.start_utc <= end, Trip.end_utc >= start)
    )


async def _load_points(
    session: AsyncSession, user_id: UUID, start: datetime, end: datetime
) -> list[Pt]:
    rows = await session.execute(
        text(
            """
            SELECT ts_utc, ST_Y(geom) AS lat, ST_X(geom) AS lon,
                   accuracy_m, altitude_m, speed_mps, source_kind
            FROM raw_point
            WHERE user_id = :uid AND ts_utc BETWEEN :start AND :end
            ORDER BY ts_utc
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    return [
        Pt(
            ts=row.ts_utc,
            lat=row.lat,
            lon=row.lon,
            accuracy_m=row.accuracy_m,
            altitude_m=row.altitude_m,
            speed_mps=row.speed_mps,
            source_kind=row.source_kind,
        )
        for row in rows
    ]


async def _load_hints(session: AsyncSession, user_id: UUID, start: datetime, end: datetime):
    """Re-parse retained originals to recover declared stays and movements."""
    from contrail.parsers.base import PlaceHint, TrackHint
    from contrail.parsers.registry import sniff

    storage = get_storage()
    files = (
        await session.execute(
            select(SourceFile).where(
                SourceFile.user_id == user_id,
                SourceFile.kind != "photo",
                SourceFile.status == "done",
                SourceFile.storage_key.is_not(None),
            )
        )
    ).scalars()

    place_hints: list[PlaceHint] = []
    track_hints: list[TrackHint] = []
    for source in files:
        span = (source.stats or {}).get("time_span") or {}
        if span.get("start") and span.get("end"):
            try:
                file_start = datetime.fromisoformat(span["start"])
                file_end = datetime.fromisoformat(span["end"])
            except ValueError:
                file_start = file_end = None
            if file_start and file_end and (file_end < start or file_start > end):
                continue  # this file cannot contribute to the window

        try:
            path = Path(storage.local_path(source.storage_key))
            if not path.exists():
                continue
            match = sniff(path)
            parser = match.parser(match.variant)
            for item in parser.parse(path):
                if isinstance(item, PlaceHint) and item.end_utc >= start and item.start_utc <= end:
                    place_hints.append(item)
                elif (
                    isinstance(item, TrackHint) and item.end_utc >= start and item.start_utc <= end
                ):
                    track_hints.append(item)
        except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the rebuild
            log.warning(
                "could not re-parse retained source during rederive",
                extra={"source_file_id": str(source.id), "error": str(exc)},
            )

    place_hints.sort(key=lambda h: h.start_utc)
    track_hints.sort(key=lambda h: h.start_utc)
    return place_hints, track_hints


async def _photo_stays(
    session: AsyncSession,
    user_id: UUID,
    start: datetime,
    end: datetime,
    existing: list[Stay],
    settings,
) -> tuple[list[Stay], list[datetime]]:
    """Photo Places are only promoted to Trip Places on photo-only days.

    On any day that has track data, the photo keeps its own place intelligence
    and merely associates with the Trip Place; promoting it would double the
    stay points on the map.
    """
    rows = await session.execute(
        text(
            """
            SELECT taken_at_utc, ST_Y(geom) AS lat, ST_X(geom) AS lon, tz_name
            FROM photo
            WHERE user_id = :uid AND taken_at_utc BETWEEN :start AND :end
            ORDER BY taken_at_utc
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    photos = [r for r in rows if r.taken_at_utc is not None]
    photo_times = [r.taken_at_utc for r in photos]
    located = [r for r in photos if r.lat is not None and r.lon is not None]
    if not located:
        return [], photo_times

    covered_days = {to_local(s.start, s.tz_name).date() for s in existing}
    orphans = [
        Pt(ts=r.taken_at_utc, lat=r.lat, lon=r.lon, source_kind="photo")
        for r in located
        if to_local(r.taken_at_utc, r.tz_name).date() not in covered_days
    ]
    if not orphans:
        return [], photo_times
    return clustering.cluster_photo_stays(orphans, r_m=settings.cluster_radius_m), photo_times


def _bucket(ts: datetime) -> int:
    return int(ts.timestamp()) // 3600


def _altitude_index(points: list[Pt]) -> dict[int, float]:
    """Max altitude per hour - the only input that separates a flight from a
    high-speed train."""
    index: dict[int, float] = {}
    for point in points:
        if point.altitude_m is None:
            continue
        key = _bucket(point.ts)
        index[key] = max(index.get(key, point.altitude_m), point.altitude_m)
    return index


def _point_ewkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def _line_ewkt(points: list[tuple[float, float]]) -> str | None:
    unique: list[tuple[float, float]] = []
    for lat, lon in points:
        if not unique or haversine_m(unique[-1][0], unique[-1][1], lat, lon) > 0.5:
            unique.append((lat, lon))
    if len(unique) < 2:
        return None
    body = ", ".join(f"{lon} {lat}" for lat, lon in unique)
    return f"SRID=4326;LINESTRING({body})"


def _bbox_ewkt(points: list[tuple[float, float]]) -> str | None:
    box = bbox_of(points)
    if box is None:
        return None
    min_lon, min_lat, max_lon, max_lat = box
    # A degenerate box (a single point) is not a valid polygon; pad it slightly.
    if min_lon == max_lon:
        min_lon, max_lon = min_lon - 1e-6, max_lon + 1e-6
    if min_lat == max_lat:
        min_lat, max_lat = min_lat - 1e-6, max_lat + 1e-6
    ring = (
        f"{min_lon} {min_lat}, {max_lon} {min_lat}, "
        f"{max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}"
    )
    return f"SRID=4326;POLYGON(({ring}))"


async def _persist(session: AsyncSession, user_id: UUID, day_trips: list[trips.DayTrip]) -> dict:
    """Write the rebuilt day-trips.

    Group assignment rule (section 2.6): a NEW trip takes the batch's group; an
    EXISTING trip keeps the group it already had. A day can be assembled from
    several sources across several imports, and "last write wins" would let an
    unrelated GPX import silently re-file an entire holiday.
    """
    created = updated = places_n = tracks_n = 0

    for day in day_trips:
        existing = (
            await session.execute(
                select(Trip).where(Trip.user_id == user_id, Trip.local_date == day.local_date)
            )
        ).scalar_one_or_none()

        coords = [(s.lat, s.lon) for s in day.stays]
        for move in day.moves:
            coords.extend(move.points)

        stats = _trip_stats(day)
        title = trips.make_title(
            day,
            city_durations=None,
            countries=None,
            is_pure_commute=False,
        )

        if existing is None:
            trip = Trip(
                user_id=user_id,
                title=title,
                local_date=day.local_date,
                anchor_tz=day.anchor_tz,
                start_utc=day.start_utc,
                end_utc=day.end_utc,
                bbox=_bbox_ewkt(coords),
                stats=stats,
            )
            session.add(trip)
            await session.flush()
            created += 1
        else:
            trip = existing
            trip.anchor_tz = day.anchor_tz
            trip.start_utc = day.start_utc
            trip.end_utc = day.end_utc
            trip.bbox = _bbox_ewkt(coords)
            trip.stats = stats
            # The title is metadata the user may have edited (P7); only refresh
            # it while it still looks auto-generated.
            if trip.is_auto and _looks_generated(trip.title):
                trip.title = title
            updated += 1

        for stay in day.stays:
            session.add(
                Place(
                    user_id=user_id,
                    trip_id=trip.id,
                    centroid=_point_ewkt(stay.lat, stay.lon),
                    radius_m=stay.radius_m,
                    start_utc=stay.start,
                    end_utc=stay.end,
                    origin=stay.origin,
                    google_place_id=stay.google_place_id,
                    is_inferred_dwell=stay.is_inferred_dwell,
                    inferred_ratio=stay.inferred_ratio,
                    tz_name=stay.tz_name,
                    point_count=stay.point_count,
                    geo_name=stay.name,
                    geo_source="google" if stay.name else None,
                    source_kinds=stay.source_kinds or ["google_timeline"],
                )
            )
            places_n += 1

        for move in day.moves:
            geom = _line_ewkt(move.points)
            if geom is None:
                continue
            session.add(
                Track(
                    user_id=user_id,
                    trip_id=trip.id,
                    geom=geom,
                    start_utc=move.start,
                    end_utc=move.end,
                    distance_m=move.distance_m,
                    distance_unknown=move.distance_unknown or move.distance_m is None,
                    geom_quality=move.geom_quality,
                    duration_s=move.duration_s,
                    speed_median_mps=move.speed_median_mps,
                    speed_p95_mps=move.speed_p95_mps,
                    elevation_gain_m=move.elevation_gain_m,
                    mode=move.mode,
                    mode_source=move.mode_source,
                    mode_confidence=move.mode_confidence,
                    point_count=move.point_count,
                    crosses_tz=move.crosses_tz,
                    source_kind=move.source_kind,
                )
            )
            tracks_n += 1

    return {
        "trips_created": created,
        "trips_updated": updated,
        "places": places_n,
        "tracks": tracks_n,
    }


def _looks_generated(title: str) -> bool:
    """Cheap check that a title has not been hand-edited."""
    return bool(title) and (title[:4].isdigit() or " · " in title)


def _trip_stats(day: trips.DayTrip) -> dict:
    by_mode: dict[str, float] = {}
    unknown_distance = 0
    for move in day.moves:
        if move.distance_m is None:
            unknown_distance += 1
            continue
        by_mode[move.mode] = by_mode.get(move.mode, 0.0) + move.distance_m
    return {
        "distance_by_mode_m": by_mode,
        "distance_total_m": sum(by_mode.values()),
        # Honesty requirement: unknown distance is reported, never counted as 0.
        "distance_unknown_segments": unknown_distance,
        "place_count": len(day.stays),
        "track_count": len(day.moves),
        "photo_count": day.photo_count,
        "photo_only": bool(day.photo_count and not day.stays and not day.moves),
        "inferred_dwell_count": sum(1 for s in day.stays if s.is_inferred_dwell),
        "timezones": sorted({s.tz_name for s in day.stays if s.tz_name}),
    }
