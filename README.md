# TrialSight

Ask a question about clinical trials in plain words and get one chart from
[ClinicalTrials.gov](https://clinicaltrials.gov). Every bar, point and line links to the trials it
counts.

> *How many phase 3 Alzheimer's trials started each year since 2015?*
> *Which sponsors run the most semaglutide trials?*
> *Compare phases for Ozempic vs Mounjaro trials.*
> *Which drugs are tested together in melanoma trials?*

It is built for people who need registry numbers they can defend: competitive-intelligence and
business-development analysts, clinical operations, consultants, investors and researchers.

## How it works

Claude reads the question, plans the search and picks the chart. Code does everything that can be
checked: it fetches every matching trial, checks the chart fits the data, counts distinct trials
and attaches the sources. **The model never produces a number**, so it cannot invent one.

Code also fixes what the registry gets wrong. For example, a search for "Ozempic" finds about 100
trials, but most of them are indexed as *semaglutide*. TrialSight sees this and searches both
names, and the chart says it did.

## Install

You need [uv](https://docs.astral.sh/uv/) (`brew install uv` or
`curl -LsSf https://astral.sh/uv/install.sh | sh`). No API key is needed.

### Claude Code

```
/plugin marketplace add pdwytr/trialsight
/plugin install trialsight@trialsight
/reload-plugins
```

Then ask a clinical-trials question. The `clinical-trials` subagent answers and gives a link to
the chart, such as `http://127.0.0.1:8765/?result=…`. To make sure Claude uses the plugin, say
*"use clinical-trials to …"*.

### Claude Desktop

Open **Settings → Developer → Edit Config** and add:

```json
{
  "mcpServers": {
    "trialsight": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/pdwytr/trialsight", "trialsight-mcp"]
    }
  }
}
```

Restart Desktop. The chart shows inside the conversation. If Desktop cannot find `uvx`, use the
full path that `which uvx` prints.

### Updating

```
/plugin marketplace update trialsight
uv cache clean trialsight
```

## Your saved answers

Every answer is saved in `~/.trialsight/results/` (set `TRIALSIGHT_HOME` to change the folder). To
browse them without Claude:

```bash
uvx --from git+https://github.com/pdwytr/trialsight trialsight-mcp serve
```

## What it can't do yet

- **Investigators and trial sites.** Questions about them, or about US states and cities, are
  refused with the reason.
- **Sponsor aliases.** The registry has no standard sponsor names, so "MSD" does not match Merck
  Sharp & Dohme LLC. Use the registered name.
- **Drug names in networks.** Nodes use the intervention name as each sponsor typed it, so one drug
  can appear under several names ("Daratumumab", "Darzalex"), and procedures such as
  "Biospecimen Collection" can appear as nodes.
- **Drug classes.** "GLP-1 agonists" has no registry field, so Claude expands it into member drugs
  from its own knowledge.

## Run it as a web service

TrialSight also runs without Claude, as a web page and an API. In this mode, the planning is done
by Pydantic AI agents, which need an OpenAI key.

```bash
git clone https://github.com/pdwytr/trialsight.git && cd trialsight
cp .env.example .env    # set OPENAI_API_KEY and TRIALSIGHT_PLANNER_MODEL
uv sync
uv run uvicorn trialsight.api.app:app --port 8765
```

Open http://localhost:8765/ for the page or http://localhost:8765/docs for the API. A demo runs at
https://cheiron-e7vsuq.fly.dev/.

## Development

```bash
uv run pytest                                          # unit tests, no API key needed
TRIALSIGHT_SOURCE=$PWD claude --plugin-dir ./plugin    # try local changes in Claude Code
uv run python scripts/vendor_web_assets.py             # refresh the pinned chart libraries
```

| Path | What it is |
|---|---|
| `plugin/` | the Claude Code plugin: MCP config and the `clinical-trials` subagent |
| `src/trialsight/mcp_server/` | the MCP server: tools, query sessions, saved results, local page |
| `src/trialsight/agents/` | the agent specs (shared by the plugin and the web service) |
| `src/trialsight/workflow/` | search plans, fetching, profiling, chart checks |
| `src/trialsight/visualize/` | counts, citations and the Vega-Lite chart |
| `src/trialsight/web/index.html` | the chart page, used everywhere |
| `evals/` | end-to-end cases against the live registry |

Data comes from the [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api). TrialSight
is not affiliated with the NIH or the NLM.
