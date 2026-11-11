"""From what the agent means to what the API is asked. Deterministic: no AI here.

The agent writes typed search steps (drugs, conditions, sponsors, countries, ...). This module
  1. merges the user's structured fields into the same slots (the field wins),
  2. resolves names to the registry's own: a brand or code name to the MeSH term its trials
     are indexed under (Ozempic -> semaglutide), an alias to the registered lead sponsor
     (MSD -> Merck Sharp & Dohme LLC), a region to its countries as the registry spells them,
  3. keeps comparison sides apart when resolution would merge them (Ozempic vs Wegovy),
  4. compiles each step into ClinicalTrials.gov parameters, with every scope rule in one place,
  5. describes in plain words what was searched, for meta (never the model's own prose).
"""

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from studytrials.fetch.endpoints import FieldValuesStep, Period, StudiesStep
from studytrials.fetch.models import DATE_AREAS, StudySearchParams, Trial, build_advanced_filter, date_range
from studytrials.models.request import QueryRequest
from studytrials.workflow.errors import InvalidSearch
from studytrials.workflow.plans import FetchResult, SearchPlan, StatsResult

log = logging.getLogger(__name__)

Kind = Literal["drug", "condition", "sponsor"]

RESOLVE_SAMPLE = 50  # trials sampled per name to see how the registry indexes it
RESOLVE_SHARE = 0.5  # a standard name is added only if it is on at least this share of them

# Which continent a country is on: geography, not registry data, so it lives here. Names are
# matched to the registry's current spellings (fetched live) after normalising case, accents
# and parenthetical variants, so "Turkey (Türkiye)" matches "turkey".
REGION_MEMBERS: dict[str, set[str]] = {
    "europe": {
        "aland islands", "albania", "andorra", "austria", "belarus", "belgium", "bosnia and herzegovina",
        "bulgaria", "croatia", "cyprus", "czechia", "czech republic", "denmark", "estonia", "faroe islands",
        "finland", "france", "georgia", "germany", "gibraltar", "greece", "holy see", "hungary", "iceland",
        "ireland", "italy", "jersey", "kosovo", "latvia", "liechtenstein", "lithuania", "luxembourg", "malta",
        "moldova", "monaco", "montenegro", "netherlands", "north macedonia", "norway", "poland", "portugal",
        "romania", "russia", "russian federation", "san marino", "serbia", "serbia and montenegro",
        "federal republic of yugoslavia", "slovakia", "slovenia", "spain", "sweden", "switzerland", "turkey",
        "turkiye", "ukraine", "united kingdom",
    },
    "asia": {
        "afghanistan", "armenia", "azerbaijan", "bahrain", "bangladesh", "bhutan", "brunei", "burma",
        "myanmar", "cambodia", "china", "hong kong", "india", "indonesia", "iran", "iraq", "israel", "japan",
        "jordan", "kazakhstan", "kuwait", "kyrgyzstan", "laos", "lebanon", "macau", "malaysia", "maldives",
        "mongolia", "nepal", "north korea", "oman", "pakistan", "palestinian territories", "philippines",
        "qatar", "saudi arabia", "singapore", "south korea", "korea", "sri lanka", "syria", "taiwan",
        "tajikistan", "thailand", "timor leste", "turkmenistan", "united arab emirates", "uzbekistan",
        "vietnam", "viet nam", "yemen",
    },
    "africa": {
        "algeria", "angola", "benin", "botswana", "burkina faso", "burundi", "cabo verde", "cameroon",
        "central african republic", "chad", "comoros", "cote d ivoire", "democratic republic of the congo",
        "djibouti", "egypt", "equatorial guinea", "eritrea", "eswatini", "ethiopia", "gabon", "ghana", "guinea",
        "guinea bissau", "kenya", "lesotho", "liberia", "libya", "madagascar", "malawi", "mali", "mauritania",
        "mauritius", "mayotte", "morocco", "mozambique", "namibia", "niger", "nigeria", "republic of the congo",
        "reunion", "rwanda", "senegal", "seychelles", "sierra leone", "somalia", "south africa", "south sudan",
        "sudan", "tanzania", "the gambia", "gambia", "togo", "tunisia", "uganda", "zambia", "zimbabwe",
    },
    "north_america": {
        "anguilla", "antigua and barbuda", "aruba", "barbados", "belize", "bermuda", "bonaire saint eustatius and saba",
        "canada", "cayman islands", "costa rica", "cuba", "curacao", "dominica", "dominican republic",
        "el salvador", "greenland", "grenada", "guadeloupe", "guatemala", "haiti", "honduras", "jamaica",
        "martinique", "mexico", "montserrat", "netherlands antilles", "nicaragua", "panama", "puerto rico",
        "saint kitts and nevis", "saint lucia", "saint martin", "saint vincent and the grenadines", "the bahamas",
        "bahamas", "trinidad and tobago", "united states", "united states minor outlying islands", "virgin islands",
    },
    "south_america": {
        "argentina", "bolivia", "brazil", "chile", "colombia", "ecuador", "french guiana", "guyana", "paraguay",
        "peru", "suriname", "uruguay", "venezuela",
    },
    "oceania": {
        "american samoa", "australia", "christmas island", "fiji", "french polynesia", "guam", "kiribati",
        "micronesia", "new caledonia", "new zealand", "niue", "northern mariana islands", "papua new guinea",
        "samoa", "solomon islands", "vanuatu",
    },
}  # fmt: skip


