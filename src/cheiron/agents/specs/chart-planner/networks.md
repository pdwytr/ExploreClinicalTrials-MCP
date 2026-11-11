# Network graphs

A network shows which values occur **in the same trials**. `x` and `series` are the two node kinds;
the **same field twice** means co-occurrence within a trial (e.g. drugs combined in one trial).

What code draws:
- **Node** = one value of `x` or `series`; its size = trials with that value.
- **Edge** = two values that appear in the same trial; its weight = trials that have both.
- Code keeps the 40 most frequent values and the 150 heaviest edges, and says so in a warning.
  Values that differ only by case or spacing ("Rituximab", "rituximab ") are one node.

## Choosing the two node kinds

| Question | `x` | `series` |
| --- | --- | --- |
| Which sponsors develop which drugs | `lead_sponsor` | `intervention` |
| Drugs used together, combination therapies | `intervention` | `intervention` |
| Which drugs are tested for which conditions | `condition` | `intervention` |
| Which conditions a sponsor works on | `lead_sponsor` | `condition` |
| Conditions studied together | `condition` | `condition` |
| Where each sponsor runs trials | `lead_sponsor` | `country` |

## Checks before answering

- Both fields must exist in the profile with few missing trials; co-occurrence needs `multi_valued`
  (a trial with one intervention cannot link to another).
- A network needs a single search (or comparison sides you do not need to show): `group` is not a
  node kind.
- The title names both node kinds and the population ("Sponsors and drugs in glioblastoma trials").

## Examples

Sponsors and the drugs they test:
```json
{"intent": "relationship", "chart_type": "network_graph", "title": "Sponsors and drugs in glioblastoma trials", "x": "lead_sponsor", "series": "intervention"}
```

Drugs used together:
```json
{"intent": "relationship", "chart_type": "network_graph", "title": "Drugs combined in pancreatic cancer trials", "x": "intervention", "series": "intervention"}
```
