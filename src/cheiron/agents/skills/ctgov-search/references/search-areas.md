# Search areas

What each query.* parameter searches, highest-weighted fields first. ✓ = synonyms are matched. An area name also works in AREA[...], e.g. AREA[ConditionSearch].
Generated from `docs/ctgov/search-areas.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


- **BasicSearch** (`query.term`, UI: Other terms): NCTId, Acronym ✓, BriefTitle ✓, OfficialTitle ✓, Condition ✓, InterventionName ✓, InterventionOtherName ✓, Phase, StdAge, PrimaryOutcomeMeasure ✓, Keyword ✓, BriefSummary ✓, … (57 fields)
- **ConditionSearch** (`query.cond`, UI: Conditions or disease): Condition ✓, BriefTitle ✓, OfficialTitle ✓, ConditionMeshTerm ✓, ConditionAncestorTerm ✓, Keyword ✓, NCTId
- **InterventionSearch** (`query.intr`, UI: Intervention / treatment): InterventionName ✓, InterventionType, ArmGroupType, InterventionOtherName ✓, BriefTitle ✓, OfficialTitle ✓, ArmGroupLabel ✓, InterventionMeshTerm ✓, Keyword ✓, InterventionAncestorTerm ✓, InterventionDescription ✓, ArmGroupDescription ✓
- **InterventionNameSearch** (no parameter; use AREA[...], UI: -): InterventionName ✓, InterventionOtherName ✓
- **ObsoleteConditionSearch** (no parameter; use AREA[...], UI: -): Condition ✓, ConditionMeshTerm ✓, ConditionAncestorTerm ✓, Keyword ✓
- **ExternalIdsSearch** (no parameter; use AREA[...], UI: -): OrgStudyId, SecondaryId
- **ExternalIdTypesSearch** (no parameter; use AREA[...], UI: -): OrgStudyIdType, SecondaryIdType
- **EligibilitySearch** (no parameter; use AREA[...], UI: -): EligibilityCriteria ✓, StudyPopulation ✓
- **OutcomeSearch** (`query.outc`, UI: Outcome measure): PrimaryOutcomeMeasure ✓, SecondaryOutcomeMeasure ✓, PrimaryOutcomeDescription ✓, SecondaryOutcomeDescription ✓, OtherOutcomeMeasure ✓, OutcomeMeasureTitle ✓, OtherOutcomeDescription ✓, OutcomeMeasureDescription ✓, OutcomeMeasurePopulationDescription ✓
- **OutcomeNameSearch** (no parameter; use AREA[...], UI: -): PrimaryOutcomeMeasure ✓, SecondaryOutcomeMeasure ✓, OtherOutcomeMeasure ✓, OutcomeMeasureTitle ✓
- **TitleSearch** (`query.titles`, UI: Title / acronym): Acronym ✓, BriefTitle ✓, OfficialTitle ✓
- **LocationSearch** (`query.locn`, UI: Location terms): LocationCity, LocationState, LocationCountry, LocationFacility, LocationZip
- **ContactSearch** (no parameter; use AREA[...], UI: -): OverallOfficialName, CentralContactName, OverallOfficialAffiliation, LocationContactName
- **NCTIdSearch** (no parameter; use AREA[...], UI: -): NCTId, NCTIdAlias
- **IdSearch** (`query.id`, UI: Study IDs): NCTId, NCTIdAlias, Acronym ✓, OrgStudyId, SecondaryId
- **SponsorSearch** (`query.spons`, UI: Sponsor / collaborator): LeadSponsorName, CollaboratorName, OrgFullName
- **FunderTypeSearch** (no parameter; use AREA[...], UI: -): LeadSponsorClass, CollaboratorClass
- **ResponsiblePartySearch** (no parameter; use AREA[...], UI: -): ResponsiblePartyInvestigatorFullName ✓, ResponsiblePartyOldNameTitle ✓, ResponsiblePartyInvestigatorAffiliation ✓, ResponsiblePartyOldOrganization ✓, ResponsiblePartyInvestigatorTitle ✓
- **PatientSearch** (`query.patient`, UI: -): Acronym ✓, Condition ✓, BriefTitle ✓, OfficialTitle ✓, ConditionMeshTerm ✓, ConditionAncestorTerm ✓, BriefSummary ✓, Keyword ✓, InterventionName ✓, InterventionOtherName ✓, PrimaryOutcomeMeasure ✓, StdAge, … (47 fields)
