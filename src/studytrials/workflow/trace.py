"""Observability: what one query run did, built from the agent's message history.

    build_trace(messages, fetches, chart_runs)  every model turn and tool call, both agents, in order
                                                -> trace.json
    run_metrics(...)                the summary numbers -> meta.metrics in the response

The trace holds tool arguments (the agent's plans) and short previews of what tools returned
(totals and profiles); never trial records, which the agent never sees either.
"""

import json
from collections import Counter
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart

from studytrials.models.response import RunMetrics
from studytrials.workflow.steps import FetchRecord

PREVIEW_CHARS = 300  # tool results are previewed, not stored whole (the profile is in fetch-N/profile.json)


def _preview(content: Any) -> str:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "…"


def _sent_back(part: Any) -> bool:
    """A rejected tool call or answer: a retry prompt, or (Pydantic AI 2.x) a tool return marked retried."""
    return isinstance(part, RetryPromptPart) or (isinstance(part, ToolReturnPart) and part.outcome != "success")


def build_trace(
    messages: list[ModelMessage], fetches: list[FetchRecord], chart_runs: dict[str, list[ModelMessage]] | None = None
) -> list[dict[str, Any]]:
    """One event per model turn, tool call, tool result and send-back, in the order they happened.
    The chart planner's events follow the plan_chart call that ran them, marked agent=chart_planner."""
    seconds = {f.number: f.seconds for f in fetches}
    events: list[dict[str, Any]] = []
    counter = {"turn": 0, "fetch": 0}
    for event in _events(messages, seconds, counter, "query_agent"):
        events.append(event)
        if event["event"] == "tool_call" and event["tool"] == "plan_chart":  # the planner ran inside this call
            events.extend(_events((chart_runs or {}).get(event["call_id"], []), seconds, counter, "chart_planner"))
    for event in events:
        event.pop("call_id", None)  # only used to place the planner's events
    return events


def _events(messages: list[ModelMessage], seconds: dict, counter: dict, agent: str):
    for message in messages:
        if isinstance(message, ModelResponse):
            counter["turn"] += 1
            yield {
                "event": "model_turn", "agent": agent, "turn": counter["turn"], "at": message.timestamp.isoformat(),
                "input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens,
            }  # fmt: skip
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    yield {"event": "tool_call", "agent": agent, "tool": part.tool_name, "args": part.args_as_dict(), "call_id": part.tool_call_id}
            continue
        for part in message.parts:
            if _sent_back(part):  # code rejected the call or the answer and told the model why
                text = part.model_response() if isinstance(part, RetryPromptPart) else part.content
                yield {"event": "sent_back", "agent": agent, "tool": part.tool_name, "reason": _preview(text)}
            elif isinstance(part, ToolReturnPart):
                event = {"event": "tool_result", "agent": agent, "tool": part.tool_name, "preview": _preview(part.content)}
                if part.tool_name == "fetch_data":
                    counter["fetch"] += 1
                    event["seconds"] = seconds.get(counter["fetch"])
                yield event


def run_metrics(
    messages: list[ModelMessage], fetches: list[FetchRecord], agent_seconds: float, build_seconds: float = 0.0
) -> RunMetrics:
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    calls = Counter(p.tool_name for m in responses for p in m.parts if isinstance(p, ToolCallPart))
    sent_back = sum(_sent_back(p) for m in messages if not isinstance(m, ModelResponse) for p in m.parts)
    fetch_seconds = sum(f.seconds or 0.0 for f in fetches)
    return RunMetrics(
        seconds_total=round(agent_seconds + build_seconds, 2),
        seconds_fetching=round(fetch_seconds, 2),
        seconds_building=round(build_seconds, 2),
        model_turns=len(responses),
        input_tokens=sum(m.usage.input_tokens for m in responses),
        output_tokens=sum(m.usage.output_tokens for m in responses),
        tool_calls=dict(calls),
        sent_back=sent_back,
        fetches=len(fetches),
        failed_fetches=sum(f.error is not None for f in fetches),
    )
