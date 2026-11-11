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
from fastapi.staticfiles import StaticFiles

from cheiron.agents.api_docs import load_api_docs
from cheiron.agents.query_agent import QueryAgent
from cheiron.api.outputs import QueryOutputs
from cheiron.api.tasks import TaskStore, TaskView
from cheiron.fetch.client import CtgovClient
from cheiron.models.request import QueryRequest
from cheiron.workflow.pipeline import QueryWorkflow

WEB_UI = Path(__file__).parent.parent / "web" / "index.html"

API_DESCRIPTION = """\
Ask a natural-language question about clinical trials and get one visualization built from
ClinicalTrials.gov data, with every value citing the trials behind it.

**How a question moves through the API**

1. `POST /queries` submits the question (and optional filters) and returns a `task_id` at once.
2. `GET /queries/{task_id}` is polled until `status` is `succeeded` or `failed`; the answer is in
   `result`.
3. `GET /health` only reports that the service is up.

The web page at `/` uses the first two. Use "Try it out" below to call them from the browser.
"""


async def build_task_store(stack: AsyncExitStack) -> TaskStore:
    """Real dependencies, created once per process and shared by every request. The API reference
    the agent reads is fetched from ClinicalTrials.gov here, so it matches the live API."""
    client = await stack.enter_async_context(CtgovClient())
    workflow = QueryWorkflow(agent=QueryAgent(docs=await load_api_docs()), source=client)
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

    app = FastAPI(
        title="cheiron",
        summary="ClinicalTrials.gov question-to-data service",
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )

    @app.post("/queries", status_code=202, response_model=TaskView, summary="Submit a question")
    async def submit_query(request: QueryRequest, response: Response) -> TaskView:
        """Validate the question and its filters, then start answering it in the background.

        Returns `202` at once with a `task_id` and a `Location: /queries/{task_id}` header; poll
        that URL for the answer. An invalid request (an unknown field, `start_year` after
        `end_year`) gets `422` before any work starts. Structured fields always apply; when the
        question text disagrees with one, the field wins.
        """
        store: TaskStore = app.state.tasks
        task = store.submit(request)
        response.headers["Location"] = f"/queries/{task.id}"
        return store.view(task)

    @app.get("/queries/{task_id}", response_model=TaskView, summary="Get a question's progress and answer")
    async def get_query(task_id: str) -> TaskView:
        """Poll every few seconds until `status` is `succeeded` or `failed`.

        `progress.stage` moves through `queued`, `planning` (the model reads the question and plans
        the search), `fetching` (code calls ClinicalTrials.gov, with a trial count), `analyzing`,
        `building` (code counts, cites and builds the chart), `saving`, then `done` or `failed`.

        On success, `result` is the `QueryResponse`: the `visualization` (every row cites its
        trials), `meta`, and a ready-to-render `vega_lite` spec. On failure, `error` says why,
        including an honest refusal for a question the service cannot answer. Tasks are kept in
        memory for 24 hours, then this returns `404`.
        """
        store: TaskStore = app.state.tasks
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"No task {task_id} (tasks are kept in memory for 24 hours).")
        return store.view(task)

    @app.get("/health", summary="Liveness check")
    async def health() -> dict[str, str]:
        """Not part of answering a question; the host calls it to check the service is up."""
        return {"status": "ok"}

    app.mount("/vendor", StaticFiles(directory=WEB_UI.parent / "vendor"), name="vendor")

    @app.get("/", include_in_schema=False)
    async def web_ui() -> FileResponse:
        return FileResponse(WEB_UI, media_type="text/html")

    return app


app = create_app()
