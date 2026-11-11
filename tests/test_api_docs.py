"""The API reference the query agent reads is loaded from the live API at startup, falling back to
the bundled snapshot per document. Live responses are faked with httpx.MockTransport."""

import asyncio
import json
import re

import httpx

from studytrials.agents.api_docs import (
    SNAPSHOT_DIR,
    SOURCES,
    load_api_docs,
    snapshot_api_docs,
)

SNAPSHOT = {path.split("?")[0]: (SNAPSHOT_DIR / file).read_text() for path, file in SOURCES.values()}


def transport(overrides: dict[str, str | int] | None = None) -> httpx.MockTransport:
    """Serves the snapshot as if live; `overrides` maps an API path to a body or an HTTP status."""
    overrides = overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api")
        body = overrides.get(path, SNAPSHOT[path])
        return httpx.Response(body) if isinstance(body, int) else httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


def test_everything_live_is_rendered_into_pages():
    newer = json.dumps({"apiVersion": "2.1.0", "dataTimestamp": "2026-11-08T10:00:00"})
    docs = asyncio.run(load_api_docs(transport({"/v2/version": newer})))

    assert docs.source == "live" and docs.api_version == "2.1.0"
    assert docs.top_level() == ["enums", "essie-syntax", "fields", "parameters", "search-areas"]
    assert "From the live ClinicalTrials.gov API (API 2.1.0)." in docs.page("enums")
    assert "`PHASE3`" in docs.page("enums")


def test_a_document_that_cannot_be_fetched_comes_from_the_snapshot():
    docs = asyncio.run(load_api_docs(transport({"/v2/studies/enums": 503})))
    assert docs.from_snapshot == ["enums"] and docs.source == "live, except enums"
    assert "`PHASE3`" in docs.page("enums")  # still there, from docs/ctgov/enums.json


def test_without_network_everything_comes_from_the_snapshot():
    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    docs = asyncio.run(load_api_docs(httpx.MockTransport(offline)))
    assert docs.source == "snapshot"
    assert docs.pages == snapshot_api_docs().pages


def test_fields_index_lists_every_module_page_and_every_field():
    docs = snapshot_api_docs()
    modules = {name for name in docs.pages if name.startswith("fields/")}
    assert set(re.findall(r"fields/[\w.-]+", docs.page("fields"))) == modules

    def leaf_pieces(nodes):
        for n in nodes:
            if n["sourceType"] != "STRUCT":
                yield n["piece"]
            yield from leaf_pieces(n.get("children", []))

    meta = json.loads((SNAPSHOT_DIR / "metadata.json").read_text())
    documented = set(re.findall(r"\| `([A-Za-z0-9]+)` \|", "".join(docs.pages[m] for m in modules)))
    assert set(leaf_pieces(meta)) <= documented


def test_pages_stay_small_enough_to_read_one_at_a_time():
    for name, text in snapshot_api_docs().pages.items():
        assert len(text) / 4 < 6000, f"{name} is too large for the agent to read whole"


def test_page_names_are_forgiving_about_md():
    docs = snapshot_api_docs()
    assert docs.page("enums.md") == docs.page("enums") and docs.page("nope") is None
