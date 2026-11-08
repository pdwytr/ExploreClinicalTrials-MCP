"""QueryAgent's tool loop with a scripted fake model (Pydantic AI FunctionModel): no API key, no cost.

Each test scripts what the model does turn by turn and checks what code allowed, refused or
sent back to it."""

import asyncio

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_workflow import FOUND, FakeSource, trial

from cheiron.agents import query_agent
from cheiron.agents.query_agent import FETCH_BUDGET, QueryAgent, build_prompt
from cheiron.models.request import QueryRequest
from cheiron.settings import Settings
from cheiron.workflow import FetchResult, QueryWorkflow
from cheiron.workflow.errors import UnsupportedQuery
from cheiron.workflow.steps import RunLog

PLAN = {"steps": [{"endpoint": "studies", "label": "Pembrolizumab", "params": {"query.intr": '"pembrolizumab"'}}],
        "rationale": "Pembrolizumab trials."}  # fmt: skip
TWO_DRUGS = {"steps": [{"endpoint": "studies", "label": "Nivolumab", "params": {"query.intr": '"nivolumab"'}},
                       {"endpoint": "studies", "label": "Pembrolizumab", "params": {"query.intr": '"pembrolizumab"'}}],
             "rationale": "Each drug's trials."}  # fmt: skip
BY_PHASE = {"intent": "distribution", "chart_type": "bar_chart", "title": "Pembrolizumab trials by phase", "x": "phase"}
BY_DRUG = {"intent": "magnitude", "chart_type": "grouped_bar_chart", "title": "Phases by drug", "x": "phase", "series": "group"}

DATA = {
    '"pembrolizumab"': FOUND,
    '"nivolumab"': FetchResult(trials=[trial(9, "PHASE3")], total_matched=1),
}


def seen_text(messages) -> str:
    """Everything the model was shown so far (prompt, tool results, retry messages)."""
    return "\n".join(str(getattr(p, "content", "")) for m in messages for p in getattr(m, "parts", []))


def scripted(*steps):
    """A fake model returning the given (tool, args) steps in order; final-result tools by short name."""
    seen = {"instructions": None, "messages": []}
    remaining = list(steps)

    def model(messages, info: AgentInfo):
        seen["instructions"] = info.instructions
        seen["messages"] = list(messages)
        tool, args = remaining.pop(0)
        if tool in ("ChartPlan", "Unanswerable"):
            tool = next(t.name for t in info.output_tools if tool in t.name)
        return ModelResponse(parts=[ToolCallPart(tool, args)])

    return FunctionModel(model), seen


def decide(model, data=DATA, log=None, **request):
    workflow = QueryWorkflow(agent=None, source=FakeSource(data))
    req = QueryRequest(query="test question", **request)

    async def fetch(plan):
        return await workflow.fetch_plan(plan, req)

    return asyncio.run(QueryAgent(model).decide(req, fetch, log if log is not None else RunLog()))


HAPPY = [
    ("fetch_data", {"plan": PLAN}),
    ("describe_data", {}),
    ("load_skill", {"name": "chart-planning"}),
    ("ChartPlan", BY_PHASE),
]


# --- The normal path ------------------------------------------------------------------------------


def test_plan_fetch_describe_load_skill_answer():
    model, seen = scripted(*HAPPY)
    result = decide(model)

    assert result.chart.x.value == "phase"
    assert result.outcome.trials_fetched == 2 and result.profile.trials_fetched == 2
    assert result.skills_loaded == ["ctgov-search", "chart-planning"]
    told = seen_text(seen["messages"])
    assert '"total_matched":2' in told.replace(" ", "")  # fetch_data returned totals only
    assert '"top_values"' in told  # describe_data returned the profile
    assert "# Choosing the chart" in told  # load_skill returned the chart-planning skill
    assert "NCT00000001" not in told  # never records


def test_instructions_hold_the_role_and_the_search_skill():
    model, seen = scripted(*HAPPY)
    decide(model)
    assert "You answer a question about clinical trials with exactly one chart" in seen["instructions"]
    assert "# Planning ClinicalTrials.gov API calls" in seen["instructions"]
    assert "# Choosing the chart" not in seen["instructions"]  # loaded only on demand


# --- Order and budget, enforced by code -----------------------------------------------------------


def test_chart_before_any_fetch_is_sent_back():
    model, seen = scripted(("ChartPlan", BY_PHASE), *HAPPY)
    decide(model)
    assert "before choosing a chart" in seen_text(seen["messages"])


def test_describe_before_fetch_is_sent_back():
    model, seen = scripted(("describe_data", {}), *HAPPY)
    decide(model)
    assert "Nothing has been fetched yet" in seen_text(seen["messages"])


def test_failed_fetch_returns_the_reason_and_allows_one_more():
    bad = {"steps": [{"endpoint": "studies", "label": "Typo", "params": {"query.intr": '"pembrolizmab"'}}], "rationale": "r"}
    model, seen = scripted(("fetch_data", {"plan": bad}), *HAPPY)
    log = RunLog()
    result = decide(model, log=log)
    told = seen_text(seen["messages"])
    assert "Fetch 1 failed: No trials matched" in told and "4 call(s) left" in told
    assert [r.error is not None for r in log.fetches] == [True, False]  # both fetches recorded
    assert result.outcome.plan.steps[0].label == "Pembrolizumab"


