"""Deterministic visualizer: fetched trials + ChartPlan -> visualization with citations.

No AI here: every number is a count of distinct trials computed from the stored records,
and every datum cites the trials behind it (NCT ID, exact field path, exact value).

Counting rules:
  - a trial counts once per distinct value of a field; fields that hold several values per
    trial (phases, conditions, interventions, countries) can therefore sum to more than the
    number of trials, which the caller reports in meta
  - phases keep clinical order, years run ascending with empty years shown as 0, other
    categories are sorted by count; more than MAX_CATEGORIES are cut to the top ones
  - enrollment is binned into fixed edges for histograms
  - networks link values of two fields (or one field with itself = co-occurrence);
    edge weight = trials sharing both values
"""

from collections import defaultdict
from collections.abc import Callable

from cheiron.fetch.models import Trial
from cheiron.models.response import ChartVisualization, Citation, NetworkVisualization
from cheiron.workflow.plans import ChartPlan, Dimension
from cheiron.workflow.profile import FIELD_VALUES

MAX_CATEGORIES = 25
MAX_NODES = 40
MAX_EDGES = 150
CITATIONS_PER_DATUM = 5
PHASE_ORDER = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"]
ENROLLMENT_EDGES = [0, 50, 100, 250, 500, 1000, 2500, 5000, 10000]

# Where each value comes from in the API record, for citations.
FIELD_PATHS = {
    Dimension.PHASE: "protocolSection.designModule.phases",
    Dimension.START_YEAR: "protocolSection.statusModule.startDateStruct.date",
    Dimension.STATUS: "protocolSection.statusModule.overallStatus",
    Dimension.SPONSOR: "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    Dimension.SPONSOR_CLASS: "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    Dimension.CONDITION: "protocolSection.conditionsModule.conditions",
    Dimension.INTERVENTION: "protocolSection.armsInterventionsModule.interventions.name",
    Dimension.INTERVENTION_TYPE: "protocolSection.armsInterventionsModule.interventions.type",
    Dimension.COUNTRY: "protocolSection.contactsLocationsModule.locations.country",
    Dimension.ENROLLMENT: "protocolSection.designModule.enrollmentInfo.count",
}

Pair = tuple[str, Trial]  # (comparison side label, trial)


def _reader(dim: Dimension) -> Callable[[str, Trial], set[str]]:
    if dim is Dimension.GROUP:
        return lambda group, trial: {group}
    read = FIELD_VALUES[dim]
    return lambda group, trial: set(read(trial))


def _excerpt(dim: Dimension, value: str, trial: Trial) -> str:
    if dim is Dimension.START_YEAR and trial.start_date:
        return trial.start_date.isoformat()  # the exact date the year came from
    return value


def _citations(dims: list[tuple[Dimension, str]], trials: list[Trial]) -> list[Citation]:
    """The first few trials (by NCT ID) with the exact value of each field that placed them here."""
    cited = []
    for trial in sorted(trials, key=lambda t: t.nct_id)[:CITATIONS_PER_DATUM]:
        for dim, value in dims:
            if dim is Dimension.GROUP:
                continue
            cited.append(Citation(nct_id=trial.nct_id, excerpt=_excerpt(dim, value, trial), field=FIELD_PATHS[dim]))
    return cited


def _order(dim: Dimension, counts: dict[str, list[Trial]], top_n: int | None) -> tuple[list[str], int]:
    """Category order and how many categories were dropped."""
    if dim is Dimension.PHASE:
        ordered = [p for p in PHASE_ORDER if p in counts] + sorted(set(counts) - set(PHASE_ORDER))
    elif dim is Dimension.START_YEAR:
        years = [int(y) for y in counts]
        ordered = [str(y) for y in range(min(years), max(years) + 1)] if years else []
    else:
        ordered = sorted(counts, key=lambda v: (-len(counts[v]), v))
    limit = top_n if top_n is not None else (None if dim in (Dimension.PHASE, Dimension.START_YEAR) else MAX_CATEGORIES)
    if limit is not None and len(ordered) > limit:
        return ordered[:limit], len(ordered) - limit
    return ordered, 0


def _channel(dim: Dimension) -> dict:
    if dim is Dimension.START_YEAR:
        return {"field": "start_year", "type": "temporal", "timeUnit": "utcyear", "title": "Start year"}
    if dim is Dimension.PHASE:
        return {"field": "phase", "type": "ordinal", "sort": PHASE_ORDER, "title": "Phase"}
    return {"field": dim.value, "type": "nominal", "title": dim.value.replace("_", " ").capitalize()}


def _row_value(dim: Dimension, value: str) -> str:
    return f"{value}-01-01" if dim is Dimension.START_YEAR else value  # ISO date for temporal axes


Y = {"field": "trial_count", "type": "quantitative", "title": "Trials"}