def _bare(text: str) -> str:
    """Compare names ignoring case, accents, quotes and punctuation."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())


def contains_term(value: str, term: str) -> bool:
    """`value` names `term` as whole words ("uveal melanoma" contains melanoma)."""
    return re.search(rf"(?<!\w){re.escape(_bare(term))}(?!\w)", _bare(value)) is not None


def negated_word(term: str, name: str) -> str | None:
    """The word of `name` that `term` negates: 'Lymphoma, Non-Hodgkin' negates 'hodgkin' in
    'Hodgkin lymphoma'. None when the name is itself the negated form ('non-small cell ...')."""
    words, bare_name = set(_bare(name).split()), _bare(name)
    tokens = _bare(term).split()
    for before, word in zip(tokens, tokens[1:]):
        if before == "non" and word in words and f"non {word}" not in bare_name:
            return word
    return None


def phrase(text: str) -> str:
    """Quote a value so the API matches it as a phrase and never reads it as syntax.
    Unquoted, 'multiple sclerosis' also matches 'tuberous sclerosis'."""
    return '"' + text.replace('"', "").strip() + '"'


def _country_aliases(name: str) -> set[str]:
    """A registry country name and its parenthetical variant: 'Turkey (Türkiye)' -> turkey, turkiye."""
    names = {_bare(name)}
    names |= {_bare(part) for part in re.findall(r"\(([^)]*)\)", name)}
    names.add(_bare(re.sub(r"\([^)]*\)", "", name)))
    return {n for n in names if n}


# --- Resolution -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """How one name is searched: the name itself, plus the registry's standard name if it differs."""

    kind: Kind
    name: str
    standard: str | None = None  # added registry name (MeSH term or registered lead sponsor)
    evidence: str | None = None  # e.g. "43 of 50 sampled trials are indexed as semaglutide"
    # A condition whose text search also matches its opposite ("Hodgkin lymphoma" matches
    # "non-Hodgkin lymphoma"): the opposite's index term, and the name's own if one was sampled.
    opposite: str | None = None
    own_term: str | None = None
    opposite_evidence: str | None = None

    def opposite_filter(self) -> str | None:
        """Leave out trials indexed as the opposite condition, unless also indexed as this one."""
        if not self.opposite:
            return None
        drop = f"NOT AREA[ConditionMeshTerm]{phrase(self.opposite)} AND NOT AREA[ConditionAncestorTerm]{phrase(self.opposite)}"
        return f"(AREA[ConditionMeshTerm]{phrase(self.own_term)} OR ({drop}))" if self.own_term else f"({drop})"

    @property
    def terms(self) -> list[str]:
        return [self.name, self.standard] if self.standard else [self.name]


