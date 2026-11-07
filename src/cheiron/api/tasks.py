"""Background query tasks, kept in memory; each query's data is saved to data/queries/<task_id>/.

One process, one task store: task status is lost on restart and not shared between
worker processes. Saved outputs survive either way.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from cheiron.api.outputs import QueryOutputs
from cheiron.models.request import QueryRequest
from cheiron.models.response import ErrorResponse
from cheiron.workflow.errors import WorkflowError
from cheiron.workflow.pipeline import QueryWorkflow
from cheiron.workflow.plans import Progress

log = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskView(BaseModel):
    """What GET /queries/{task_id} returns."""

    task_id: str
    status: TaskStatus
    progress: Progress
    output_dir: str | None = None  # data/queries/<task_id>
    error: ErrorResponse | None = None
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _saved_summary(trials: int, stats: int) -> str:
    parts = [f"{trials:,} trials"] if trials or not stats else []
    if stats:
        parts.append(f"{stats} registry stats result" + ("s" if stats > 1 else ""))
    return " and ".join(parts)


@dataclass
class Task:
    id: str
    request: QueryRequest
    status: TaskStatus = TaskStatus.QUEUED
    progress: Progress = field(default_factory=lambda: Progress(stage="queued", message="Waiting to start"))
    output_dir: Path | None = None
    error: ErrorResponse | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    handle: asyncio.Task | None = None

    def update(self, **changes) -> None:
        for name, value in changes.items():
            setattr(self, name, value)
        self.updated_at = _now()


class TaskStore:
    def __init__(self, workflow: QueryWorkflow, outputs: QueryOutputs, keep_finished: timedelta = timedelta(hours=24)):
        self.workflow = workflow
        self.outputs = outputs
        self.keep_finished = keep_finished
        self._tasks: dict[str, Task] = {}

    def submit(self, request: QueryRequest) -> Task:
        self._forget_old()
        task = Task(id=str(uuid.uuid4()), request=request)
        self._tasks[task.id] = task
        task.handle = asyncio.create_task(self._execute(task), name=f"query-{task.id}")
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def view(self, task: Task) -> TaskView:
        return TaskView(
            task_id=task.id,
            status=task.status,
            progress=task.progress,
            output_dir=self.outputs.relative(task.output_dir) if task.output_dir else None,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def aclose(self) -> None:
        """Cancel unfinished tasks (server shutdown)."""
        running = [t.handle for t in self._tasks.values() if t.handle and not t.handle.done()]
        for handle in running:
            handle.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    async def _execute(self, task: Task) -> None:
        started = _now()
        meta: dict = {"task_id": task.id, "started_at": started.isoformat()}
        task.update(status=TaskStatus.RUNNING)
        folder = await asyncio.to_thread(self.outputs.create, task.id, task.request)
        task.update(output_dir=folder)
        try:
            outcome = await self.workflow.plan_and_fetch(task.request, progress=lambda p: task.update(progress=p))
            saved = _saved_summary(outcome.trials_fetched, outcome.stats_fetched)
            task.update(progress=Progress(stage="saving", message=f"Saving {saved}"))
            await asyncio.to_thread(self.outputs.save_fetch, folder, outcome)
            meta |= {
                "status": TaskStatus.SUCCEEDED.value,
                "rationale": outcome.plan.rationale,
                "total_trials_matched": outcome.total_matched,
                "trials_fetched": outcome.trials_fetched,
                "stats_fetched": outcome.stats_fetched,
                "warnings": outcome.warnings,
                "data_as_of": outcome.version.data_timestamp.isoformat(),
                "api_version": outcome.version.api_version,
            }
            task.update(
                status=TaskStatus.SUCCEEDED,
                progress=Progress(
                    stage="done",
                    message=f"Saved {saved}",
                    trials_fetched=outcome.trials_fetched,
                    trials_total=outcome.total_matched,
                ),
            )
        except asyncio.CancelledError:
            meta |= {"status": TaskStatus.FAILED.value, "error": {"error": "internal_error", "message": "Cancelled"}}
            raise
        except Exception as exc:
            if isinstance(exc, WorkflowError):
                error = exc.to_response()
            else:
                log.exception("query task %s failed", task.id)
                error = ErrorResponse(error="internal_error", message="Unexpected error; see server logs.")
            meta |= {"status": TaskStatus.FAILED.value, "error": error.model_dump()}
            task.update(status=TaskStatus.FAILED, error=error, progress=Progress(stage="failed", message=error.message))
        finally:
            finished = _now()
            meta |= {"finished_at": finished.isoformat(), "duration_seconds": round((finished - started).total_seconds(), 2)}
            await asyncio.to_thread(self.outputs.save_meta, folder, meta)

    def _forget_old(self) -> None:
        cutoff = _now() - self.keep_finished
        for task_id, task in list(self._tasks.items()):
            if task.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED) and task.updated_at < cutoff:
                del self._tasks[task_id]
