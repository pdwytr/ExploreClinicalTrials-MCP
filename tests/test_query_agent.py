"""The query agent and its chart planner sub-agent, with a scripted fake model (Pydantic AI
FunctionModel): no API key, no cost.

One fake model plays both agents: each test scripts the turns in the order they happen. The query
agent's plan_chart call runs the chart planner, whose turns come next, then the run ends with its
chart (or plan_chart sends the reason back to the query agent)."""

import asyncio

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from test_workflow import FOUND, FakeSource, trial

from trialsight.agents import query_agent
from trialsight.agents.api_docs import ApiDocs
from trialsight.agents.chart_planner import ChartInput, breakdown_problem
from trialsight.agents.chart_planner import build_prompt as chart_prompt
from trialsight.agents.query_agent import FETCH_BUDGET, QueryAgent, build_prompt
from trialsight.models.request import QueryRequest
from trialsight.settings import Settings
from trialsight.workflow import ChartPlan, FetchResult, QueryWorkflow, SearchPlan
from trialsight.workflow.errors import UnsupportedQuery
from trialsight.workflow.steps import RunLog

PLAN = {"steps": [{"endpoint": "studies", "label": "Pembrolizumab", "drugs": ["pembrolizumab"]}],
        "rationale": "Pembrolizumab trials."}  # fmt: skip
TWO_DRUGS = {"steps": [{"endpoint": "studies", "label": "Nivolumab", "drugs": ["nivolumab"]},
                       {"endpoint": "studies", "label": "Pembrolizumab", "drugs": ["pembrolizumab"]}],
             "rationale": "Each drug's trials."}  # fmt: skip
BY_PHASE = {"intent": "distribution", "chart_type": "bar_chart", "title": "Pembrolizumab trials by phase", "x": "phase"}
BY_DRUG = {"intent": "magnitude", "chart_type": "grouped_bar_chart", "title": "Phases by drug", "x": "phase", "series": "group"}

DATA = {
    "pembrolizumab": FOUND,
    "nivolumab": FetchResult(trials=[trial(9, "PHASE3")], total_matched=1),
}

FETCH = ("fetch_data", {"plan": PLAN})
DESCRIBE = ("describe_data", {})
PLAN_CHART = ("plan_chart", {"brief": "Show the phases of the pembrolizumab trials."})
HAPPY = [FETCH, DESCRIBE, PLAN_CHART, ("chart_plan", BY_PHASE)]


def seen_text(messages) -> str:
    """Everything a model was shown (prompt, tool results, retry messages)."""
    return "\n".join(str(getattr(p, "content", "")) for m in messages for p in getattr(m, "parts", []))


def scripted(*steps):
    """A fake model returning the given (tool, args) steps in order, whichever agent asks.
    `seen` keeps every call: which agent (by its instructions), and what it had been shown."""
    seen = {"calls": []}
    remaining = list(steps)

    def model(messages, info: AgentInfo):
        agent = "chart_planner" if "# Choosing the chart" in (info.instructions or "") else "query_agent"
        seen["calls"].append({"agent": agent, "instructions": info.instructions, "messages": list(messages)})
        tool, args = remaining.pop(0)
        return ModelResponse(parts=[ToolCallPart(tool, args)])

    def shown(agent: str) -> str:
        return "\n".join(seen_text(c["messages"]) for c in seen["calls"] if c["agent"] == agent)

    seen["shown"] = shown
    return FunctionModel(model), seen


def decide(model, data=DATA, log=None, docs=None, **request):
    workflow = QueryWorkflow(agent=None, source=FakeSource(data))
    req = QueryRequest(query="test question", **request)

    async def fetch(plan):
        return await workflow.fetch_plan(plan, req)

    return asyncio.run(QueryAgent(model, docs=docs).decide(req, fetch, log if log is not None else RunLog()))


# --- The normal path ------------------------------------------------------------------------------


