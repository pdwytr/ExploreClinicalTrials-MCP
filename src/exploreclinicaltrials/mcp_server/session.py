"""The query agent's work without the agent: the same steps, driven by whoever calls the tools.

In the web service a Pydantic AI agent plans, fetches, profiles and picks the chart
(agents/query_agent.py). Inside an MCP client, its model does the planning and the chart choice, and these
functions do everything code does there: execute a search plan, profile the data, check a chart
plan against it, and build the response with citations. A number never comes from the model.

    Queries.start(request)                 -> query id
    Queries.fetch(query_id, plan)          -> what was fetched (counts, warnings)
    Queries.describe(query_id)             -> profile of the latest successful fetch
    Queries.build(query_id, chart)         -> QueryResponse, saved to the ResultStore

State lives in memory for the life of the process (one client session); answers are saved to disk.
"""

import dataclasses
import secrets
import time
from dataclasses import dataclass, field

from exploreclinicaltrials.agents.chart_planner import breakdown_problem
from exploreclinicaltrials.models.request import QueryRequest
from exploreclinicaltrials.models.response import QueryResponse
from exploreclinicaltrials.workflow.errors import InvalidSearch, NoResults, UnsupportedQuery
from exploreclinicaltrials.workflow.pipeline import FetchOutcome, QueryWorkflow, check_chart_plan
from exploreclinicaltrials.workflow.plans import ChartPlan, DataProfile, SearchPlan, StatsResult
from exploreclinicaltrials.workflow.profile import build_profile
from exploreclinicaltrials.workflow.steps import AgentResult, FetchRecord, RunLog
from exploreclinicaltrials.workflow.translate import year_bounds

FETCH_BUDGET = 5  # as for the query agent: each question gets at most 5 fetches
MAX_QUERIES = 50  # oldest questions are forgotten past this (their saved answers stay on disk)
QUERY_TTL_SECONDS = 2 * 60 * 60  # a query_id expires 2 hours after start_query (MCP: handles have a bounded lifetime)


class QueryError(Exception):
    """A problem the caller can fix (unknown id, nothing fetched yet, a chart that does not fit)."""


@dataclass
class QuerySession:
    id: str
    request: QueryRequest
    fetches: list[FetchRecord] = field(default_factory=list)
    outcome: FetchOutcome | None = None  # the latest successful fetch: what gets charted
    profile: DataProfile | None = None
    started: float = field(default_factory=time.perf_counter)
    created: float = field(default_factory=lambda: time.monotonic())

    def expired(self, now: float) -> bool:
        return now - self.created > QUERY_TTL_SECONDS


@dataclass
class _ChosenChart:
    """A QueryPlanner whose decision was already made (by the client's model, through the tools), so the
    workflow can assemble the response exactly as it does for the web service's agent."""

    result: AgentResult
    fetches: list[FetchRecord]
    seconds: float

    async def decide(self, request, fetch, log: RunLog) -> AgentResult:
        log.fetches, log.seconds = list(self.fetches), self.seconds
        return self.result


class Queries:
    def __init__(self, workflow: QueryWorkflow):
        self.workflow = workflow
        self._sessions: dict[str, QuerySession] = {}

    def start(self, request: QueryRequest) -> QuerySession:
        now = time.monotonic()
        for query_id in [q for q, s in self._sessions.items() if s.expired(now)]:
            del self._sessions[query_id]
        while len(self._sessions) >= MAX_QUERIES:
            self._sessions.pop(next(iter(self._sessions)))
        # An opaque handle with 128 random bits, as MCP asks of server-minted handles.
        session = QuerySession(id=f"q-{secrets.token_hex(16)}", request=request)
        self._sessions[session.id] = session
        return session

    def get(self, query_id: str) -> QuerySession:
        session = self._sessions.get(query_id)
        if session is None:
            raise QueryError(f"Unknown or expired query_id {query_id!r}. Call start_query again.")
        if session.expired(time.monotonic()):
            del self._sessions[query_id]
            raise QueryError(f"query_id {query_id!r} has expired (after 2 hours). Call start_query again.")
        return session

    async def fetch(self, query_id: str, plan: SearchPlan) -> dict:
        session = self.get(query_id)
        if len(session.fetches) >= FETCH_BUDGET:
            raise QueryError(f"The fetch budget ({FETCH_BUDGET}) is used up. Call describe_data and decide.")
        record = FetchRecord(number=len(session.fetches) + 1, plan=plan)
        session.fetches.append(record)
        left = FETCH_BUDGET - len(session.fetches)
        started = time.perf_counter()
        try:
            outcome = await self.workflow.fetch_plan(plan, session.request)
        except (InvalidSearch, NoResults) as exc:
            record.error, record.seconds = exc.message, time.perf_counter() - started
            return {
                "fetch": record.number,
                "status": "failed",
                "error": exc.message,
                "next": f"fix the plan and call fetch_data again ({left} call(s) left)",
            }
        record.seconds = time.perf_counter() - started
        stats = [(label, r) for (label, _), r in zip(outcome.prepared, outcome.results) if isinstance(r, StatsResult)]
        profile = build_profile(outcome.trials_by_group, outcome.total_matched, stats, outcome.version.data_timestamp)
        record.outcome, record.profile = outcome, profile
        session.outcome, session.profile = outcome, profile
        return {
            "fetch": record.number,
            "status": "ok",
            "fetched": [
                {"label": label, "endpoint": getattr(r, "endpoint", "studies"), "total_matched": getattr(r, "total_matched", None)}
                for (label, _), r in zip(outcome.prepared, outcome.results)
            ],
            "searched": outcome.descriptions,
            "notes": outcome.notes,
            "warnings": outcome.warnings,
            "fetches_left": left,
            "next": "call describe_data",
        }

    def describe(self, query_id: str) -> DataProfile:
        session = self.get(query_id)
        if session.profile is None:
            raise QueryError("Nothing has been fetched yet for this query: call fetch_data first.")
        return session.profile

    async def build(self, query_id: str, chart: ChartPlan) -> QueryResponse:
        """Check the chart against the latest fetch (as the chart planner's validator does), then
        have code count, cite and assemble the response."""
        session = self.get(query_id)
        if session.outcome is None or session.profile is None:
            raise QueryError("Fetch the data (fetch_data) and look at it (describe_data) before build_chart.")
        plan = session.outcome.plan
        problem = breakdown_problem(plan, chart)
        if problem:
            raise QueryError(problem)
        try:
            warnings = check_chart_plan(chart, plan, session.profile, year_bounds(plan, session.request))
        except UnsupportedQuery as exc:
            raise QueryError(f"This chart does not fit the fetched data: {exc.message}") from exc
        decided = AgentResult(
            chart=chart,
            outcome=session.outcome,
            profile=session.profile,
            chart_warnings=warnings,
            docs_read=[],
            references_read=[],
        )
        agent = _ChosenChart(decided, session.fetches, time.perf_counter() - session.started)
        response, _ = await dataclasses.replace(self.workflow, agent=agent).run(session.request)
        return response
