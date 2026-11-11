"""Deterministic visualizer: fetched trials + ChartPlan -> visualization with citations.

No AI here: every number is a count of distinct trials computed from the stored records,
and every datum cites the trials behind it (NCT ID, exact field path, exact value).

Counting rules:
  - a trial counts once per distinct value of a field; fields that hold several values per
    trial (phases, conditions, interventions, countries) can therefore sum to more than the
    number of trials, which the caller reports in meta
  - phases keep clinical order, years run ascending with empty years shown as 0, other
    categories are sorted by count; more than MAX_CATEGORIES are cut to the top ones
  - values that differ only by case, hyphens, punctuation or spacing ("Rituximab", "rituximab ",
    "Non-small Cell Lung Cancer", "Non Small Cell Lung Cancer") are one category,
    shown with the spelling most trials use; citations still quote each trial's own spelling
  - enrollment is binned into fixed edges for histograms; the edges grow geometrically, so bins
    are drawn as ordered range labels of equal width ("50–99", "10,000+"), not on a linear axis
    where the open top bin (10,000 .. largest trial) would fill the chart
  - networks link values of two fields (or one field with itself = co-occurrence);
    edge weight = trials sharing both values
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable
from datetime import date

from trialsight.fetch.models import Trial
from trialsight.models.response import ChartVisualization, Citation, NetworkVisualization
from trialsight.visualize.labels import labels_for
from trialsight.workflow.plans import YEAR_DIMENSIONS, ChartPlan, Dimension
from trialsight.workflow.profile import FIELD_VALUES, merged_reader, stats_fields, value_key

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
    Dimension.STUDY_TYPE: "protocolSection.designModule.studyType",
    Dimension.ALLOCATION: "protocolSection.designModule.designInfo.allocation",
    Dimension.MASKING: "protocolSection.designModule.designInfo.maskingInfo.masking",
    Dimension.PRIMARY_PURPOSE: "protocolSection.designModule.designInfo.primaryPurpose",
}

Pair = tuple[str, Trial]  # (comparison side label, trial)


def _reader(dim: Dimension, pairs: list[Pair]) -> Callable[[str, Trial], set[str]]:
    """Reads a field's distinct values per trial, merged by value_key (see profile.merged_reader)."""
    if dim is Dimension.GROUP:
        return lambda group, trial: {group}
    read = merged_reader(FIELD_VALUES[dim], (t for _, t in pairs))
    return lambda group, trial: read(trial)


def _excerpt(dim: Dimension, value: str, trial: Trial) -> str:
    # the date the year came from, as the registry wrote it ("2018-03", not the padded 2018-03-01)
    if dim is Dimension.START_YEAR and trial.start_date:
        return trial.start_date_text or trial.start_date.isoformat()
    if dim is Dimension.COMPLETION_YEAR and trial.completion_date:
        return trial.completion_date_text or trial.completion_date.isoformat()
    # the trial's own spelling of the (possibly merged) value
    return next((v for v in FIELD_VALUES[dim](trial) if value_key(v) == value_key(value)), value)


def _citations(dims: list[tuple[Dimension, str]], trials: list[Trial]) -> list[Citation]:
    """The first few trials (by NCT ID) with the exact value of each field that placed them here."""
    cited = []
    for trial in sorted(trials, key=lambda t: t.nct_id)[:CITATIONS_PER_DATUM]:
        for dim, value in dims:
            if dim is Dimension.GROUP:
                continue
            cited.append(
                Citation(nct_id=trial.nct_id, excerpt=_excerpt(dim, value, trial), field=FIELD_PATHS[dim], title=trial.title)
            )
    return cited


def _ids(trials: list[Trial]) -> list[str]:
    """Every trial behind a data point: the complete reference list (citations sample it)."""
    return sorted({t.nct_id for t in trials})


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


def build_visualization(
    trials_by_group: dict[str, list[Trial]],
    plan: ChartPlan,
    bounds: dict[str, tuple[int | None, int | None]] | None = None,
    as_of: date | None = None,
    stats: list | None = None,
) -> tuple[ChartVisualization | NetworkVisualization, list[str]]:
    """Trials + chart plan -> visualization with citations, and display names for coded values."""
    viz, warnings = _build(trials_by_group, plan, bounds, as_of, stats)
    return _with_labels(viz), warnings


