"""CtgovClient against a fake HTTP server (httpx.MockTransport): no network."""

import asyncio

import httpx
import pytest

from cheiron.fetch.client import CtgovClient
from cheiron.fetch.models import StudySearchParams
from cheiron.workflow.errors import InvalidSearch, UpstreamError


def study(n: int) -> dict:
    return {"protocolSection": {"identificationModule": {"nctId": f"NCT{n:08d}"}}}


class FakeStudiesApi:
    """Serves `total` studies in pages of the requested size; records every request."""

    def __init__(self, total: int):
        self.total = total
        self.requests: list[httpx.QueryParams] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        self.requests.append(params)
        size = int(params["pageSize"])
        start = int(params.get("pageToken", "0"))
        end = min(start + size, self.total)
        body = {"studies": [study(i) for i in range(start, end)]}
        if "countTotal" in params:
            body["totalCount"] = self.total
        if end < self.total:
            body["nextPageToken"] = str(end)
        return httpx.Response(200, json=body)


def run(coro):
    return asyncio.run(coro)


def client(handler) -> CtgovClient:
    return CtgovClient(transport=httpx.MockTransport(handler), backoff_seconds=0)


SEARCH = StudySearchParams(search={"query.cond": '"asthma"'})


async def search(handler, limit: int):
    async with client(handler) as c:
        return await c.search(SEARCH, limit)


# --- Pagination ------------------------------------------------------------------------------


def test_follows_every_page_until_done():
    api = FakeStudiesApi(total=2500)
    result = run(search(api, limit=5000))

    assert len(result.trials) == 2500 and result.total_matched == 2500 and not result.truncated
    assert len(api.requests) == 3  # 1000 + 1000 + 500
    assert "countTotal" in api.requests[0] and "pageToken" not in api.requests[0]
    assert "countTotal" not in api.requests[1] and api.requests[1]["pageToken"] == "1000"
    assert all(r["query.cond"] == '"asthma"' for r in api.requests)  # same search on every page
    assert len({t.nct_id for t in result.trials}) == 2500  # no duplicates


def test_stops_at_the_limit_and_reports_truncation():
    api = FakeStudiesApi(total=13126)
    result = run(search(api, limit=1500))

    assert len(result.trials) == 1500
    assert result.total_matched == 13126 and result.truncated
    assert len(api.requests) == 2  # never fetches pages it does not need


def test_small_limit_uses_a_small_page():
    api = FakeStudiesApi(total=50)
    run(search(api, limit=10))
    assert api.requests[0]["pageSize"] == "10"


def test_endpoint_without_pagination_yields_one_page():
    def handler(request):
        return httpx.Response(200, json={"apiVersion": "2.0.5"})

    async def collect():
        async with client(handler) as c:
            return [p async for p in c.pages("/version")]

    assert run(collect()) == [{"apiVersion": "2.0.5"}]


# --- Errors and retries ------------------------------------------------------------------------


def test_bad_request_becomes_invalid_search_with_the_api_message():
    def handler(request):
        return httpx.Response(400, text="Error parsing query in advanced filter: missing ')' at '<EOF>'")

    with pytest.raises(InvalidSearch, match="missing '\\)'"):
        run(search(handler, limit=10))


def test_temporary_failure_is_retried():
    api = FakeStudiesApi(total=5)
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else api(request)

    assert len(run(search(flaky, limit=10)).trials) == 5
    assert calls["n"] == 2


def test_rate_limit_is_retried():
    api = FakeStudiesApi(total=5)
    calls = {"n": 0}

    def limited(request):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}) if calls["n"] == 1 else api(request)

    assert len(run(search(limited, limit=10)).trials) == 5


def test_persistent_failure_raises_upstream_error():
    with pytest.raises(UpstreamError, match="HTTP 503"):
        run(search(lambda request: httpx.Response(503), limit=10))


def test_network_failure_raises_upstream_error():
    def broken(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(UpstreamError, match="unreachable"):
        run(search(broken, limit=10))
