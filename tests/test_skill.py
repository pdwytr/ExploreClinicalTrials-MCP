"""The ctgov-search skill follows the Agent Skills specification (https://agentskills.io/specification)
and stays small enough for progressive disclosure."""

import json
import re
from pathlib import Path

import pytest
import yaml

from cheiron.fetch.models import SEARCH_PARAMS, SNAPSHOT_API_VERSION
from cheiron.workflow import ChartPlan, Dimension, SearchPlan

SKILL_DIR = Path(__file__).resolve().parent.parent / "src" / "cheiron" / "agents" / "skills" / "ctgov-search"
SKILL_MD = SKILL_DIR / "SKILL.md"


def split_skill() -> tuple[dict, str]:
    text = SKILL_MD.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter between --- lines"
    return yaml.safe_load(match.group(1)), match.group(2)


def test_frontmatter_follows_spec():
    meta, _ = split_skill()
    name = meta["name"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert name == SKILL_DIR.name, "name must match the directory name"
    assert 1 <= len(meta["description"]) <= 1024
    assert all(isinstance(v, str) for v in meta.get("metadata", {}).values()), "metadata values must be strings"


def test_snapshot_api_version_is_the_same_everywhere():
    """Code, stored docs and the skill must all describe the same API release."""
    meta, _ = split_skill()
    docs_version = json.loads((SKILL_DIR.parents[3].parent / "docs" / "ctgov" / "version.json").read_text())["apiVersion"]
    assert SNAPSHOT_API_VERSION == docs_version == meta["metadata"]["api-version"]


def test_body_stays_within_recommended_size():
    _, body = split_skill()
    assert len(body.splitlines()) < 500
    assert len(body) / 4 < 5000, "keep SKILL.md under ~5,000 tokens; move detail to references/"


def test_every_reference_is_reachable_through_the_index():
    """SKILL.md lists the top-level references; data-structure/index.md lists every module file."""
    _, body = split_skill()
    refs = SKILL_DIR / "references"
    linked = set(re.findall(r"references/[\w./-]+\.md", body))
    top_level = {f"references/{p.name}" for p in refs.glob("*.md")} | {"references/data-structure/index.md"}
    assert linked == top_level, "SKILL.md must list (with when to read it) every top-level reference and the index"

    index = (refs / "data-structure" / "index.md").read_text()
    modules = {f"data-structure/{p.name}" for p in (refs / "data-structure").glob("*.md") if p.name != "index.md"}
    assert set(re.findall(r"data-structure/[\w.-]+\.md", index)) == modules, "index must list every module file"


def test_index_covers_every_field_of_the_data_structure():
    meta = json.loads((SKILL_DIR.parents[3].parent / "docs" / "ctgov" / "metadata.json").read_text())

    def leaf_pieces(nodes):
        for n in nodes:
            if n["sourceType"] != "STRUCT":
                yield n["piece"]
            yield from leaf_pieces(n.get("children", []))

    module_text = "".join(p.read_text() for p in (SKILL_DIR / "references" / "data-structure").glob("*.md"))
    documented = set(re.findall(r"\| `([A-Za-z0-9]+)` \|", module_text))
    assert set(leaf_pieces(meta)) <= documented


@pytest.mark.parametrize(
    "ref", sorted((SKILL_DIR / "references").rglob("*.md")), ids=lambda p: p.relative_to(SKILL_DIR).as_posix()
)
def test_reference_files_stay_focused(ref):
    assert len(ref.read_text()) / 4 < 6000, "split large references so the agent loads less"


def test_worked_examples_are_valid_plans():
    _, body = split_skill()
    examples = re.findall(r"```json\n(.*?)\n```", body, re.DOTALL)
    assert len(examples) >= 3
    for example in examples:
        SearchPlan.model_validate(json.loads(example))


@pytest.mark.parametrize("path", [SKILL_MD, SKILL_DIR / "references" / "parameters.md"], ids=lambda p: p.name)
def test_skill_only_teaches_parameters_code_accepts(path):
    taught = set(re.findall(r"`((?:query|filter)\.\w+)`", path.read_text()))
    assert taught <= SEARCH_PARAMS, f"teaches parameters code rejects: {taught - SEARCH_PARAMS}"


# --- chart-planning skill -----------------------------------------------------------------------

CHART_SKILL = SKILL_DIR.parent / "chart-planning" / "SKILL.md"


CHART_DIR = CHART_SKILL.parent
ALL_SKILLS = sorted(p.parent for p in SKILL_DIR.parent.glob("*/SKILL.md"))


@pytest.mark.parametrize("skill", ALL_SKILLS, ids=lambda p: p.name)
def test_every_skill_follows_the_agent_skills_spec(skill):
    """https://agentskills.io/specification: frontmatter fields and limits, a body under 500 lines and
    ~5000 tokens, and every file it links to exists (relative to the skill root)."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", (skill / "SKILL.md").read_text(), re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter between --- lines"
    meta, body = yaml.safe_load(match.group(1)), match.group(2)
    assert set(meta) <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    name = meta["name"]
    assert name == skill.name and len(name) <= 64 and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
    assert 1 <= len(meta["description"]) <= 1024
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in (meta.get("metadata") or {}).items())
    assert len(body.splitlines()) < 500 and len(body) / 4 < 5000
    for path in set(re.findall(r"\breferences/[\w./-]+\.md\b", body)):
        assert (skill / path).is_file(), f"{skill.name} links to missing {path}"


def test_chart_skill_is_a_procedure_with_gotchas_and_on_demand_references():
    body = CHART_SKILL.read_text()
    for section in ("## Procedure", "## Default chart per question", "## Output", "## Gotchas", "## References"):
        assert section in body, f"missing {section}"
    assert re.search(r"use this skill when", body.split("---")[1], re.IGNORECASE), "description says when to use it"
    references = sorted(p.relative_to(CHART_DIR).as_posix() for p in (CHART_DIR / "references").glob("*.md"))
    assert references, "detail lives in references/"
    table = body.split("## References")[1]
    for path in references:
        assert f"`{path}`" in table, f"{path} is not listed with when to read it"


def test_chart_skill_examples_are_valid_chart_plans():
    files = [CHART_SKILL, *sorted((CHART_DIR / "references").glob("*.md"))]
    examples = [e for f in files for e in re.findall(r"```json\n(.*?)\n```", f.read_text(), re.DOTALL)]
    assert len(examples) >= 8
    for example in examples:
        ChartPlan.model_validate(json.loads(example))


def test_chart_skill_names_exactly_the_chartable_fields():
    text = CHART_SKILL.read_text()
    section = text.split("## Fields you can chart")[1].split("##")[0]
    assert set(re.findall(r"`([a-z_]+)`", section)) == {d.value for d in Dimension}


# --- Skills must not contain the eval questions -----------------------------------------------

EVAL_CASES = Path(__file__).resolve().parent.parent / "evals" / "cases"
_GENERIC = set(
    "the and for with that this have from what which how many trials trial per each show were are does "
    "more most into than across their year years since".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _GENERIC}


def test_skill_examples_are_not_eval_questions():
    """Skills teach the shape of a choice; if an example is (nearly) an eval question, that eval
    measures copying, not judgment. Every quoted example and title is compared with every eval query."""
    queries = [(c["id"], c["request"]["query"]) for f in sorted(EVAL_CASES.glob("*.json")) for c in json.loads(f.read_text())]
    leaks = []
    for md in sorted(SKILL_DIR.parent.rglob("*.md")):
        for snippet in re.findall(r'"([^"\n]{20,200})"', md.read_text()):
            words = _words(snippet)
            if len(words) < 3:
                continue
            for case_id, query in queries:
                q = _words(query)
                if len(words & q) / len(words | q) >= 0.4:
                    leaks.append(f"{md.name}: {snippet!r} ~ {case_id}")
    assert not leaks, "skill examples copy eval questions:\n" + "\n".join(leaks)

