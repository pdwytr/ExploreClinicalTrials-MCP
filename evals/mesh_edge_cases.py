"""Probe the registry's own MeSH terms with deliberately hard name variants.

    uv run python evals/mesh_edge_cases.py [report.json]

Read-only: a few searches against the public ClinicalTrials.gov API (no service, no LLM).

For each edge case we fetch trials whose typed text contains a tricky variant (a salt form,
a brand, a code name, an abbreviation...), then look at the MeSH terms NLM attached to those
trials (derivedSection) and ask: does the variant land on the concept we would want, stay
apart from what it must not merge with, or get no MeSH term at all?

How a typed name is linked to a MeSH term, in order:
  contains     a MeSH term of that trial appears as whole words in the cleaned typed name
  overlap      most of a MeSH term's words are in the typed name (cancer = carcinoma = neoplasm)
  only_option  the trial has one typed name and one MeSH term
  none         no link. Candidates are only ever the trial's own MeSH terms, never all of MeSH.
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://clinicaltrials.gov/api/v2/studies"
PAGE = 200
FIELDS = "NCTId,InterventionName,InterventionType,Condition,InterventionBrowseModule,ConditionBrowseModule"
SALTS = (
    r"\b(hydrochloride|hcl|sodium|potassium|mesylate|maleate|sulfate|acetate|citrate|phosphate|tartrate|"
    r"besylate|succinate|fumarate|tosylate|calcium|magnesium|bromide|chloride|dihydrate|monohydrate)\b"
)

# kind: intervention | condition
# search: API params that pull trials containing the variant
# variant: regex picking the typed names we probe in those trials
# want: MeSH term(s) the variant should land on (any of); avoid: terms it must NOT land on
# expect_none: the variant should have no MeSH term (non-drugs)
CASES = [
    # one concept, many strings
    {"id": "salt", "kind": "intervention", "search": {"query.intr": '"doxorubicin hydrochloride"'},
     "variant": r"doxorubicin hydrochloride", "want": ["Doxorubicin"]},
    {"id": "dose_in_name", "kind": "intervention", "search": {"query.intr": '"paclitaxel"'},
     "variant": r"paclitaxel\s+\d", "want": ["Paclitaxel"]},
    {"id": "brand", "kind": "intervention", "search": {"query.intr": '"keytruda"'},
     "variant": r"keytruda", "want": ["Pembrolizumab", "pembrolizumab"]},
    {"id": "code_name", "kind": "intervention", "search": {"query.intr": '"MK-3475"'},
     "variant": r"mk-?3475", "want": ["Pembrolizumab", "pembrolizumab"]},
    {"id": "biosimilar", "kind": "intervention", "search": {"query.intr": '"trastuzumab-dkst"'},
     "variant": r"trastuzumab-dkst|ogivri", "want": ["Trastuzumab"]},
    {"id": "abbreviation", "kind": "condition", "search": {"query.cond": '"NSCLC"'},
     "variant": r"^nsclc$", "want": ["Carcinoma, Non-Small-Cell Lung"]},
    {"id": "spelling", "kind": "condition", "search": {"query.cond": '"Non Small Cell Lung Cancer"'},
     "variant": r"^non[\s-]small[\s-]cell lung cancer$", "want": ["Carcinoma, Non-Small-Cell Lung"]},
    # must NOT merge
    {"id": "liposomal", "kind": "intervention", "search": {"query.intr": '"pegylated liposomal doxorubicin"'},
     "variant": r"liposomal doxorubicin|doxil|caelyx", "want": ["Liposomal doxorubicin", "liposomal doxorubicin"],
     "avoid": ["Doxorubicin"]},
    {"id": "insulin_types", "kind": "intervention", "search": {"query.intr": '"insulin glargine"'},
     "variant": r"insulin glargine|lantus", "want": ["Insulin Glargine"], "avoid": ["Insulin"]},
    {"id": "diabetes_types", "kind": "condition", "search": {"query.cond": '"type 1 diabetes"'},
     "variant": r"type 1 diabetes", "want": ["Diabetes Mellitus, Type 1"], "avoid": ["Diabetes Mellitus, Type 2"]},
    # ambiguous abbreviation
    {"id": "ambiguous_ms", "kind": "condition", "search": {"query.cond": '"MS"'},
     "variant": r"^ms$", "want": ["Multiple Sclerosis"]},
    # combination strings
    {"id": "regimen", "kind": "intervention", "search": {"query.intr": '"FOLFOX"'},
     "variant": r"^folfox", "want": ["Oxaliplatin", "Fluorouracil", "Leucovorin"]},
    # not drugs
    {"id": "placebo", "kind": "intervention", "search": {"query.intr": '"placebo"', "query.cond": '"asthma"'},
     "variant": r"^placebo", "expect_none": True},
    {"id": "procedure", "kind": "intervention", "search": {"query.intr": '"Laboratory Biomarker Analysis"'},
     "variant": r"laboratory biomarker analysis", "expect_none": True},
    {"id": "questionnaire", "kind": "intervention", "search": {"query.intr": '"Questionnaire Administration"'},
     "variant": r"questionnaire administration", "expect_none": True},
    # new drugs, maybe not in MeSH yet
    {"id": "new_drug", "kind": "intervention", "search": {"query.intr": '"datopotamab deruxtecan"'},
     "variant": r"datopotamab", "want": ["datopotamab deruxtecan", "Datopotamab deruxtecan"]},
    # class: is the drug class reachable through the ancestors?
    {"id": "drug_class", "kind": "intervention", "search": {"query.intr": '"semaglutide"'},
     "variant": r"semaglutide", "want": ["semaglutide", "Semaglutide"],
     "ancestor": "Glucagon-Like Peptide-1 Receptor Agonists"},
]  # fmt: skip


def fetch(params: dict) -> list[dict]:
    query = {**params, "pageSize": PAGE, "fields": FIELDS}
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(query)}", headers={"user-agent": "cheiron-evals"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("studies", [])


def clean(name: str) -> str:
    s = re.sub(r"\d+(\.\d+)?\s*(mg|g|mcg|µg|ml|iu|units?)(/\s*(m2|m²|kg|day|d))?", " ", name.casefold())
    s = re.sub(SALTS, " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def typed_names(study: dict, kind: str) -> list[str]:
    p = study.get("protocolSection", {})
    if kind == "intervention":
        return [i["name"] for i in p.get("armsInterventionsModule", {}).get("interventions", [])]
    return p.get("conditionsModule", {}).get("conditions", [])


def browse(study: dict, kind: str) -> dict:
    module = "interventionBrowseModule" if kind == "intervention" else "conditionBrowseModule"
    return study.get("derivedSection", {}).get(module, {})


# words that mean the same in typed text and MeSH headings
SAME_WORD = {"cancer": "neoplasm", "cancers": "neoplasm", "carcinoma": "neoplasm", "neoplasms": "neoplasm",
             "tumor": "neoplasm", "tumors": "neoplasm", "tumour": "neoplasm", "diabetes": "diabetes"}  # fmt: skip
FILLER = {"mellitus", "disease", "disorder", "of", "the", "and", "with", "in", "injection", "tablet", "oral"}
MIN_OVERLAP = 0.6  # share of the MeSH term's words found in the typed name


def words(text: str) -> set[str]:
    return {SAME_WORD.get(w, w) for w in clean(text).split()} - FILLER


def link(name: str, b: dict, n_typed: int) -> tuple[str | None, str]:
    """The MeSH term this typed name lands on, chosen only among the trial's own MeSH terms."""
    candidates = [m["term"] for m in b.get("meshes", [])]
    typed = f" {clean(name)} "
    for term in candidates:  # 1. exact or whole-word containment ("Pembrolizumab (KEYTRUDA®)")
        if f" {clean(term)} " in typed:
            return term, "contains"
    scored = []  # 2. word overlap ("Type 1 Diabetes" ~ "Diabetes Mellitus, Type 1")
    for term in candidates:
        tw = words(term)
        if tw:
            scored.append((len(tw & words(name)) / len(tw), term))
    best = max(scored, default=(0.0, None))
    if best[0] >= MIN_OVERLAP and [s for s, _ in scored].count(best[0]) == 1:
        return best[1], "overlap"
    if n_typed == 1 and len(candidates) == 1:  # 3. one typed name, one MeSH term ("NSCLC")
        return candidates[0], "only_option"
    return None, "none"


