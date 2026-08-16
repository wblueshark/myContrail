"""Content-correction routes: reserved, deliberately not implemented.

P7 draws the line: a Trip's CONTENT (places, tracks, geometry, times, which day
it belongs to) is produced by the algorithms and the user cannot edit it, while
title, group and tags are metadata the user owns and can change at any time.

These routes exist so the API shape does not change when correction ships, and
so the frontend can detect the capability rather than guessing. The UI must
state the boundary in words - otherwise users assume grouping is locked too.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["corrections"])

NOT_IMPLEMENTED = "content correction is not implemented in the MVP; metadata is editable"


@router.put("/trips/{trip_id}/content", status_code=501)
async def correct_trip_content(trip_id: uuid.UUID) -> None:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@router.put("/trips/{trip_id}/segments/{segment_id}", status_code=501)
async def correct_trip_segment(trip_id: uuid.UUID, segment_id: uuid.UUID) -> None:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@router.put("/places/{place_id}", status_code=501)
async def correct_place(place_id: uuid.UUID) -> None:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@router.post("/trips/{trip_id}/split", status_code=501)
async def split_trip(trip_id: uuid.UUID) -> None:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)


@router.post("/trips/merge", status_code=501)
async def merge_trips() -> None:
    raise HTTPException(status_code=501, detail=NOT_IMPLEMENTED)
