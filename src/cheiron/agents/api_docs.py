"""The ClinicalTrials.gov API reference the query agent reads, loaded from the live API at startup.

    load_api_docs()        fetch the OpenAPI spec, enums, search areas, field metadata and version
                           from clinicaltrials.gov; any document that cannot be fetched comes from the
                           bundled snapshot in docs/ctgov/ instead, and the result says which
    ApiDocs.page(name)     one page of agent-readable markdown, rendered in memory

This is context for the agent only. Code never derives types or validation from these documents:
the request and plan models stay hand-written, so an upstream change cannot alter them at runtime.

Pages: parameters, enums, search-areas, essie-syntax, fields (an index), fields/<module>.
The Essie syntax page is rendered by JavaScript on the website, so it is always the bundled copy.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from cheiron.fetch.models import SEARCH_PARAMS

log = logging.getLogger(__name__)

API = "https://clinicaltrials.gov/api"
# The repo's docs/ctgov; an installed wheel carries a copy next to this file (pyproject force-include).
_PACKAGED_SNAPSHOT = Path(__file__).resolve().parent / "ctgov-snapshot"
SNAPSHOT_DIR = _PACKAGED_SNAPSHOT if _PACKAGED_SNAPSHOT.is_dir() else Path(__file__).resolve().parents[3] / "docs" / "ctgov"
LOAD_TIMEOUT = 20.0

# name -> (live URL path, bundled snapshot file)
SOURCES = {
    "openapi": ("/oas/v2", "openapi.yaml"),
    "search_areas": ("/v2/studies/search-areas", "search-areas.json"),
    "enums": ("/v2/studies/enums", "enums.json"),
    # every field ("piece"), including search-only ones (counters, year fields), for AREA[...]
    "metadata": ("/v2/studies/metadata?includeIndexedOnly=true", "metadata.json"),
    "version": ("/v2/version", "version.json"),
}

# Endpoints a plan step can call besides /studies, and the parameters the agent may set on each
# (paging, fields, format and sort are set by code).
ENDPOINT_PARAMS = {
    "/studies/{nctId}": ["nctId"],
    "/stats/field/values": ["fields", "types"],
    "/stats/field/sizes": ["fields"],
    "/stats/size": [],
}
SECTION_NAMES = {
    "protocolSection": "protocol",
    "resultsSection": "results",
    "derivedSection": "derived",
    "annotationSection": "annotation",
    "documentSection": "document",
}


@dataclass(frozen=True)
class ApiDocs:
    pages: dict[str, str]
    api_version: str
    from_snapshot: list[str] = field(default_factory=list)  # documents that could not be fetched live

    @property
    def source(self) -> str:
        if not self.from_snapshot:
            return "live"
        return "snapshot" if len(self.from_snapshot) == len(SOURCES) else f"live, except {', '.join(self.from_snapshot)}"

    def page(self, name: str) -> str | None:
        return self.pages.get(name.strip().removesuffix(".md"))

    def top_level(self) -> list[str]:
        return sorted(name for name in self.pages if "/" not in name)


async def load_api_docs(transport: httpx.AsyncBaseTransport | None = None) -> ApiDocs:
    """Fetch every document from the live API; fall back to the snapshot per document."""
    raw: dict[str, Any] = {}
    fallback: list[str] = []
    async with httpx.AsyncClient(
        base_url=API, timeout=LOAD_TIMEOUT, transport=transport, headers={"User-Agent": "cheiron"}
    ) as client:
        for name, (path, _) in SOURCES.items():
            try:
                response = await client.get(path)
                response.raise_for_status()
                raw[name] = yaml.safe_load(response.text)  # the spec is YAML; the rest is JSON, which YAML reads
            except (httpx.HTTPError, yaml.YAMLError) as exc:
                log.warning("Could not load %s from the live API (%s); using the bundled snapshot.", name, exc)
                raw[name] = _snapshot(name)
                fallback.append(name)
    docs = render(raw, fallback)
    log.info("ClinicalTrials.gov API docs loaded: version %s, %s, %d pages.", docs.api_version, docs.source, len(docs.pages))
    return docs


def snapshot_api_docs() -> ApiDocs:
    """The bundled snapshot only: for tests and for running without network access."""
    return render({name: _snapshot(name) for name in SOURCES}, list(SOURCES))


def _snapshot(name: str) -> Any:
    return yaml.safe_load((SNAPSHOT_DIR / SOURCES[name][1]).read_text())


def render(raw: dict[str, Any], from_snapshot: list[str]) -> ApiDocs:
    version = raw["version"]["apiVersion"]
    where = "the bundled snapshot" if set(from_snapshot) == set(SOURCES) else "the live ClinicalTrials.gov API"
    stamp = f"From {where} (API {version})."
    pages = {
        "parameters": _parameters(raw["openapi"], stamp),
        "search-areas": _search_areas(raw["search_areas"], stamp),
        "enums": _enums(raw["enums"], stamp),
        "essie-syntax": (SNAPSHOT_DIR / "essie-syntax.md").read_text(),
        **_fields(raw["metadata"], stamp),
    }
    return ApiDocs(pages=pages, api_version=version, from_snapshot=list(from_snapshot))


def _plain(text: str | None) -> str:
    """Markdown links to site pages -> their text; collapse whitespace; escape table pipes."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text or "")
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def _header(title: str, purpose: str, stamp: str) -> str:
    return f"# {title}\n\n{purpose}\n{stamp}\n\n"