def probe(case: dict) -> dict:
    studies = fetch(case["search"])
    pattern = re.compile(case["variant"], re.IGNORECASE)
    landed, how, ancestors = Counter(), Counter(), Counter()
    trials_with_mesh = names = 0
    examples = []
    for s in studies:
        b = browse(s, case["kind"])
        trials_with_mesh += bool(b.get("meshes"))
        typed = typed_names(s, case["kind"])
        for name in typed:
            if not pattern.search(name):
                continue
            names += 1
            term, method = link(name, b, len(typed))
            landed[term or "(no MeSH)"] += 1
            how[method] += 1
            ancestors.update(a["term"] for a in b.get("ancestors", []))
            if len(examples) < 3:
                examples.append({"typed": name, "mesh": term, "via": method,
                                 "trial_mesh": [m["term"] for m in b.get("meshes", [])][:6]})  # fmt: skip
    return {"studies": len(studies), "trials_with_mesh": trials_with_mesh, "names": names,
            "landed": dict(landed.most_common(6)), "via": dict(how), "examples": examples,
            "ancestor_found": case.get("ancestor") in ancestors if case.get("ancestor") else None}  # fmt: skip


def verdict(case: dict, r: dict) -> str:
    if not r["names"]:
        return "NO DATA"
    top = max(r["landed"], key=r["landed"].get)
    share = r["landed"][top] / r["names"]
    if case.get("expect_none"):
        return "PASS" if top == "(no MeSH)" else f"FAIL: mapped to {top}"
    if any(a in r["landed"] for a in case.get("avoid", [])):
        return f"FAIL: merged into {[a for a in case['avoid'] if a in r['landed']]}"
    if r.get("ancestor_found") is False:
        return f"FAIL: class '{case['ancestor']}' not among ancestors"
    if top in case["want"]:
        return "PASS" if share >= 0.8 else f"PARTIAL: {share:.0%} land on {top}"
    hits = sum(r["landed"].get(w, 0) for w in case["want"])
    return f"PARTIAL: {hits / r['names']:.0%} land on wanted" if hits else f"FAIL: lands on {top}"


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "mesh_report.json"
    report = []
    for case in CASES:
        r = probe(case)
        r |= {"id": case["id"], "verdict": verdict(case, r)}
        report.append(r)
        print(f"[{case['id']:14}] {r['verdict']:42} names {r['names']:4}  landed {r['landed']}  via {r['via']}")
    out.write_text(json.dumps(report, indent=1))
    print(f"\n{sum(r['verdict'] == 'PASS' for r in report)}/{len(report)} pass; details in {out}")


if __name__ == "__main__":
    main()