_PARAM = {"drug": "query.intr", "condition": "query.cond", "sponsor": "query.spons"}
_READ: dict[Kind, Callable[[Trial], list[str]]] = {
    "drug": lambda t: t.intervention_mesh,
    "condition": lambda t: t.condition_mesh,
    "sponsor": lambda t: [t.lead_sponsor] if t.lead_sponsor else [],
}
_INDEXED_AS = {"drug": "indexed as", "condition": "indexed as", "sponsor": "led by"}

Search = Callable[..., Awaitable[FetchResult]]
Stats = Callable[[FieldValuesStep], Awaitable[StatsResult]]


class Resolver:
    """Looks up how the registry itself names things, from samples of matching trials.

    One registry call per new name, cached for the life of the process (names do not change
    meaning between questions). Every lookup is deterministic for a given registry version."""

    def __init__(self, search: Search, stats: Stats | None = None):
        self._search = search
        self._stats = stats
        self._cache: dict[tuple[Kind, str], Resolution] = {}
        self._countries: list[str] | None = None

    async def resolve(self, kind: Kind, name: str) -> Resolution:
        key = (kind, _bare(name))
        if key not in self._cache:
            self._cache[key] = await self._lookup(kind, name)
        return self._cache[key]

    async def _lookup(self, kind: Kind, name: str) -> Resolution:
        sample = await self._search(StudySearchParams(search={_PARAM[kind]: phrase(name)}), RESOLVE_SAMPLE)
        trials = sample.trials
        counts = Counter(v for t in trials for v in {_bare(x): x for x in _READ[kind](t)}.values())
        if not trials or not counts:
            return Resolution(kind, name)
        base = Resolution(kind, name)
        if kind == "condition":
            base = self._opposite(name, counts, len(trials))
            if base.opposite:  # the opposite disease is never a name for this one
                counts = Counter({t: c for t, c in counts.items() if not negated_word(t, name)})
        if any(_bare(v) == _bare(name) for v in counts):
            # the registry already indexes under this very name; the most common other term is a
            # co-intervention or co-condition (nivolumab trials are often ipilimumab combinations)
            return base
        if not counts:
            return base
        top, hits = counts.most_common(1)[0]
        if hits < RESOLVE_SHARE * len(trials) or _bare(top) == _bare(name) or contains_term(name, top):
            return base
        evidence = f"{hits} of {len(trials)} sampled trials matching '{name}' are {_INDEXED_AS[kind]} '{top}'"
        return replace(base, standard=top, evidence=evidence)

    @staticmethod
    def _opposite(name: str, counts: Counter, sampled: int) -> Resolution:
        """Detect a text search that also matches the opposite condition, from the sample's index
        terms: 'Lymphoma, Non-Hodgkin' among trials matching 'Hodgkin lymphoma'."""
        negated = [(t, c, negated_word(t, name)) for t, c in counts.most_common() if negated_word(t, name)]
        if not negated:
            return Resolution("condition", name)
        opposite, hits, word = negated[0]
        own = [t for t, _ in counts.most_common() if contains_term(t, word) and not negated_word(t, name)]
        evidence = f"{hits} of {sampled} sampled trials matching '{name}' are indexed as '{opposite}'"
        return Resolution(
            "condition", name, opposite=opposite, own_term=own[0] if own else None, opposite_evidence=evidence
        )

    async def countries(self) -> list[str]:
        """Every site country as the registry spells it today (GET /stats/field/values)."""
        if self._countries is None:
            if self._stats is None:
                return []
            result = await self._stats(FieldValuesStep(label="Countries", fields=["LocationCountry"]))
            fields = result.data.root if hasattr(result.data, "root") else []
            self._countries = sorted({v.value.strip() for f in fields for v in getattr(f, "top_values", [])})
            unplaced = [c for c in self._countries if not any(_country_aliases(c) & m for m in REGION_MEMBERS.values())]
            if unplaced:
                log.warning("registry countries in no region (update REGION_MEMBERS): %s", unplaced)
        return self._countries

    async def region(self, region: str) -> list[str]:
        members = REGION_MEMBERS[region]
        return [c for c in await self.countries() if _country_aliases(c) & members]

    async def country(self, name: str) -> str:
        """The registry's spelling of a country the user typed ('south korea', 'Türkiye')."""
        wanted = _bare(name)
        for registered in await self.countries():
            if wanted in _country_aliases(registered):
                return registered
        return name