def _parameters(spec: dict, stamp: str) -> str:
    def described(path: str) -> dict[str, str]:
        return {p["name"]: _plain(p.get("description")) for p in spec["paths"][path]["get"].get("parameters", [])}

    lines = [_header("Parameters by endpoint", "What each endpoint accepts. Paging, fields, format and sorting are set by code.", stamp)]
    studies = described("/studies")
    lines.append("## `studies` (GET /studies)\n\n| Parameter | Description |\n| --- | --- |")
    for name in sorted(SEARCH_PARAMS, key=lambda n: (not n.startswith("query"), n)):
        if name in studies:
            lines.append(f"| `{name}` | {studies[name]} |")
    for path, names in ENDPOINT_PARAMS.items():
        endpoint = "study" if path == "/studies/{nctId}" else path.removeprefix("/")
        lines.append(f"\n## `{endpoint}` (GET {path})\n")
        if not names:
            lines.append("No parameters.")
            continue
        params = described(path)
        lines.append("| Parameter | Description |\n| --- | --- |")
        lines.extend(f"| `{n}` | {params.get(n, '')} |" for n in names)
    return "\n".join(lines) + "\n"


def _search_areas(data: list, stamp: str) -> str:
    lines = [_header("Search areas", "Every field each query.* parameter searches, highest weight first. ✓ = synonyms are "
                     "matched. An area name also works in AREA[...], e.g. AREA[ConditionSearch].", stamp)]  # fmt: skip
    for area in data[0]["areas"]:
        param = f"`query.{area['param']}`" if area.get("param") else "no parameter; use AREA[...]"
        fields = [
            piece + (" ✓" if part.get("isSynonyms") else "")
            for part in sorted(area["parts"], key=lambda p: -p["weight"])
            for piece in part["pieces"]
        ]
        lines.append(f"- **{area['name']}** ({param}, UI: {area.get('uiLabel', '-')}, {len(fields)} fields): {', '.join(fields)}")
    return "\n".join(lines) + "\n"


def _enums(data: list, stamp: str) -> str:
    lines = [_header("Enum values", "Exact values for every enum type; use them as written, e.g. AREA[Phase]PHASE3. "
                     "'Used by' lists the fields that take that enum.", stamp)]  # fmt: skip
    for enum in sorted(data, key=lambda e: e["type"]):
        values = ", ".join(f"`{v['value']}`" for v in enum["values"])
        lines.append(f"- **{enum['type']}** (used by {', '.join(enum.get('pieces', []))}): {values}")
    return "\n".join(lines) + "\n"


def _walk(nodes, path=()):
    for node in nodes:
        yield path, node
        yield from _walk(node.get("children", []), path + (node,))


def _slug(text: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", text.removesuffix("Module")).lower()


def _fields(meta: list, stamp: str) -> dict[str, str]:
    """`fields` (an index of modules) plus one `fields/<module>` page per module."""
    modules: dict[str, dict] = {}
    for path, node in _walk(meta):
        if not path:  # a section itself (or the top-level hasResults flag)
            if node["sourceType"] != "STRUCT":
                modules.setdefault("other", {"title": "Top-level flags", "section": "-", "rows": []})["rows"].append(node)
            continue
        section = path[0]
        module = path[1] if len(path) > 1 else node
        key = f"{SECTION_NAMES.get(section['name'], section['name'])}.{_slug(module['name'])}"
        entry = modules.setdefault(key, {"title": module.get("title", module["name"]), "section": section["name"], "rows": []})
        if node is not module:
            entry["rows"].append(node)

    pages: dict[str, str] = {}
    index = [_header("Study data structure: index", "Every field of a study record, grouped by module. Read the ONE module "
                     "page you need. Field names (\"pieces\") work in AREA[Piece]...; dates and numbers also in RANGE[...].", stamp)]  # fmt: skip
    index.append("| Module | Section | Fields | Page |\n| --- | --- | --- | --- |")
    for key, module in modules.items():
        rows = [n for n in module["rows"] if n["sourceType"] != "STRUCT" or n.get("nested")]
        if not rows:
            continue
        name = f"fields/{key}"
        index.append(f"| {_plain(module['title'])} | {module['section']} | {len(rows)} | {name} |")
        body = [_header(f"Fields: {_plain(module['title'])}", "Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields "
                        "within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.", stamp)]  # fmt: skip
        body.append("| Field | Type | Meaning | Notes |\n| --- | --- | --- | --- |")
        for n in rows:
            notes = []
            if n.get("nested"):
                notes.append(f"⤷ SEARCH[{n['piece']}]")
            if n.get("synonyms"):
                notes.append("✓")
            if n.get("indexedOnly"):
                notes.append("search-only")
            if n.get("altPieceNames"):
                notes.append("also: " + ", ".join(n["altPieceNames"]))
            meaning = _plain(n.get("title"))
            if n.get("description"):
                meaning += f". {_plain(n['description'])}"
            body.append(f"| `{n['piece']}` | {_plain(n['type'])} | {meaning} | {'; '.join(notes)} |")
        pages[name] = "\n".join(body) + "\n"
    pages["fields"] = "\n".join(index) + "\n"
    return pages
