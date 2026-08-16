"""ARQ worker.

    arq contrail.worker.WorkerSettings

Scope note: in local mode imports do NOT run here. A photo import needs the
absolute directory path, and that path must never leave the API process - see
picker.py. Routing it through a worker would serialise it into Redis, which is
precisely what the pick_token design prevents. Local imports therefore run
in-process (tasks.py).

What belongs here is work that is identified by a storage key rather than a
path, and cloud mode, where uploaded bytes are the only input and no local path
exists.

The rule that makes this worker usable at all: ARQ ORCHESTRATES ONLY. Import
work is CPU-bound (EXIF parsing, JPEG decoding, clustering, geometry
simplification), not IO-bound. Running it directly on the worker's event loop
blocks it, and progress reporting and job cancellation then stop working
without any error being raised.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings

from contrail.config import get_settings
from contrail.db import dispose_engine, session_scope
from contrail.logging_config import configure_logging, task_id_var
from contrail.pipeline import importer, refresh
from contrail.pipeline.derive import rederive_window

log = logging.getLogger(__name__)


async def run_cpu(ctx: dict, fn: Callable, *args: Any):
    """Run a CPU-bound callable in the worker's process pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(ctx["pool"], fn, *args)


async def import_uploaded_file(
    ctx: dict, user_id: str, storage_path: str, display_name: str, options: dict | None = None
) -> dict:
    """Import a file already present in the data directory, by path relative to it."""
    task_id_var.set(ctx.get("job_id"))
    path = Path(storage_path)
    if not path.is_absolute():
        path = get_settings().data_dir / storage_path
    if not path.exists():
        raise FileNotFoundError(f"upload not found: {display_name}")

    async with session_scope() as session:
        report = await importer.import_track_file(
            session, UUID(user_id), path, display_name, options or {}
        )
        await refresh.full_refresh(session, UUID(user_id))
    return report.as_dict()


async def rederive(ctx: dict, user_id: str, start_iso: str, end_iso: str) -> dict:
    """Recompute a window - used after an undo or a parameter change."""
    from datetime import datetime

    task_id_var.set(ctx.get("job_id"))
    async with session_scope() as session:
        result = await rederive_window(
            session,
            UUID(user_id),
            datetime.fromisoformat(start_iso),
            datetime.fromisoformat(end_iso),
        )
        result.update(await refresh.full_refresh(session, UUID(user_id)))
    return result


async def geocode_pending(ctx: dict, user_id: str) -> dict:
    """Low-priority reverse geocoding. Never blocks the user seeing the map."""
    async with session_scope() as session:
        return await refresh.geocode_anchors(session, UUID(user_id))


async def startup(ctx: dict) -> None:
    configure_logging()
    ctx["pool"] = ProcessPoolExecutor(max_workers=4)
    log.info("arq worker ready")


async def shutdown(ctx: dict) -> None:
    ctx["pool"].shutdown(wait=True)
    await dispose_engine()


class WorkerSettings:
    functions = [import_uploaded_file, rederive, geocode_pending]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    job_timeout = 3600
    keep_result = 3600

    @staticmethod
    def redis_settings() -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_url)