# --- Merging the user's structured fields ------------------------------------------------------

_FIELD_SLOTS = {"drug_name": "drugs", "condition": "conditions", "sponsor": "sponsors", "country": "countries"}


def merge_request(plan: SearchPlan, request: QueryRequest) -> tuple[SearchPlan, list[str], list[str]]:
    """The user's structured fields fill the same slots as the agent's: the field wins.

    Returns the merged plan, warnings (for meta.warnings) and notes (for meta.assumptions).
    In a comparison, a field that is one of the compared sides is skipped; one that is none of
    them sends the plan back (InvalidSearch), since replacing every side would erase it."""
    warnings: list[str] = []
    notes: list[str] = []
    studies = [s for s in plan.steps if isinstance(s, StudiesStep)]
    if request.filters():
        stats = [s.endpoint for s in plan.steps if s.endpoint.startswith("stats/")]
        if stats:
            raise InvalidSearch(
                f"The user supplied filters {request.filters()}, but {stats} cover the whole registry and "
                "cannot apply them. Use 'studies' steps for filtered questions."
            )
        if any(s.endpoint == "study" for s in plan.steps):
            warnings.append("Filters do not apply to a lookup of one trial by NCT number.")

    updates: dict[int, dict] = {id(s): {} for s in studies}
    for req_field, slot in _FIELD_SLOTS.items():
        wanted = getattr(request, req_field)
        if wanted is None:
            continue
        sides = {tuple(sorted(_bare(v) for v in getattr(s, slot))) for s in studies}
        if plan.is_comparison and len(sides) > 1:
            if any(_bare(wanted) in {_bare(v) for v in getattr(s, slot)} for s in studies):
                warnings.append(f"Ignored {req_field}={wanted!r}: the question compares searches by {slot}.")
                continue
            raise InvalidSearch(
                f"The user set {req_field}={wanted!r}, but the plan compares other {slot} "
                f"({', '.join(s.label for s in studies)}). The user's field applies to every side: compare "
                f"something else, or make {wanted!r} one of the sides.",
                {"field": req_field, "value": wanted},
            )
        for s in studies:
            current = list(getattr(s, slot))
            narrower = [v for v in current if contains_term(v, wanted)]
            if narrower:
                updates[id(s)][slot] = narrower
                dropped = [v for v in current if v not in narrower]
                if dropped:
                    notes.append(f"{s.label}: {', '.join(dropped)} dropped; the user's {req_field}={wanted!r} applies.")
            else:
                updates[id(s)][slot] = [wanted]
                if current:
                    notes.append(f"{s.label}: the question's {', '.join(current)} replaced by the user's {req_field}={wanted!r}.")
            if slot == "countries" and s.region:
                updates[id(s)]["region"] = None
    for req_field, slot in (("trial_phase", "phases"), ("recruitment_status", "statuses")):
        wanted = getattr(request, req_field)
        if not wanted:
            continue
        for s in studies:
            if getattr(s, slot) and set(getattr(s, slot)) != set(wanted):
                notes.append(f"{s.label}: {slot} set by the user's {req_field}.")
            updates[id(s)][slot] = list(wanted)

    steps = [s.model_copy(update=updates[id(s)]) if isinstance(s, StudiesStep) else s for s in plan.steps]
    return plan.model_copy(update={"steps": steps}), warnings, notes


# --- Resolving names, and keeping comparison sides apart ------------------------------------------

_SLOT_KINDS: dict[str, Kind] = {"drugs": "drug", "conditions": "condition", "sponsors": "sponsor"}


@dataclass
class ResolvedStep:
    step: StudiesStep
    names: dict[tuple[str, str], Resolution] = field(default_factory=dict)  # (slot, name) -> resolution
    countries: list[str] = field(default_factory=list)  # registry spellings, region expanded

    def terms(self, slot: str, name: str) -> list[str]:
        r = self.names.get((slot, name))
        return r.terms if r else [name]

    def opposite_filter(self) -> str | None:
        """The filter that drops the opposite condition. Only for a step with that one condition:
        with several OR-ed conditions it would also cut trials matching the others."""
        if len(self.step.conditions) != 1:
            return None
        res = self.names.get(("conditions", self.step.conditions[0]))
        return res.opposite_filter() if res else None


