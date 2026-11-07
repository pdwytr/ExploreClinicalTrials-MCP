# Filterable fields for AREA[...]

Fields with fixed values, dates, numbers or booleans, grouped by module. Use as AREA[Piece]VALUE or AREA[Piece]RANGE[min,max]. Enum values are in references/enums.md. Free-text fields are searched with query.* parameters (see references/search-areas.md).
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.



## identificationModule

| Field | Type | Meaning |
| --- | --- | --- |
| `OrgStudyIdType` | enum OrgStudyIdType | Organization Id Type |
| `SecondaryIdType` | enum SecondaryIdType | Secondary ID Type |
| `OrgClass` | enum AgencyClass | Organization type |

## statusModule

| Field | Type | Meaning |
| --- | --- | --- |
| `StatusVerifiedDate` | date | Record Verification Date |
| `OverallStatus` | enum Status | Overall Recruitment Status or Expanded Access Status |
| `LastKnownStatus` | enum Status | Last Known Status |
| `DelayedPosting` | boolean | Delayed Posting |
| `HasExpandedAccess` | text | Has EA for compassionate use |
| `ExpandedAccessStatusForNCTId` | enum ExpandedAccessStatus | EA Recruitment Status |
| `StartDate` | date | Study Start Date |
| `StartDateType` | enum DateType | Study Start Date Type |
| `PrimaryCompletionDate` | date | Primary Completion Date |
| `PrimaryCompletionDateType` | enum DateType | Primary Completion Date Type |
| `CompletionDate` | date | Study Completion Date |
| `CompletionDateType` | enum DateType | Study Completion Date Type |
| `StudyFirstSubmitDate` | date | Study First Submitted Date |
| `StudyFirstSubmitQCDate` | date | Study First Submission Date that Met QC Criteria |
| `StudyFirstPostDate` | date | Study First Posted Date |
| `StudyFirstPostDateType` | enum DateType | First Study Posted Date Type |
| `ResultsWaived` | boolean |  |
| `ResultsFirstSubmitDate` | date | Results First Submitted Date |
| `ResultsFirstSubmitQCDate` | date | Results First Submitted that Met QC Criteria |
| `ResultsFirstPostDate` | date | Results First Posted Date |
| `ResultsFirstPostDateType` | enum DateType | Results First Posted Date Type |
| `DispFirstSubmitDate` | date | Certification/Extension (aka Delayed Results) First Submitted Date |
| `DispFirstSubmitQCDate` | date | Certification/Extension First Submitted that Passed QC Review |
| `DispFirstPostDate` | date | Certification/Extension First Posted Date |
| `DispFirstPostDateType` | enum DateType | Certification/Extension First Posted Date Type |
| `LastUpdateSubmitDate` | date | Last Update Submitted Date |
| `LastUpdatePostDate` | date | Last Update Posted Date |
| `LastUpdatePostDateType` | enum DateType | Last Update Posted Date Type |

## sponsorCollaboratorsModule

| Field | Type | Meaning |
| --- | --- | --- |
| `ResponsiblePartyType` | enum ResponsiblePartyType | Responsible Party Type |
| `LeadSponsorClass` | enum AgencyClass | Lead Sponsor Type |
| `CollaboratorClass` | enum AgencyClass | Collaborator Type |

## oversightModule

| Field | Type | Meaning |
| --- | --- | --- |
| `OversightHasDMC` | boolean | Has Data Monitoring Committee (DMC) |
| `IsFDARegulatedDrug` | boolean | Is FDA Regulated Drug |
| `IsFDARegulatedDevice` | boolean | Is FDA Regulated Device |
| `IsUnapprovedDevice` | boolean | Is Unapproved Device |
| `IsPPSD` | boolean | Pediatric Postmarket Surveillance of a Device Product |
| `IsUSExport` | boolean | Product Exported from US |
| `FDAAA801Violation` | boolean |  |

## designModule

