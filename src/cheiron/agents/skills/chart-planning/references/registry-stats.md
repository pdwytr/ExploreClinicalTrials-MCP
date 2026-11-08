# Registry-wide statistics

Fields marked `from_registry_stats` in the profile come from a `stats/field/values` fetch: counts
over **all registered studies**, not over trials fetched for this question.

Rules (checked by code):
- Only a `bar_chart` of **one** field: `x` set, no `series`.
- `x` must be a field that the stats step fetched; otherwise add it to the stats step's fields and
  fetch again.
- These counts carry no per-trial citations; code says so in the response.

Title: say it covers the whole registry ("Most common conditions across all registered studies").
Use `top_n` for a ranking, as usual.

Example:
```json
{"intent": "ranking", "chart_type": "bar_chart", "title": "Interventions with the most registered studies", "x": "intervention", "top_n": 15}
```