def test_fetch_describe_then_the_chart_planner_answers():
    model, seen = scripted(*HAPPY)
    log = RunLog()
    result = decide(model, log=log)

    assert result.chart.x.value == "phase"
    assert result.outcome.trials_fetched == 2 and result.profile.trials_fetched == 2
    assert [c["agent"] for c in seen["calls"]] == ["query_agent"] * 3 + ["chart_planner"]
    told = seen["shown"]("query_agent")
    assert '"total_matched":2' in told.replace(" ", "")  # fetch_data returned totals only
    assert '"top_values"' in told  # describe_data returned the profile
    assert "NCT00000001" not in told + seen["shown"]("chart_planner")  # neither agent sees records
    assert len(log.chart_runs) == 1 and all(log.chart_runs.values())


def test_the_chart_planner_is_told_the_question_plan_brief_and_profile_by_code():
    model, seen = scripted(*HAPPY)
    decide(model, drug_name="Pembrolizumab")
    told = seen["shown"]("chart_planner")
    assert "Question: test question" in told and "- drug_name: Pembrolizumab" in told
    assert "Query agent's brief: Show the phases of the pembrolizumab trials." in told
    assert '"label":"Pembrolizumab"' in told.replace(" ", "")  # the search plan
    assert '"top_values"' in told  # the profile, without a describe_data call of its own


def test_each_agent_gets_only_its_own_instructions():
    model, seen = scripted(*HAPPY)
    decide(model)
    query = next(c["instructions"] for c in seen["calls"] if c["agent"] == "query_agent")
    chart = next(c["instructions"] for c in seen["calls"] if c["agent"] == "chart_planner")
    assert "You answer a question about clinical trials with exactly one chart" in query
    assert "# Planning ClinicalTrials.gov searches" in query and "# Choosing the chart" not in query
    assert "# Planning ClinicalTrials.gov searches" not in chart


# --- Order and budget, enforced by code -----------------------------------------------------------


def test_plan_chart_before_any_fetch_is_sent_back():
    model, seen = scripted(PLAN_CHART, *HAPPY)
    decide(model)
    assert "before calling plan_chart" in seen["shown"]("query_agent")


def test_describe_before_fetch_is_sent_back():
    model, seen = scripted(DESCRIBE, *HAPPY)
    decide(model)
    assert "Nothing has been fetched yet" in seen["shown"]("query_agent")


def test_failed_fetch_returns_the_reason_and_allows_one_more():
    bad = {"steps": [{"endpoint": "studies", "label": "Typo", "drugs": ["pembrolizmab"]}], "rationale": "r"}
    model, seen = scripted(("fetch_data", {"plan": bad}), *HAPPY)
    log = RunLog()
    result = decide(model, log=log)
    told = seen["shown"]("query_agent")
    assert "Fetch 1 failed: No trials matched" in told and "4 call(s) left" in told
    assert [r.error is not None for r in log.fetches] == [True, False]  # both fetches recorded
    assert result.outcome.plan.steps[0].label == "Pembrolizumab"


def test_fetch_budget_is_enforced():
    model, seen = scripted(*[FETCH] * (FETCH_BUDGET + 1), DESCRIBE, PLAN_CHART, ("chart_plan", BY_PHASE))
    log = RunLog()
    decide(model, log=log)
    assert FETCH_BUDGET == 5 and len(log.fetches) == 5
    assert "fetch budget (5) is used up" in seen["shown"]("query_agent")


# --- The chart is checked against the data ----------------------------------------------------------


def test_a_chart_that_does_not_fit_goes_back_to_the_chart_planner():
    model, seen = scripted(FETCH, DESCRIBE, PLAN_CHART, ("chart_plan", BY_DRUG), ("chart_plan", BY_PHASE))
    result = decide(model)
    assert "does not fit the fetched data" in seen["shown"]("chart_planner")
    assert "does not fit" not in seen["shown"]("query_agent")  # fixed inside the sub-agent
    assert result.chart.chart_type == "bar_chart"


def test_comparison_chart_is_accepted_for_two_sides():
    model, _ = scripted(("fetch_data", {"plan": TWO_DRUGS}), DESCRIBE, PLAN_CHART, ("chart_plan", BY_DRUG))
    result = decide(model)
    assert result.profile.group_sizes == {"Nivolumab": 1, "Pembrolizumab": 2}