| Field | Type | Meaning |
| --- | --- | --- |
| `StudyType` | enum StudyType | Study Type |
| `NPtrsToThisExpAccNCTId` | numeric | Number of References to an Expanded Access Study |
| `ExpAccTypeIndividual` | boolean | Individual Patients |
| `ExpAccTypeIntermediate` | boolean | Intermediate-type Population |
| `ExpAccTypeTreatment` | boolean | Treatment IND/Protocol |
| `PatientRegistry` | boolean | Patient Registry |
| `Phase` | enum Phase | Study Phase |
| `DesignAllocation` | enum DesignAllocation | Design Allocation |
| `DesignInterventionModel` | enum InterventionalAssignment | Interventional Study Design |
| `DesignPrimaryPurpose` | enum PrimaryPurpose | Design Primary Purpose |
| `DesignObservationalModel` | enum ObservationalModel | Observational Study Model |
| `DesignTimePerspective` | enum DesignTimePerspective | Time Perspective |
| `DesignMasking` | enum DesignMasking | Design Masking |
| `DesignWhoMasked` | enum WhoMasked |  |
| `BioSpecRetention` | enum BioSpecRetention | Biospecimen Retention |
| `EnrollmentCount` | numeric | Enrollment |
| `EnrollmentType` | enum EnrollmentType | Enrollment Type |

## armsInterventionsModule

| Field | Type | Meaning |
| --- | --- | --- |
| `ArmGroupType` | enum ArmGroupType | Arm Group Type |
| `InterventionType` | enum InterventionType | Intervention/Treatment Type |

## eligibilityModule

| Field | Type | Meaning |
| --- | --- | --- |
| `HealthyVolunteers` | boolean | Accepts Healthy Volunteers |
| `Sex` | enum Sex | Sex/Gender |
| `GenderBased` | boolean | Gender-Based Eligibility |
| `StdAge` | enum StandardAge | Age Group |
| `SamplingMethod` | enum SamplingMethod | Sampling Method |

## contactsLocationsModule

| Field | Type | Meaning |
| --- | --- | --- |
| `CentralContactRole` | enum ContactRole | Central Contact Role |
| `OverallOfficialRole` | enum OfficialRole | Overall Official Role |
| `LocationStatus` | enum RecruitmentStatus | Individual site recruitment status |
| `LocationContactRole` | enum ContactRole | Location Contact Role |

## referencesModule

| Field | Type | Meaning |
| --- | --- | --- |
| `ReferenceType` | enum ReferenceType | Reference Type |

## ipdSharingStatementModule

| Field | Type | Meaning |
| --- | --- | --- |
| `IPDSharing` | enum IpdSharing | Plan to Share IPD |
| `IPDSharingInfoType` | enum IpdSharingInfoType | IPDSharing Info Type |

## miscInfoModule

| Field | Type | Meaning |
| --- | --- | --- |
| `VersionHolder` | date | Version Holder |
| `EstimatedResultsFirstSubmitDate` | date | Estimated Results First Submitted Date |
| `FirstMCPPostDate` | date | First MCP Posted Date |
| `FirstMCPPostDateType` | enum DateType | First MCP Posted Date Type |
| `SubmissionReleaseDate` | date | Release Date |
| `SubmissionUnreleaseDate` | date | Unrelease Date |
| `SubmissionUnreleaseDateUnknown` | boolean |  |
| `SubmissionResetDate` | date | Reset Date |
| `SubmissionMCPReleaseN` | numeric | Number of MCPs |

## conditionBrowseModule

| Field | Type | Meaning |
| --- | --- | --- |
| `ConditionBrowseLeafRelevance` | enum BrowseLeafRelevance | Relevance to Condition Leaf Topic |

## interventionBrowseModule

| Field | Type | Meaning |
| --- | --- | --- |
| `InterventionBrowseLeafRelevance` | enum BrowseLeafRelevance | Relevance to Intervention Leaf Topic |

## hasResults

| Field | Type | Meaning |
| --- | --- | --- |
| `HasResults` | func present(resultsfirstsubmitdate) | Has Results |
