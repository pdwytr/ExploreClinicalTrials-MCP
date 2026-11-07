# Fields: Misc Information Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `VersionHolder` | NormalizedDate | Version Holder. The most recent date where Ingest ran successfully |  |
| `RemovedCountry` | text[] | Removed Countries. Country for which all locations have been removed from the study |  |
| `NumRemovedCountries` | short | Number of Removed Countries. Number of removed countries | search-only |
| `EstimatedResultsFirstSubmitDate` | NormalizedDate | Estimated Results First Submitted Date. Results First Submitted Date but not yet Posted (e.g., still under QC review). ResultsFirstSubmitDate at this point is kept empty until Results is published on the public site |  |
| `FirstMCPPostDate` | NormalizedDate | First MCP Posted Date. Date of first MCP posted date | also: RESULTS-FIRST-MCP-POSTED, ResultsFirstPostedQCCommentsDate |
| `FirstMCPPostDateType` | DateType | First MCP Posted Date Type. Date type for first MCP posted date | also: ResultsFirstPostedQCCommentsDateType |
| `SubmissionReleaseDate` | NormalizedDate | Release Date. Results released by DP to NLM |  |
| `SubmissionUnreleaseDate` | NormalizedDate | Unrelease Date. Results unrelease (canceled release) by DP |  |
| `SubmissionUnreleaseDateUnknown` | boolean |  |  |
| `SubmissionResetDate` | NormalizedDate | Reset Date. NLM QC reviewer reset/unlock study back to DP |  |
| `SubmissionMCPReleaseN` | integer | Number of MCPs. Number of Major Comment Postings of a study |  |
