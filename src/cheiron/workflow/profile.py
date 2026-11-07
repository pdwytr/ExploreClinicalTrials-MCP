"""The data profile: a compact, deterministic summary of everything fetched for a question.

This is what the agent sees about the data (via the describe_data tool) instead of the
records themselves: per field, how many trials have it, how many distinct values, the top
values with counts, whether a trial can have several values, and per comparison side how
many are missing. Registry-wide /stats results are summarised the same way.
"""

import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime

from cheiron.fetch.models import Trial
from cheiron.fetch.stats import (
    BooleanStats,
    DateStats,
    EnumStats,
    FieldSizesResponse,
    FieldValuesResponse,
    IntegerStats,
    NumberStats,
    RecordSizesResponse,
    StringStats,
)
from cheiron.workflow.plans import (
    DataProfile,
    Dimension,
    FieldProfile,
    NumericSummary,
    StatsFieldSummary,
    StatsResult,
    StatsSummary,
)

TOP_VALUES = 10  # per field: enough to choose a chart, small enough for the prompt

# How each dimension is read from a trial; lists mean a trial can have several values.
_VALUES: dict[Dimension, Callable[[Trial], list[str]]] = {
    Dimension.PHASE: lambda t: t.phases,
    Dimension.START_YEAR: lambda t: [str(t.start_year)] if t.start_year else [],
    Dimension.STATUS: lambda t: [t.overall_status] if t.overall_status else [],
    Dimension.SPONSOR: lambda t: [t.lead_sponsor] if t.lead_sponsor else [],
    Dimension.SPONSOR_CLASS: lambda t: [t.sponsor_class] if t.sponsor_class else [],
    Dimension.CONDITION: lambda t: t.conditions,
    Dimension.INTERVENTION: lambda t: [i.name for i in t.interventions],
    Dimension.INTERVENTION_TYPE: lambda t: [i.type for i in t.interventions if i.type],
    Dimension.COUNTRY: lambda t: t.countries,
}
_MULTI_VALUED = {Dimension.PHASE, Dimension.CONDITION, Dimension.INTERVENTION, Dimension.INTERVENTION_TYPE, Dimension.COUNTRY}


def _profile_values(trials_by_group: dict[str, list[Trial]], read: Callable[[Trial], list[str]], multi: bool) -> FieldProfile:
    counts: Counter[str] = Counter()
    missing_by_group: dict[str, int] = {}
    for group, trials in trials_by_group.items():
        missing = 0
        for trial in trials:
            values = set(read(trial))  # a trial counts once per distinct value
            if not values:
                missing += 1
            counts.update(values)
        missing_by_group[group] = missing
    return FieldProfile(
        distinct=len(counts),
        missing=sum(missing_by_group.values()),
        top_values=counts.most_common(TOP_VALUES),
        multi_valued=multi,
        missing_by_group=missing_by_group if len(trials_by_group) > 1 else None,
    )


def _profile_enrollment(trials_by_group: dict[str, list[Trial]]) -> FieldProfile:
    values = [t.enrollment for trials in trials_by_group.values() for t in trials if t.enrollment is not None]
    missing_by_group = {g: sum(t.enrollment is None for t in ts) for g, ts in trials_by_group.items()}
    return FieldProfile(
        distinct=len(set(values)),
        missing=sum(missing_by_group.values()),
        numeric=NumericSummary(min=min(values), median=statistics.median(values), max=max(values)) if values else None,
        missing_by_group=missing_by_group if len(trials_by_group) > 1 else None,
    )


def _summarise_stats(label: str, result: StatsResult) -> StatsSummary:
    data = result.data
    if isinstance(data, FieldValuesResponse):
        fields = []
        for f in data.root:
            summary = StatsFieldSummary(piece=f.piece, type=f.type, missing=f.missing_studies_count)
            if isinstance(f, EnumStats | StringStats):
                summary.distinct = f.unique_values_count
                summary.top_values = [(v.value, v.studies_count) for v in f.top_values[:TOP_VALUES]]
                summary.incomplete = f.piece in result.incomplete_fields
            elif isinstance(f, DateStats | IntegerStats | NumberStats):
                summary.min, summary.max = f.min, f.max
                summary.avg = getattr(f, "avg", None)
            elif isinstance(f, BooleanStats):
                summary.top_values = [("true", f.true_count), ("false", f.false_count)]
            fields.append(summary)
        return StatsSummary(label=label, endpoint=result.endpoint, fields=fields)
    if isinstance(data, FieldSizesResponse):
        fields = [
            StatsFieldSummary(
                piece=f.piece,
                type="LIST_SIZE",
                missing=0,
                distinct=f.unique_sizes_count,
                top_values=[(str(s.size), s.studies_count) for s in f.top_sizes[:TOP_VALUES]],
                incomplete=f.piece in result.incomplete_fields,
                min=f.min_size,
                max=f.max_size,
            )
            for f in data.root
        ]
        return StatsSummary(label=label, endpoint=result.endpoint, fields=fields)
    assert isinstance(data, RecordSizesResponse)
    return StatsSummary(
        label=label,
        endpoint=result.endpoint,
        note=f"{data.total_studies:,} studies; average record {data.average_size_bytes:,} bytes; "
        f"{len(data.ranges)} size ranges; largest {data.largest_studies[0].id if data.largest_studies else '-'}",
    )


def build_profile(
    trials_by_group: dict[str, list[Trial]],
    total_matched: int,
    stats: Iterable[tuple[str, StatsResult]] = (),
    data_as_of: datetime | None = None,
) -> DataProfile:
    """Profile every fetched field (all of them: the agent needs them all to choose a chart)."""
    fields: dict[Dimension, FieldProfile] = {}
    if any(trials_by_group.values()):
        for dim, read in _VALUES.items():
            fields[dim] = _profile_values(trials_by_group, read, dim in _MULTI_VALUED)
        fields[Dimension.ENROLLMENT] = _profile_enrollment(trials_by_group)
    return DataProfile(
        total_matched=total_matched,
        trials_fetched=sum(len(t) for t in trials_by_group.values()),
        group_sizes={g: len(t) for g, t in trials_by_group.items()},
        fields=fields,
        stats=[_summarise_stats(label, result) for label, result in stats],
        data_as_of=data_as_of,
    )