async def resolve_plan(plan: SearchPlan, resolver: Resolver) -> tuple[dict[str, ResolvedStep], list[str], list[str]]:
    """Resolve every name in every studies step; then undo resolutions that would make compared
    sides search the same thing. Returns {label: ResolvedStep}, warnings and notes."""
    resolved: dict[str, ResolvedStep] = {}
    for s in plan.steps:
        if not isinstance(s, StudiesStep):
            continue
        r = ResolvedStep(s)
        for slot, kind in _SLOT_KINDS.items():
            for name in getattr(s, slot):
                r.names[(slot, name)] = await resolver.resolve(kind, name)
        countries = [await resolver.country(c) for c in s.countries]
        if s.region:
            countries += await resolver.region(s.region)
        r.countries = list(dict.fromkeys(countries))
        resolved[s.label] = r

    warnings: list[str] = []
    if len(resolved) > 1:
        for slot in _SLOT_KINDS:
            own = {label: {_bare(n) for n in getattr(r.step, slot)} for label, r in resolved.items()}
            added = {  # decided on every side before any expansion is undone
                label: {_bare(x.standard) for (sl, _), x in r.names.items() if sl == slot and x.standard}
                for label, r in resolved.items()
            }
            for label, r in resolved.items():
                for (s_slot, name), res in list(r.names.items()):
                    if s_slot != slot or not res.standard:
                        continue
                    std = _bare(res.standard)
                    clash = [o for o in resolved if o != label and (std in own[o] or std in added[o])]
                    if clash:
                        r.names[(s_slot, name)] = replace(res, standard=None, evidence=None)
                        warnings.append(
                            f"{name} and {', '.join(clash)} are both indexed as {res.standard}: each side counts "
                            f"only trials that name it, so the comparison stays meaningful."
                        )
    notes = [
        f"{res.name} was also searched as {res.standard}, the registry's name for it ({res.evidence})."
        for r in resolved.values()
        for res in r.names.values()
        if res.standard
    ]
    for r in resolved.values():
        for (slot, name), res in r.names.items():
            if slot != "conditions" or not res.opposite:
                continue
            if r.opposite_filter():
                kept = f"; trials also indexed as {res.own_term} are kept" if res.own_term else ""
                notes.append(
                    f"The text search for {name} also matches trials of the opposite condition, {res.opposite} "
                    f"({res.opposite_evidence}), so trials indexed as {res.opposite} are left out{kept}."
                )
            else:
                warnings.append(
                    f"The text search for {name} also matches {res.opposite} ({res.opposite_evidence}); with "
                    f"several conditions in one search, those trials could not be left out."
                )
    return resolved, list(dict.fromkeys(warnings)), list(dict.fromkeys(notes))


# --- Compiling to API parameters ---------------------------------------------------------------


def _any(terms: list[str]) -> str:
    quoted = [phrase(t) for t in dict.fromkeys(terms)]
    return quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")"


def _text(include: list[list[str]], exclude: list[str], match_all: bool) -> str | None:
    """One text parameter: alternatives per name OR-ed, names OR-ed (or AND-ed for match_all),
    excluded names NOT-ed."""
    if not include:
        return None
    joined = (" AND " if match_all else " OR ").join(_any(terms) for terms in include)
    for name in exclude:
        joined = f"({joined}) NOT {phrase(name)}"
    return joined


def effective_periods(step: StudiesStep, request: QueryRequest) -> list[Period]:
    """The periods a step is filtered on. The user's start_year / end_year replace the planner's
    start-date period; a completion-date period is kept alongside."""
    periods = []
    if request.start_year or request.end_year:
        periods.append(Period(field="start", from_year=request.start_year, to_year=request.end_year))
    if step.period and not (periods and step.period.field == "start"):
        periods.append(step.period)
    return periods


