# Example runs

Five questions, one per class from the brief, run against the live service with
`uv run python scripts/run_examples.py` (requests in `requests.json`). Each folder holds the
exact request and the actual JSON the API returned (`GET /queries/{id}` → `result`).

| Example | Question class | Request | Chart | Trials | Notes in the response |
|---|---|---|---|---|---|
| [`1-time-trend`](1-time-trend/response.json) | Time trend (the brief's own example request) | How has the number of trials for this drug changed over time? (+ drug_name: Pembrolizumab) | `time_series`: Pembrolizumab trials started over time | 3,003 | 10 trials with only estimated dates after the data date are left out of the time axis.; 2026 is partial: data as of 2026-11-06. |
| [`2-comparison`](2-comparison/response.json) | Comparison of two drugs | Compare phases for trials involving nivolumab vs pembrolizumab. | `grouped_bar_chart`: Trial phases: nivolumab vs pembrolizumab | 5,044 | – |
| [`3-geography`](3-geography/response.json) | Geographic pattern | Which countries have the most recruiting trials for multiple sclerosis? | `bar_chart`: Countries with the most recruiting multiple sclerosis trials | 382 | Showing the top 25 values of country; 31 smaller categories are left out. |
| [`4-network`](4-network/response.json) | Relationships: sponsor-drug network | Show a network of sponsors and drugs for Hodgkin lymphoma trials. | `network_graph`: Sponsors and drugs in Hodgkin lymphoma trials | 7,225 | Network shows the 40 most frequent of 7666 values. |
| [`5-scatter`](5-scatter/response.json) | Two numbers per trial: enrollment against duration | Do bigger heart failure trials take longer? Plot enrollment against duration. | `scatter_plot`: Enrollment vs trial duration in heart failure trials | 7,406 | 3174 trials without both values are left out (duration needs a start date and an actual primary completion).; 122 trials that enrolled no one (mostly withdrawn) left out. |

What to look at in each `response.json`:

- `visualization`: `type`, `title`, `encoding` (fields per channel, display `labels` for coded values), `data`
  (every row cites its trials: `citations` with exact excerpts and `nct_ids` listing every trial behind it).
- `meta`: `interpretation` (written by code from what was searched), `request_filters`, `filters_applied`
  (the exact API calls, the agent's intent, and names searched under the registry's standard name),
  `assumptions`, `warnings`, `units`, trial counts, data date and API version, and `chain` (every fetch).
- `vega_lite`: a ready-to-render Vega-Lite v5 spec (null for the network graph).

Sizes: the files are pretty-printed; the network and scatter responses are the largest because every
node, edge and point carries its sources.
