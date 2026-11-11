# StudyTrials

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

StudyTrials is one MCP server. It works in any MCP client (Claude, Codex, Cursor, VS Code and
others) and uses that client's own model, so it needs no API key.

The model reads the question, plans the search and picks the chart. Code does everything that
can be checked: it fetches every matching trial, checks that the chart fits the data, counts
distinct trials and attaches the sources. **The model never produces a number**, so it cannot
invent one.

Code also fixes what the registry gets wrong. For example, a search for "Ozempic" finds about 100
trials, but most of them are indexed as *semaglutide*. StudyTrials sees this and searches both
names, and the chart says it did.

Where the chart shows depends on the client. Clients that support
[MCP Apps](https://modelcontextprotocol.io/extensions/apps), such as Claude Desktop, show it inside
the conversation. Every other client gets a link to a local page, such as
`http://127.0.0.1:8765/?result=…`.

## Install

You need [uv](https://docs.astral.sh/uv/) (`brew install uv` or
`curl -LsSf https://astral.sh/uv/install.sh | sh`). Every client runs the same command:

```
uvx studytrials-mcp@latest
```

With `@latest`, uv checks for a new release each time the server starts, so you get updates
without doing anything.

### Claude Code

```bash
claude mcp add -s user studytrials -- uvx studytrials-mcp@latest
```

Or install it as a plugin. The plugin adds a `clinical-trials` subagent, which answers in its own
context and keeps your conversation short:

```
/plugin marketplace add pdwytr/studytrials
/plugin install studytrials@studytrials
```

### Claude Desktop

Open **Settings → Developer → Edit Config** and add the following, then restart Desktop:

```json
{
  "mcpServers": {
    "studytrials": { "command": "uvx", "args": ["studytrials-mcp@latest"] }
  }
}
```

If Desktop cannot find `uvx`, use the full path that `which uvx` prints.

### Codex

```bash
codex mcp add studytrials -- uvx studytrials-mcp@latest
```

Or add this to `~/.codex/config.toml`. Fetching every trial for a large question can take a
minute, which is why `tool_timeout_sec` is raised:

```toml
[mcp_servers.studytrials]
command = "uvx"
args = ["studytrials-mcp@latest"]
tool_timeout_sec = 180
```

### Cursor

Add this to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "studytrials": { "command": "uvx", "args": ["studytrials-mcp@latest"] }
  }
}
```

### VS Code (Copilot agent mode)

```bash
code --add-mcp '{"name":"studytrials","command":"uvx","args":["studytrials-mcp@latest"]}'
```

### Any other MCP client

Add a stdio server with the command `uvx` and the argument `studytrials-mcp@latest`.

## Using it

Ask a clinical-trials question in plain words. If the client answers from its own knowledge
instead, say *"use studytrials to …"*.

The tools are `start_query`, `fetch_data`, `describe_data`, `build_chart`, `read_api_docs` and
`read_reference`. `start_query` returns the procedure the model follows, so any client's model
calls the tools in the right order. No tool changes anything outside your machine (`build_chart`
saves the answer locally), and every tool is marked read-only, which clients can use to skip
asking you for approval.

## Your saved answers

Every answer is saved in `~/.studytrials/results/` (set `STUDYTRIALS_HOME` to change the folder). To
browse them without an MCP client:

```bash
uvx studytrials-mcp@latest serve
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

StudyTrials also runs without Claude, as a web page and an API. In this mode, the planning is done
by Pydantic AI agents, which need an OpenAI key.

```bash
git clone https://github.com/pdwytr/studytrials.git && cd studytrials
cp .env.example .env    # set OPENAI_API_KEY and STUDYTRIALS_PLANNER_MODEL
uv sync
uv run uvicorn studytrials.api.app:app --port 8765
```

Open http://localhost:8765/ for the page or http://localhost:8765/docs for the API. A demo runs at
https://cheiron-e7vsuq.fly.dev/.

## Development

```bash
uv run pytest                                          # unit tests, no API key needed
STUDYTRIALS_SOURCE=$PWD claude --plugin-dir ./plugin    # try local changes in Claude Code
uv run python scripts/vendor_web_assets.py             # refresh the pinned chart libraries
```

| Path | What it is |
|---|---|
| `plugin/` | the Claude Code plugin: MCP config and the `clinical-trials` subagent |
| `src/studytrials/mcp_server/` | the MCP server: tools, query sessions, saved results, local page |
| `src/studytrials/agents/` | the agent specs (shared by the plugin and the web service) |
| `src/studytrials/workflow/` | search plans, fetching, profiling, chart checks |
| `src/studytrials/visualize/` | counts, citations and the Vega-Lite chart |
| `src/studytrials/web/index.html` | the chart page, used everywhere |
| `evals/` | end-to-end cases against the live registry |

Data comes from the [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api). StudyTrials
is not affiliated with the NIH or the NLM.
