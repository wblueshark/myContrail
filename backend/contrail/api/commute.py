"""Commute routes.

The action endpoint enforces the rule that makes bulk deletion safe: only a
`pure` commute day may be deleted. A `mixed` day still contains other places
and photos, and deleting it wholesale would be an irreversible mistake the user
did not intend.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.db import get_session
from contrail.pipeline import refresh
from contrail.schemas import CommuteAction
from contrail.security import current_user_id

router = APIRouter(prefix="/commute", tags=["commute"])


@router.get("/ods")
async def list_ods(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """Detected OD pairs with the evidence that produced them.

    The evidence is shown because every criterion is a plain statistic the user
    can check: how many times, on which days, how tight the departure time is,
    how similar the route.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT c.id, c.occurrence, c.weekday_ratio, c.depart_hour_mean,
                       c.depart_hour_circstd, c.path_jaccard, c.evidence,
                       fa.id AS from_id, ST_Y(fa.centroid) AS from_lat,
                       ST_X(fa.centroid) AS from_lon, fa.kind::text AS from_kind,
                       coalesce(fa.geo_name, fa.geo_city) AS from_label,
                       ta.id AS to_id, ST_Y(ta.centroid) AS to_lat,
                       ST_X(ta.centroid) AS to_lon, ta.kind::text AS to_kind,
                       coalesce(ta.geo_name, ta.geo_city) AS to_label,
                       (SELECT count(*) FROM track t WHERE t.commute_od_id = c.id) AS track_count
                  FROM commute_od c
                  JOIN place_anchor fa ON fa.id = c.from_anchor_id
                  JOIN place_anchor ta ON ta.id = c.to_anchor_id
                 WHERE c.user_id = :uid
                 ORDER BY c.occurrence DESC
                """
            ),
            {"uid": str(user_id)},
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "occurrence": r.occurrence,
            "weekday_ratio": r.weekday_ratio,
            "depart_hour_mean": r.depart_hour_mean,
            "depart_hour_circstd": r.depart_hour_circstd,
            "path_jaccard": r.path_jaccard,
            "evidence": r.evidence,
            "track_count": r.track_count,
            "from": {
                "id": str(r.from_id),
                "lat": r.from_lat,
                "lon": r.from_lon,
                "kind": r.from_kind,
                "label": r.from_label,
            },
            "to": {
                "id": str(r.to_id),
                "lat": r.to_lat,
                "lon": r.to_lon,
                "kind": r.to_kind,
                "label": r.to_label,
            },
        }
        for r in rows
    ]


@router.get("/trips")
async def commute_trips(
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
    class_: str | None = Query(default=None, alias="class", pattern="^(pure|mixed)$"),
) -> list[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT t.id, t.title, t.local_date, t.commute_class::text AS commute_class,
                       (SELECT count(*) FROM place p WHERE p.trip_id = t.id) AS place_count,
                       (SELECT count(*) FROM photo ph WHERE ph.trip_id = t.id) AS photo_count,
                       (SELECT count(*) FROM track tr
                         WHERE tr.trip_id = t.id AND tr.is_commute) AS commute_track_count
                  FROM trip t
                 WHERE t.user_id = :uid
                   AND t.commute_class::text <> 'none'
                   AND (CAST(:cls AS text) IS NULL OR t.commute_class::text = :cls)
                 ORDER BY t.local_date DESC
                """
            ),
            {"uid": str(user_id), "cls": class_},
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "local_date": r.local_date.isoformat(),
            "commute_class": r.commute_class,
            "place_count": r.place_count,
            "photo_count": r.photo_count,
            "commute_track_count": r.commute_track_count,
            # A mixed day is never deletable as a whole - the UI must say why.
            "deletable": r.commute_class == "pure",
        }
        for r in rows
    ]


@router.post("/trips/actions")
async def commute_actions(
    payload: CommuteAction,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ids = [str(t) for t in payload.trip_ids]
    if not ids:
        return {"affected": 0}

    classes = (
        await session.execute(
            text(
                "SELECT id, commute_class::text AS c FROM trip "
                "WHERE user_id = :uid AND id = ANY(:ids)"
            ),
            {"uid": str(user_id), "ids": ids},
        )
    ).all()
    found = {str(r.id): r.c for r in classes}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(status_code=404, detail={"not_found": missing})

    if payload.action == "delete":
        impure = [i for i, c in found.items() if c != "pure"]
        if impure:
            # Refused server-side, not merely hidden in the UI: a mixed day
            # holds other places and photos that the user did not ask to lose.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "only pure commute trips can be deleted",
                    "trip_ids": impure,
                },
            )
        # Deleting removes the derived layer only. The retained original files
        # are untouched, so re-importing restores everything.
        await session.execute(
            text("DELETE FROM place WHERE user_id = :uid AND trip_id = ANY(:ids)"),
            {"uid": str(user_id), "ids": ids},
        )
        await session.execute(
            text("DELETE FROM track WHERE user_id = :uid AND trip_id = ANY(:ids)"),
            {"uid": str(user_id), "ids": ids},
        )
        await session.execute(
            text("DELETE FROM trip WHERE user_id = :uid AND id = ANY(:ids)"),
            {"uid": str(user_id), "ids": ids},
        )

    elif payload.action == "to_normal":
        await session.execute(
            text(
                "UPDATE trip SET commute_class = 'none' WHERE user_id = :uid AND id = ANY(:ids)"
            ),
            {"uid": str(user_id), "ids": ids},
        )
        await session.execute(
            text(
                "UPDATE track SET is_commute = false, commute_od_id = NULL "
                "WHERE user_id = :uid AND trip_id = ANY(:ids)"
            ),
            {"uid": str(user_id), "ids": ids},
        )

    elif payload.action == "collapse":
        # Collapse is presentation state: the data stays, the map hides it.
        await session.execute(
            text(
                "UPDATE trip SET stats = jsonb_set(stats, '{collapsed}', 'true') "
                "WHERE user_id = :uid AND id = ANY(:ids)"
            ),
            {"uid": str(user_id), "ids": ids},
        )

    await session.commit()
    return {"affected": len(ids), "action": payload.action}


@router.post("/recompute")
async def recompute(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> dict:
    result = await refresh.refresh_commute(session, user_id)
    await session.commit()
    return result
