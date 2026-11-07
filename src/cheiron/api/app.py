"""HTTP service: submit a question, poll its status, get the visualization. Outputs are also
written to data/queries/<task_id>/.

    POST /queries          QueryRequest -> 202 TaskView (Location: /queries/{task_id})
    GET  /queries/{id}     TaskView: status, progress, result (QueryResponse when done), error
    GET  /health
    GET  /                 the web UI (src/cheiron/web/index.html)

Run:  uv run uvicorn cheiron.api.app:app
"""

from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse

from cheiron.agents.query_agent import QueryAgent
from cheiron.api.outputs import QueryOutputs
from cheiron.api.tasks import TaskStore, TaskView
from cheiron.fetch.client import CtgovClient
from cheiron.models.request import QueryRequest
from cheiron.workflow.pipeline import QueryWorkflow

WEB_UI = Path(__file__).parent.parent / "web" / "index.html"


async def build_task_store(stack: AsyncExitStack) -> TaskStore:
    """Real dependencies, created once per process and shared by every request."""
    client = await stack.enter_async_context(CtgovClient())
    workflow = QueryWorkflow(agent=QueryAgent(), source=client)
    return TaskStore(workflow, QueryOutputs())


def create_app(task_store_factory: Callable[[AsyncExitStack], object] = build_task_store) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            store = await task_store_factory(stack)
            app.state.tasks = store
            try:
                yield
            finally:
                await store.aclose()

    app = FastAPI(title="cheiron", summary="ClinicalTrials.gov question-to-data service", lifespan=lifespan)

    @app.post("/queries", status_code=202, response_model=TaskView)
    async def submit_query(request: QueryRequest, response: Response) -> TaskView:
        store: TaskStore = app.state.tasks
        task = store.submit(request)
        response.headers["Location"] = f"/queries/{task.id}"
        return store.view(task)

    @app.get("/queries/{task_id}", response_model=TaskView)
    async def get_query(task_id: str) -> TaskView:
        store: TaskStore = app.state.tasks
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"No task {task_id} (tasks are kept in memory for 24 hours).")
        return store.view(task)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def web_ui() -> FileResponse:
        return FileResponse(WEB_UI, media_type="text/html")

    return app


app = create_app()
