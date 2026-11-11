"""The local web page for answers made in an MCP client: http://localhost:<port>/?result=<result_id>.

    GET /                     the same page as the web service (src/exploreclinicaltrials/web/index.html)
    GET /results              recent answers (id, time, question, title)
    GET /results/<id>         one saved answer's QueryResponse
    GET /vendor/<file>        the page's pinned JavaScript
    GET /health               {"status": "ok", "app": "exploreclinicaltrials"}: how a second process recognises it

Inside an MCP server it starts lazily, on the first chart, in a background thread, and only on
127.0.0.1. If another exploreclinicaltrials process already serves the port, that one is reused: every process
reads the same result files.
"""

import logging
import os
import socket
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from exploreclinicaltrials.mcp_server.results import ResultStore

WEB = Path(__file__).parent.parent / "web"
HOST = "127.0.0.1"
ALLOWED_HOSTS = [HOST, "localhost"]  # the only names this page is reached by (port is ignored)
DEFAULT_PORT = int(os.environ.get("EXPLORECLINICALTRIALS_PORT", "8765"))
PORT_TRIES = 10  # DEFAULT_PORT .. DEFAULT_PORT + 9

log = logging.getLogger(__name__)


def create_results_app(store: ResultStore) -> FastAPI:
    app = FastAPI(title="exploreclinicaltrials (local)", docs_url=None, redoc_url=None, openapi_url=None)
    # DNS rebinding: a website can point its own domain at 127.0.0.1 and read this page's saved
    # answers (the questions can be confidential). Such requests carry that domain as Host: refuse it.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")

    @app.get("/")
    async def page() -> FileResponse:
        return FileResponse(WEB / "index.html", media_type="text/html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "app": "exploreclinicaltrials"}

    @app.get("/results")
    async def recent() -> list[dict]:
        return store.recent()

    @app.get("/results/{result_id}")
    async def result(result_id: str) -> dict:
        doc = store.load(result_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No saved result {result_id!r}.")
        return doc["response"]

    return app


def _is_exploreclinicaltrials(port: int) -> bool:
    try:
        reply = httpx.get(f"http://{HOST}:{port}/health", timeout=0.5)
        return reply.status_code == 200 and reply.json().get("app") == "exploreclinicaltrials"
    except (httpx.HTTPError, ValueError):
        return False


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) != 0


class LocalWeb:
    """Starts the page once per process, on the first call to url_for()."""

    def __init__(self, store: ResultStore):
        self.store = store
        self._base: str | None = None
        self._lock = threading.Lock()

    def url_for(self, result_id: str) -> str | None:
        base = self.ensure_running()
        return f"{base}/?result={result_id}" if base else None

    def ensure_running(self) -> str | None:
        with self._lock:
            if self._base and _is_exploreclinicaltrials(int(self._base.rsplit(":", 1)[1])):
                return self._base
            self._base = None
            for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_TRIES):
                if _is_exploreclinicaltrials(port):  # another client session's server: same result files
                    self._base = f"http://{HOST}:{port}"
                    break
                if _port_free(port):
                    self._start(port)
                    self._base = f"http://{HOST}:{port}"
                    break
            else:
                log.warning("no free port in %s-%s for the exploreclinicaltrials page", DEFAULT_PORT, DEFAULT_PORT + PORT_TRIES - 1)
            return self._base

    def _start(self, port: int) -> None:
        import time

        import uvicorn

        config = uvicorn.Config(create_results_app(self.store), host=HOST, port=port, log_level="warning", log_config=None)
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, name="exploreclinicaltrials-web", daemon=True).start()
        for _ in range(50):  # up to 5 s
            if server.started:
                return
            time.sleep(0.1)
        log.warning("the exploreclinicaltrials page did not start on port %s", port)


def serve(port: int = DEFAULT_PORT) -> None:
    """`exploreclinicaltrials-mcp serve`: only the page, in the foreground, to reopen saved answers."""
    import uvicorn

    print(f"exploreclinicaltrials: saved answers at http://{HOST}:{port}/  (Ctrl+C to stop)")
    uvicorn.run(create_results_app(ResultStore()), host=HOST, port=port, log_level="warning")
