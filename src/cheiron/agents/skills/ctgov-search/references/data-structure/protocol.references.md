# Fields: referencesModule

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `ReferencePMID` | text | PubMed Identifier | also: PUBMED-IDS |
| `ReferenceType` | ReferenceType | Reference Type |  |
| `ReferenceCitation` | text | Reference Citation | ✓; also: CITATIONS |
| `RetractionPMID` | text | PMID for Publication Retraction. PMID for publication retraction |  |
| `RetractionSource` | text |  | ✓ |
| `NumRetractionsForRef` | short | Number of Reference Retractions | search-only |
| `NumReferences` | short | Number of References to an Expanded Access Study | search-only; also: NUMBER-OF-CITATIONS |
| `NumRetractionsAllRefs` | short | Number of Retractions All Refs | search-only |
| `SeeAlsoLinkLabel` | markup | See Also Link Label Title | ✓; also: LINK-LABELS |
| `SeeAlsoLinkURL` | text |  | also: LINKS |
| `NumSeeAlsoLinks` | short | Number of See Also Links | search-only |
| `AvailIPDId` | text | Available IPD ID | ✓ |
| `AvailIPDType` | text | Available IPD Type | ✓ |
| `AvailIPDURL` | text | Available IPD URL |  |
| `AvailIPDComment` | markup | Available IPD Comment | ✓ |
| `NumAvailIPDs` | short | Number of Available IPDs | search-only |
