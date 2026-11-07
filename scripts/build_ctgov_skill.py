"""Generate the ctgov-search skill's reference files from the API snapshots in docs/ctgov/.

Each reference is small and focused so the agent can load only what a question needs
(Agent Skills progressive disclosure: https://agentskills.io/specification).
Only SKILL.md is hand-written; rerun this after scripts/refresh_ctgov_docs.py.

    uv run python scripts/build_ctgov_skill.py
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from cheiron.fetch.models import SEARCH_PARAMS  # noqa: E402  (the parameters code accepts)

DOCS = ROOT / "docs" / "ctgov"
OUT = ROOT / "src" / "cheiron" / "agents" / "skills" / "ctgov-search" / "references"
# Sections whose fields are useful in AREA[...] filters (results/annotation/document are not).
FILTER_SECTIONS = {"protocolSection", "derivedSection", "hasResults"}
SCALAR_TYPES = {"date", "integer", "boolean", "normalized_date", "PartialDate", "DateTimeMinutes"}


def plain(text: str) -> str:
    """Markdown links to site pages -> their text; collapse whitespace."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text or "")
    return re.sub(r"\s+", " ", text).strip()


def header(title: str, source: str, purpose: str) -> str:
    version = json.loads((DOCS / "version.json").read_text())["apiVersion"]
    return f"# {title}\n\n{purpose}\nGenerated from `docs/ctgov/{source}` (API {version}) by scripts/build_ctgov_skill.py.\n\n"


def build_parameters() -> str:
    spec = yaml.safe_load((DOCS / "openapi.yaml").read_text())
    params = {p["name"]: p for p in spec["paths"]["/studies"]["get"]["parameters"]}
    lines = [header("Search parameters (GET /studies)", "openapi.yaml",
                    "The parameters you may set. Paging, fields and sorting are set by code.")]  # fmt: skip
    lines.append("| Parameter | Description |\n| --- | --- |")
    for name in sorted(SEARCH_PARAMS, key=lambda n: (not n.startswith("query"), n)):
        if name in params:
            desc = plain(params[name].get("description", "")).replace("|", "\\|")
            lines.append(f"| `{name}` | {desc} |")
    return "\n".join(lines) + "\n"


def build_search_areas() -> str:
    areas = json.loads((DOCS / "search-areas.json").read_text())[0]["areas"]
    lines = [header("Search areas", "search-areas.json",
                    "What each query.* parameter searches, highest-weighted fields first. "
                    "✓ = synonyms are matched. An area name also works in AREA[...], e.g. AREA[ConditionSearch].")]  # fmt: skip
    for area in areas:
        param = f"`query.{area['param']}`" if area.get("param") else "no parameter; use AREA[...]"
        fields = []
        for part in sorted(area["parts"], key=lambda p: -p["weight"]):
            for piece in part["pieces"]:
                fields.append(piece + (" ✓" if part.get("isSynonyms") else ""))
        shown = ", ".join(fields[:12]) + (f", … ({len(fields)} fields)" if len(fields) > 12 else "")
        lines.append(f"- **{area['name']}** ({param}, UI: {area.get('uiLabel', '-')}): {shown}")
    return "\n".join(lines) + "\n"


def _walk(nodes, path=()):
    for node in nodes:
        yield path, node
        yield from _walk(node.get("children", []), path + (node["name"],))


def build_fields(enum_names: set[str]) -> tuple[str, set[str]]:
    meta = json.loads((DOCS / "metadata.json").read_text())
    used_enums: set[str] = set()
    rows: dict[str, list[str]] = {}
    for path, node in _walk(meta):
        section = path[0] if path else node["name"]
        if section not in FILTER_SECTIONS or node["sourceType"] == "STRUCT":
            continue
        base = node["type"].removesuffix("[]")
        if base in enum_names:
            used_enums.add(base)
            kind = f"enum {base}"
        elif base in SCALAR_TYPES or node["sourceType"] in {"DATE", "NUMERIC", "BOOLEAN"}:
            kind = node["sourceType"].lower()
        else:
            continue  # free text: search it with query.* instead
        module = path[1] if len(path) > 1 else section
        rows.setdefault(module, []).append(f"| `{node['piece']}` | {kind} | {plain(node.get('title', ''))} |")
    lines = [header("Filterable fields for AREA[...]", "metadata.json",
                    "Fields with fixed values, dates, numbers or booleans, grouped by module. "
                    "Use as AREA[Piece]VALUE or AREA[Piece]RANGE[min,max]. Enum values are in references/enums.md. "
                    "Free-text fields are searched with query.* parameters (see references/search-areas.md).")]  # fmt: skip
    for module, module_rows in rows.items():
        lines.append(f"\n## {module}\n\n| Field | Type | Meaning |\n| --- | --- | --- |")
        lines.extend(module_rows)
    return "\n".join(lines) + "\n", used_enums


def build_enums(used: set[str], enums: list[dict]) -> str:
    lines = [header("Enum values", "enums.json",
                    "Exact values for enum fields; use them as written, e.g. AREA[Phase]PHASE3.")]  # fmt: skip
    for enum in sorted((e for e in enums if e["type"] in used), key=lambda e: e["type"]):
        values = ", ".join(f"`{v['value']}`" for v in enum["values"])
        lines.append(f"- **{enum['type']}**: {values}")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    enums = json.loads((DOCS / "enums.json").read_text())
    fields_md, used_enums = build_fields({e["type"] for e in enums})
    files = {
        "parameters.md": build_parameters(),
        "search-areas.md": build_search_areas(),
        "fields.md": fields_md,
        "enums.md": build_enums(used_enums, enums),
        "essie-syntax.md": (DOCS / "essie-syntax.md").read_text(),
    }
    for name, text in files.items():
        (OUT / name).write_text(text)
        print(f"{name:18} {len(text):>7,} chars  ~{len(text) // 4:>6,} tokens")


if __name__ == "__main__":
    main()
