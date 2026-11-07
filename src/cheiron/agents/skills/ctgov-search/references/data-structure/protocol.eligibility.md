# Fields: eligibilityModule

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `EligibilityCriteria` | markup | Inclusion and exclusion eligibility criteria | ✓ |
| `HealthyVolunteers` | boolean | Accepts Healthy Volunteers | also: HEALTHY-VOLUNTEERS |
| `Sex` | Sex | Sex/Gender | also: Gender, GENDER |
| `GenderBased` | boolean | Gender-Based Eligibility |  |
| `GenderDescription` | markup | Gender Description | ✓ |
| `MinimumAge` | NormalizedTime | Minimum Age | also: MINIMUM-AGE |
| `MaximumAge` | NormalizedTime | Maximum Age | also: MAXIMUM-AGE |
| `StdAge` | StandardAge[] | Age Group. Ingest calculated the StdAge if there is minimumAge and/or maximimumAge entered. Redacted for Withheld studies | also: AGE-GROUP |
| `NumStdAges` | short | Num Std Measure Ages | search-only |
| `StudyPopulation` | markup | Study Population Description | ✓ |
| `SamplingMethod` | SamplingMethod | Sampling Method |  |
