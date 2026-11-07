# Parameters by endpoint

What you may set on each endpoint. Paging, fields, format and sorting are set by code.
Generated from `docs/ctgov/openapi.yaml` (API 2.0.5) by scripts/build_ctgov_skill.py.


## `studies` (GET /studies)

| Parameter | Description |
| --- | --- |
| `query.cond` | "Conditions or disease" query in Essie expression syntax. See "ConditionSearch Area" on Search Areas for more details. |
| `query.id` | "Study IDs" query in Essie expression syntax. See "IdSearch Area" on Search Areas for more details. |
| `query.intr` | "Intervention / treatment" query in Essie expression syntax. See "InterventionSearch Area" on Search Areas for more details. |
| `query.lead` | Searches in "LeadSponsorName" field. See Study Data Structure for more details. The query is in Essie expression syntax. |
| `query.locn` | "Location terms" query in Essie expression syntax. See "LocationSearch Area" on Search Areas for more details. |
| `query.outc` | "Outcome measure" query in Essie expression syntax. See "OutcomeSearch Area" on Search Areas for more details. |
| `query.spons` | "Sponsor / collaborator" query in Essie expression syntax. See "SponsorSearch Area" on Search Areas for more details. |
| `query.term` | "Other terms" query in Essie expression syntax. See "BasicSearch Area" on Search Areas for more details. |
| `query.titles` | "Title / acronym" query in Essie expression syntax. See "TitleSearch Area" on Search Areas for more details. |
| `filter.advanced` | Filter by query in Essie expression syntax |
| `filter.geo` | Filter by geo-function. Currently only distance function is supported. Format: `distance(latitude,longitude,distance)` |
| `filter.ids` | Filter by comma- or pipe-separated list of NCT IDs (a.k.a. ClinicalTrials.gov identifiers). The provided IDs will be searched in NCTId and NCTIdAlias fields. |
| `filter.overallStatus` | Filter by comma- or pipe-separated list of statuses |

## `study` (GET /studies/{nctId})

| Parameter | Description |
| --- | --- |
| `nctId` | NCT Number of a study. If found in NCTIdAlias field, 301 HTTP redirect to the actual study will be returned. |

## `stats/field/values` (GET /stats/field/values)

| Parameter | Description |
| --- | --- |
| `fields` | Filter by piece names or field paths of leaf fields. See Data Structure for the available values. If specified, must be non-empty comma- or pipe-separated list of fields to return. |
| `types` | Filter by field types |

## `stats/field/sizes` (GET /stats/field/sizes)

| Parameter | Description |
| --- | --- |
| `fields` | Filter by piece names or field paths of leaf fields. See Data Structure for the available values. If specified, must be non-empty comma- or pipe-separated list of fields to return. If unspecified, all available stats will be returned. |

## `stats/size` (GET /stats/size)

No parameters.
