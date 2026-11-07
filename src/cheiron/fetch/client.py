"""HTTP client for the ClinicalTrials.gov API. All pagination and retrying lives here.

One rule covers every endpoint: if a response has `nextPageToken`, request again
with the same parameters plus `pageToken`; otherwise that was everything. Only
/studies paginates (max 1,000 per page); every other endpoint answers in one response.

Note: /stats/field/values and /stats/field/sizes return only the top values of a
field and cannot be paged further. A result is incomplete when
len(topValues) < uniqueValuesCount. They also take no search filters (whole registry only).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from cheiron.fetch.models import BASE_URL, MAX_PAGE_SIZE, StudiesPage, StudySearchParams, Trial
from cheiron.workflow.errors import InvalidSearch, UpstreamError
from cheiron.workflow.plans import FetchResult

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}

# At most this many requests in flight per client, across all searches and pages,
# so we never overload the ClinicalTrials.gov servers. Share one client per process
# to make the limit global.
MAX_CONCURRENT_REQUESTS = 5

ProgressCallback = Callable[[int, int | None], None]  # (trials fetched so far, total matching)


class CtgovClient:
    """Implements the workflow's TrialSource. Use as `async with CtgovClient() as client:`."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # tests pass a fake transport
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=timeout, headers={"User-Agent": "cheiron"}
        )
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._slots = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> "CtgovClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._http.aclose()

    # --- Generic: any endpoint -------------------------------------------------------

    async def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """One request, retried on network errors, 429 and 5xx with exponential backoff."""
        for attempt in range(self._max_retries + 1):
            try:
                async with self._slots:
                    response = await self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise UpstreamError(f"ClinicalTrials.gov unreachable: {exc}") from exc
                await self._wait(attempt, None)
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code == 400:  # the search itself is wrong: the planner can fix it
                raise InvalidSearch(response.text.strip()[:500], {"params": params or {}})
            if response.status_code in RETRY_STATUSES and attempt < self._max_retries:
                await self._wait(attempt, response.headers.get("Retry-After"))
                continue
            raise UpstreamError(f"ClinicalTrials.gov returned HTTP {response.status_code}", {"path": path})
        raise AssertionError("unreachable")

    async def pages(
        self, path: str, params: dict[str, str] | None = None, *, items_key: str | None = None, max_items: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every page of a response, following nextPageToken while present.

        Endpoints without pagination yield exactly one page. Stops early once
        `max_items` items (counted under `items_key`) have been collected.
        """
        params = dict(params or {})
        collected = 0
        while True:
            page = await self.get(path, params)
            yield page
            if items_key:
                collected += len(page.get(items_key, []))
            token = page.get("nextPageToken")
            if not token or (max_items is not None and collected >= max_items):
                return
            params["pageToken"] = token
            params.pop("countTotal", None)  # only meaningful on the first page

    # --- TrialSource: /studies ---------------------------------------------------------

    async def search(
        self, params: StudySearchParams, limit: int | None = None, on_progress: ProgressCallback | None = None
    ) -> FetchResult:
        """Fetch every trial matching one search (or the first `limit`), across as many pages as needed.

        Default is no limit: counts must be exact, so all matching trials are fetched.
        `on_progress(fetched, total)` is called after each page, for task status updates.
        """
        page_size = MAX_PAGE_SIZE if limit is None else min(MAX_PAGE_SIZE, limit)
        query = params.model_copy(update={"page_size": page_size, "count_total": True})
        trials: list[Trial] = []
        total: int | None = None
        async for raw in self.pages("/studies", query.to_query_params(), items_key="studies", max_items=limit):
            page = StudiesPage.model_validate(raw)
            if total is None:
                total = page.total_count
            trials.extend(Trial.from_raw(study) for study in page.studies)
            if on_progress:
                on_progress(len(trials), total)
        if limit is not None:
            trials = trials[:limit]
        log.info("fetched %d of %s trials for %s", len(trials), total, params.search)
        return FetchResult(trials=trials, total_matched=total if total is not None else len(trials))

    # --- Internals ------------------------------------------------------------------------

    async def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = float(retry_after) if retry_after and retry_after.isdigit() else self._backoff * 2**attempt
        log.warning("retrying ClinicalTrials.gov request in %.1fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)
