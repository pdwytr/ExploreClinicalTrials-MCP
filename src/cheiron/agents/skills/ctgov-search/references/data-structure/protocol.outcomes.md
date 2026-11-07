# Fields: Outcome Measure Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `PrimaryOutcomeMeasure` | text | Primary Outcome Title | ✓; also: PRIMARY-OUTCOME-MEASURE |
| `PrimaryOutcomeDescription` | markup | Primary Outcome Measure Description | ✓ |
| `PrimaryOutcomeTimeFrame` | text | Primary Outcome Measure Time Frame | ✓ |
| `NumPrimaryOutcomes` | short | Number of Primary Outcome Measures | search-only; also: NUMBER-OF-PRIMARY-OMS |
| `SecondaryOutcomeMeasure` | text | Secondary Outcome Measure Title | ✓; also: SECONDARY-OUTCOME-MEASURE |
| `SecondaryOutcomeDescription` | markup | Secondary Outcome Measure Description | ✓ |
| `SecondaryOutcomeTimeFrame` | text | Secondary Outcome Measure Time Frame | ✓ |
| `NumSecondaryOutcomes` | short | Number of Secondary Measure Outcomes | search-only; also: NUMBER-OF-SECONDARY-OMS |
| `OtherOutcomeMeasure` | text | Other Outcome Measure Measure Title | ✓ |
| `OtherOutcomeDescription` | markup | Other Outcome Measure Description | ✓ |
| `OtherOutcomeTimeFrame` | text | Other Outcome Measure Time Frame | ✓ |
| `NumOtherOutcomes` | short | Num of Other Outcome Measures | search-only |
| `NumOutcomes` | short | Number of Outcome Measures | search-only |
