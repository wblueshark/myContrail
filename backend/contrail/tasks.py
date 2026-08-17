"""In-process task manager with SSE progress.

Why imports run here rather than in the ARQ worker: a photo import needs the
absolute directory path, and that path must not leave this process (picker.py).
Handing it to a worker would serialise it through Redis, which is exactly the
property the pick_token design exists to prevent. Local mode is single-user, so
one process is enough.

worker.py keeps the ARQ entry point for cloud mode, where imports work from
uploaded bytes identified by a storage key and no local path exists.

CPU-bound work still goes to a ProcessPoolExecutor (see importer.py). Running it
on the event loop would block progress reporting and cancellation - the two
things a long import needs most.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

QUEUE_MAX = 256


@dataclass
class TaskState:
    id: str
    kind: str
    display_name: str
    status: str = "queued"  # queued | running | done | failed | cancelled
    stage: str | None = None
    processed: int = 0
    total: int | None = None
    # One entry per phase, kept in the order the phases were first reported.
    # The import wizard draws three bars at once (EXIF / thumbnails /
    # clustering), which a single current-stage field cannot describe.
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def eta_seconds(self) -> int | None:
        """Remaining seconds, extrapolated from the run so far.

        None while the total is unknown or nothing has been processed yet: a
        countdown invented from no data is worse than no countdown.
        """
        if self.status != "running" or not self.total or self.processed <= 0:
            return None
        elapsed = (datetime.now(UTC) - self.created_at).total_seconds()
        if elapsed <= 0:
            return None
        rate = self.processed / elapsed
        remaining = max(0, self.total - self.processed)
        return int(remaining / rate) if rate > 0 else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "display_name": self.display_name,
            "status": self.status,
            "stage": self.stage,
            # Total is unknown while streaming a file of unknown length, so an
            # absolute count is reported rather than an invented percentage.
            "processed": self.processed,
            "total": self.total,
            "stages": [
                {"key": key, "processed": v["processed"], "total": v["total"]}
                for key, v in self.stages.items()
            ],
            "eta_seconds": self.eta_seconds(),
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}
        self._runners: dict[str, asyncio.Task] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def create(self, kind: str, display_name: str) -> TaskState:
        state = TaskState(id=str(uuid.uuid4()), kind=kind, display_name=display_name)
        self._tasks[state.id] = state
        self._subscribers[state.id] = []
        return state

    def get(self, task_id: str) -> TaskState | None:
        return self._tasks.get(task_id)

    def list(self) -> list[TaskState]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def start(
        self, state: TaskState, work: Callable[[Callable[..., None]], Awaitable[dict]]
    ) -> None:
        """Run `work`, passing it a progress callback."""
        loop = asyncio.get_running_loop()

        def progress(stage: str, processed: int, total: int | None) -> None:
            state.stage = stage
            state.processed = processed
            state.total = total
            state.stages[stage] = {"processed": processed, "total": total}
            # Called from the worker coroutine; publishing is fire-and-forget so
            # a slow SSE consumer can never stall the import itself.
            loop.call_soon_threadsafe(self._publish, state)

        async def runner() -> None:
            state.status = "running"
            self._publish(state)
            try:
                state.result = await work(progress)
                state.status = "done"
            except asyncio.CancelledError:
                state.status = "cancelled"
                self._publish(state)
                raise
            except Exception as exc:  # noqa: BLE001 - the failure must reach the UI
                state.status = "failed"
                state.error = {"type": type(exc).__name__, "message": str(exc)}
                log.exception("task failed", extra={"task_id": state.id})
            finally:
                state.finished_at = datetime.now(UTC)
                self._publish(state)
                self._close(state.id)

        self._runners[state.id] = asyncio.create_task(runner())

    def cancel(self, task_id: str) -> bool:
        runner = self._runners.get(task_id)
        if runner is None or runner.done():
            return False
        runner.cancel()
        return True

    def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self._subscribers.setdefault(task_id, []).append(queue)
        state = self._tasks.get(task_id)
        if state is not None:
            queue.put_nowait(state.snapshot())
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(task_id)
        if subscribers and queue in subscribers:
            subscribers.remove(queue)

    def _publish(self, state: TaskState) -> None:
        payload = state.snapshot()
        for queue in list(self._subscribers.get(state.id, [])):
            # A stalled reader loses intermediate ticks, never the import itself.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    def _close(self, task_id: str) -> None:
        for queue in list(self._subscribers.get(task_id, [])):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)  # sentinel: stream complete


TASKS = TaskManager()