def test_unanswerable_becomes_unsupported_query_and_the_log_is_kept():
    model, _ = scripted(FETCH, ("unanswerable", {"reason": "Efficacy is not in registry records."}))
    log = RunLog()
    with pytest.raises(UnsupportedQuery, match="Efficacy"):
        decide(model, log=log)
    assert len(log.fetches) == 1 and log.messages and log.seconds > 0  # the caller can still save what happened


def test_when_the_chart_planner_cannot_chart_the_query_agent_decides():
    model, seen = scripted(
        FETCH, DESCRIBE, PLAN_CHART,
        ("unanswerable", {"reason": "No field holds trial sites per city."}),  # the chart planner
        ("unanswerable", {"reason": "Cities are not in registry records."}),  # the query agent
    )  # fmt: skip
    with pytest.raises(UnsupportedQuery, match="Cities"):
        decide(model)
    assert "could not chart the latest fetch: No field holds trial sites per city." in seen["shown"]("query_agent")


def test_a_chart_planner_out_of_retries_reports_its_last_problem():
    model, seen = scripted(
        FETCH, DESCRIBE, PLAN_CHART, *[("chart_plan", BY_DRUG)] * 4,  # 1 try + 3 retries, all rejected
        ("unanswerable", {"reason": "Gave up."}),
    )  # fmt: skip
    with pytest.raises(UnsupportedQuery, match="Gave up"):
        decide(model)
    assert "could not chart the latest fetch: This chart does not fit" in seen["shown"]("query_agent")


# --- References -----------------------------------------------------------------------------------


def test_api_docs_are_read_on_demand_from_what_was_loaded():
    docs = ApiDocs(pages={"enums": "LIVE ENUMS PAGE"}, api_version="9.9.9")
    model, seen = scripted(("read_api_docs", {"page": "../etc/passwd"}), ("read_api_docs", {"page": "enums"}), *HAPPY)
    result = decide(model, docs=docs)
    told = seen["shown"]("query_agent")
    assert "Unknown page '../etc/passwd'. Start from: enums" in told
    assert "LIVE ENUMS PAGE" in told and result.docs_read == ["enums"]


def test_the_chart_planner_reads_its_own_references():
    model, seen = scripted(
        FETCH, DESCRIBE, PLAN_CHART,
        ("read_reference", {"page": "nope"}), ("read_reference", {"page": "networks"}), ("chart_plan", BY_PHASE),
    )  # fmt: skip
    result = decide(model)
    assert "Unknown reference 'nope'. Available: chart-types, examples, networks, registry-stats" in seen["shown"]("chart_planner")
    assert result.references_read == ["networks"]


def test_prompt_lists_user_filters():
    prompt = build_prompt(QueryRequest(query="Trials per year", drug_name="Pembrolizumab", trial_phase=["PHASE3"]))
    assert "Question: Trials per year" in prompt
    assert "- drug_name: Pembrolizumab" in prompt and "- trial_phase: ['PHASE3']" in prompt


# --- Model configuration --------------------------------------------------------------------------


