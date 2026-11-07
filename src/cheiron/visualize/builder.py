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
from datetime import date

from cheiron.fetch.models import Trial
from cheiron.models.response import ChartVisualization, Citation, NetworkVisualization
from cheiron.workflow.plans import YEAR_DIMENSIONS, ChartPlan, Dimension
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
    Dimension.COMPLETION_YEAR: "protocolSection.statusModule.completionDateStruct.date",
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
    if dim is Dimension.COMPLETION_YEAR and trial.completion_date:
        return trial.completion_date.isoformat()
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


def _order(
    dim: Dimension, counts: dict[str, list[Trial]], top_n: int | None, window: tuple[int | None, int | None] = (None, None)
) -> tuple[list[str], int]:
    """Category order and how many categories were dropped. Years run continuously over the window."""
    if dim is Dimension.PHASE:
        ordered = [p for p in PHASE_ORDER if p in counts] + sorted(set(counts) - set(PHASE_ORDER))
    elif dim in YEAR_DIMENSIONS:
        years = [int(y) for y in counts]
        lo = window[0] if window[0] is not None else min(years, default=None)
        hi = window[1] if window[1] is not None else max(years, default=None)
        ordered = [str(y) for y in range(lo, hi + 1)] if lo is not None and hi is not None else []
    else:
        ordered = sorted(counts, key=lambda v: (-len(counts[v]), v))
    limit = top_n if top_n is not None else (None if dim is Dimension.PHASE or dim in YEAR_DIMENSIONS else MAX_CATEGORIES)
    if limit is not None and len(ordered) > limit:
        return ordered[:limit], len(ordered) - limit
    return ordered, 0


def _channel(dim: Dimension) -> dict:
    if dim in YEAR_DIMENSIONS:
        title = "Start year" if dim is Dimension.START_YEAR else "Completion year"
        return {"field": dim.value, "type": "temporal", "timeUnit": "utcyear", "title": title}
    if dim is Dimension.PHASE:
        return {"field": "phase", "type": "ordinal", "sort": PHASE_ORDER, "title": "Phase"}
    return {"field": dim.value, "type": "nominal", "title": dim.value.replace("_", " ").capitalize()}


def _row_value(dim: Dimension, value: str) -> str:
    return f"{value}-01-01" if dim in YEAR_DIMENSIONS else value  # ISO date for temporal axes


Y = {"field": "trial_count", "type": "quantitative", "title": "Trials"}


def _year_windows(
    plan: ChartPlan, bounds: dict | None, as_of: date | None
) -> tuple[dict[Dimension, tuple[int | None, int | None]], list[str]]:
    """For each year dimension on the chart: the years to show (the searched period, never past the
    data date) and notes for meta."""
    windows, notes = {}, []
    for dim in (plan.x, plan.series):
        field = YEAR_DIMENSIONS.get(dim) if dim else None
        if not field:
            continue
        lo, hi = (bounds or {}).get(field, (None, None))
        if as_of is not None:
            hi = as_of.year if hi is None else min(hi, as_of.year)
            notes.append(f"{as_of.year} is partial: data as of {as_of.isoformat()}.")
        windows[dim] = (lo, hi)
    return windows, notes


def _within(dim: Dimension, read, window):
    """A reader that keeps only years inside the window."""
    lo, hi = window
    return lambda group, trial: {v for v in read(group, trial) if (lo is None or int(v) >= lo) and (hi is None or int(v) <= hi)}


def build_visualization(
    trials_by_group: dict[str, list[Trial]],
    plan: ChartPlan,
    bounds: dict[str, tuple[int | None, int | None]] | None = None,
    as_of: date | None = None,
) -> tuple[ChartVisualization | NetworkVisualization, list[str]]:
    """Returns the visualization and warnings for meta.

    `bounds` are the year ranges the searches were filtered on (per date field) and `as_of` the
    data date: year axes cover the searched period and stop at the data date, because later dates
    are estimates for trials that have not started or finished yet."""
    pairs: list[Pair] = [(g, t) for g, ts in trials_by_group.items() for t in ts]
    if plan.chart_type == "network_graph":
        return _network(pairs, plan)
    if plan.chart_type == "histogram":
        return _histogram(pairs, plan), []

    windows, year_notes = _year_windows(plan, bounds, as_of)
    future = set()
    for dim, (_, hi) in windows.items():
        read = _reader(dim)
        if hi is not None:
            future |= {t.nct_id for g, t in pairs if read(g, t) and all(int(v) > hi for v in read(g, t))}

    read_x = _reader(plan.x) if plan.x not in windows else _within(plan.x, _reader(plan.x), windows[plan.x])
    if plan.series is None:
        buckets: dict[str, list[Trial]] = defaultdict(list)
        for group, trial in pairs:
            for value in read_x(group, trial):
                buckets[value].append(trial)
        order, dropped = _order(plan.x, buckets, plan.top_n, windows.get(plan.x, (None, None)))
        rows = [
            {
                plan.x.value: _row_value(plan.x, v),
                "trial_count": len(buckets.get(v, [])),
                "citations": _citations([(plan.x, v)], buckets.get(v, [])),
            }
            for v in order
        ]
        ordered_axis = plan.x is Dimension.PHASE or plan.x in YEAR_DIMENSIONS
        encoding = {"x": _channel(plan.x) | ({} if ordered_axis else {"sort": "-y"}), "y": Y}
    else:
        read_s = _reader(plan.series) if plan.series not in windows else _within(plan.series, _reader(plan.series), windows[plan.series])
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
        order, dropped = _order(plan.x, x_totals, plan.top_n, windows.get(plan.x, (None, None)))
        series_order, dropped_series = _order(plan.series, s_totals, None, windows.get(plan.series, (None, None)))
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
    if future:
        warnings.append(
            f"{len(future)} trials with only estimated dates after the data date are left out of the time axis."
        )
    warnings += year_notes
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
