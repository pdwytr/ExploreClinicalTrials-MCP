# Fields: Identification Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `NCTId` | nct | National Clinical Trial (NCT) Identification Number. The unique identification code given to each clinical study upon registration at ClinicalTrials.gov. The format is "NCT" followed by an 8-digit number. Also known as ClinicalTrials.gov Identifier | also: NCT-ID |
| `NCTIdAlias` | nct[] | Obsolete or duplicate NCT that's associated with a published NCT. Identifier(s) that are considered "Obsolete" or "Duplicate". No study is displayed on public site. Request is redirected/forwarded to another NCT Identifier |  |
| `NumNCTAliases` | short | Number of obsolete NCT's associated with a published NCT. Number of obsolete identifiers for a NCTId | search-only |
| `OrgStudyId` | text | Organization's Unique Protocol Identification Number | also: ORGANIZATION-STUDY-ID |
| `OrgStudyIdType` | OrgStudyIdType | Organization Id Type. Type of organization's unique protocol ID | also: ORGANIZATION-STUDY-ID-TYPE |
| `OrgStudyIdLink` | text | Organization ID Link. URL link based on OrgStudyId and OrgStudyIdType input in PRS, include system-generated links to NIH RePORTER, specifically (associated with the types of federal funding identified as OrgStudyIdType) |  |
| `SecondaryId` | text | Secondary ID | also: SECONDARY-ID |
| `SecondaryIdType` | SecondaryIdType | Secondary ID Type | also: SECONDARY-ID-TYPE |
| `SecondaryIdDomain` | text | Secondary ID Description based on ID Type selected | ✓; also: SECONDARY-ID-DOMAIN |
| `SecondaryIdLink` | text | Secondary ID Link. URL link based on SecondaryId and SecondaryIdType, including system-generated links to NIH RePORTER, specifically (associated with the types of federal funding identified as SecondaryIdType) |  |
| `NumSecondaryIds` | short | Number of Secondary IDs. Number of Secondary ID for an NCT | search-only; also: NUMBER-OF-SECONDARY_IDS |
| `BriefTitle` | text | Brief Title | ✓; also: BRIEF-TITLE |
| `OfficialTitle` | text | Official Title | ✓; also: OFFICIAL-TITLE |
| `Acronym` | text | Acronym | ✓; also: ACRONYM |
| `OrgFullName` | text | Organization Full Name. A (registered) organization (typically the Responsible Party) that sponsors the clinical trial (study) | also: ORGANIZATION-FULLNAME |
| `OrgClass` | AgencyClass | Organization type. Organization type | also: ORGANIZATION-CLASS |