def _with_labels(viz: ChartVisualization | NetworkVisualization) -> ChartVisualization | NetworkVisualization:
    """Attach display names: per coded channel for charts, per node group for networks."""
    if isinstance(viz, NetworkVisualization):
        groups = {n.group for n in viz.data.nodes if n.group}
        names = {g: g.replace("_", " ").capitalize() for g in sorted(groups)}
        return viz.model_copy(update={"encoding": viz.encoding.model_copy(update={"group_labels": names or None})})
    enc = viz.encoding
    updates = {}
    for name in ("x", "color", "x_offset"):
        channel = getattr(enc, name)
        if channel is None:
            continue
        shown = {str((row.model_extra or {}).get(channel.field)) for row in viz.data}
        labels = labels_for(channel.field, shown)
        if labels:
            updates[name] = channel.model_copy(update={"labels": labels})
    return viz.model_copy(update={"encoding": enc.model_copy(update=updates)}) if updates else viz


def _row_value(dim: Dimension, value: str) -> str:
    return f"{value}-01-01" if dim in YEAR_DIMENSIONS else value  # ISO date for temporal axes


Y = {"field": "trial_count", "type": "quantitative", "title": "Trials"}
Y_SHARE = {"field": "percent", "type": "quantitative", "title": "% of trials"}


def _add_shares(rows: list[dict], denominator: Callable[[dict], int]) -> None:
    """percent = trial_count / denominator, with the denominator kept on the row (of_trials)."""
    for row in rows:
        total = denominator(row)
        row["of_trials"] = total
        row["percent"] = round(100 * row["trial_count"] / total, 1) if total else 0.0


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


def _build(
    trials_by_group: dict[str, list[Trial]],
    plan: ChartPlan,
    bounds: dict[str, tuple[int | None, int | None]] | None = None,
    as_of: date | None = None,
    stats: list | None = None,
) -> tuple[ChartVisualization | NetworkVisualization, list[str]]:
    """Returns the visualization and warnings for meta.

    `bounds` are the year ranges the searches were filtered on (per date field) and `as_of` the
    data date: year axes cover the searched period and stop at the data date, because later dates
    are estimates for trials that have not started or finished yet."""
    pairs: list[Pair] = [(g, t) for g, ts in trials_by_group.items() for t in ts]
    if not pairs and stats:
        return _registry_bars(stats, plan)
    if plan.chart_type == "network_graph":
        return _network(pairs, plan)
    if plan.chart_type == "histogram":
        return _histogram(pairs, plan), []
    if plan.chart_type == "scatter_plot":
        return _scatter(pairs, plan)

    windows, year_notes = _year_windows(plan, bounds, as_of)
    future = set()
    for dim, (_, hi) in windows.items():
        read = _reader(dim, pairs)
        if hi is not None:
            future |= {t.nct_id for g, t in pairs if read(g, t) and all(int(v) > hi for v in read(g, t))}

    read_x = _reader(plan.x, pairs)
    if plan.x in windows:
        read_x = _within(plan.x, read_x, windows[plan.x])
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
                "nct_ids": _ids(buckets.get(v, [])),
            }
            for v in order
        ]
        ordered_axis = plan.x is Dimension.PHASE or plan.x in YEAR_DIMENSIONS
        encoding = {"x": _channel(plan.x) | ({} if ordered_axis else {"sort": "-y"}), "y": Y}
        if plan.measure == "share":  # of every trial with a value for x
            everyone = len({t.nct_id for ts in buckets.values() for t in ts})
            _add_shares(rows, lambda row: everyone)
            encoding["y"] = Y_SHARE
    else:
        read_s = _reader(plan.series, pairs)
        if plan.series in windows:
            read_s = _within(plan.series, read_s, windows[plan.series])
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
                "nct_ids": _ids(cells.get((x, s), [])),
            }
            for x in order
            for s in series_order
        ]
        series_channel = _channel(plan.series)
        encoding = {"x": _channel(plan.x), "y": Y, "color": series_channel}
        if plan.measure == "share":
            if plan.share_of == "all":  # of every trial with a value for both x and the series
                everyone = len({t.nct_id for ts in cells.values() for t in ts})
                _add_shares(rows, lambda row: everyone)
            elif plan.series is Dimension.GROUP:  # of each compared side (its trials that have an x value)
                side = {s: len({t.nct_id for (x, s2), ts in cells.items() if s2 == s for t in ts}) for s in series_order}
                _add_shares(rows, lambda row: side[row[plan.series.value]])
            else:  # of the trials in each x category
                per_x = {x: len({t.nct_id for t in ts}) for x, ts in x_totals.items()}
                key = {_row_value(plan.x, x): x for x in order}
                _add_shares(rows, lambda row: per_x[key[row[plan.x.value]]])
            encoding["y"] = Y_SHARE
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
    """Bins [from, to) with `to` exclusive; the last bin is open-ended (to = None) past the top edge."""
    values = [(t.enrollment, t) for _, t in pairs if t.enrollment is not None]
    top = max((v for v, _ in values), default=0)
    edges: list[int | None] = [e for e in ENROLLMENT_EDGES if e <= top]
    edges.append(None if top >= ENROLLMENT_EDGES[-1] else max(top + 1, ENROLLMENT_EDGES[0] + 1))
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        trials = [t for v, t in values if lo <= v and (hi is None or v < hi)]
        rows.append(
            {
                "enrollment_range": f"{lo:,}+" if hi is None else f"{lo:,}–{hi - 1:,}",
                "enrollment_from": lo,
                "enrollment_to": hi,
                "trial_count": len(trials),
                "citations": [
                    Citation(nct_id=t.nct_id, excerpt=str(t.enrollment), field=FIELD_PATHS[Dimension.ENROLLMENT], title=t.title)
                    for t in sorted(trials, key=lambda t: t.nct_id)[:CITATIONS_PER_DATUM]
                ],
                "nct_ids": _ids(trials),
            }
        )
    encoding = {
        "x": {
            "field": "enrollment_range",
            "type": "ordinal",
            "sort": [r["enrollment_range"] for r in rows],
            "title": "Enrollment (participants)",
        },
        "y": Y,
    }
    return ChartVisualization(type="histogram", intent=plan.intent, title=plan.title, encoding=encoding, data=rows)