def build_visualization(
    trials_by_group: dict[str, list[Trial]], plan: ChartPlan
) -> tuple[ChartVisualization | NetworkVisualization, list[str]]:
    """Returns the visualization and warnings for meta."""
    pairs: list[Pair] = [(g, t) for g, ts in trials_by_group.items() for t in ts]
    if plan.chart_type == "network_graph":
        return _network(pairs, plan)
    if plan.chart_type == "histogram":
        return _histogram(pairs, plan), []

    read_x = _reader(plan.x)
    if plan.series is None:
        buckets: dict[str, list[Trial]] = defaultdict(list)
        for group, trial in pairs:
            for value in read_x(group, trial):
                buckets[value].append(trial)
        order, dropped = _order(plan.x, buckets, plan.top_n)
        rows = [
            {
                plan.x.value: _row_value(plan.x, v),
                "trial_count": len(buckets.get(v, [])),
                "citations": _citations([(plan.x, v)], buckets.get(v, [])),
            }
            for v in order
        ]
        encoding = {"x": _channel(plan.x) | ({"sort": "-y"} if plan.x not in (Dimension.PHASE, Dimension.START_YEAR) else {}), "y": Y}
    else:
        read_s = _reader(plan.series)
        cells: dict[tuple[str, str], list[Trial]] = defaultdict(list)
        x_totals: dict[str, list[Trial]] = defaultdict(list)
        s_totals: dict[str, list[Trial]] = defaultdict(list)
        for group, trial in pairs:
            xs, ss = read_x(group, trial), read_s(group, trial)
            for x in xs:
                x_totals[x].append(trial)
                for s in ss:
                    cells[(x, s)].append(trial)
            for s in ss:
                s_totals[s].append(trial)
        order, dropped = _order(plan.x, x_totals, plan.top_n)
        series_order, dropped_series = _order(plan.series, s_totals, None)
        dropped += dropped_series
        rows = [
            {
                plan.x.value: _row_value(plan.x, x),
                plan.series.value: s,
                "trial_count": len(cells.get((x, s), [])),
                "citations": _citations([(plan.x, x), (plan.series, s)], cells.get((x, s), [])),
            }
            for x in order
            for s in series_order
        ]
        series_channel = _channel(plan.series)
        encoding = {"x": _channel(plan.x), "y": Y, "color": series_channel}
        if plan.chart_type == "grouped_bar_chart":
            encoding["xOffset"] = series_channel

    warnings = [f"Showing the top {len(order)} values of {plan.x.value}; {dropped} smaller categories are left out."] if dropped else []
    viz = ChartVisualization(type=plan.chart_type, intent=plan.intent, title=plan.title, encoding=encoding, data=rows)
    return viz, warnings


def _histogram(pairs: list[Pair], plan: ChartPlan) -> ChartVisualization:
    values = [(t.enrollment, t) for _, t in pairs if t.enrollment is not None]
    top = max((v for v, _ in values), default=0)
    edges = [e for e in ENROLLMENT_EDGES if e <= top] + [max(top + 1, ENROLLMENT_EDGES[0] + 1)]
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        trials = [t for v, t in values if lo <= v < hi]
        rows.append(
            {
                "enrollment_from": lo,
                "enrollment_to": hi,
                "trial_count": len(trials),
                "citations": [
                    Citation(nct_id=t.nct_id, excerpt=str(t.enrollment), field=FIELD_PATHS[Dimension.ENROLLMENT])
                    for t in sorted(trials, key=lambda t: t.nct_id)[:CITATIONS_PER_DATUM]
                ],
            }
        )
    encoding = {
        "x": {"field": "enrollment_from", "type": "quantitative", "bin": "binned", "title": "Enrollment (participants)"},
        "x2": {"field": "enrollment_to"},
        "y": Y,
    }
    return ChartVisualization(type="histogram", intent=plan.intent, title=plan.title, encoding=encoding, data=rows)


def _network(pairs: list[Pair], plan: ChartPlan) -> tuple[NetworkVisualization, list[str]]:
    assert plan.series is not None
    read_a, read_b = _reader(plan.x), _reader(plan.series)
    same_kind = plan.x == plan.series
    node_trials: dict[tuple[Dimension, str], list[Trial]] = defaultdict(list)
    edge_trials: dict[tuple[tuple[Dimension, str], tuple[Dimension, str]], list[Trial]] = defaultdict(list)
    for group, trial in pairs:
        a_vals, b_vals = sorted(read_a(group, trial)), sorted(read_b(group, trial))
        for a in a_vals:
            node_trials[(plan.x, a)].append(trial)
        if not same_kind:
            for b in b_vals:
                node_trials[(plan.series, b)].append(trial)
        if same_kind:  # co-occurrence: every pair of distinct values within one trial
            links = [((plan.x, a), (plan.x, b)) for i, a in enumerate(a_vals) for b in a_vals[i + 1 :]]
        else:
            links = [((plan.x, a), (plan.series, b)) for a in a_vals for b in b_vals]
        for link in links:
            edge_trials[link].append(trial)

    ranked = sorted(node_trials, key=lambda n: (-len(node_trials[n]), n[1]))
    kept = set(ranked[:MAX_NODES]) if same_kind else set(
        [n for n in ranked if n[0] == plan.x][: MAX_NODES // 2] + [n for n in ranked if n[0] == plan.series][: MAX_NODES // 2]
    )
    edges = sorted(
        ((link, ts) for link, ts in edge_trials.items() if link[0] in kept and link[1] in kept),
        key=lambda e: -len(e[1]),
    )[:MAX_EDGES]

    def node_id(node: tuple[Dimension, str]) -> str:
        return f"{node[0].value}:{node[1]}"

    nodes = [
        {"id": node_id(n), "label": n[1], "group": n[0].value, "size": len(node_trials[n]),
         "citations": _citations([n], node_trials[n])}
        for n in sorted(kept, key=lambda n: (-len(node_trials[n]), n[1]))
    ]  # fmt: skip
    links = [
        {"source": node_id(a), "target": node_id(b), "weight": len(ts), "citations": _citations([a, b], ts)}
        for (a, b), ts in edges
    ]
    warnings = []
    if len(node_trials) > len(kept):
        warnings.append(f"Network shows the {len(kept)} most frequent of {len(node_trials)} values.")
    viz = NetworkVisualization(type="network_graph", title=plan.title, data={"nodes": nodes, "edges": links})
    return viz, warnings
