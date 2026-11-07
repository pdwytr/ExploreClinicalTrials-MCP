# Fields: Design Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `StudyType` | StudyType | Study Type | also: STUDY-TYPE, STUDY-TYPES |
| `NPtrsToThisExpAccNCTId` | integer | Number of References to an Expanded Access Study. Number of studies that reference this EA study |  |
| `ExpAccTypeIndividual` | boolean | Individual Patients. For individual participants, including for emergency use, as specified in 21 CFR 312.310. Allows a single patient, with a serious disease or condition who cannot participate in a clinical trial, access to a drug or biological product that has not been approved by the FDA. This category also includes access in an emergency situation. |  |
| `ExpAccTypeIntermediate` | boolean | Intermediate-type Population. For intermediate-size participant populations, as specified in 21 CFR 312.315. Allows more than one patient (but generally fewer patients than through a Treatment IND/Protocol) access to a drug or biological product that has not been approved by the FDA. This type of expanded access is used when multiple patients with the same disease or condition seek access to a specific drug or biological product that has not been approved by the FDA. |  |
| `ExpAccTypeTreatment` | boolean | Treatment IND/Protocol. Under a treatment IND or treatment protocol, as specified in 21 CFR 312.320. Allows a large, widespread population access to a drug or biological product that has not been approved by the FDA. This type of expanded access can only be provided if the product is already being developed for marketing for the same use as the expanded access use. |  |
| `PatientRegistry` | boolean | Patient Registry. A type of observational study that collects information about patients' medical conditions and/or treatments to better understand how a condition or treatment affects patients in the real world. | also: PATIENT-REGISTRY |
| `TargetDuration` | NormalizedTime | Target Follow-Up Duration |  |
| `Phase` | Phase[] | Study Phase | also: PHASE |
| `NumPhases` | short | Number of Phases. Indicate which phase(s) the study is in | search-only |
| `DesignAllocation` | DesignAllocation | Design Allocation | also: DESIGN-ALLOCATION |
| `DesignInterventionModel` | InterventionalAssignment | Interventional Study Design | also: DESIGN-INTERVENTION-MODEL |
| `DesignInterventionModelDescription` | markup | Interventional Study Design Description | ✓; also: DESIGN-INTERVENTION-MODEL-DESCRIPTION |
| `DesignPrimaryPurpose` | PrimaryPurpose | Design Primary Purpose | also: DESIGN-PRIMARY-PURPOSE |
| `DesignObservationalModel` | ObservationalModel | Observational Study Model | also: DESIGN-OBSERVATIONAL-MODEL |
| `DesignTimePerspective` | DesignTimePerspective | Time Perspective | also: DESIGN-TIME-PERSPECTIVE |
| `DesignMasking` | DesignMasking | Design Masking | also: DESIGN-MASKING |
| `DesignMaskingDescription` | markup | Masking Description | ✓ |
| `DesignWhoMasked` | WhoMasked[] |  | also: DESIGN-WHO-MASKED |
| `NumDesignWhoMaskeds` | short |  | search-only |
| `BioSpecRetention` | BioSpecRetention | Biospecimen Retention | also: BIOSPECIMEN-RETENTION |
| `BioSpecDescription` | markup | Biospecimen Description | ✓; also: BIOSPECIMEN-DESCRIPTION |
| `EnrollmentCount` | integer | Enrollment | also: ENROLLMENT |
| `EnrollmentType` | EnrollmentType | Enrollment Type |  |
