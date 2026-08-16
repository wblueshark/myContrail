"""Settings, privacy fences and recomputation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.config import get_settings
from contrail.db import get_session
from contrail.models import AppUser, Geofence
from contrail.pipeline import commute as commute_lib
from contrail.pipeline import refresh
from contrail.pipeline.derive import rederive_window
from contrail.schemas import GeofenceIn, GeofenceOut, SettingsIn
from contrail.security import current_user_id

router = APIRouter(tags=["settings"])

TUNABLES = (
    "cluster_radius_m",
    "cluster_min_dwell_s",
    "cluster_gap_s",
    "accuracy_max_m",
    "photo_infer_tolerance_s",
    "geocoding_enabled",
    "commute_min_repeats",
    "display_local_time",
)


@router.get("/settings")
async def read_settings(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> dict:
    user = await session.get(AppUser, user_id)
    defaults = get_settings()
    stored = (user.settings or {}) if user else {}
    return {
        "default_tz": user.default_tz if user else "UTC",
        "cluster_radius_m": stored.get("cluster_radius_m", defaults.cluster_radius_m),
        "cluster_min_dwell_s": stored.get("cluster_min_dwell_s", defaults.cluster_min_dwell_s),
        "cluster_gap_s": stored.get("cluster_gap_s", defaults.cluster_gap_s),
        "accuracy_max_m": stored.get("accuracy_max_m", defaults.accuracy_max_m),
        "photo_infer_tolerance_s": stored.get(
            "photo_infer_tolerance_s", defaults.photo_infer_tolerance_s
        ),
        "geocoding_enabled": stored.get("geocoding_enabled", defaults.geocoding_enabled),
        "commute_min_repeats": stored.get("commute_min_repeats", commute_lib.MIN_OCCURRENCE),
        "display_local_time": stored.get("display_local_time", True),
        # The token itself never crosses this boundary in either direction: it
        # lives in .env, and SettingsIn forbids extra fields, so posting one is
        # a 422 rather than a secret quietly landing in the database.
        "mapbox_token_configured": bool(defaults.mapbox_token),
        # Scenario presets from the design; the UI offers these as one click.
        "presets": {
            "city": {"cluster_radius_m": 150, "cluster_min_dwell_s": 900},
            "long_drive": {"cluster_radius_m": 200, "cluster_min_dwell_s": 1800},
            "hiking": {"cluster_radius_m": 80, "cluster_min_dwell_s": 1200},
            "coarse": {"cluster_radius_m": 500, "cluster_min_dwell_s": 3600},
        },
    }


@router.put("/settings")
async def write_settings(
    payload: SettingsIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    stored = dict(user.settings or {})
    for field in TUNABLES:
        value = getattr(payload, field, None)
        if value is not None:
            stored[field] = value
    user.settings = stored
    if payload.default_tz:
        user.default_tz = payload.default_tz
    await session.commit()
    return await read_settings(user_id=user_id, session=session)


@router.get("/geofences", response_model=list[GeofenceOut])
async def list_fences(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> list[GeofenceOut]:
    """Ordered by last visit, so the user can tell which address is which.

    There are usually several: 13 years of real data held 24 distinct home
    coordinates and 37 work coordinates. Every one is a fence, active at all
    times - a "current home only" fence would leak the 2019 address the moment
    the user exports their 2019 footprints, which is exactly what a year in
    review does.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT id, kind::text AS kind, label, ST_Y(center) AS lat, ST_X(center) AS lon,
                       radius_m, enabled, visit_count, first_visit_utc, last_visit_utc
                  FROM geofence WHERE user_id = :uid
                 ORDER BY last_visit_utc DESC NULLS LAST, label
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    return [GeofenceOut(**dict(r._mapping)) for r in rows]


@router.get("/geofences/suggestions")
async def fence_suggestions(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> dict:
    """Suggested fences, grouped by how much they can be trusted.

    The three tiers are never merged. A confirmed Home and an inferred one were
    measured 427 m apart; folded into a single 500 m suggestion, the user would
    confirm one address and leave the other entirely exposed.

    This is also what breaks the cold-start deadlock: the old flow asked the
    user to set fences before importing, when the map was blank and the only way
    to find their own home was to search for the address - which is forward
    geocoding, i.e. sending their home address to a third party. Inference is
    fully offline.
    """
    suggestions = await refresh.suggest_fences(session, user_id)
    tiers = {"google_confirmed": [], "google_inferred": [], "heuristic": []}
    for item in suggestions:
        tiers.setdefault(item["confidence"], []).append(item)
    return {"tiers": tiers, "total": len(suggestions)}


@router.post("/geofences", response_model=GeofenceOut, status_code=201)
async def create_fence(
    payload: GeofenceIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> GeofenceOut:
    fence = await refresh.create_fence(
        session, user_id, payload.kind, payload.label, payload.lat, payload.lon, payload.radius_m
    )
    fence.enabled = payload.enabled
    await session.commit()
    return GeofenceOut(
        id=fence.id,
        kind=fence.kind,
        label=fence.label,
        lat=payload.lat,
        lon=payload.lon,
        radius_m=fence.radius_m,
        enabled=fence.enabled,
    )


@router.patch("/geofences/{fence_id}", response_model=GeofenceOut)
async def update_fence(
    fence_id: uuid.UUID,
    payload: GeofenceIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> GeofenceOut:
    fence = await session.get(Geofence, fence_id)
    if fence is None or fence.user_id != user_id:
        raise HTTPException(status_code=404, detail="fence not found")
    fence.kind = payload.kind
    fence.label = payload.label
    fence.radius_m = payload.radius_m
    fence.enabled = payload.enabled
    # buffer_geom is re-materialised by the database trigger on center/radius.
    fence.center = f"SRID=4326;POINT({payload.lon} {payload.lat})"
    await session.commit()
    return GeofenceOut(
        id=fence.id,
        kind=fence.kind,
        label=fence.label,
        lat=payload.lat,
        lon=payload.lon,
        radius_m=fence.radius_m,
        enabled=fence.enabled,
    )


@router.delete("/geofences/{fence_id}", status_code=204)
async def delete_fence(
    fence_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    fence = await session.get(Geofence, fence_id)
    if fence is None or fence.user_id != user_id:
        raise HTTPException(status_code=404, detail="fence not found")
    await session.delete(fence)
    await session.commit()


@router.post("/recluster")
async def recluster(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> dict:
    """Recompute the derived layer with the current parameters.

    Trips with is_auto = false are user-owned and are left alone.
    """
    span = (
        await session.execute(
            text("SELECT min(ts_utc) AS lo, max(ts_utc) AS hi FROM raw_point WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).first()
    if span is None or span.lo is None:
        return {"recomputed": False, "reason": "no data"}

    photo_span = (
        await session.execute(
            text(
                "SELECT min(taken_at_utc) AS lo, max(taken_at_utc) AS hi "
                "FROM photo WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
    ).first()

    lo = min(filter(None, [span.lo, photo_span.lo if photo_span else None]))
    hi = max(filter(None, [span.hi, photo_span.hi if photo_span else None]))

    result = await rederive_window(session, user_id, lo, hi)
    result.update(await refresh.full_refresh(session, user_id))
    await session.commit()
    return {
        "recomputed": True,
        "window": {"start": lo.isoformat(), "end": hi.isoformat()},
        "at": datetime.now(UTC).isoformat(),
        **result,
    }
