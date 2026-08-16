"""Export routes - the one place where data leaves this machine as a picture.

POST /exports/fence-check must be called first. If the selection intersects any
enabled fence and the export request arrives WITHOUT fence_actions, the server
returns 422 and renders nothing.

That check lives here rather than only in the UI on purpose: a frontend dialog
can be bypassed, a server-side 422 cannot. A fence leak is the one unacceptable
bug in this product, so its enforcement belongs where it cannot be routed
around.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.db import get_session
from contrail.render.png import RenderScope, render
from contrail.schemas import ExportRequest, FenceCheckRequest, FenceCheckResponse, FenceHit
from contrail.security import current_user_id
from contrail.storage import get_storage

router = APIRouter(tags=["export"])

# The preview is a fast, low-resolution render for the export panel's live
# preview. The full render takes 3-8 s, which is far too slow to drive a UI.
PREVIEW_SIZE = (400, 720)
# Beyond this, rendering moves to a background task.
INLINE_PIXEL_BUDGET = 4000 * 4000


async def _fence_hits(
    session: AsyncSession, user_id, trip_ids: list[uuid.UUID], place_ids: list[uuid.UUID]
) -> FenceCheckResponse:
    params = {
        "uid": str(user_id),
        "trip_ids": [str(t) for t in trip_ids] or None,
        "place_ids": [str(p) for p in place_ids] or None,
    }
    rows = (
        await session.execute(
            text(
                """
                SELECT f.id, f.label, f.kind::text AS kind,
                       (SELECT count(*) FROM place p
                         WHERE p.user_id = :uid
                           AND ((CAST(:trip_ids AS uuid[]) IS NULL OR p.trip_id = ANY(:trip_ids))
                             OR (CAST(:place_ids AS uuid[]) IS NOT NULL AND p.id = ANY(:place_ids)))
                           AND ST_Intersects(p.centroid, f.buffer_geom)) AS affected_places,
                       (SELECT count(*) FROM track t
                         WHERE t.user_id = :uid AND NOT t.is_shadow
                           AND (CAST(:trip_ids AS uuid[]) IS NULL OR t.trip_id = ANY(:trip_ids))
                           AND ST_Intersects(t.geom, f.buffer_geom)) AS affected_tracks
                  FROM geofence f
                 WHERE f.user_id = :uid AND f.enabled AND f.buffer_geom IS NOT NULL
                """
            ),
            params,
        )
    ).all()

    hits = [
        FenceHit(
            fence_id=r.id,
            label=r.label,
            kind=r.kind,
            affected_places=r.affected_places,
            affected_tracks=r.affected_tracks,
        )
        for r in rows
        if r.affected_places or r.affected_tracks
    ]
    return FenceCheckResponse(
        intersects=bool(hits),
        fences=hits,
        affected_places=sum(h.affected_places for h in hits),
        affected_tracks=sum(h.affected_tracks for h in hits),
    )


@router.post("/exports/fence-check", response_model=FenceCheckResponse)
async def fence_check(
    payload: FenceCheckRequest,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> FenceCheckResponse:
    """Which fences the selection touches, and how much they affect.

    The frontend uses this to raise a blocking dialog before any export.
    """
    return await _fence_hits(session, user_id, payload.trip_ids, payload.place_ids)


async def _guard(session: AsyncSession, user_id, payload: ExportRequest) -> str | None:
    """Return the fence action to apply, or refuse the export."""
    check = await _fence_hits(session, user_id, payload.trip_ids, payload.place_ids)
    if not check.intersects:
        return None
    if payload.fence_actions is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "the selection intersects a privacy fence; fence_actions is required",
                "fences": [h.model_dump(mode="json") for h in check.fences],
                "affected_places": check.affected_places,
                "affected_tracks": check.affected_tracks,
                "choices": ["blur", "remove"],
            },
        )
    return payload.fence_actions


@router.post("/exports/preview")
async def export_preview(
    payload: ExportRequest,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Low-resolution preview for the export panel. Fenced exactly like the
    real export - a preview is an image too."""
    action = await _guard(session, user_id, payload)
    try:
        png = await render(
            session,
            user_id,
            RenderScope(payload.trip_ids, payload.place_ids),
            template=payload.template,
            width=PREVIEW_SIZE[0],
            height=PREVIEW_SIZE[1],
            theme=payload.theme,
            fence_action=action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png")


@router.post("/exports", status_code=202)
async def create_export(
    payload: ExportRequest,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Render the export.

    Anything within the inline pixel budget renders synchronously; a poster-size
    render (A4 at 300 dpi) takes long enough that it belongs in a task.
    """
    action = await _guard(session, user_id, payload)

    row = (
        await session.execute(
            text(
                "INSERT INTO export_task (user_id, status, params) "
                "VALUES (:uid, 'running', :params) RETURNING id"
            ),
            {"uid": str(user_id), "params": json.dumps(payload.model_dump(mode="json"))},
        )
    ).first()
    export_id = row.id

    if payload.width * payload.height > INLINE_PIXEL_BUDGET:
        # Reserved for the background path; the MVP renders inline and reports
        # honestly rather than pretending to queue.
        await session.execute(
            text("UPDATE export_task SET status = 'failed', error_detail = :e WHERE id = :id"),
            {
                "id": export_id,
                "e": json.dumps({"error": "size exceeds the inline render budget"}),
            },
        )
        await session.commit()
        raise HTTPException(status_code=413, detail="requested size exceeds the render budget")

    try:
        png = await render(
            session,
            user_id,
            RenderScope(payload.trip_ids, payload.place_ids),
            template=payload.template,
            width=payload.width,
            height=payload.height,
            theme=payload.theme,
            fence_action=action,
        )
    except ValueError as exc:
        await session.execute(
            text("UPDATE export_task SET status = 'failed', error_detail = :e WHERE id = :id"),
            {"id": export_id, "e": json.dumps({"error": str(exc)})},
        )
        await session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    key = get_storage().put("exports", f"{export_id}.png", png)
    await session.execute(
        text(
            "UPDATE export_task SET status = 'done', storage_key = :k, finished_at = now() "
            "WHERE id = :id"
        ),
        {"k": key, "id": export_id},
    )
    await session.commit()
    return {
        "task_id": str(export_id),
        "status": "done",
        "download_url": f"/api/v1/exports/{export_id}/file",
        "fence_action": action,
    }


# Declared BEFORE /exports/{export_id}: FastAPI matches in declaration order,
# so a literal path placed after a parameterised one is never reached -
# "data" would be parsed as a UUID and rejected.
@router.get("/exports/data")
async def export_data(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Full data export: GeoJSON + GPX in one zip.

    NOT fence-clipped, by design. This is the user's own data leaving for the
    user's own machine - data portability, not publication. The fence exists to
    protect what gets SHARED.
    """
    places = (
        await session.execute(
            text(
                """
                SELECT id, ST_AsGeoJSON(centroid) AS geom, start_utc, end_utc, duration_s,
                       coalesce(name, geo_name, geo_city) AS label, geo_city, geo_country,
                       origin, is_inferred_dwell
                  FROM place WHERE user_id = :uid ORDER BY start_utc
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    tracks = (
        await session.execute(
            text(
                """
                SELECT id, ST_AsGeoJSON(geom) AS geom, start_utc, end_utc, distance_m,
                       distance_unknown, mode::text AS mode, geom_quality
                  FROM track WHERE user_id = :uid AND NOT is_shadow ORDER BY start_utc
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(r.geom),
                "properties": {
                    "kind": "place",
                    "id": str(r.id),
                    "start_utc": r.start_utc.isoformat(),
                    "end_utc": r.end_utc.isoformat(),
                    "duration_s": r.duration_s,
                    "label": r.label,
                    "city": r.geo_city,
                    "country": r.geo_country,
                    "origin": r.origin,
                    "is_inferred_dwell": r.is_inferred_dwell,
                },
            }
            for r in places
        ]
        + [
            {
                "type": "Feature",
                "geometry": json.loads(r.geom),
                "properties": {
                    "kind": "track",
                    "id": str(r.id),
                    "start_utc": r.start_utc.isoformat(),
                    "end_utc": r.end_utc.isoformat(),
                    "distance_m": r.distance_m,
                    # Preserved in the export too: unknown must stay unknown.
                    "distance_unknown": r.distance_unknown,
                    "mode": r.mode,
                    "geom_quality": r.geom_quality,
                },
            }
            for r in tracks
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("contrail.geojson", json.dumps(geojson, ensure_ascii=False, indent=1))
        archive.writestr("contrail.gpx", _to_gpx(tracks))
        archive.writestr(
            "README.txt",
            "Contrail full data export.\n"
            "contrail.geojson - places and tracks, WGS-84 (EPSG:4326)\n"
            "contrail.gpx     - tracks only\n"
            "Privacy fences are NOT applied: this is your own data.\n",
        )

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="contrail-{stamp}.zip"'},
    )


def _to_gpx(tracks) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Contrail" xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for row in tracks:
        geometry = json.loads(row.geom)
        coords = geometry.get("coordinates") or []
        if geometry.get("type") == "MultiLineString":
            coords = [c for line in coords for c in line]
        parts.append(f"  <trk><name>{row.mode} {row.start_utc.isoformat()}</name><trkseg>")
        for lon, lat, *_ in coords:
            parts.append(f'    <trkpt lat="{lat}" lon="{lon}"/>')
        parts.append("  </trkseg></trk>")
    parts.append("</gpx>")
    return "\n".join(parts)


@router.get("/exports/{export_id}")
async def get_export(
    export_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT id, status, storage_key, error_detail, created_at, finished_at "
                "FROM export_task WHERE id = :id AND user_id = :uid"
            ),
            {"id": str(export_id), "uid": str(user_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="export not found")
    return {
        "id": str(row.id),
        "status": row.status,
        "download_url": f"/api/v1/exports/{row.id}/file" if row.storage_key else None,
        "error": row.error_detail,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


@router.get("/exports/{export_id}/file")
async def download_export(
    export_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    key = (
        await session.execute(
            text("SELECT storage_key FROM export_task WHERE id = :id AND user_id = :uid"),
            {"id": str(export_id), "uid": str(user_id)},
        )
    ).scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="export not found")
    return Response(
        content=get_storage().get(key),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="contrail-{export_id}.png"'},
    )
