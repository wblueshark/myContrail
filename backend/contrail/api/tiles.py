"""Vector tiles - the load-bearing piece of the rendering architecture.

Why MVT rather than GeoJSON: sending a whole track set to the browser is
gigabytes and a crash; filtering by bbox still returns everything at world zoom;
thinning server-side works but recomputes on every zoom with nothing cacheable.
ST_AsMVT produces tens of kilobytes per tile, simplifies natively, and caches by
its very shape.

Two details decide whether this is fast or unusable:

  * t.geom and the tile envelope are both `geometry`, so `&&` uses the GiST
    index. The earlier `geography && geometry` form triggered an implicit cast
    that disabled the index and turned every tile request into a full table
    scan.
  * mode / source / is_commute / group_id / time are emitted as FEATURE
    ATTRIBUTES, not SQL predicates. The timeline slider then filters entirely on
    the client at 60 fps with no server round-trip at all.

No Redis tile cache: at this data volume tiles generate in real time, and the
MVP has no concurrency. That also removes a whole class of cache-invalidation
bugs. If a cache is ever reinstated, its key MUST include a monotonic
user_data_version bumped by every write - otherwise a user who spots their home
on the map, adds a fence and reloads gets the stale tile back, home still on it.

Fences are NOT applied here in the MVP. The single enforcement point is export
(see exports.py). contrail_apply_fence exists and the flag is wired so cloud
mode only has to flip it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.db import get_session
from contrail.security import current_user_id

router = APIRouter(tags=["tiles"])

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
MAX_ZOOM = 22
# Photos aggregate into clusters below this zoom and are drawn individually at
# or above it.
PHOTO_CLUSTER_MAX_Z = 14

TRACK_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(:z, :x, :y) AS geom
),
fenced AS (
  SELECT t.id, t.mode::text AS mode, t.distance_m, t.start_utc, t.end_utc,
         t.is_commute, t.trip_id, t.source_kind::text AS source_kind,
         t.geom_quality, t.distance_unknown,
         CASE WHEN :apply_fence THEN contrail_apply_fence(t.geom, :uid)
              ELSE t.geom END AS geom
    FROM track t
   WHERE t.user_id = :uid
     AND NOT t.is_shadow
     AND (CAST(:from_ts AS timestamptz) IS NULL OR t.end_utc   >= :from_ts)
     AND (CAST(:to_ts AS timestamptz)   IS NULL OR t.start_utc <= :to_ts)
     AND t.geom && ST_Transform((SELECT geom FROM bounds), 4326)
),
mvtgeom AS (
  SELECT ST_AsMVTGeom(
           ST_Simplify(
             ST_Transform(geom, 3857),
             -- roughly two screen pixels at this zoom
             GREATEST(0.5, 156543.03 / (2 ^ :z) * 2)
           ),
           (SELECT geom FROM bounds), 4096, 64, true) AS geom,
         id, mode, distance_m, distance_unknown, geom_quality,
         extract(epoch from start_utc)::bigint AS start_ts,
         extract(epoch from end_utc)::bigint   AS end_ts,
         is_commute, trip_id, source_kind
    FROM fenced
   WHERE geom IS NOT NULL
)
SELECT ST_AsMVT(mvtgeom.*, 'tracks', 4096, 'geom') FROM mvtgeom
"""

PLACE_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(:z, :x, :y) AS geom
),
fenced AS (
  SELECT p.id, p.duration_s, p.start_utc, p.trip_id, p.origin,
         p.is_inferred_dwell, coalesce(p.name, p.geo_name, p.geo_city) AS label,
         p.source_kinds::text[] AS source_kinds,
         CASE WHEN :apply_fence THEN contrail_apply_fence(p.centroid, :uid)
              ELSE p.centroid END AS geom
    FROM place p
   WHERE p.user_id = :uid
     AND (CAST(:from_ts AS timestamptz) IS NULL OR p.end_utc   >= :from_ts)
     AND (CAST(:to_ts AS timestamptz)   IS NULL OR p.start_utc <= :to_ts)
     AND p.centroid && ST_Transform((SELECT geom FROM bounds), 4326)
),
mvtgeom AS (
  SELECT ST_AsMVTGeom(ST_Transform(geom, 3857), (SELECT geom FROM bounds), 4096, 64, true)
             AS geom,
         id, duration_s, is_inferred_dwell, origin, trip_id, label,
         array_to_string(source_kinds, ',') AS sources,
         extract(epoch from start_utc)::bigint AS start_ts
    FROM fenced
   WHERE geom IS NOT NULL
)
SELECT ST_AsMVT(mvtgeom.*, 'places', 4096, 'geom') FROM mvtgeom
"""

PHOTO_POINT_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(:z, :x, :y) AS geom
),
src AS (
  SELECT ph.id, ph.taken_at_utc, ph.trip_id, ph.trip_place_id,
         ph.location_confidence::text AS location_confidence,
         CASE WHEN :apply_fence THEN contrail_apply_fence(ph.geom, :uid)
              ELSE ph.geom END AS geom
    FROM photo ph
   WHERE ph.user_id = :uid AND ph.geom IS NOT NULL
     AND (CAST(:from_ts AS timestamptz) IS NULL OR ph.taken_at_utc >= :from_ts)
     AND (CAST(:to_ts AS timestamptz)   IS NULL OR ph.taken_at_utc <= :to_ts)
     AND ph.geom && ST_Transform((SELECT geom FROM bounds), 4326)
),
mvtgeom AS (
  SELECT ST_AsMVTGeom(ST_Transform(geom, 3857), (SELECT geom FROM bounds), 4096, 64, true)
             AS geom,
         id, trip_id, trip_place_id, location_confidence,
         extract(epoch from taken_at_utc)::bigint AS taken_ts,
         1 AS cluster_size
    FROM src
   WHERE geom IS NOT NULL
)
SELECT ST_AsMVT(mvtgeom.*, 'photos', 4096, 'geom') FROM mvtgeom
"""

