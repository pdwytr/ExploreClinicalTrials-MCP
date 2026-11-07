# Fields: Contacts Locations Measure Module

Legend: ⤷ = nested group, use SEARCH[Name](...) to match fields within one item; ✓ = synonyms matched; search-only = usable in AREA[...] but not returned in records.
Generated from `docs/ctgov/metadata.json` (API 2.0.5) by scripts/build_ctgov_skill.py.


| Field | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `CentralContactName` | text | Central Contact Name |  |
| `CentralContactRole` | ContactRole | Central Contact Role. Role for any Central Contact added |  |
| `CentralContactPhone` | text | Central Contact Phone |  |
| `CentralContactPhoneExt` | text | Central Contact Phone Ext |  |
| `CentralContactEMail` | text | Central Contact EMail |  |
| `NumCentralContacts` | short | Number of Central Contacts | search-only |
| `OverallOfficialName` | text | Overall Official Name |  |
| `OverallOfficialAffiliation` | text | Overall Official Affiliation |  |
| `OverallOfficialRole` | OfficialRole | Overall Official Role |  |
| `NumOverallOfficials` | short | Number of Overall Officials | search-only |
| `Location` | Location[] | Location | ⤷ SEARCH[Location] |
| `LocationFacility` | text | Facility Name | also: LOCATION-NAME, FACILITY |
| `LocationStatus` | RecruitmentStatus | Individual site recruitment status | also: LOCATION-STATUS |
| `LocationCity` | GeoName | City | also: LOCATION-CITY, CITY |
| `LocationState` | GeoName | State | also: LOCATION-STATE, STATE |
| `LocationZip` | text | Zipcode | also: LOCATION-ZIP |
| `LocationCountry` | text | Country | also: LOCATION-COUNTRY, COUNTRY, COUNTRIES |
| `LocationContactName` | text | Location Contact Name |  |
| `LocationContactRole` | ContactRole | Location Contact Role |  |
| `LocationContactPhone` | text | Location Contact Phone |  |
| `LocationContactPhoneExt` | text | Location Contact Phone Ext |  |
| `LocationContactEMail` | text | Location Contact EMail |  |
| `NumLocationContacts` | short | Number of Individual Location Contacts | search-only |
| `LocationCountryCode` | keyword | ISO Country Code | search-only |
| `LocationGeoPoint` | GeoPoint | Location Geo Point |  |
| `NumLocations` | short | Number of Individual Sites/Locations | search-only; also: NUMBER-OF-LOCATIONS |
| `NumUniqueLocationCountries` | short | Num Unique Measure Location Countries | search-only; also: NUMBER-OF-COUNTRIES |
