"""The two agent specs (Pydantic AI agent spec YAML): each declares what code registers, stays small,
lists every reference with when to read it, and its examples are valid plans."""

import json
import re
from pathlib import Path

import pytest
from pydantic_ai.agent.spec import AgentSpec

from trialsight.agents import chart_planner, query_agent
from trialsight.agents.api_docs import snapshot_api_docs
from trialsight.fetch.models import SEARCH_PARAMS, SNAPSHOT_API_VERSION
from trialsight.workflow import ChartPlan, Dimension, SearchPlan

SPECS = Path(query_agent.__file__).parent / "specs"
QUERY_SPEC, CHART_SPEC = SPECS / "query-agent.yaml", SPECS / "chart-planner.yaml"
CHART_REFS = SPECS / "chart-planner"


def spec(path: Path) -> AgentSpec:
    return AgentSpec.from_file(path)


@pytest.mark.parametrize("path", [QUERY_SPEC, CHART_SPEC], ids=lambda p: p.stem)
def test_spec_loads_and_stays_within_size(path):
    s = spec(path)
    assert s.name and 1 <= len(s.description) <= 1024
    assert len(s.instructions) / 4 < 6000, "keep instructions small; move detail to references"


def test_specs_declare_exactly_what_code_registers():
    """metadata lists each agent's tools and outputs, so the spec reads as its whole contract."""
    assert spec(QUERY_SPEC).metadata["tools"] == [t.__name__ for t in query_agent.TOOLS]
    assert spec(CHART_SPEC).metadata["tools"] == [t.__name__ for t in chart_planner.TOOLS]
    assert spec(QUERY_SPEC).metadata["output"] == ["plan_chart", "unanswerable"]
    assert spec(CHART_SPEC).metadata["output"] == ["chart_plan", "unanswerable"]
    assert spec(QUERY_SPEC).metadata["fetch_budget"] == query_agent.FETCH_BUDGET
    assert f"at most {query_agent.FETCH_BUDGET} times" in spec(QUERY_SPEC).instructions


def test_snapshot_api_version_is_the_same_everywhere():
    """The version the specs and evals were checked on is the bundled fallback's version."""
    assert SNAPSHOT_API_VERSION == snapshot_api_docs().api_version


# --- Query agent ------------------------------------------------------------------------------------


def test_query_spec_lists_every_api_docs_page_it_can_read():
    table = spec(QUERY_SPEC).instructions.split("## API reference")[1]
    assert set(re.findall(r"\| `([\w-]+)` \|", table)) == set(snapshot_api_docs().top_level())


def test_query_spec_examples_are_valid_plans():
    examples = re.findall(r"```json\n(.*?)\n```", spec(QUERY_SPEC).instructions, re.DOTALL)
    assert len(examples) >= 3
    for example in examples:
        SearchPlan.model_validate(json.loads(example))


def test_query_spec_only_teaches_parameters_code_accepts():
    taught = set(re.findall(r"`((?:query|filter)\.\w+)`", spec(QUERY_SPEC).instructions))
    assert taught <= SEARCH_PARAMS, f"teaches parameters code rejects: {taught - SEARCH_PARAMS}"


# --- Chart planner ----------------------------------------------------------------------------------


def test_chart_spec_is_a_procedure_with_gotchas_and_on_demand_references():
    body = spec(CHART_SPEC).instructions
    for section in ("## Procedure", "## Default chart per question", "## Output", "## Gotchas", "## References"):
        assert section in body, f"missing {section}"
    table = body.split("## References")[1]
    for page in sorted(p.stem for p in CHART_REFS.glob("*.md")):
        assert f"`{page}`" in table, f"{page} is not listed with when to read it"


@pytest.mark.parametrize("ref", sorted(CHART_REFS.glob("*.md")), ids=lambda p: p.name)
def test_chart_references_stay_focused(ref):
    assert len(ref.read_text()) / 4 < 6000


def test_chart_spec_examples_are_valid_chart_plans():
    texts = [spec(CHART_SPEC).instructions, *(p.read_text() for p in sorted(CHART_REFS.glob("*.md")))]
    examples = [e for t in texts for e in re.findall(r"```json\n(.*?)\n```", t, re.DOTALL)]
    assert len(examples) >= 8
    for example in examples:
        ChartPlan.model_validate(json.loads(example))


def test_chart_spec_names_exactly_the_chartable_fields():
    section = spec(CHART_SPEC).instructions.split("## Fields you can chart")[1].split("##")[0]
    assert set(re.findall(r"`([a-z_]+)`", section)) == {d.value for d in Dimension}


def test_chart_planner_reads_only_its_own_references():
    assert chart_planner.REFERENCES == CHART_REFS


# --- Specs must not contain the eval questions -----------------------------------------------------

EVAL_CASES = Path(__file__).resolve().parent.parent / "evals" / "cases"
_GENERIC = set(
    "the and for with that this have from what which how many trials trial per each show were are does "
    "more most into than across their year years since".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _GENERIC}


def test_spec_examples_are_not_eval_questions():
    """Specs teach the shape of a choice; if an example is (nearly) an eval question, that eval
    measures copying, not judgment. Every quoted example and title is compared with every eval query."""
    queries = [(c["id"], c["request"]["query"]) for f in sorted(EVAL_CASES.glob("*.json")) for c in json.loads(f.read_text())]
    files = [QUERY_SPEC, CHART_SPEC, *sorted(CHART_REFS.glob("*.md"))]
    leaks = []
    for path in files:
        for snippet in re.findall(r'"([^"\n]{20,200})"', path.read_text()):
            words = _words(snippet)
            if len(words) < 3:
                continue
            for case_id, query in queries:
                q = _words(query)
                if len(words & q) / len(words | q) >= 0.4:
                    leaks.append(f"{path.name}: {snippet!r} ~ {case_id}")
    assert not leaks, "spec examples copy eval questions:\n" + "\n".join(leaks)