SCATTER_MAX_POINTS = 1000  # enough to show the pattern; each point carries 3 cited values
_NUMBER: dict[Dimension, Callable[[Trial], float | None]] = {
    Dimension.ENROLLMENT: lambda t: t.enrollment,
    Dimension.DURATION: lambda t: t.duration_months,
}
_AXIS_TITLES = {Dimension.ENROLLMENT: "Enrollment (participants, log scale)", Dimension.DURATION: "Duration (months, start to primary completion)"}


def _number_citations(dim: Dimension, t: Trial) -> list[Citation]:
    """The exact values a point's coordinate comes from: enrollment, or both dates of a duration."""
    if dim is Dimension.ENROLLMENT:
        return [Citation(nct_id=t.nct_id, excerpt=str(t.enrollment), field=FIELD_PATHS[dim], title=t.title)]
    start = t.start_date_text or t.start_date.isoformat()
    end = t.primary_completion_date_text or t.primary_completion_date.isoformat()
    return [
        Citation(nct_id=t.nct_id, excerpt=start, field=FIELD_PATHS[Dimension.START_YEAR], title=t.title),
        Citation(nct_id=t.nct_id, excerpt=end, field="protocolSection.statusModule.primaryCompletionDateStruct.date", title=t.title),
    ]


def _scatter(pairs: list[Pair], plan: ChartPlan) -> tuple[ChartVisualization, list[str]]:
    """One point per trial with both numbers. Large sets are thinned to an even, deterministic sample
    (by a hash of the NCT ID, so neither old nor new trials are favoured)."""
    assert plan.y is not None
    read_x, read_y = _NUMBER[plan.x], _NUMBER[plan.y]
    read_s = _reader(plan.series, pairs) if plan.series else None
    points, skipped, empty = [], set(), set()
    for group, t in pairs:
        x, y = read_x(t), read_y(t)
        if x is None or y is None:
            skipped.add(t.nct_id)
            continue
        if t.enrollment == 0:  # enrolled no one (mostly withdrawn): says nothing about size vs anything
            empty.add(t.nct_id)
            continue
        for s in sorted(read_s(group, t)) if read_s else [None]:
            points.append((t, x, y, s))
    warnings = []
    if skipped:
        n = len(skipped)
        what = "trial without both values is" if n == 1 else "trials without both values are"
        warnings.append(f"{n} {what} left out (duration needs a start date and an actual primary completion).")
    if empty:
        warnings.append(f"{len(empty)} trial{'s' if len(empty) != 1 else ''} that enrolled no one (mostly withdrawn) left out.")
    if len(points) > SCATTER_MAX_POINTS:
        warnings.append(f"Showing an even sample of {SCATTER_MAX_POINTS} of {len(points)} points.")
        points = sorted(points, key=lambda p: hashlib.sha256(p[0].nct_id.encode()).hexdigest())[:SCATTER_MAX_POINTS]
    rows = []
    for t, x, y, s in sorted(points, key=lambda p: (p[1], p[2], p[0].nct_id)):
        row = {plan.x.value: x, plan.y.value: y, "nct_ids": [t.nct_id]}
        if plan.series:
            row[plan.series.value] = s
        cited = _number_citations(plan.x, t) + _number_citations(plan.y, t)
        row["citations"] = [c if i == 0 else c.model_copy(update={"title": None}) for i, c in enumerate(cited)]  # title once
        rows.append(row)
    def axis(dim: Dimension) -> dict:
        # enrollment spans 1 to tens of millions (registries): on a linear axis every trial is a dot at 0
        return {"field": dim.value, "type": "quantitative", "title": _AXIS_TITLES[dim]} | (
            {"scale": "log"} if dim is Dimension.ENROLLMENT else {}
        )

    encoding = {"x": axis(plan.x), "y": axis(plan.y)}
    if plan.series:
        encoding["color"] = _channel(plan.series)
    viz = ChartVisualization(type="scatter_plot", intent=plan.intent, title=plan.title, encoding=encoding, data=rows)
    return viz, warnings


