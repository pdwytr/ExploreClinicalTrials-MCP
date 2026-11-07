# Fields: Outcome Measure Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `OutcomeMeasureType` | OutcomeMeasureType | Outcome Measure Type |  |
| `OutcomeMeasureTitle` | text | Outcome Measure title | ✓ |
| `OutcomeMeasureDescription` | markup | Outcome Measure Description | ✓ |
| `OutcomeMeasurePopulationDescription` | markup | Analysis Population Description | ✓ |
| `OutcomeMeasureReportingStatus` | ReportingStatus | Reporting Status. Whether there is Outcome Measure Data reported |  |
| `OutcomeMeasureAnticipatedPostingDate` | PartialDate | Anticipated Reporting Date |  |
| `OutcomeMeasureParamType` | MeasureParam | Outcome Measure Data Type |  |
| `OutcomeMeasureDispersionType` | text | Outcome Measure Dispersion/Precision | ✓ |
| `OutcomeMeasureUnitOfMeasure` | text | Unit of Measure | ✓ |
| `OutcomeMeasureCalculatePct` | boolean | Calculated Percentage. percentage of OutcomeMeasurementValue/OutcomeMeasureDenomCountValue (internally calculated) |  |
| `OutcomeMeasureTimeFrame` | text | Outcome Measure Time Frame | ✓ |
| `OutcomeMeasureTypeUnitsAnalyzed` | text | Units Analyzed | ✓ |
| `OutcomeMeasureDenomUnitsSelected` | text | . OutcomeMeasureTypeUnitsAnalyzed | ✓ |
| `OutcomeGroupId` | text |  | ✓ |
| `OutcomeGroupTitle` | text |  | ✓ |
| `OutcomeGroupDescription` | markup |  | ✓ |
| `NumOutcomeGroups` | short |  | search-only |
| `OutcomeDenomUnits` | text |  | ✓ |
| `OutcomeDenomCountGroupId` | text |  | ✓ |
| `OutcomeDenomCountValue` | text |  | ✓ |
| `NumOutcomeDenoms` | short |  | search-only |
| `OutcomeClassTitle` | text |  | ✓ |
| `OutcomeClassDenomUnits` | text |  | ✓ |
| `OutcomeClassDenomCountGroupId` | text |  | ✓ |
| `OutcomeClassDenomCountValue` | text |  | ✓ |
| `OutcomeCategoryTitle` | text | Category Title | ✓ |
| `OutcomeMeasurementGroupId` | text | Group ID | ✓ |
| `OutcomeMeasurementValue` | text | data | ✓ |
| `OutcomeMeasurementSpread` | text | data | ✓ |
| `OutcomeMeasurementLowerLimit` | text | data | ✓ |
| `OutcomeMeasurementUpperLimit` | text | data | ✓ |
| `OutcomeMeasurementComment` | markup | Comments for N/A values | ✓ |
| `NumOutcomeMeasurements` | short |  | search-only |
| `NumOutcomeCategories` | short |  | search-only |
| `NumOutcomeClasses` | short |  | search-only |
| `OutcomeAnalysisParamType` | text | Estimation Parameter | ✓ |
| `OutcomeAnalysisParamValue` | text | Estimated Value |  |
| `OutcomeAnalysisDispersionType` | AnalysisDispersionType | Estimation Dispersion Type |  |
| `OutcomeAnalysisDispersionValue` | text | Parameter Dispersion Value | ✓ |
| `OutcomeAnalysisStatisticalMethod` | text | Statistical Method | ✓ |
| `OutcomeAnalysisStatisticalComment` | markup | Statistical Comment | ✓ |
| `OutcomeAnalysisPValue` | text | P-Value |  |
| `OutcomeAnalysisPValueComment` | markup | P-Value Comment | ✓ |
| `OutcomeAnalysisCINumSides` | ConfidenceIntervalNumSides | Number of Sides for Confidence Interval |  |
| `OutcomeAnalysisCIPctValue` | text | Percentage for Confidence Interval | ✓ |
| `OutcomeAnalysisCILowerLimit` | text | Lower Limit for 2-sided Confidence Interval | ✓ |
| `OutcomeAnalysisCIUpperLimit` | text | Upper Limit for 2-sided Confidence Interval | ✓ |
| `OutcomeAnalysisCILowerLimitComment` | markup | Lower Limit Comment. Confidence Interval - lower limit comment | ✓ |
| `OutcomeAnalysisCIUpperLimitComment` | markup | Upper Limit Comment. Confidence Interval - upper limit comment (Explain why the upper limit data are not available, if "NA" is reported as upper-limit of "2-sided" confidence interval.) | ✓ |
| `OutcomeAnalysisEstimateComment` | markup | Estimation Comment | ✓ |
| `OutcomeAnalysisTestedNonInferiority` | boolean | Non-inferiority or Equivalence Test Type |  |
| `OutcomeAnalysisNonInferiorityType` | NonInferiorityType | Type of Statistical Test |  |
| `OutcomeAnalysisNonInferiorityComment` | markup | Non-inferiority or Equivalence Comment | ✓ |
| `OutcomeAnalysisOtherAnalysisDescription` | markup | Other Statistical Analysis | ✓ |
| `OutcomeAnalysisGroupDescription` | markup | Selected Comparison Group Description | ✓ |
| `OutcomeAnalysisGroupId` | text[] |  | ✓ |
| `NumOutcomeAnalysisGroupIds` | short | Number of selected Arm/Groups for Analysis. Number of comparison groups selected for an Analysis (internal count) | search-only |
| `NumOutcomeAnalyses` | short | Number of Analysis. Number of Analyses per Outcome Measure (internally calculated) | search-only |
| `NumOutcomeMeasures` | short | Number of Outcome Measures. Number of Outcome Measures (internally calculated) | search-only |