# Below z14 photos would overplot into an unreadable mass, so they are clustered
# server-side and the count travels as an attribute.
PHOTO_CLUSTER_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(:z, :x, :y) AS geom
),
src AS (
  SELECT ph.id, ph.taken_at_utc, ph.geom,
         ST_ClusterDBSCAN(ST_Transform(ph.geom, 3857),
                          eps := GREATEST(50, 156543.03 / (2 ^ :z) * 40),
                          minpoints := 1) OVER () AS cid
    FROM photo ph
   WHERE ph.user_id = :uid AND ph.geom IS NOT NULL
     AND (CAST(:from_ts AS timestamptz) IS NULL OR ph.taken_at_utc >= :from_ts)
     AND (CAST(:to_ts AS timestamptz)   IS NULL OR ph.taken_at_utc <= :to_ts)
     AND ph.geom && ST_Transform((SELECT geom FROM bounds), 4326)
),
clustered AS (
  SELECT cid,
         count(*) AS cluster_size,
         (array_agg(id ORDER BY taken_at_utc))[1] AS id,
         min(taken_at_utc) AS taken_at_utc,
         ST_Centroid(ST_Collect(geom)) AS geom
    FROM src GROUP BY cid
),
mvtgeom AS (
  SELECT ST_AsMVTGeom(ST_Transform(geom, 3857), (SELECT geom FROM bounds), 4096, 64, true)
             AS geom,
         id, cluster_size,
         extract(epoch from taken_at_utc)::bigint AS taken_ts
    FROM clustered
   WHERE geom IS NOT NULL
)
SELECT ST_AsMVT(mvtgeom.*, 'photos', 4096, 'geom') FROM mvtgeom
"""


def _validate(z: int, x: int, y: int, crs: str) -> None:
    if not 0 <= z <= MAX_ZOOM:
        raise HTTPException(status_code=400, detail="zoom out of range")
    limit = 1 << z
    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=400, detail="tile coordinates out of range")
    if crs != "wgs84":
        # The parameter is kept as a placeholder. Mapbox basemaps and stored
        # data are both WGS-84, so no datum shift exists anywhere in the MVP.
        raise HTTPException(status_code=400, detail="only crs=wgs84 is supported")


async def _render(
    session: AsyncSession, sql: str, user_id, z: int, x: int, y: int, from_, to_
) -> Response:
    data = (
        await session.execute(
            text(sql),
            {
                "uid": str(user_id),
                "z": z,
                "x": x,
                "y": y,
                "from_ts": from_,
                "to_ts": to_,
                # MVP: fences are enforced at export only. Flip this in cloud
                # mode, where tiles become an outbound channel.
                "apply_fence": False,
            },
        )
    ).scalar_one()
    return Response(
        content=bytes(data or b""),
        media_type=MVT_MEDIA_TYPE,
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.get("/tiles/tracks/{z}/{x}/{y}.mvt")
async def track_tiles(
    z: int,
    x: int,
    y: int,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    crs: str = "wgs84",
) -> Response:
    _validate(z, x, y, crs)
    return await _render(session, TRACK_SQL, user_id, z, x, y, from_, to)


@router.get("/tiles/places/{z}/{x}/{y}.mvt")
async def place_tiles(
    z: int,
    x: int,
    y: int,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    crs: str = "wgs84",
) -> Response:
    _validate(z, x, y, crs)
    return await _render(session, PLACE_SQL, user_id, z, x, y, from_, to)


@router.get("/tiles/photos/{z}/{x}/{y}.mvt")
async def photo_tiles(
    z: int,
    x: int,
    y: int,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    crs: str = "wgs84",
) -> Response:
    _validate(z, x, y, crs)
    sql = PHOTO_POINT_SQL if z >= PHOTO_CLUSTER_MAX_Z else PHOTO_CLUSTER_SQL
    return await _render(session, sql, user_id, z, x, y, from_, to)
