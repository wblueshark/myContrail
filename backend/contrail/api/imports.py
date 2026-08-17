"""Import routes: directory picking, prescan, upload, import tasks, undo.

The contract that matters here: /sources/prescan and /imports accept a
pick_token or an upload_id, and NOTHING else. A request carrying a path field is
rejected with 400. There is no path to validate because there is no path field.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contrail import picker
from contrail.config import get_settings
from contrail.db import get_session, session_scope
from contrail.models import SourceFile
from contrail.pipeline import importer, refresh
from contrail.schemas import (
    ImportRequest,
    PickResponse,
    PrescanRequest,
    SourceOut,
    TaskResponse,
)
from contrail.security import current_user_id, reject_path_fields
from contrail.tasks import TASKS

router = APIRouter(tags=["import"])

UPLOAD_BUCKET = "uploads"
# Above this, the UI asks a second time before starting: the user picked the
# folder themselves and may well have picked their home directory.
LARGE_DIRECTORY_THRESHOLD = 20_000


def _upload_dir() -> Path:
    path = get_settings().data_dir / UPLOAD_BUCKET
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/fs/pick", response_model=PickResponse | None)
async def pick_directory(_user_id=Depends(current_user_id)) -> Response | PickResponse:
    """Open the host's native folder chooser.

    Blocks until the user chooses or cancels. Cancelling returns 204. The
    response contains a display name (the last path component) and never the
    absolute path.
    """
    if not picker.picker_available():
        raise HTTPException(
            status_code=501,
            detail="no native directory picker on this host; photo import is unavailable",
        )

    chosen = await asyncio.to_thread(picker.open_native_picker)
    if chosen is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    token, display = picker.register(chosen)
    prescan = await asyncio.to_thread(importer.prescan_directory, chosen)
    prescan["needs_confirmation"] = prescan["file_count"] > LARGE_DIRECTORY_THRESHOLD
    return PickResponse(pick_token=token, display_name=display, prescan=prescan)


@router.post("/sources/prescan")
async def prescan(request: Request, _user_id=Depends(current_user_id)) -> dict:
    raw = await request.json()
    reject_path_fields(raw)
    payload = PrescanRequest(**raw)

    if payload.pick_token:
        # peek, not consume: the wizard re-scans the same token when the user
        # toggles "include subfolders", and the counts have to follow.
        directory = picker.peek(payload.pick_token)
        if directory is None:
            raise HTTPException(status_code=410, detail="pick token expired or already used")
        result = await asyncio.to_thread(
            importer.prescan_directory, directory, 40, payload.include_subdirs
        )
        result["display_name"] = picker.display_name(payload.pick_token)
        result["needs_confirmation"] = result["file_count"] > LARGE_DIRECTORY_THRESHOLD
        return result

    if payload.upload_id:
        path = _upload_dir() / payload.upload_id
        if not path.exists():
            raise HTTPException(status_code=404, detail="upload not found")
        from contrail.parsers.base import UnknownFormatError
        from contrail.parsers.registry import sniff

        try:
            match = sniff(path)
        except UnknownFormatError as exc:
            # Unknown format is reported, with a sample retained. Never a silent
            # skip (P6).
            raise HTTPException(
                status_code=422,
                detail={"error": str(exc), "sample": str(exc.sample)},
            ) from exc
        return {
            "upload_id": payload.upload_id,
            "kind": match.source_kind,
            "variant": match.variant,
            "confidence": match.confidence,
            "byte_size": path.stat().st_size,
        }

    raise HTTPException(status_code=400, detail="pick_token or upload_id is required")


@router.post("/sources/upload")
async def upload(file: UploadFile, _user_id=Depends(current_user_id)) -> dict:
    """Store an uploaded trajectory file and return an upload_id.

    The extension is not trusted; the format is decided by sniffing the bytes.
    """
    upload_id = f"{uuid.uuid4().hex}{Path(file.filename or '').suffix.lower()}"
    target = _upload_dir() / upload_id
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    return {
        "upload_id": upload_id,
        "display_name": file.filename or upload_id,
        "byte_size": target.stat().st_size,
    }


@router.post("/imports", status_code=202, response_model=TaskResponse)
async def create_import(
    request: Request, user_id=Depends(current_user_id)
) -> TaskResponse:
    """Start an import. Returns immediately with a task id; watch /events."""
    raw = await request.json()
    reject_path_fields(raw)
    payload = ImportRequest(**raw)
    options = {
        "group_id": str(payload.group_id) if payload.group_id else None,
        "tag_ids": [str(t) for t in payload.tag_ids],
        **payload.options.model_dump(mode="json"),
    }

    if payload.kind == "photo":
        directory = picker.consume(payload.source_ref)  # one-shot
        if directory is None:
            raise HTTPException(status_code=410, detail="pick token expired or already used")
        display = directory.name
        state = TASKS.create("photo", display)

        async def work(progress):
            async with session_scope() as session:
                report = await importer.import_photo_directory(
                    session, user_id, directory, display, options, progress
                )
                # The commute conclusion belongs to the report, but only the
                # refresh can produce it - so it is filled in after, not before.
                outcome = await refresh.full_refresh(session, user_id)
                report.commute = importer.commute_summary(outcome.get("commute", {}))
            return report.as_dict()

    else:
        path = _upload_dir() / payload.source_ref
        if not path.exists():
            raise HTTPException(status_code=404, detail="upload not found")
        display = payload.source_ref
        state = TASKS.create("file", display)

        async def work(progress):
            async with session_scope() as session:
                report = await importer.import_track_file(
                    session, user_id, path, display, options, progress
                )
                outcome = await refresh.full_refresh(session, user_id)
                report.commute = importer.commute_summary(outcome.get("commute", {}))
            return report.as_dict()

    TASKS.start(state, work)
    return TaskResponse(**state.snapshot())


@router.get("/imports", response_model=list[TaskResponse])
async def list_imports(_user_id=Depends(current_user_id)) -> list[TaskResponse]:
    return [TaskResponse(**t.snapshot()) for t in TASKS.list()]


@router.get("/imports/{task_id}", response_model=TaskResponse)
async def get_import(task_id: str, _user_id=Depends(current_user_id)) -> TaskResponse:
    state = TASKS.get(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskResponse(**state.snapshot())


@router.get("/imports/{task_id}/events")
async def import_events(task_id: str, _user_id=Depends(current_user_id)) -> StreamingResponse:
    """Server-sent progress stream."""
    if TASKS.get(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")

    queue = TASKS.subscribe(task_id)

    async def stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"  # keeps proxies from closing the stream
                    continue
                if payload is None:
                    yield "event: end\ndata: {}\n\n"
                    return
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            TASKS.unsubscribe(task_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/imports/{task_id}", status_code=202)
async def cancel_import(task_id: str, _user_id=Depends(current_user_id)) -> dict:
    if TASKS.get(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"cancelled": TASKS.cancel(task_id)}


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    user_id=Depends(current_user_id), session: AsyncSession = Depends(get_session)
) -> list[SourceOut]:
    rows = (
        await session.execute(
            select(SourceFile)
            .where(SourceFile.user_id == user_id)
            .order_by(SourceFile.imported_at.desc())
        )
    ).scalars()
    return [
        SourceOut(
            id=s.id,
            kind=s.kind,
            display_name=s.display_name,
            status=s.status,
            byte_size=s.byte_size,
            stats=s.stats or {},
            error_detail=s.error_detail,
            imported_at=s.imported_at,
            has_original=bool(s.storage_key),
        )
        for s in rows
    ]


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    user_id=Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Undo an import: cascade the raw points, then recompute the window.

    The derived layer is deleted, but the retained original file was already
    removed too, so re-importing means picking the file again. Photos shared
    with another source are kept.
    """
    result = await importer.undo_source(session, user_id, source_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="source not found")
    await refresh.full_refresh(session, user_id)
    await session.commit()
    return result