def _network(pairs: list[Pair], plan: ChartPlan) -> tuple[NetworkVisualization, list[str]]:
    assert plan.series is not None
    read_a, read_b = _reader(plan.x, pairs), _reader(plan.series, pairs)
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
         "citations": _citations([n], node_trials[n]), "nct_ids": _ids(node_trials[n])}
        for n in sorted(kept, key=lambda n: (-len(node_trials[n]), n[1]))
    ]  # fmt: skip
    links = [
        {"source": node_id(a), "target": node_id(b), "weight": len(ts), "citations": _citations([a, b], ts), "nct_ids": _ids(ts)}
        for (a, b), ts in edges
    ]
    warnings = []
    if len(node_trials) > len(kept):
        warnings.append(f"Network shows the {len(kept)} most frequent of {len(node_trials)} values.")
    viz = NetworkVisualization(type="network_graph", title=plan.title, data={"nodes": nodes, "edges": links})
    return viz, warnings


def _registry_bars(stats: list, plan: ChartPlan) -> tuple[ChartVisualization, list[str]]:
    """A bar chart straight from registry-wide /stats/field/values counts (all registered studies)."""
    field = stats_fields(stats)[plan.x]
    counts = {v.value: v.studies_count for v in field.top_values}
    if plan.x is Dimension.PHASE:
        order = [p for p in PHASE_ORDER if p in counts]
    else:
        order = sorted(counts, key=lambda v: (-counts[v], v))[: plan.top_n or MAX_CATEGORIES]
    rows = [{plan.x.value: v, "trial_count": counts[v], "citations": []} for v in order]
    encoding = {"x": _channel(plan.x) | ({} if plan.x is Dimension.PHASE else {"sort": "-y"}), "y": Y}
    warnings = ["Counts are registry-wide statistics for all registered studies (/stats/field/values); "
                "no per-trial citations exist for them."]  # fmt: skip
    if len(field.top_values) < field.unique_values_count:
        warnings.append(
            f"The API returns only the top {len(field.top_values)} of {field.unique_values_count:,} values of {plan.x.value}."
        )
    viz = ChartVisualization(type="bar_chart", intent=plan.intent, title=plan.title, encoding=encoding, data=rows)
    return viz, warnings