def test_missing_settings_fail_with_a_clear_message(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TRIALSIGHT_PLANNER_MODEL", raising=False)
    monkeypatch.delenv("CHEIRON_PLANNER_MODEL", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert {e["loc"][0] for e in exc.value.errors()} == {"openai_api_key", "TRIALSIGHT_PLANNER_MODEL"}


def test_only_openai_models_are_supported(monkeypatch):
    fake = Settings(_env_file=None, openai_api_key="sk-test", trialsight_planner_model="anthropic:claude")
    monkeypatch.setattr(query_agent, "get_settings", lambda: fake)
    with pytest.raises(ValueError, match="use 'openai:<model>'"):
        query_agent.model_from_settings()


def test_openai_model_is_built_from_settings(monkeypatch):
    fake = Settings(_env_file=None, openai_api_key="sk-test", trialsight_planner_model="openai:gpt-5.4")
    monkeypatch.setattr(query_agent, "get_settings", lambda: fake)
    assert query_agent.model_from_settings().model_name == "gpt-5.4"


# --- Trace and metrics ----------------------------------------------------------------------------


def test_trace_and_metrics_cover_both_agents_without_records():
    from trialsight.workflow.trace import build_trace, run_metrics

    model, _ = scripted(PLAN_CHART, FETCH, DESCRIBE, PLAN_CHART, ("chart_plan", BY_DRUG), ("chart_plan", BY_PHASE))
    log = RunLog()
    decide(model, log=log)
    trace = build_trace(log.messages, log.fetches, log.chart_runs)
    metrics = run_metrics(log.all_messages, log.fetches, log.seconds)

    assert any(e["event"] == "sent_back" and "before calling plan_chart" in e["reason"] for e in trace)
    assert next(e for e in trace if e["event"] == "tool_result" and e["tool"] == "fetch_data")["seconds"] is not None
    agents = [e["agent"] for e in trace if e["event"] == "model_turn"]
    assert agents == ["query_agent"] * 4 + ["chart_planner"] * 2  # the planner's turns follow its plan_chart call
    assert metrics.model_turns == 6 and metrics.sent_back == 2 and metrics.fetches == 1
    assert metrics.tool_calls["fetch_data"] == 1 and metrics.tool_calls["chart_plan"] == 2
    assert "NCT00000001" not in str(trace)


# --- The breakdown the plan states ----------------------------------------------------------------

BY_STATE = {**PLAN, "breakdown": "unsupported: US state"}
BY_COUNTRY_PLAN = {**PLAN, "breakdown": "country"}


def test_an_unsupported_breakdown_must_be_refused_not_swapped_for_another_field():
    # r05: asked "by state", answered with a country chart
    model, seen = scripted(
        ("fetch_data", {"plan": BY_STATE}), DESCRIBE, PLAN_CHART,
        ("chart_plan", BY_PHASE),  # the chart planner tries another field
        ("unanswerable", {"reason": "US state is not available."}),  # and is told to refuse
        ("unanswerable", {"reason": "US state is not available in the fetched data."}),
    )  # fmt: skip
    with pytest.raises(UnsupportedQuery, match="US state"):
        decide(model)
    assert "Answer unanswerable" in seen["shown"]("chart_planner")


def test_the_chart_must_show_the_stated_breakdown_or_the_plan_is_fixed():
    model, seen = scripted(
        ("fetch_data", {"plan": BY_COUNTRY_PLAN}), DESCRIBE, PLAN_CHART,
        ("chart_plan", BY_PHASE),  # charts phase although the plan said country
        ("unanswerable", {"reason": "The plan's breakdown (country) does not match the question (phase)."}),
        ("fetch_data", {"plan": {**PLAN, "breakdown": "phase"}}),  # the query agent corrects its plan
        DESCRIBE, PLAN_CHART, ("chart_plan", BY_PHASE),
    )  # fmt: skip
    result = decide(model)
    assert "asks for a breakdown by country, but the chart shows ['phase']" in seen["shown"]("chart_planner")
    assert "corrected breakdown" in seen["shown"]("query_agent")
    assert result.chart.x.value == "phase" and result.outcome.plan.breakdown == "phase"


def test_a_network_breakdown_names_both_node_kinds():
    plan = SearchPlan.model_validate({**PLAN, "breakdown": "lead_sponsor x intervention"})
    network = ChartPlan(intent="relationship", chart_type="network_graph", title="t", x="lead_sponsor", series="intervention")
    assert breakdown_problem(plan, network) is None
    assert "not a chartable field" in breakdown_problem(SearchPlan.model_validate({**PLAN, "breakdown": "site x sponsor"}), network)


def test_chart_prompt_says_when_there_are_no_filters_or_brief():
    from trialsight.workflow.profile import build_profile

    profile = build_profile({"Pembrolizumab": FOUND.trials}, 2)
    prompt = chart_prompt(ChartInput(QueryRequest(query="Any question"), SearchPlan.model_validate(PLAN), profile, " "))
    assert "User-supplied filters: none" in prompt and "Query agent's brief: (none)" in prompt
