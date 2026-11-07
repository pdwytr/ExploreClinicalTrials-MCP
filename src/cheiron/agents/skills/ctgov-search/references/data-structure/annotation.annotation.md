# Fields: Annotation Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `UnpostedResponsibleParty` | text | Responsible Party for Unposted Events. Information provider (Responsible Party) | ✓ |
| `UnpostedEventType` | UnpostedEventType | Study Results Submission Type. Study Results Submission Type |  |
| `UnpostedEventDate` | NormalizedDate | Study Results Submission Date. Study Results Submission Date |  |
| `UnpostedEventDateUnknown` | boolean | Unposted Event Date is Unknown |  |
| `NumUnpostedEvents` | short | Number of events for the Results submission/review cycle. Number of events for the Results submission/review cycle | search-only |
| `ViolationEventType` | ViolationEventType | Violation Event Type. • Violation Identified by FDA • Correction Confirmed by FDA • Penalty Imposed by FDA |  |
| `ViolationEventDescription` | text | Violation Event Type Description. • Failure to Submit. The entry for this clinical trial was not complete at the time of submission, as required by law. This may or may not have any bearing on the accuracy of the information in the entry. • Submission of False Information. The entry for this clinical trial was found to be false or misleading and therefore not in compliance with the law. • Non-submission. The entry for this clinical trial did not contain information on the primary and secondary outcomes at the time of submission, as required by law. This may or may not have any bearing on the accuracy of the information in the entry. • The responsible party has corrected the violation. • A $XX,XXX penalty was imposed against the responsible party for the violation. | ✓ |
| `ViolationEventCreationDate` | NormalizedDate | Violation Event Creation Date. Date the violation entered in PRS |  |
| `ViolationEventIssuedDate` | NormalizedDate | Violation Event Issued Date. Date the FDA issued the violation |  |
| `ViolationEventReleaseDate` | NormalizedDate | Violation Event Released Date. Date the study record was submitted |  |
| `ViolationEventPostedDate` | NormalizedDate | Violation Event Posted Date. Date the violation is available on clinicaltrials.gov |  |
| `NumViolationEvents` | short | Number of Violation Events. Number of FDAAA 801 violations - related events | search-only |