def compile_step(r: ResolvedStep, request: QueryRequest) -> StudySearchParams:
    s = r.step
    params: dict[str, str | None] = {
        "query.intr": _text([r.terms("drugs", d) for d in s.drugs], s.exclude_drugs, s.drugs_match == "all"),
        "query.cond": _text([r.terms("conditions", c) for c in s.conditions], s.exclude_conditions, False),
        "query.lead": _text([r.terms("sponsors", p) for p in s.sponsors], [], False),
        "query.locn": " OR ".join(phrase(c) for c in r.countries) or None,
        "query.term": " AND ".join(phrase(k) for k in s.keywords) or None,
        "filter.overallStatus": "|".join(st.value for st in s.statuses) or None,
    }
    advanced = [build_advanced_filter(s.phases or None), r.opposite_filter()]
    if s.study_type != "any":
        advanced.append(f"AREA[StudyType]{s.study_type.upper()}")
    if s.min_enrollment is not None or s.max_enrollment is not None:
        lo = s.min_enrollment if s.min_enrollment is not None else "MIN"
        hi = s.max_enrollment if s.max_enrollment is not None else "MAX"
        advanced.append(f"AREA[EnrollmentCount]RANGE[{lo},{hi}]")
    if s.advanced:
        advanced.append(f"({s.advanced})")
    advanced += [date_range(p.field, p.from_year, p.to_year) for p in effective_periods(s, request)]
    params["filter.advanced"] = " AND ".join(a for a in advanced if a) or None
    intent = s.model_dump(mode="json", exclude_defaults=True, exclude={"label", "endpoint"})
    searched = {
        f"{slot}:{name}": res.terms for (slot, name), res in r.names.items() if res.standard
    }  # names searched under more than their own spelling
    return StudySearchParams(
        search={k: v for k, v in params.items() if v},
        intent=intent,
        searched_as=searched,
        countries=r.countries,
    )


# --- Plain-words description (meta.interpretation) -------------------------------------------------


def describe(label: str, r: ResolvedStep, request: QueryRequest) -> str:
    s = r.step

    def names(slot: str, items: list[str]) -> str:
        return ", ".join(" or ".join(r.terms(slot, n)) for n in items)

    parts = []
    if s.drugs:
        joiner = "all of" if s.drugs_match == "all" and len(s.drugs) > 1 else ""
        parts.append(f"testing {joiner} {names('drugs', s.drugs)}".replace("  ", " "))
    if s.exclude_drugs:
        parts.append(f"not {', '.join(s.exclude_drugs)}")
    if s.conditions:
        parts.append(f"for {names('conditions', s.conditions)}")
        res = r.names.get(("conditions", s.conditions[0]))
        if r.opposite_filter() and res:
            parts.append(f"not trials indexed only as {res.opposite}")
    if s.exclude_conditions:
        parts.append(f"excluding {', '.join(s.exclude_conditions)}")
    if s.sponsors:
        parts.append(f"led by {names('sponsors', s.sponsors)}")
    if s.region:
        parts.append(f"with sites in {s.region.replace('_', ' ').title()} ({len(r.countries)} countries)")
    elif r.countries:
        parts.append(f"with sites in {', '.join(r.countries)}")
    if s.keywords:
        parts.append(f"mentioning {', '.join(s.keywords)}")
    if s.phases:
        parts.append("in " + ", ".join(p.value for p in s.phases))
    if s.statuses:
        parts.append("status " + ", ".join(st.value for st in s.statuses))
    if s.min_enrollment is not None or s.max_enrollment is not None:
        parts.append(f"enrolling {s.min_enrollment or 0}–{s.max_enrollment if s.max_enrollment is not None else 'any'}")
    for p in effective_periods(s, request):
        verb = "started" if p.field == "start" else "completing"
        parts.append(f"{verb} {p.from_year or 'any time'}–{p.to_year or 'now'}")
    if s.advanced:
        parts.append(f"plus the agent's own filter {s.advanced}")
    scope = {"any": "all study types", "interventional": "interventional studies only", "observational": "observational studies only"}
    return f"{label}: {scope[s.study_type]} " + "; ".join(parts) + "."


__all__ = [
    "DATE_AREAS",
    "REGION_MEMBERS",
    "Resolution",
    "ResolvedStep",
    "Resolver",
    "compile_step",
    "contains_term",
    "describe",
    "effective_periods",
    "merge_request",
    "phrase",
    "resolve_plan",
]
