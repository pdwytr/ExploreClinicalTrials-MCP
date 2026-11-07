# Fields: Baseline Measure Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `BaselinePopulationDescription` | markup | Baseline Analysis Population Description | ✓ |
| `BaselineTypeUnitsAnalyzed` | text | Type of Units Analyzed | ✓ |
| `BaselineGroupId` | text | Arm/Group ID. Internally generated ID | ✓ |
| `BaselineGroupTitle` | text | Arm/Group Title | ✓ |
| `BaselineGroupDescription` | markup | Arm/Group Description | ✓ |
| `NumBaselineGroups` | short | Number of Baseline Arm/Groups. Number of Arm/Groups for Baseline | search-only |
| `BaselineDenomUnits` | text | Overall Number of Units Analyzed | ✓ |
| `BaselineDenomCountGroupId` | text | Arm/Group ID. Internally generated ID for each Arm/Group | ✓ |
| `BaselineDenomCountValue` | text |  | ✓ |
| `NumBaselineDenoms` | short | . Number of BaselineDenomUnits (Row) | search-only |
| `BaselineMeasureTitle` | text | Baseline Measure Title | ✓ |
| `BaselineMeasureDescription` | markup | Baseline Measure Title for Study-Specified Measure | ✓ |
| `BaselineMeasurePopulationDescription` | markup | Baseline Measure Description | ✓ |
| `BaselineMeasureParamType` | MeasureParam | Baseline Measure Type |  |
| `BaselineMeasureDispersionType` | MeasureDispersionType | Baseline Measure Dispersion/Precision |  |
| `BaselineMeasureUnitOfMeasure` | text | Unit of Measure | ✓ |
| `BaselineMeasureCalculatePct` | boolean | Calculated Percentage. percentage of BaselineMeasurementValue/BaselineMeasureDenomCountValue |  |
| `BaselineMeasureDenomUnitsSelected` | text | Type of Units Selected | ✓ |
| `BaselineMeasureDenomUnits` | text | Analysis Population Type | ✓ |
| `BaselineMeasureDenomCountGroupId` | text | . Internally generated ID for each Arm/Group | ✓ |
| `BaselineMeasureDenomCountValue` | text |  | ✓ |
| `NumBaselineMeasureDenoms` | short |  | search-only |
| `BaselineClassTitle` | text | Baseline RowTitle | ✓ |
| `BaselineClassDenomUnits` | text | Baseline Row Unit of Measure. Possible analysis population when data are presented in rows (e.g., if units other than participants are included in baseline, both participants and the units are listed as BaselineClassDenomUnits for the applicable baseline measure) | ✓ |
| `BaselineClassDenomCountGroupId` | text | . Internal ID per Arm/Group for a Baseline Measure | ✓ |
| `BaselineClassDenomCountValue` | text | . Data per Arm/Group per Baseline Measure per Row | ✓ |
| `BaselineCategoryTitle` | text | Category Title | ✓ |
| `BaselineMeasurementGroupId` | text | Arm/Group ID. Internal ID per Arm/Group per Category | ✓ |
| `BaselineMeasurementValue` | text | data | ✓ |
| `BaselineMeasurementSpread` | text | data. Data per Arm/Group per Category. Based on Measure Type and Measure of Dispersion (e.g., Standard Deviation) | ✓ |
| `BaselineMeasurementLowerLimit` | text | data. Data per Arm/Group per Category. Based on Measure Type and Measure of Dispersion (e.g., lower limit of Full Range) | ✓ |
| `BaselineMeasurementUpperLimit` | text | data. Data per Arm/Group per Category. Based on Measure Type and Measure of Dispersion (e.g., upper limit of Full Range) | ✓ |
| `BaselineMeasurementComment` | markup | Comments for N/A values. Explain why baseline measure data are not available, if "NA" is reported for Baseline Measure Data. | ✓ |
| `NumBaselineMeasurements` | short | Number of Arm/Groups. Number of Baseline Arm/Groups (internally calculated) | search-only |
| `NumBaselineCategories` | short | Number of Categories. Number of categories per Baseline Measure | search-only |
| `NumBaselineClasses` | short | . Number of classes (rows) per Baseline Measure (internally calculated) | search-only |
| `NumBaselineMeasures` | short | Number of Baseline Measures. Number of Baseline Measures (internally calculated) | search-only |
