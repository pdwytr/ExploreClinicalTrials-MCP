# Fields: Status Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `StatusVerifiedDate` | PartialDate | Record Verification Date | also: VERIFICATION-DATE |
| `OverallStatus` | Status | Overall Recruitment Status or Expanded Access Status | also: OVERALL-STATUS |
| `LastKnownStatus` | Status | Last Known Status. A study on ClinicalTrials.gov whose last known status was recruiting; not yet recruiting; or active, not recruiting but that has passed its completion date, and the status has not been last verified within the past 2 years. | also: LAST-KNOWN-STATUS |
| `DelayedPosting` | boolean | Delayed Posting | also: DELAYED |
| `WhyStopped` | markup | Reason why a study stopped | ✓; also: WHY-STOPPED |
| `HasExpandedAccess` | boolean | Has EA for compassionate use | also: HAS-EXPANDED-ACCESS |
| `ExpandedAccessNCTId` | nct | NCT of an EA study | also: HAS-EXPANDED-ACCESS-NCT |
| `ExpandedAccessStatusForNCTId` | ExpandedAccessStatus | EA Recruitment Status. recruitment status of the EA study that's linked to INT/OBS |  |
| `StartDate` | PartialDate | Study Start Date | also: START-DATE |
| `StartDateType` | DateType | Study Start Date Type. Date Type |  |
| `PrimaryCompletionDate` | PartialDate | Primary Completion Date | also: COMPLETION-DATE-PRIMARY |
| `PrimaryCompletionDateType` | DateType | Primary Completion Date Type |  |
| `CompletionDate` | PartialDate | Study Completion Date | also: COMPLETION-DATE |
| `CompletionDateType` | DateType | Study Completion Date Type |  |
| `StudyFirstSubmitDate` | NormalizedDate | Study First Submitted Date. The date on which the study sponsor or investigator first submitted a study record to ClinicalTrials.gov. There is typically a delay of a few days between the first submitted date and the record's availability on ClinicalTrials.gov (the first posted date). | also: STUDY-FIRST-SUBMITTED, FIRST-RECEIVED-DATE |
| `StudyFirstSubmitYear` | short | Study First Submitted Year | search-only |
| `StudyFirstSubmitQCDate` | NormalizedDate | Study First Submission Date that Met QC Criteria. The date on which the study sponsor or investigator first submits a study record that is consistent with National Library of Medicine (NLM) quality control (QC) review criteria. The sponsor or investigator may need to revise and submit a study record one or more times before NLM's QC review criteria are met. It is the responsibility of the sponsor or investigator to ensure that the study record is consistent with the NLM QC review criteria. | also: STUDY-FIRST-SUBMITTED-QC |
| `StudyFirstPostDate` | NormalizedDate | Study First Posted Date. The date on which the study record was first available on ClinicalTrials.gov after National Library of Medicine (NLM) quality control (QC) review has concluded. There is typically a delay of a few days between the date the study sponsor or investigator submitted the study record and the first posted date. | also: STUDY-FIRST-POSTED |
| `StudyFirstPostYear` | short | Year the Study First Posted on the Public Site | search-only |
| `StudyFirstPostDateType` | DateType | First Study Posted Date Type |  |
| `ResultsWaived` | boolean |  |  |
| `ResultsFirstSubmitDate` | NormalizedDate | Results First Submitted Date. The date on which the study sponsor or investigator first submits a study record with summary results information. There is typically a delay between the results first submitted date and when summary results information becomes available on ClinicalTrials.gov (the results first posted date). | also: RESULTS-FIRST-SUBMITTED, FIRST-RECEIVED-RESULTS-DATE |
| `ResultsFirstSubmitYear` | short | Results First Submitted Year | search-only |
| `ResultsFirstSubmitQCDate` | NormalizedDate | Results First Submitted that Met QC Criteria. The date on which the study sponsor or investigator first submits a study record with summary results information that is consistent with National Library of Medicine (NLM) quality control (QC) review criteria. The sponsor or investigator may need to revise and submit results information one or more times before NLM's QC review criteria are met. It is the responsibility of the sponsor or investigator to ensure that the study record is consistent with the NLM QC review criteria. | also: RESULTS-FIRST-SUBMITTED-QC |
| `ResultsFirstPostDate` | NormalizedDate | Results First Posted Date. The date on which summary results information was first available on ClinicalTrials.gov after National Library of Medicine (NLM) quality control (QC) review has concluded. There is typically a delay between the date the study sponsor or investigator first submits summary results information (the results first submitted date) and the results first posted date. Some results information may be available at an earlier date if Results First Posted with QC Comments. | also: RESULTS-FIRST-POSTED |
| `ResultsFirstPostYear` | short | Results First Posted Year | search-only |
| `ResultsFirstPostDateType` | DateType | Results First Posted Date Type. Results first posted date type. Due to historical reason, some studies have date type "Estimate" |  |
| `DispFirstSubmitDate` | NormalizedDate | Certification/Extension (aka Delayed Results) First Submitted Date. The date on which the study sponsor or investigator first submitted a certification or an extension request to delay submission of results. A sponsor or investigator who submits a certification can delay results submission up to 2 years after this date, unless certain events occur sooner. There is typically a delay between the date the certification or extension request was submitted and the date the information is first available on ClinicalTrials.gov (certification/extension first posted). | also: DISPOSITION-FIRST-SUBMITTED, FIRST-RECEIVED-DISPOSITION-DATE |
| `DispFirstSubmitYear` | short | Certification/Extension First Submitted Year | search-only |
| `DispFirstSubmitQCDate` | NormalizedDate | Certification/Extension First Submitted that Passed QC Review. Certification/extension first submitted that met QC criteria | also: DISPOSITION-FIRST-SUBMITTED-QC |
| `DispFirstPostDate` | NormalizedDate | Certification/Extension First Posted Date. The date on which information about a certification to delay submission of results or an extension request was first available on ClinicalTrials.gov. ClinicalTrials.gov does not indicate whether the submission was a certification or extension request. There is typically a delay between the date the study sponsor or investigator submitted the certification or extension request and the first posted date. | also: DISPOSITION-FIRST-POSTED |
| `DispFirstPostYear` | short | Certification/Extension First Posted Year | search-only |
| `DispFirstPostDateType` | DateType | Certification/Extension First Posted Date Type. Due to data requirements and collections over the years, some studies might have "Estimate" dates |  |
| `LastUpdateSubmitDate` | NormalizedDate | Last Update Submitted Date. The most recent date on which the study sponsor or investigator submitted changes to a study record to ClinicalTrials.gov. There is typically a delay of a few days between the last update submitted date and when the date changes are posted on ClinicalTrials.gov (the last update posted date). | also: LAST-UPDATE-SUBMITTED, LAST-RELEASE-DATE |
| `LastUpdateSubmitYear` | short | Last Update Submitted Year | search-only |
| `LastUpdatePostDate` | NormalizedDate | Last Update Posted Date. The most recent date on which changes to a study record were made available on ClinicalTrials.gov. There may be a delay between when the changes were submitted to ClinicalTrials.gov by the study's sponsor or investigator (the last update submitted date) and the last update posted date. | also: LAST-UPDATE-POSTED |
| `LastUpdatePostYear` | short | Last Update Posted Year. Study record last update posted year on public site | search-only |
| `LastUpdatePostDateType` | DateType | Last Update Posted Date Type. Due to data requirements and collections over the years, some studies might have "Estimate" dates |  |