def test_fetch_budget_is_enforced():
    fetch = ("fetch_data", {"plan": PLAN})
    model, seen = scripted(*[fetch] * (FETCH_BUDGET + 1), ("describe_data", {}), ("ChartPlan", BY_PHASE))
    log = RunLog()
    decide(model, log=log)
    assert FETCH_BUDGET == 5 and len(log.fetches) == 5
    assert "fetch budget (5) is used up" in seen_text(seen["messages"])


# --- The answer is checked against the data ---------------------------------------------------------


def test_chart_that_does_not_fit_the_data_is_sent_back_with_the_reason():
    model, seen = scripted(
        ("fetch_data", {"plan": PLAN}), ("describe_data", {}), ("ChartPlan", BY_DRUG), ("ChartPlan", BY_PHASE)
    )
    result = decide(model)
    assert "does not fit the fetched data" in seen_text(seen["messages"])
    assert result.chart.chart_type == "bar_chart"


def test_comparison_chart_is_accepted_for_two_sides():
    model, _ = scripted(("fetch_data", {"plan": TWO_DRUGS}), ("describe_data", {}), ("ChartPlan", BY_DRUG))
    result = decide(model)
    assert result.profile.group_sizes == {"Nivolumab": 1, "Pembrolizumab": 2}


def test_unanswerable_becomes_unsupported_query_and_the_log_is_kept():
    model, _ = scripted(("fetch_data", {"plan": PLAN}), ("Unanswerable", {"reason": "Efficacy is not in registry records."}))
    log = RunLog()
    with pytest.raises(UnsupportedQuery, match="Efficacy"):
        decide(model, log=log)
    assert len(log.fetches) == 1 and log.messages and log.seconds > 0  # the caller can still save what happened


# --- Skills and references -----------------------------------------------------------------------


def test_unknown_skill_is_refused_with_the_list():
    model, seen = scripted(("fetch_data", {"plan": PLAN}), ("load_skill", {"name": "charts"}), *HAPPY[1:])
    decide(model)
    assert "Unknown skill 'charts'. Available: chart-planning, ctgov-search" in seen_text(seen["messages"])


def test_references_are_read_on_demand_and_paths_are_restricted():
    model, seen = scripted(
        ("read_reference", {"path": "../../../../etc/passwd"}),
        ("read_reference", {"path": "references/data-structure/protocol.design.md"}),
        *HAPPY,
    )
    result = decide(model)
    assert "Unknown reference '../../../../etc/passwd'" in seen_text(seen["messages"])
    assert result.references_read == ["references/data-structure/protocol.design.md"]


def test_prompt_lists_user_filters():
    prompt = build_prompt(QueryRequest(query="Trials per year", drug_name="Pembrolizumab", trial_phase=["PHASE3"]))
    assert "Question: Trials per year" in prompt
    assert "- drug_name: Pembrolizumab" in prompt and "- trial_phase: ['PHASE3']" in prompt


# --- Model configuration --------------------------------------------------------------------------


def test_missing_settings_fail_with_a_clear_message(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHEIRON_PLANNER_MODEL", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert {e["loc"][0] for e in exc.value.errors()} == {"openai_api_key", "cheiron_planner_model"}


def test_only_openai_models_are_supported(monkeypatch):
    fake = Settings(_env_file=None, openai_api_key="sk-test", cheiron_planner_model="anthropic:claude")
    monkeypatch.setattr(query_agent, "get_settings", lambda: fake)
    with pytest.raises(ValueError, match="use 'openai:<model>'"):
        query_agent.model_from_settings()


def test_openai_model_is_built_from_settings(monkeypatch):
    fake = Settings(_env_file=None, openai_api_key="sk-test", cheiron_planner_model="openai:gpt-5.4")
    monkeypatch.setattr(query_agent, "get_settings", lambda: fake)
    assert query_agent.model_from_settings().model_name == "gpt-5.4"


# --- Trace and metrics ----------------------------------------------------------------------------


def test_trace_and_metrics_record_the_run_without_records():
    from cheiron.workflow.trace import build_trace, run_metrics

    model, _ = scripted(("ChartPlan", BY_PHASE), *HAPPY)  # one answer sent back, then the normal path
    log = RunLog()
    decide(model, log=log)
    trace = build_trace(log.messages, log.fetches)
    metrics = run_metrics(log.messages, log.fetches, log.seconds)

    assert any(e["event"] == "sent_back" and "before choosing a chart" in e["reason"] for e in trace)
    assert next(e for e in trace if e["event"] == "tool_result" and e["tool"] == "fetch_data")["seconds"] is not None
    assert metrics.model_turns == 5 and metrics.sent_back == 1 and metrics.fetches == 1
    assert metrics.tool_calls["fetch_data"] == 1 and metrics.tool_calls["describe_data"] == 1
    assert "NCT00000001" not in str(trace)
