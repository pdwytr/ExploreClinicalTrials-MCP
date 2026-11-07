"""Generate the ctgov-search skill's reference files from the API snapshots in docs/ctgov/.

Indexed for progressive disclosure (https://agentskills.io/specification): SKILL.md links
to small files and to data-structure/index.md, which points to one file per module, so
the agent loads only what a question needs. Only SKILL.md is hand-written; rerun this
after scripts/refresh_ctgov_docs.py.

    uv run --group dev python scripts/build_ctgov_skill.py
"""

import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cheiron.fetch.models import SEARCH_PARAMS  # noqa: E402  (the /studies parameters code accepts)

DOCS = ROOT / "docs" / "ctgov"
OUT = ROOT / "src" / "cheiron" / "agents" / "skills" / "ctgov-search" / "references"

# Endpoints a plan step can call, and the parameters the planner may set on each
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


def plain(text: str | None) -> str:
    """Markdown links to site pages -> their text; collapse whitespace; escape table pipes."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text or "")
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def header(title: str, source: str, purpose: str) -> str:
    version = json.loads((DOCS / "version.json").read_text())["apiVersion"]
    return f"# {title}\n\n{purpose}\nGenerated from `docs/ctgov/{source}` (API {version}) by scripts/build_ctgov_skill.py.\n\n"


# --- parameters.md -------------------------------------------------------------------------


def build_parameters() -> str:
    spec = yaml.safe_load((DOCS / "openapi.yaml").read_text())

    def described(path: str) -> dict[str, str]:
        return {p["name"]: plain(p.get("description")) for p in spec["paths"][path]["get"].get("parameters", [])}

    lines = [header("Parameters by endpoint", "openapi.yaml",
                    "What you may set on each endpoint. Paging, fields, format and sorting are set by code.")]  # fmt: skip
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


# --- search-areas.md ----------------------------------------------------------------------------


def build_search_areas() -> str:
    areas = json.loads((DOCS / "search-areas.json").read_text())[0]["areas"]
    lines = [header("Search areas", "search-areas.json",
                    "Every field each query.* parameter searches, highest weight first. ✓ = synonyms are matched. "
                    "An area name also works in AREA[...], e.g. AREA[ConditionSearch].")]  # fmt: skip
    for area in areas:
        param = f"`query.{area['param']}`" if area.get("param") else "no parameter; use AREA[...]"
        fields = []
        for part in sorted(area["parts"], key=lambda p: -p["weight"]):
            for piece in part["pieces"]:
                fields.append(piece + (" ✓" if part.get("isSynonyms") else ""))
        lines.append(f"- **{area['name']}** ({param}, UI: {area.get('uiLabel', '-')}, {len(fields)} fields): {', '.join(fields)}")
    return "\n".join(lines) + "\n"


# --- enums.md --------------------------------------------------------------------------------------


def build_enums() -> str:
    enums = json.loads((DOCS / "enums.json").read_text())
    lines = [header("Enum values", "enums.json",
                    "Exact values for every enum type; use them as written, e.g. AREA[Phase]PHASE3. "
                    "'Used by' lists the fields that take that enum.")]  # fmt: skip
    for enum in sorted(enums, key=lambda e: e["type"]):
        values = ", ".join(f"`{v['value']}`" for v in enum["values"])
        lines.append(f"- **{enum['type']}** (used by {', '.join(enum.get('pieces', []))}): {values}")
    return "\n".join(lines) + "\n"


# --- data-structure/ --------------------------------------------------------------------------------


def _walk(nodes, path=()):
    for node in nodes:
        yield path, node
        yield from _walk(node.get("children", []), path + (node,))


def _slug(text: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", text.removesuffix("Module")).lower()


def build_data_structure() -> dict[str, str]:
    """data-structure/index.md plus one file per module: {relative path: text}."""
    meta = json.loads((DOCS / "metadata.json").read_text())
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

    files: dict[str, str] = {}
    index = [header("Study data structure: index", "metadata.json",
                    "Every field of a study record, grouped by module. Read the ONE module file you need. "
                    "Field names (\"pieces\") work in AREA[Piece]...; dates and numbers also in RANGE[...].")]  # fmt: skip
    index.append("| Module | Section | Fields | File |\n| --- | --- | --- | --- |")
    for key, module in modules.items():
        rows = [n for n in module["rows"] if n["sourceType"] != "STRUCT" or n.get("nested")]
        if not rows:
            continue
        name = f"data-structure/{key}.md"
        index.append(f"| {plain(module['title'])} | {module['section']} | {len(rows)} | {name} |")
        body = [header(f"Fields: {plain(module['title'])}", "metadata.json",
                       "Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; "
                       "✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.")]  # fmt: skip
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
            meaning = plain(n.get("title"))
            if n.get("description"):
                meaning += f". {plain(n['description'])}"
            body.append(f"| `{n['piece']}` | {plain(n['type'])} | {meaning} | {'; '.join(notes)} |")
        files[name] = "\n".join(body) + "\n"
    files["data-structure/index.md"] = "\n".join(index) + "\n"
    return files


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)  # remove files that no longer exist upstream
    (OUT / "data-structure").mkdir(parents=True)
    files = {
        "parameters.md": build_parameters(),
        "search-areas.md": build_search_areas(),
        "enums.md": build_enums(),
        "essie-syntax.md": (DOCS / "essie-syntax.md").read_text(),
        **build_data_structure(),
    }
    for name, text in sorted(files.items()):
        (OUT / name).write_text(text)
    biggest = max(files.items(), key=lambda kv: len(kv[1]))
    print(f"{len(files)} files, {sum(len(t) for t in files.values()) // 4:,} tokens in total")
    print(f"largest: {biggest[0]} (~{len(biggest[1]) // 4:,} tokens)")
    for name in ["data-structure/index.md", "parameters.md", "search-areas.md", "enums.md"]:
        print(f"  {name:28} ~{len(files[name]) // 4:,} tokens")


if __name__ == "__main__":
    main()
