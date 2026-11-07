# Fields: Condition Browse Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `ConditionMeshId` | text | Condition MeSH ID. MeSH ID |  |
| `ConditionMeshTerm` | text | Condition MeSH Term. MeSH Heading | ✓ |
| `NumConditionMeshes` | short | Number of Condition MeSH Terms. Number of condition MeSH terms | search-only |
| `ConditionAncestorId` | text | Condition Ancestor MeSH ID. MeSH ID |  |
| `ConditionAncestorTerm` | text | Condition Ancestor MeSH Term. MeSH Heading | ✓ |
| `NumConditionAncestors` | short | Number of Condition Ancestor MeSH Terms | search-only |
| `ConditionBrowseLeafId` | text | Condition Leaf Topic ID | also: CONDITION-BROWSE-LEAF-ID |
| `ConditionBrowseLeafName` | text | Condition Leaf Topic Name | ✓ |
| `ConditionBrowseLeafAsFound` | text | Found by Condition Term. Normalized Condition term used to find the topic | ✓ |
| `ConditionBrowseLeafRelevance` | BrowseLeafRelevance | Relevance to Condition Leaf Topic |  |
| `NumConditionBrowseLeafs` | short | Number of Condition Leaf Topics | search-only |
| `ConditionBrowseBranchAbbrev` | text | Condition Branch Topic Short Name | ✓; also: CONDITION-BROWSE-BRANCH-ABBREV |
| `ConditionBrowseBranchName` | text | Condition Branch Topic Name | ✓ |
| `NumConditionBrowseBranches` | short | Number of Condition Branch Topics | search-only |
