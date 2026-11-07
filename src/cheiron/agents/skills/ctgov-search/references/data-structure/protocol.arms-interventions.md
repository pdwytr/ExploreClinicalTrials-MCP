# Fields: armsInterventionsModule

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `ArmGroupLabel` | text | Arm Group Label | ✓; also: ARM-GROUP-LABEL |
| `ArmGroupType` | ArmGroupType | Arm Group Type | also: ARM-GROUP-TYPE, ARM-GROUP-TYPES |
| `ArmGroupDescription` | markup | Arm Description for INT, Group/Cohort Description for OBS | ✓; also: ARM-GROUP-DESCRIPTION |
| `ArmGroupInterventionName` | text[] | Arm/Group that Receives a Specific Intervention/Treatment | ✓; also: ARM-GROUP-INTERVENTION |
| `NumArmGroupInterventionNames` | short |  | search-only |
| `NumArmGroups` | short |  | search-only; also: NUMBER-OF-ARM-GROUPS |
| `InterventionType` | InterventionType | Intervention/Treatment Type | also: INTERVENTION-TYPE, INTERVENTION-TYPES |
| `InterventionName` | text | Intervention Name | ✓; also: INTERVENTION, INTERVENTIONS, INTERVENTION-NAME |
| `InterventionDescription` | markup | Intervention Description | ✓; also: INTERVENTION-DESCRIPTION |
| `InterventionArmGroupLabel` | text[] | Arm Group Label for Intervention. Arm/Group and Intervention Cross Reference | ✓ |
| `NumInterventionArmGroupLabels` | short |  | search-only |
| `InterventionOtherName` | text[] | Other Intervention Name | ✓; also: INTERVENTION-OTHER-NAME |
| `NumInterventionOtherNames` | short | Other Intervention Name Count | search-only |
| `NumInterventions` | short | Number of Interventions | search-only; also: NUMBER-OF-INTERVENTIONS |
