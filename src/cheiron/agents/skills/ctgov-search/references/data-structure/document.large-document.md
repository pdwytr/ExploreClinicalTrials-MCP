# Fields: Document Upload Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `LargeDocNoSAP` | boolean | Document Has No Statistical Analysis Plan (SAP). Indicate that No Statistical Analysis Plan (SAP) exists for this study. |  |
| `LargeDocTypeAbbrev` | text | Document Type |  |
| `LargeDocHasProtocol` | boolean | Document Includes Study Protocol. Indicate if document includes Study Protocol (Yes/No) |  |
| `LargeDocHasSAP` | boolean | Document Includes Statistical Analysis Plan (SAP). Indicate is document includes Statistical Analysis Plan (Yes/No) |  |
| `LargeDocHasICF` | boolean | Document Includes Informed Consent Form (ICF). Indicate if document includes Informed Consent Form (Yes/No) |  |
| `LargeDocLabel` | text | Document Label | ✓ |
| `LargeDocDate` | NormalizedDate | Document Date |  |
| `LargeDocUploadDate` | DateTimeMinutes | Document Uploaded Date. Date the document was uploaded to PRS |  |
| `LargeDocFilename` | text | Document File Name. Document file name (by data provider) |  |
| `LargeDocSize` | long | Document File Size. Document file size |  |
| `NumLargeDocs` | short | Number of Uploaded Documents. Number of uploaded documents for a study record (internally calculated) | search-only |
