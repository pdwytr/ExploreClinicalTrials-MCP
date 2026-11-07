# Fields: Adverse Events

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `EventsFrequencyThreshold` | text | Frequency Threshold |  |
| `EventsTimeFrame` | text | Adverse Event Time Frame | ✓ |
| `EventsDescription` | markup | Adverse Event Reporting Description | ✓ |
| `EventsAllCauseMortalityComment` | markup | All Cause Mortality Comment | ✓ |
| `EventGroupId` | text | Arm/Group ID. Internal group id | ✓ |
| `EventGroupTitle` | text | Arm/Group Title | ✓ |
| `EventGroupDescription` | markup | Arm/Group Description | ✓ |
| `EventGroupDeathsNumAffected` | integer | Total Number Affected by All-Cause Mortality |  |
| `EventGroupDeathsNumAtRisk` | integer | Total Number at Risk for All-Cause Mortality |  |
| `EventGroupSeriousNumAffected` | integer | Number Affected by a Serious Adverse Event |  |
| `EventGroupSeriousNumAtRisk` | integer | Number at Risk for a Serious Adverse Event |  |
| `EventGroupOtherNumAffected` | integer | Number Affected by Any Other Adverse Event |  |
| `EventGroupOtherNumAtRisk` | integer | Number at Risk for Any Other Adverse Event |  |
| `NumEventGroups` | short | Number of Arm/Group. Number of Arm/Group for Adverse Event (internal count) | search-only |
| `SeriousEventTerm` | text | Adverse Event Term | ✓ |
| `SeriousEventOrganSystem` | text | Organ System | ✓ |
| `SeriousEventSourceVocabulary` | text | Source Vocabulary Name for Serious Adverse Event | ✓ |
| `SeriousEventAssessmentType` | EventAssessment | Collection Approach (or Collection Approach for Table Default required) |  |
| `SeriousEventNotes` | markup | Serious Adverse Event Term Additional Description | ✓ |
| `SeriousEventStatsGroupId` | text | Group ID. Internal Arm/Group ID | ✓ |
| `SeriousEventStatsNumEvents` | integer | Number of Serious Events in an Arm/Group |  |
| `SeriousEventStatsNumAffected` | integer | Number of Participants Affected |  |
| `SeriousEventStatsNumAtRisk` | integer | Number of Participants at Risk |  |
| `NumSeriousEventStatss` | short | Number of Event Groups. Number of Event Group (Arm/Group in an Adverse Event) | search-only |
| `NumSeriousEvents` | short | Number of Serious Adverse Events. Number of Serious Adverse Events | search-only |
| `OtherEventTerm` | text |  | ✓ |
| `OtherEventOrganSystem` | text |  | ✓ |
| `OtherEventSourceVocabulary` | text |  | ✓ |
| `OtherEventAssessmentType` | EventAssessment |  |  |
| `OtherEventNotes` | markup |  | ✓ |
| `OtherEventStatsGroupId` | text |  | ✓ |
| `OtherEventStatsNumEvents` | integer |  |  |
| `OtherEventStatsNumAffected` | integer |  |  |
| `OtherEventStatsNumAtRisk` | integer |  |  |
| `NumOtherEventStatss` | short |  | search-only |
| `NumOtherEvents` | short |  | search-only |
| `NumEvents` | short |  | search-only |
