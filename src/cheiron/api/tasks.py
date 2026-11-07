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
from cheiron.models.response import ErrorResponse, QueryResponse
from cheiron.workflow.errors import WorkflowError
from cheiron.workflow.pipeline import QueryWorkflow
from cheiron.workflow.plans import Progress
from cheiron.workflow.steps import FetchRecord
from cheiron.workflow.trace import build_trace, run_metrics

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
    result: QueryResponse | None = None  # the visualization, once succeeded
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
    result: QueryResponse | None = None
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
            result=task.result,
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
            response, result = await self.workflow.run(task.request, progress=lambda p: task.update(progress=p))
            outcome = result.outcome
            saved = _saved_summary(outcome.trials_fetched, outcome.stats_fetched)
            task.update(progress=Progress(stage="saving", message=f"Saving {saved}"))
            records = result.fetches or [FetchRecord(1, outcome.plan, outcome, result.profile)]
            for record in records:
                await asyncio.to_thread(
                    self.outputs.save_fetch, folder / f"fetch-{record.number}",
                    record.plan, record.outcome, record.profile, record.error,
                )  # fmt: skip
            await asyncio.to_thread(self.outputs.save_response, folder, response)
            await asyncio.to_thread(self.outputs.save_trace, folder, build_trace(result.messages, records))
            meta |= {
                "metrics": response.meta.metrics.model_dump() if response.meta.metrics else None,
                "status": TaskStatus.SUCCEEDED.value,
                "rationale": outcome.plan.rationale,
                "total_trials_matched": outcome.total_matched,
                "trials_fetched": outcome.trials_fetched,
                "fetches": len(records),
                "stats_fetched": outcome.stats_fetched,
                "warnings": outcome.warnings,
                "data_as_of": outcome.version.data_timestamp.isoformat(),
                "api_version": outcome.version.api_version,
            }
            task.update(
                status=TaskStatus.SUCCEEDED,
                result=response,
                progress=Progress(
                    stage="done",
                    message=f"Saved {saved}",
                    trials_fetched=outcome.trials_fetched,
                    trials_total=outcome.total_matched,
                ),
            )
        except asyncio.CancelledError as exc:
            meta |= {"status": TaskStatus.FAILED.value, "error": {"error": "internal_error", "message": "Cancelled"}}
            meta |= self._save_partial(folder, exc)
            raise
        except Exception as exc:
            meta |= self._save_partial(folder, exc)
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

    def _save_partial(self, folder: Path, exc: BaseException) -> dict:
        """Save the fetches and trace of a failed or cancelled run; return its metrics for meta.json."""
        fetches, messages = getattr(exc, "fetches", []), getattr(exc, "messages", [])
        for record in fetches:
            error = record.error or (None if record.outcome else "did not finish")
            try:
                self.outputs.save_fetch(folder / f"fetch-{record.number}", record.plan, record.outcome, record.profile, error)
            except Exception:  # never let saving hide the original failure
                log.exception("could not save fetch %s of task folder %s", record.number, folder)
        if not messages:
            return {}
        try:
            self.outputs.save_trace(folder, build_trace(messages, fetches))
            return {"metrics": run_metrics(messages, fetches, getattr(exc, "seconds", 0.0)).model_dump()}
        except Exception:
            log.exception("could not save the trace of task folder %s", folder)
            return {}

    def _forget_old(self) -> None:
        cutoff = _now() - self.keep_finished
        for task_id, task in list(self._tasks.items()):
            if task.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED) and task.updated_at < cutoff:
                del self._tasks[task_id]
