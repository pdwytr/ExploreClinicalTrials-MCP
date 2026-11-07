# Fields: Drug/Intervention Browse Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `InterventionMeshId` | text | Intervention MeSH ID. MeSH ID |  |
| `InterventionMeshTerm` | text | Intervention MeSH Term. MeSH Heading | ✓ |
| `NumInterventionMeshes` | short | Number of Intervention MeSH Terms | search-only |
| `InterventionAncestorId` | text | Intervention Ancestor MeSH ID. MeSH ID |  |
| `InterventionAncestorTerm` | text | Intervention Ancestor MeSH Term. MeSH Heading | ✓ |
| `NumInterventionAncestors` | short | Number of Intervention Ancestor MeSH Terms | search-only |
| `InterventionBrowseLeafId` | text | Intervention Leaf Topic ID | also: INTERVENTION-BROWSE-LEAF-ID |
| `InterventionBrowseLeafName` | text | Intervention Leaf Topic Name | ✓ |
| `InterventionBrowseLeafAsFound` | text | Found by Intervention Term. Normalized Intervention term used to find the topic | ✓ |
| `InterventionBrowseLeafRelevance` | BrowseLeafRelevance | Relevance to Intervention Leaf Topic |  |
| `NumInterventionBrowseLeafs` | short | Number of Intervention Leaf Topics | search-only |
| `InterventionBrowseBranchAbbrev` | text | Intervention Branch Topic Short Name | ✓; also: INTERVENTION-BROWSE-BRANCH-ABBREV |
| `InterventionBrowseBranchName` | text | Intervention Branch Topic Name | ✓ |
| `NumInterventionBrowseBranches` | short | Number of Intervention Branch Topics | search-only |
