"""Groups, tags and bulk assignment.

Constraints: a trip or place has AT MOST ONE group (exclusive filing) and ANY
NUMBER of tags (non-exclusive annotation). A place with no group inherits its
trip's group for display and filtering.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from contrail.db import get_session
from contrail.models import Group, PlaceTag, Tag, Trip, TripTag
from contrail.schemas import BulkAssign, GroupIn, GroupOut, TagIn, TagOut, TripPatch
from contrail.security import current_user_id

router = APIRouter(tags=["organize"])


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> list[GroupOut]:
    rows = (
        await session.execute(
            select(Group, func.count(Trip.id))
            .outerjoin(Trip, Trip.group_id == Group.id)
            .where(Group.user_id == user_id)
            .group_by(Group.id)
            .order_by(Group.created_at)
        )
    ).all()
    return [
        GroupOut(id=g.id, name=g.name, kind=g.kind, color=g.color, trip_count=count)
        for g, count in rows
    ]


@router.post("/groups", response_model=GroupOut, status_code=201)
async def create_group(
    payload: GroupIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> GroupOut:
    group = Group(user_id=user_id, name=payload.name, color=payload.color, kind="user")
    session.add(group)
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - unique (user_id, name)
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="a group with that name already exists"
        ) from exc
    return GroupOut(id=group.id, name=group.name, kind=group.kind, color=group.color)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: uuid.UUID,
    payload: GroupIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> GroupOut:
    group = await session.get(Group, group_id)
    if group is None or group.user_id != user_id:
        raise HTTPException(status_code=404, detail="group not found")
    group.name = payload.name
    group.color = payload.color
    await session.commit()
    return GroupOut(id=group.id, name=group.name, kind=group.kind, color=group.color)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    group = await session.get(Group, group_id)
    if group is None or group.user_id != user_id:
        raise HTTPException(status_code=404, detail="group not found")
    if group.kind == "system_commute":
        # System-created; the commute pass depends on it existing.
        raise HTTPException(status_code=422, detail="the system commute group cannot be deleted")
    await session.delete(group)  # trip.group_id is ON DELETE SET NULL
    await session.commit()


@router.get("/tags", response_model=list[TagOut])
async def list_tags(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> list[TagOut]:
    rows = (
        await session.execute(select(Tag).where(Tag.user_id == user_id).order_by(Tag.name))
    ).scalars()
    return [TagOut(id=t.id, name=t.name, color=t.color) for t in rows]


@router.post("/tags", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> TagOut:
    tag = Tag(user_id=user_id, name=payload.name, color=payload.color)
    session.add(tag)
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        raise HTTPException(status_code=409, detail="a tag with that name already exists") from exc
    return TagOut(id=tag.id, name=tag.name, color=tag.color)


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagIn,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> TagOut:
    tag = await session.get(Tag, tag_id)
    if tag is None or tag.user_id != user_id:
        raise HTTPException(status_code=404, detail="tag not found")
    tag.name = payload.name
    tag.color = payload.color
    await session.commit()
    return TagOut(id=tag.id, name=tag.name, color=tag.color)


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    tag = await session.get(Tag, tag_id)
    if tag is None or tag.user_id != user_id:
        raise HTTPException(status_code=404, detail="tag not found")
    await session.delete(tag)
    await session.commit()


@router.patch("/trips/{trip_id}")
async def patch_trip(
    trip_id: uuid.UUID,
    payload: TripPatch,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Metadata only: title, group, tags.

    Trip CONTENT - places, tracks, geometry, times, which day it belongs to -
    is produced by the algorithms and cannot be edited (P7). The correction
    endpoints exist and return 501.
    """
    trip = await session.get(Trip, trip_id)
    if trip is None or trip.user_id != user_id:
        raise HTTPException(status_code=404, detail="trip not found")

    if payload.title is not None:
        trip.title = payload.title
    if payload.group_id is not None:
        trip.group_id = payload.group_id
    if payload.tag_ids is not None:
        await session.execute(delete(TripTag).where(TripTag.trip_id == trip_id))
        for tag_id in payload.tag_ids:
            await session.execute(
                pg_insert(TripTag).values(trip_id=trip_id, tag_id=tag_id).on_conflict_do_nothing()
            )
    await session.commit()
    return {"id": str(trip.id), "title": trip.title}


@router.post("/trips/bulk-assign")
async def bulk_assign_trips(
    payload: BulkAssign,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not payload.trip_ids:
        return {"updated": 0}
    ids = [str(t) for t in payload.trip_ids]

    if payload.group_id is not None:
        await session.execute(
            text("UPDATE trip SET group_id = :g WHERE user_id = :uid AND id = ANY(:ids)"),
            {"g": str(payload.group_id), "uid": str(user_id), "ids": ids},
        )
    for tag_id in payload.add_tags:
        for trip_id in ids:
            await session.execute(
                pg_insert(TripTag).values(trip_id=trip_id, tag_id=tag_id).on_conflict_do_nothing()
            )
    if payload.remove_tags:
        await session.execute(
            delete(TripTag).where(
                TripTag.trip_id.in_(payload.trip_ids), TripTag.tag_id.in_(payload.remove_tags)
            )
        )
    await session.commit()
    return {"updated": len(ids)}


@router.post("/places/bulk-assign")
async def bulk_assign_places(
    payload: BulkAssign,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not payload.place_ids:
        return {"updated": 0}
    ids = [str(p) for p in payload.place_ids]

    if payload.group_id is not None:
        await session.execute(
            text("UPDATE place SET group_id = :g WHERE user_id = :uid AND id = ANY(:ids)"),
            {"g": str(payload.group_id), "uid": str(user_id), "ids": ids},
        )
    for tag_id in payload.add_tags:
        for place_id in ids:
            await session.execute(
                pg_insert(PlaceTag)
                .values(place_id=place_id, tag_id=tag_id)
                .on_conflict_do_nothing()
            )
    if payload.remove_tags:
        await session.execute(
            delete(PlaceTag).where(
                PlaceTag.place_id.in_(payload.place_ids), PlaceTag.tag_id.in_(payload.remove_tags)
            )
        )
    await session.commit()
    return {"updated": len(ids)}
