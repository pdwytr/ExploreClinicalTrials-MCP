"""SearchPlannerAgent with a scripted fake model (Pydantic AI FunctionModel): no API key, no cost."""

import asyncio

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cheiron.agents import search_planner
from cheiron.agents.search_planner import SearchPlannerAgent, build_prompt
from cheiron.models.request import QueryRequest
from cheiron.settings import Settings
from cheiron.workflow.errors import UnsupportedQuery

PLAN = {"plan": {"searches": [{"label": "Asthma", "params": {"query.cond": '"asthma"'}}], "rationale": "Asthma trials."}}


def output_tool(info: AgentInfo, kind: str) -> str:
    return next(t.name for t in info.output_tools if kind in t.name)


def scripted(*steps):
    """A fake model that returns the given steps in order; each step is (tool, args) or a callable(info)."""
    seen = {"instructions": None, "prompts": []}
    remaining = list(steps)

    def model(messages, info: AgentInfo):
        seen["instructions"] = info.instructions
        seen["prompts"].append(messages)
        tool, args = remaining.pop(0)
        name = output_tool(info, tool) if tool in ("SearchDecision", "Unanswerable") else tool
        return ModelResponse(parts=[ToolCallPart(name, args)])

    return FunctionModel(model), seen


def seen_text(messages) -> str:
    """Everything the model was shown in a conversation (prompt, tool results, retry messages)."""
    return "\n".join(str(getattr(p, "content", "")) for m in messages for p in getattr(m, "parts", []))


def run(agent, **request):
    return asyncio.run(agent.plan(QueryRequest(query="test question", **request)))


def test_skill_is_loaded_into_the_instructions():
    model, seen = scripted(("SearchDecision", PLAN))
    run(SearchPlannerAgent(model))
    assert "You are the search planner" in seen["instructions"]
    assert "# Planning ClinicalTrials.gov searches" in seen["instructions"]  # SKILL.md body
    assert "name: ctgov-search" not in seen["instructions"]  # frontmatter stripped


def test_returns_a_validated_plan():
    model, _ = scripted(("SearchDecision", PLAN))
    plan = run(SearchPlannerAgent(model))
    assert plan.searches[0].params == {"query.cond": '"asthma"'}


def decide(agent, query="test question"):
    return asyncio.run(agent.decide(QueryRequest(query=query)))


def test_reference_is_read_on_demand_through_the_tool():
    model, seen = scripted(("read_reference", {"path": "references/enums.md"}), ("SearchDecision", PLAN))
    result = decide(SearchPlannerAgent(model))
    assert result.references_read == ["references/enums.md"]
    assert "AgencyClass" in seen_text(seen["prompts"][-1])  # the file's text reached the model
    assert result.usage.requests == 2  # tool call + final answer


def test_unknown_reference_is_refused_with_the_list_of_files():
    model, seen = scripted(
        ("read_reference", {"path": "../../../../etc/passwd"}),
        ("read_reference", {"path": "references/fields.md"}),
        ("SearchDecision", PLAN),
    )
    result = decide(SearchPlannerAgent(model))
    told = seen_text(seen["prompts"][-1])
    assert "Unknown reference '../../../../etc/passwd'" in told and "references/fields.md" in told
    assert result.references_read == ["references/fields.md"]  # only the valid file was read


def test_concurrent_runs_keep_separate_state():
    def model(messages, info: AgentInfo):
        question = seen_text(messages[:1])
        if not any(isinstance(p, ToolCallPart) for m in messages for p in getattr(m, "parts", [])):
            ref = "references/enums.md" if "A?" in question else "references/fields.md"
            return ModelResponse(parts=[ToolCallPart("read_reference", {"path": ref})])
        return ModelResponse(parts=[ToolCallPart(output_tool(info, "SearchDecision"), PLAN)])

    agent = SearchPlannerAgent(FunctionModel(model))

    async def both():
        return await asyncio.gather(
            agent.decide(QueryRequest(query="Question A?")), agent.decide(QueryRequest(query="Question B?"))
        )

    a, b = asyncio.run(both())
    assert a.references_read == ["references/enums.md"] and b.references_read == ["references/fields.md"]


def test_invalid_plan_is_sent_back_and_fixed():
    bad = {"plan": {"searches": [{"label": "x", "params": {"pageSize": "10"}}], "rationale": "r"}}
    model, seen = scripted(("SearchDecision", bad), ("SearchDecision", PLAN))
    plan = run(SearchPlannerAgent(model))
    assert plan.searches[0].label == "Asthma"
    assert "unknown or reserved" in seen_text(seen["prompts"][-1])  # our Pydantic error reached the model


def test_unanswerable_becomes_unsupported_query():
    model, _ = scripted(("Unanswerable", {"reason": "Efficacy is not in registry records."}))
    with pytest.raises(UnsupportedQuery, match="Efficacy"):
        run(SearchPlannerAgent(model))


def test_prompt_lists_user_filters_and_feedback():
    request = QueryRequest(query="Trials per year", drug_name="Pembrolizumab", trial_phase=["PHASE3"])
    prompt = build_prompt(request, ["No trials matched these searches: [...]"])
    assert "Question: Trials per year" in prompt
    assert "- drug_name: Pembrolizumab" in prompt and "- trial_phase: ['PHASE3']" in prompt
    assert "Your previous plan failed. Fix exactly this:" in prompt


def test_missing_settings_fail_with_a_clear_message(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHEIRON_PLANNER_MODEL", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)  # ignore any real .env
    missing = {e["loc"][0] for e in exc.value.errors()}
    assert missing == {"openai_api_key", "cheiron_planner_model"}


def test_only_openai_models_are_supported(monkeypatch):
    fake = Settings(_env_file=None, openai_api_key="sk-test", cheiron_planner_model="anthropic:claude")
    monkeypatch.setattr(search_planner, "get_settings", lambda: fake)
    with pytest.raises(ValueError, match="use 'openai:<model>'"):
        search_planner.model_from_settings()


def test_openai_model_is_built_from_settings(monkeypatch):
    fake = Settings(_env_file=None, openai_api_key="sk-test", cheiron_planner_model="openai:gpt-5.4")
    monkeypatch.setattr(search_planner, "get_settings", lambda: fake)
    assert search_planner.model_from_settings().model_name == "gpt-5.4"
