"""Read routes: trips, places, tracks, photos, search, stats, anchors."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.db import get_session
from contrail.schemas import AnchorOut, PhotoOut, PlaceOut, TrackOut, TripOut
from contrail.security import current_user_id
from contrail.storage import get_storage

router = APIRouter(tags=["query"])

MAX_LIMIT = 2000


def _bbox_clause(bbox: str | None, column: str) -> tuple[str, dict]:
    """`bbox` is min_lon,min_lat,max_lon,max_lat in WGS-84."""
    if not bbox:
        return "", {}
    try:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="bbox must be 4 comma-separated numbers"
        ) from exc
    # && against a geometry envelope so the GiST index is actually used.
    return (
        f" AND {column} && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)",
        {"min_lon": min_lon, "min_lat": min_lat, "max_lon": max_lon, "max_lat": max_lat},
    )


@router.get("/trips", response_model=list[TripOut])
async def list_trips(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    bbox: str | None = None,
    group: uuid.UUID | None = None,
    tag: uuid.UUID | None = None,
    commute: str | None = Query(default=None, pattern="^(pure|mixed|none)$"),
    q: str | None = None,
    limit: int = Query(default=200, le=MAX_LIMIT),
    cursor: date | None = None,
) -> list[TripOut]:
    clause, params = _bbox_clause(bbox, "t.bbox")
    sql = f"""
        SELECT t.id, t.title, t.local_date, t.anchor_tz, t.start_utc, t.end_utc,
               t.group_id, t.commute_class::text AS commute_class, t.stats,
               t.cover_photo_id,
               COALESCE(array_agg(tt.tag_id) FILTER (WHERE tt.tag_id IS NOT NULL), '{{}}')
                   AS tag_ids,
               EXISTS (SELECT 1 FROM track tr
                        WHERE tr.trip_id = t.id AND tr.crosses_tz) AS crosses_tz
          FROM trip t
          LEFT JOIN trip_tag tt ON tt.trip_id = t.id
         WHERE t.user_id = :uid
           AND (CAST(:from_date AS date) IS NULL OR t.local_date >= :from_date)
           AND (CAST(:to_date AS date)   IS NULL OR t.local_date <= :to_date)
           AND (CAST(:group_id AS uuid)  IS NULL OR t.group_id = :group_id)
           AND (CAST(:commute AS text)   IS NULL OR t.commute_class::text = :commute)
           AND (CAST(:cursor AS date)    IS NULL OR t.local_date < :cursor)
           AND (CAST(:q AS text) IS NULL OR t.title ILIKE '%' || :q || '%')
           AND (CAST(:tag_id AS uuid) IS NULL OR EXISTS
                 (SELECT 1 FROM trip_tag x WHERE x.trip_id = t.id AND x.tag_id = :tag_id))
           {clause}
         GROUP BY t.id
         ORDER BY t.local_date DESC
         LIMIT :limit
    """
    rows = (
        await session.execute(
            text(sql),
            {
                "uid": str(user_id),
                "from_date": from_,
                "to_date": to,
                "group_id": str(group) if group else None,
                "tag_id": str(tag) if tag else None,
                "commute": commute,
                "cursor": cursor,
                "q": q,
                "limit": limit,
                **params,
            },
        )
    ).all()
    return [
        TripOut(
            id=r.id,
            title=r.title,
            local_date=r.local_date,
            anchor_tz=r.anchor_tz,
            start_utc=r.start_utc,
            end_utc=r.end_utc,
            group_id=r.group_id,
            commute_class=r.commute_class,
            stats=r.stats or {},
            tag_ids=list(r.tag_ids or []),
            cover_photo_id=r.cover_photo_id,
            crosses_tz=bool(r.crosses_tz),
        )
        for r in rows
    ]


@router.get("/trips/{trip_id}")
async def get_trip(
    trip_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One day, fully expanded: its places, tracks and photos in time order."""
    row = (
        await session.execute(
            text(
                """
                SELECT t.id, t.title, t.local_date, t.anchor_tz, t.start_utc, t.end_utc,
                       t.group_id, t.commute_class::text AS commute_class, t.stats,
                       t.cover_photo_id
                  FROM trip t WHERE t.id = :id AND t.user_id = :uid
                """
            ),
            {"id": str(trip_id), "uid": str(user_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="trip not found")

    # `from_` defaults to a FastAPI Query object, which only resolves to a value
    # when FastAPI itself calls the endpoint. Calling these directly means every
    # optional argument has to be passed explicitly, or a Query instance reaches
    # the driver as a bind parameter.
    places = await list_places(
        user_id=user_id, session=session, trip_id=trip_id, from_=None, limit=MAX_LIMIT
    )
    tracks = await list_tracks(
        user_id=user_id, session=session, trip_id=trip_id, from_=None, limit=MAX_LIMIT
    )
    photos = await list_photos(
        user_id=user_id, session=session, trip_id=trip_id, from_=None, limit=MAX_LIMIT
    )
    return {
        "trip": {
            "id": str(row.id),
            "title": row.title,
            "local_date": row.local_date.isoformat(),
            "anchor_tz": row.anchor_tz,
            "start_utc": row.start_utc.isoformat(),
            "end_utc": row.end_utc.isoformat(),
            "group_id": str(row.group_id) if row.group_id else None,
            "commute_class": row.commute_class,
            "stats": row.stats or {},
            "cover_photo_id": str(row.cover_photo_id) if row.cover_photo_id else None,
        },
        "places": [p.model_dump(mode="json") for p in places],
        "tracks": [t.model_dump(mode="json") for t in tracks],
        "photos": [p.model_dump(mode="json") for p in photos],
    }


@router.get("/places", response_model=list[PlaceOut])
async def list_places(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    trip_id: uuid.UUID | None = None,
    bbox: str | None = None,
    center: str | None = None,
    radius: float | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    group: uuid.UUID | None = None,
    tag: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(default=500, le=MAX_LIMIT),
) -> list[PlaceOut]:
    clause, params = _bbox_clause(bbox, "p.centroid")
    radius_clause = ""
    if center and radius:
        try:
            lat, lon = (float(v) for v in center.split(","))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="center must be 'lat,lon'") from exc
        # ST_DWithin on geography gives a true metric radius; the geometry form
        # would silently be in degrees.
        radius_clause = (
            " AND ST_DWithin(p.centroid::geography,"
            " ST_SetSRID(ST_MakePoint(:c_lon, :c_lat), 4326)::geography, :radius)"
        )
        params.update({"c_lat": lat, "c_lon": lon, "radius": radius})

    sql = f"""
        SELECT p.id, p.trip_id, ST_Y(p.centroid) AS lat, ST_X(p.centroid) AS lon,
               p.radius_m, p.start_utc, p.end_utc, p.duration_s, p.origin,
               p.is_inferred_dwell, p.inferred_ratio, p.tz_name, p.name,
               p.geo_name, p.geo_city, p.geo_country, p.point_count,
               p.source_kinds::text[] AS source_kinds,
               (SELECT count(*) FROM photo ph WHERE ph.trip_place_id = p.id) AS photo_count
          FROM place p
         WHERE p.user_id = :uid
           AND (CAST(:trip_id AS uuid) IS NULL OR p.trip_id = :trip_id)
           AND (CAST(:from_ts AS timestamptz) IS NULL OR p.end_utc   >= :from_ts)
           AND (CAST(:to_ts AS timestamptz)   IS NULL OR p.start_utc <= :to_ts)
           AND (CAST(:group_id AS uuid) IS NULL OR p.group_id = :group_id OR
                (p.group_id IS NULL AND EXISTS
                  (SELECT 1 FROM trip t WHERE t.id = p.trip_id AND t.group_id = :group_id)))
           AND (CAST(:tag_id AS uuid) IS NULL OR EXISTS
                 (SELECT 1 FROM place_tag x WHERE x.place_id = p.id AND x.tag_id = :tag_id))
           AND (CAST(:q AS text) IS NULL OR
                (coalesce(p.name,'') || ' ' || coalesce(p.geo_name,'') || ' ' ||
                 coalesce(p.geo_city,'')) ILIKE '%' || :q || '%')
           {clause}{radius_clause}
         ORDER BY p.start_utc
         LIMIT :limit
    """
    rows = (
        await session.execute(
            text(sql),
            {
                "uid": str(user_id),
                "trip_id": str(trip_id) if trip_id else None,
                "from_ts": from_,
                "to_ts": to,
                "group_id": str(group) if group else None,
                "tag_id": str(tag) if tag else None,
                "q": q,
                "limit": limit,
                **params,
            },
        )
    ).all()
    return [
        PlaceOut(
            id=r.id,
            trip_id=r.trip_id,
            lat=r.lat,
            lon=r.lon,
            radius_m=r.radius_m,
            start_utc=r.start_utc,
            end_utc=r.end_utc,
            duration_s=r.duration_s,
            origin=r.origin,
            is_inferred_dwell=r.is_inferred_dwell,
            inferred_ratio=r.inferred_ratio,
            tz_name=r.tz_name,
            name=r.name,
            geo_name=r.geo_name,
            geo_city=r.geo_city,
            geo_country=r.geo_country,
            point_count=r.point_count,
            source_kinds=list(r.source_kinds or []),
            photo_count=r.photo_count,
        )
        for r in rows
    ]


@router.get("/tracks", response_model=list[TrackOut])
async def list_tracks(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    trip_id: uuid.UUID | None = None,
    bbox: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    mode: str | None = None,
    source: str | None = None,
    commute: bool | None = None,
    limit: int = Query(default=500, le=MAX_LIMIT),
) -> list[TrackOut]:
    clause, params = _bbox_clause(bbox, "t.geom")
    sql = f"""
        SELECT t.id, t.trip_id, t.start_utc, t.end_utc, t.distance_m,
               t.distance_unknown, t.geom_quality, t.duration_s,
               t.mode::text AS mode, t.mode_source, t.mode_confidence,
               t.is_commute, t.crosses_tz, t.source_kind::text AS source_kind
          FROM track t
         WHERE t.user_id = :uid AND NOT t.is_shadow
           AND (CAST(:trip_id AS uuid) IS NULL OR t.trip_id = :trip_id)
           AND (CAST(:from_ts AS timestamptz) IS NULL OR t.end_utc   >= :from_ts)
           AND (CAST(:to_ts AS timestamptz)   IS NULL OR t.start_utc <= :to_ts)
           AND (CAST(:mode AS text)   IS NULL OR t.mode::text = :mode)
           AND (CAST(:source AS text) IS NULL OR t.source_kind::text = :source)
           AND (CAST(:commute AS boolean) IS NULL OR t.is_commute = :commute)
           {clause}
         ORDER BY t.start_utc
         LIMIT :limit
    """
    rows = (
        await session.execute(
            text(sql),
            {
                "uid": str(user_id),
                "trip_id": str(trip_id) if trip_id else None,
                "from_ts": from_,
                "to_ts": to,
                "mode": mode,
                "source": source,
                "commute": commute,
                "limit": limit,
                **params,
            },
        )
    ).all()
    return [TrackOut(**dict(r._mapping)) for r in rows]


@router.get("/photos", response_model=list[PhotoOut])
async def list_photos(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    trip_id: uuid.UUID | None = None,
    place_id: uuid.UUID | None = None,
    bbox: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(default=500, le=MAX_LIMIT),
) -> list[PhotoOut]:
    """Photo metadata. `orig_path` is never included - absolute paths do not
    travel over HTTP, on the way in or on the way out."""
    clause, params = _bbox_clause(bbox, "p.geom")
    sql = f"""
        SELECT p.id, p.trip_id, p.place_id,
               ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
               p.taken_at_utc, p.taken_at_local, p.tz_name, p.tz_source,
               p.location_confidence::text AS location_confidence,
               p.orig_filename, p.width, p.height, p.camera_make, p.camera_model
          FROM photo p
         WHERE p.user_id = :uid
           AND (CAST(:trip_id AS uuid)  IS NULL OR p.trip_id = :trip_id)
           AND (CAST(:place_id AS uuid) IS NULL OR p.trip_place_id = :place_id)
           AND (CAST(:from_ts AS timestamptz) IS NULL OR p.taken_at_utc >= :from_ts)
           AND (CAST(:to_ts AS timestamptz)   IS NULL OR p.taken_at_utc <= :to_ts)
           {clause}
         ORDER BY p.taken_at_utc
         LIMIT :limit
    """
    rows = (
        await session.execute(
            text(sql),
            {
                "uid": str(user_id),
                "trip_id": str(trip_id) if trip_id else None,
                "place_id": str(place_id) if place_id else None,
                "from_ts": from_,
                "to_ts": to,
                "limit": limit,
                **params,
            },
        )
    ).all()
    return [PhotoOut(**dict(r._mapping)) for r in rows]


async def _photo_blob(session: AsyncSession, user_id, photo_id: uuid.UUID, column: str) -> bytes:
    key = (
        await session.execute(
            text(f"SELECT {column} FROM photo WHERE id = :id AND user_id = :uid"),
            {"id": str(photo_id), "uid": str(user_id)},
        )
    ).scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="thumbnail not available")
    try:
        return get_storage().get(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="thumbnail not available") from exc


@router.get("/photos/{photo_id}/thumb")
async def photo_thumb(
    photo_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    data = await _photo_blob(session, user_id, photo_id, "thumb_key")
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/photos/{photo_id}/micro")
async def photo_micro(
    photo_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    data = await _photo_blob(session, user_id, photo_id, "micro_key")
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/anchors", response_model=list[AnchorOut])
async def list_anchors(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    kind: str | None = None,
) -> list[AnchorOut]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, ST_Y(centroid) AS lat, ST_X(centroid) AS lon,
                       kind::text AS kind, kind_source, visit_count, total_duration_s,
                       weekday_ratio, first_visit_utc, last_visit_utc,
                       geo_name, geo_city, hour_histogram
                  FROM place_anchor
                 WHERE user_id = :uid AND (CAST(:kind AS text) IS NULL OR kind::text = :kind)
                 ORDER BY total_duration_s DESC
                """
            ),
            {"uid": str(user_id), "kind": kind},
        )
    ).all()
    return [AnchorOut(**dict(r._mapping)) for r in rows]


@router.get("/search")
async def search(
    q: str,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=30, le=200),
) -> dict:
    """Unified search over place names and trip titles.

    ILIKE backed by the trigram index rather than to_tsvector: the 'simple'
    text-search configuration does not segment CJK, so searching the
    two-character form of a Japanese city name matches nothing. Trigram + ILIKE
    does match - verified on this machine.
    """
    places = (
        await session.execute(
            text(
                """
                SELECT id, ST_Y(centroid) AS lat, ST_X(centroid) AS lon,
                       coalesce(name, geo_name, geo_city) AS label, geo_city, geo_country,
                       start_utc, trip_id
                  FROM place
                 WHERE user_id = :uid
                   AND (coalesce(name,'') || ' ' || coalesce(geo_name,'') || ' ' ||
                        coalesce(geo_city,'') || ' ' || coalesce(geo_country,''))
                       ILIKE '%' || :q || '%'
                 ORDER BY start_utc DESC
                 LIMIT :limit
                """
            ),
            {"uid": str(user_id), "q": q, "limit": limit},
        )
    ).all()
    trips = (
        await session.execute(
            text(
                """
                SELECT id, title, local_date FROM trip
                 WHERE user_id = :uid AND title ILIKE '%' || :q || '%'
                 ORDER BY local_date DESC LIMIT :limit
                """
            ),
            {"uid": str(user_id), "q": q, "limit": limit},
        )
    ).all()
    return {
        "places": [
            {
                "id": str(r.id),
                "label": r.label,
                "lat": r.lat,
                "lon": r.lon,
                "city": r.geo_city,
                "country": r.geo_country,
                "trip_id": str(r.trip_id) if r.trip_id else None,
                "start_utc": r.start_utc.isoformat(),
            }
            for r in places
        ],
        "trips": [
            {"id": str(r.id), "title": r.title, "local_date": r.local_date.isoformat()}
            for r in trips
        ],
    }


@router.get("/stats")
async def stats(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    group: uuid.UUID | None = None,
) -> dict:
    """Aggregate panel data.

    Computed live: a GROUP BY over 240k rows is a matter of milliseconds, so the
    daily-rollup table the original design called for was cut.

    Distance totals report the unknown count separately. 53% of semantic-era
    segments have no distance, so the lifetime total is necessarily an
    underestimate and the panel must say so rather than pass silence off as zero.
    """
    params = {
        "uid": str(user_id),
        "from_date": from_,
        "to_date": to,
        "group_id": str(group) if group else None,
    }
    where = """
        t.user_id = :uid
        AND (CAST(:from_date AS date) IS NULL OR t.local_date >= :from_date)
        AND (CAST(:to_date AS date)   IS NULL OR t.local_date <= :to_date)
        AND (CAST(:group_id AS uuid)  IS NULL OR t.group_id = :group_id)
    """

    totals = (
        await session.execute(
            text(
                f"""
                SELECT count(*) AS trip_count,
                       min(t.local_date) AS first_day,
                       max(t.local_date) AS last_day
                  FROM trip t WHERE {where}
                """
            ),
            params,
        )
    ).first()

    by_mode = (
        await session.execute(
            text(
                f"""
                SELECT tr.mode::text AS mode,
                       SUM(COALESCE(tr.distance_m, 0)) AS distance_m,
                       COUNT(*) FILTER (WHERE tr.distance_m IS NULL) AS unknown_count,
                       COUNT(*) AS segment_count,
                       SUM(tr.duration_s) AS duration_s
                  FROM track tr JOIN trip t ON t.id = tr.trip_id
                 WHERE {where} AND NOT tr.is_shadow
                 GROUP BY tr.mode
                """
            ),
            params,
        )
    ).all()

    coverage = (
        await session.execute(
            text(
                f"""
                SELECT count(DISTINCT p.geo_country) FILTER (WHERE p.geo_country IS NOT NULL)
                           AS countries,
                       count(DISTINCT p.geo_city)    FILTER (WHERE p.geo_city IS NOT NULL)
                           AS cities,
                       count(*) AS place_count,
                       count(*) FILTER (WHERE p.is_inferred_dwell) AS inferred_dwell_count
                  FROM place p JOIN trip t ON t.id = p.trip_id
                 WHERE {where}
                """
            ),
            params,
        )
    ).first()

    activity = (
        await session.execute(
            text(
                f"""
                SELECT t.local_date AS day,
                       count(DISTINCT p.id) AS places,
                       COALESCE(SUM(DISTINCT tr.distance_m), 0) AS distance_m
                  FROM trip t
                  LEFT JOIN place p  ON p.trip_id = t.id
                  LEFT JOIN track tr ON tr.trip_id = t.id
                 WHERE {where}
                 GROUP BY t.local_date ORDER BY t.local_date
                """
            ),
            params,
        )
    ).all()

    photos = (
        await session.execute(
            text(
                f"""
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE ph.location_confidence = 'inferred') AS inferred,
                       count(*) FILTER (WHERE ph.geom IS NULL) AS unlocated
                  FROM photo ph JOIN trip t ON t.id = ph.trip_id
                 WHERE {where}
                """
            ),
            params,
        )
    ).first()

    return {
        "trip_count": totals.trip_count if totals else 0,
        "first_day": totals.first_day.isoformat() if totals and totals.first_day else None,
        "last_day": totals.last_day.isoformat() if totals and totals.last_day else None,
        "distance_by_mode": [
            {
                "mode": r.mode,
                "distance_m": float(r.distance_m or 0),
                "segments": r.segment_count,
                # Surfaced deliberately: this is how much of the total is missing.
                "unknown_distance_segments": r.unknown_count,
                "duration_s": int(r.duration_s or 0),
            }
            for r in by_mode
        ],
        "distance_total_m": sum(float(r.distance_m or 0) for r in by_mode),
        "unknown_distance_segments": sum(r.unknown_count for r in by_mode),
        "countries": coverage.countries if coverage else 0,
        "cities": coverage.cities if coverage else 0,
        "place_count": coverage.place_count if coverage else 0,
        "inferred_dwell_count": coverage.inferred_dwell_count if coverage else 0,
        "photos": {
            "total": photos.total if photos else 0,
            "inferred_location": photos.inferred if photos else 0,
            "unlocated": photos.unlocated if photos else 0,
        },
        "activity": [
            {"day": r.day.isoformat(), "places": r.places, "distance_m": float(r.distance_m or 0)}
            for r in activity
        ],
    }
