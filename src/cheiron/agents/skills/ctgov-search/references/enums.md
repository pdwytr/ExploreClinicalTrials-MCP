# Enum values

Exact values for every enum type; use them as written, e.g. AREA[Phase]PHASE3. 'Used by' lists the fields that take that enum.
Generated from `docs/ctgov/enums.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


- **AgencyClass** (used by OrgClass, LeadSponsorClass, CollaboratorClass): `NIH`, `FED`, `OTHER_GOV`, `INDIV`, `INDUSTRY`, `NETWORK`, `AMBIG`, `OTHER`, `UNKNOWN`
- **AgreementRestrictionType** (used by AgreementRestrictionType): `LTE60`, `GT60`, `OTHER`
- **AnalysisDispersionType** (used by OutcomeAnalysisDispersionType): `STANDARD_DEVIATION`, `STANDARD_ERROR_OF_MEAN`
- **ArmGroupType** (used by ArmGroupType): `EXPERIMENTAL`, `ACTIVE_COMPARATOR`, `PLACEBO_COMPARATOR`, `SHAM_COMPARATOR`, `NO_INTERVENTION`, `OTHER`
- **BioSpecRetention** (used by BioSpecRetention): `NONE_RETAINED`, `SAMPLES_WITH_DNA`, `SAMPLES_WITHOUT_DNA`
- **BrowseLeafRelevance** (used by ConditionBrowseLeafRelevance, InterventionBrowseLeafRelevance): `LOW`, `HIGH`
- **ConfidenceIntervalNumSides** (used by OutcomeAnalysisCINumSides): `ONE_SIDED`, `TWO_SIDED`
- **ContactRole** (used by CentralContactRole, LocationContactRole): `STUDY_CHAIR`, `STUDY_DIRECTOR`, `PRINCIPAL_INVESTIGATOR`, `SUB_INVESTIGATOR`, `CONTACT`
- **DateType** (used by StartDateType, PrimaryCompletionDateType, CompletionDateType, StudyFirstPostDateType, ResultsFirstPostDateType, DispFirstPostDateType, LastUpdatePostDateType, FirstMCPPostDateType): `ACTUAL`, `ESTIMATED`
- **DesignAllocation** (used by DesignAllocation): `RANDOMIZED`, `NON_RANDOMIZED`, `NA`
- **DesignMasking** (used by DesignMasking): `NONE`, `SINGLE`, `DOUBLE`, `TRIPLE`, `QUADRUPLE`
- **DesignTimePerspective** (used by DesignTimePerspective): `RETROSPECTIVE`, `PROSPECTIVE`, `CROSS_SECTIONAL`, `OTHER`
- **EnrollmentType** (used by EnrollmentType): `ACTUAL`, `ESTIMATED`
- **EventAssessment** (used by SeriousEventAssessmentType, OtherEventAssessmentType): `NON_SYSTEMATIC_ASSESSMENT`, `SYSTEMATIC_ASSESSMENT`
- **ExpandedAccessStatus** (used by ExpandedAccessStatusForNCTId): `AVAILABLE`, `NO_LONGER_AVAILABLE`, `TEMPORARILY_NOT_AVAILABLE`, `APPROVED_FOR_MARKETING`
- **InterventionType** (used by InterventionType): `BEHAVIORAL`, `BIOLOGICAL`, `COMBINATION_PRODUCT`, `DEVICE`, `DIAGNOSTIC_TEST`, `DIETARY_SUPPLEMENT`, `DRUG`, `GENETIC`, `PROCEDURE`, `RADIATION`, `OTHER`
- **InterventionalAssignment** (used by DesignInterventionModel): `SINGLE_GROUP`, `PARALLEL`, `CROSSOVER`, `FACTORIAL`, `SEQUENTIAL`
- **IpdSharing** (used by IPDSharing): `YES`, `NO`, `UNDECIDED`
- **IpdSharingInfoType** (used by IPDSharingInfoType): `STUDY_PROTOCOL`, `SAP`, `ICF`, `CSR`, `ANALYTIC_CODE`
- **MeasureDispersionType** (used by BaselineMeasureDispersionType): `NA`, `STANDARD_DEVIATION`, `STANDARD_ERROR`, `INTER_QUARTILE_RANGE`, `FULL_RANGE`, `CONFIDENCE_80`, `CONFIDENCE_90`, `CONFIDENCE_95`, `CONFIDENCE_975`, `CONFIDENCE_99`, `CONFIDENCE_OTHER`, `GEOMETRIC_COEFFICIENT`
- **MeasureParam** (used by BaselineMeasureParamType, OutcomeMeasureParamType): `GEOMETRIC_MEAN`, `GEOMETRIC_LEAST_SQUARES_MEAN`, `LEAST_SQUARES_MEAN`, `LOG_MEAN`, `MEAN`, `MEDIAN`, `NUMBER`, `COUNT_OF_PARTICIPANTS`, `COUNT_OF_UNITS`
- **NonInferiorityType** (used by OutcomeAnalysisNonInferiorityType): `SUPERIORITY`, `NON_INFERIORITY`, `EQUIVALENCE`, `OTHER`, `NON_INFERIORITY_OR_EQUIVALENCE`, `SUPERIORITY_OR_OTHER`, `NON_INFERIORITY_OR_EQUIVALENCE_LEGACY`, `SUPERIORITY_OR_OTHER_LEGACY`
- **ObservationalModel** (used by DesignObservationalModel): `COHORT`, `CASE_CONTROL`, `CASE_ONLY`, `CASE_CROSSOVER`, `ECOLOGIC_OR_COMMUNITY`, `FAMILY_BASED`, `DEFINED_POPULATION`, `NATURAL_HISTORY`, `OTHER`
- **OfficialRole** (used by OverallOfficialRole): `STUDY_CHAIR`, `STUDY_DIRECTOR`, `PRINCIPAL_INVESTIGATOR`, `SUB_INVESTIGATOR`
- **OrgStudyIdType** (used by OrgStudyIdType): `NIH`, `FDA`, `VA`, `CDC`, `AHRQ`, `SAMHSA`
- **OutcomeMeasureType** (used by OutcomeMeasureType): `PRIMARY`, `SECONDARY`, `OTHER_PRE_SPECIFIED`, `POST_HOC`
- **Phase** (used by Phase): `NA`, `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`
- **PrimaryPurpose** (used by DesignPrimaryPurpose): `TREATMENT`, `PREVENTION`, `DIAGNOSTIC`, `ECT`, `SUPPORTIVE_CARE`, `SCREENING`, `HEALTH_SERVICES_RESEARCH`, `BASIC_SCIENCE`, `DEVICE_FEASIBILITY`, `OTHER`
- **RecruitmentStatus** (used by LocationStatus): `ACTIVE_NOT_RECRUITING`, `COMPLETED`, `ENROLLING_BY_INVITATION`, `NOT_YET_RECRUITING`, `RECRUITING`, `SUSPENDED`, `TERMINATED`, `WITHDRAWN`, `AVAILABLE`
- **ReferenceType** (used by ReferenceType): `BACKGROUND`, `RESULT`, `DERIVED`
- **ReportingStatus** (used by OutcomeMeasureReportingStatus): `NOT_POSTED`, `POSTED`
- **ResponsiblePartyType** (used by ResponsiblePartyType): `SPONSOR`, `PRINCIPAL_INVESTIGATOR`, `SPONSOR_INVESTIGATOR`
- **SamplingMethod** (used by SamplingMethod): `PROBABILITY_SAMPLE`, `NON_PROBABILITY_SAMPLE`
- **SecondaryIdType** (used by SecondaryIdType): `NIH`, `FDA`, `VA`, `CDC`, `AHRQ`, `SAMHSA`, `OTHER_GRANT`, `EUDRACT_NUMBER`, `CTIS`, `REGISTRY`, `OTHER`
- **Sex** (used by Sex): `FEMALE`, `MALE`, `ALL`
- **StandardAge** (used by StdAge): `CHILD`, `ADULT`, `OLDER_ADULT`
- **Status** (used by OverallStatus, LastKnownStatus): `ACTIVE_NOT_RECRUITING`, `COMPLETED`, `ENROLLING_BY_INVITATION`, `NOT_YET_RECRUITING`, `RECRUITING`, `SUSPENDED`, `TERMINATED`, `WITHDRAWN`, `AVAILABLE`, `NO_LONGER_AVAILABLE`, `TEMPORARILY_NOT_AVAILABLE`, `APPROVED_FOR_MARKETING`, `WITHHELD`, `UNKNOWN`
- **StudyType** (used by StudyType): `EXPANDED_ACCESS`, `INTERVENTIONAL`, `OBSERVATIONAL`
- **UnpostedEventType** (used by UnpostedEventType): `RESET`, `RELEASE`, `UNRELEASE`
- **ViolationEventType** (used by ViolationEventType): `VIOLATION_IDENTIFIED`, `CORRECTION_CONFIRMED`, `PENALTY_IMPOSED`, `ISSUES_IN_LETTER_ADDRESSED_CONFIRMED`
- **WhoMasked** (used by DesignWhoMasked): `PARTICIPANT`, `CARE_PROVIDER`, `INVESTIGATOR`, `OUTCOMES_ASSESSOR`
