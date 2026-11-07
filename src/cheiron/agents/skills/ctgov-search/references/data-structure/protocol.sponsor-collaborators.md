# Fields: sponsorCollaboratorsModule

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `ResponsiblePartyType` | ResponsiblePartyType | Responsible Party Type | also: RESPONSIBLE-PARTY-TYPE |
| `ResponsiblePartyInvestigatorFullName` | text | Responsible Party Investigator Full Name | ✓ |
| `ResponsiblePartyInvestigatorTitle` | text | Responsible Party Investigator Title | ✓ |
| `ResponsiblePartyInvestigatorAffiliation` | text | Responsible Party Investigator Affiliation | ✓ |
| `ResponsiblePartyOldNameTitle` | text | Older format for Responsible Party Investigator Title | ✓ |
| `ResponsiblePartyOldOrganization` | text | Older format for Responsible Party Investigator Organization | ✓ |
| `LeadSponsorName` | text | Lead Sponsor Name | also: SPONSOR, LEAD-SPONSOR |
| `LeadSponsorClass` | AgencyClass | Lead Sponsor Type. Sponsor organization type: Type of lead sponsor | also: LEAD-SPONSOR-CLASS |
| `CollaboratorName` | text | Collaborator Name | also: COLLABORATOR |
| `CollaboratorClass` | AgencyClass | Collaborator Type. Type of collaborator | also: COLLABORATOR-CLASS |
| `NumCollaborators` | short | Number of Collaborators for a study. number of collaborators | search-only |
| `NumCollaboratorsPlusLead` | short | Number of Collaborators Plus Lead Sponsor | search-only |
