"""Display names for coded values, so a renderer never has to invent them.

Data rows keep the registry's codes (PHASE1, ACTIVE_NOT_RECRUITING): citations quote them and
sorting relies on them. Each encoded channel gets a `labels` map from code to the registry's own
display name ("Phase 1", "Active, not recruiting"), read from the official enum snapshot
(docs/ctgov/enums.json, field `legacyValue`). Free-text fields (sponsors, drugs, conditions,
countries) are already display text and get no map.
"""

import json
from functools import cache

from studytrials.settings import PROJECT_ROOT

ENUMS_FILE = PROJECT_ROOT / "docs" / "ctgov" / "enums.json"

# Used only where the registry's own display name is just the code again (sponsor classes:
# INDUSTRY -> "INDUSTRY"). Wording from the registry's data-element definitions.
FALLBACK = {
    "sponsor_class": {
        "NIH": "NIH", "FED": "U.S. federal (non-NIH)", "OTHER_GOV": "Other government", "INDIV": "Individual",
        "INDUSTRY": "Industry", "NETWORK": "Network", "AMBIG": "Ambiguous", "OTHER": "Other", "UNKNOWN": "Unknown",
    },
}  # fmt: skip

# Chart field -> the registry enum type its values come from.
ENUM_FIELDS = {
    "phase": "Phase",
    "overall_status": "Status",
    "sponsor_class": "AgencyClass",
    "intervention_type": "InterventionType",
    "study_type": "StudyType",
    "allocation": "DesignAllocation",
    "masking": "DesignMasking",
    "primary_purpose": "PrimaryPurpose",
}


@cache
def _enum_labels() -> dict[str, dict[str, str]]:
    if not ENUMS_FILE.exists():
        return {}
    enums = {e["type"]: e["values"] for e in json.loads(ENUMS_FILE.read_text())}
    labels: dict[str, dict[str, str]] = {}
    for field, enum_type in ENUM_FIELDS.items():
        names = {}
        for v in enums.get(enum_type, []):
            shown = v.get("legacyValue")
            names[v["value"]] = shown if shown and shown != v["value"] else FALLBACK.get(field, {}).get(v["value"], v["value"])
        labels[field] = names
    return labels


def labels_for(field: str, values: set[str]) -> dict[str, str] | None:
    """Display names for the coded values a chart actually shows, or None for free-text fields."""
    known = _enum_labels().get(field)
    if not known:
        return None
    shown = {v: known[v] for v in sorted(values) if v in known}
    return shown or None
