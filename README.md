# hindsight

> *"What did I actually do today? Which AI did I ask for help? What got solved? What's still open?"*

`hindsight` aggregates your daily activity across **ActivityWatch**, **Claude Code**, **Codex CLI**, and other AI-dialog sources into a single local SQLite store, then asks an LLM to turn the raw mess into a readable daily digest. Export to Markdown, JSON, or push straight to a Notion database.

## Why

Personal activity is fragmented across many tools. Each one has its own log format and UI. `hindsight` reads them where they already live on disk, normalizes them into one schema, and lets an LLM summarize. No agents in the cloud, no SaaS lock-in — just a small Python CLI and a SQLite file.

## Data sources

| Source | Where | What |
| --- | --- | --- |
| ActivityWatch | `http://localhost:5600` REST API | window / afk / web buckets |
| Claude Code — sessions | `~/.claude/projects/*/*.jsonl` | session transcripts |
| Claude Code — memories | `~/.claude/projects/*/memory/*.md` | long-term memory files (user / project / feedback / reference) |
| Claude Code — plans | `~/.claude/plans/*.md` | design plans |
| Claude Code — tasks | `~/.claude/tasks/<session>/*.json` | TaskCreate snapshots + status |
| Claude Code — history | `~/.claude/history.jsonl` | every prompt you typed (project-tagged) |
| Codex CLI — sessions | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | session rollouts |
| Codex CLI — history | `~/.codex/history.jsonl` | every prompt you typed |
| _(pluggable)_ | your collector | subclass `Collector` |

Adding a new source = one file under `hindsight/collectors/` that yields `Event` objects.

## Install

```bash
git clone https://github.com/Enkoic/hindsight.git
cd hindsight
uv venv && source .venv/bin/activate     # or: python -m venv .venv && source .venv/bin/activate
uv pip install .                         # or: pip install .
cp .env.example .env                     # fill in API keys
```

### Requirements

- Python 3.10+
- [ActivityWatch](https://activitywatch.net/) running locally (optional)
- An Anthropic or OpenAI API key for summarization (any OpenAI-compatible endpoint works — DeepSeek, Volcengine Ark, local llama.cpp, etc. via `OPENAI_BASE_URL`)
- A Notion internal integration token + database id (optional, for Notion export)

## Usage

```bash
# 1. pull recent events from all sources into the local SQLite store
hindsight collect

# 2. terminal sanity check — no LLM call
hindsight report --day today

# 3. LLM digest (cached in SQLite by provider/model)
hindsight summarize --day today

# 4. export
hindsight export markdown --day today      # ./out/2026-04-22.md
hindsight export json     --day today      # ./out/2026-04-22.json
hindsight export notion   --day today      # new page in your Notion DB

# one-shot: collect → summarize → export markdown
hindsight run --day today --targets markdown,notion
```

`--day` accepts `today`, `yesterday`, or an ISO date (`2026-04-22`).

## Notion setup

1. Create a Notion [internal integration](https://www.notion.so/my-integrations) and copy the secret into `NOTION_TOKEN`.
2. Create a Notion database (must have a **title** property; a **Date** property is optional but recommended). Share the database with your integration.
3. Copy the database id from the URL (`https://www.notion.so/<workspace>/<DATABASE_ID>?v=…`) into `NOTION_DATABASE_ID`.

The exporter converts the LLM's Markdown into Notion blocks (`heading_1..3`, `bulleted_list_item`, `paragraph`). Code/table blocks are intentionally kept minimal — the digest is conversational prose, not docs.

## Architecture

```
collectors/*            → normalize to Event{source, kind, ts_start, ts_end, title, project, body, meta}
    ↓
Store (SQLite, ~/Library/Application Support/hindsight/hindsight.sqlite by default)
    ↓
summarizer.render_digest()   → compact text the LLM can reason over
    ↓
Summarizer (Anthropic | OpenAI-compatible)
    ↓
exporters/{markdown, json, notion}
```

### The digest step

We never send raw ActivityWatch windows to the LLM — that's thousands of rows for a normal day. `render_digest` aggregates:

- ActivityWatch → per-app minutes, top window titles, web activity, afk totals
- Claude Code / Codex sessions → grouped by session, with only user/assistant messages kept
- Memories / plans / tasks → a list of what was created or updated that day (not the raw body of every file)
- History → chronological user-prompt stream grouped by project (gives the LLM a ground-truth timeline even when a session transcript is noisy)

That keeps the prompt small enough to run on Haiku / 4o-mini / DeepSeek if you want to cut cost.

### Extending

To add a source (e.g. Cursor, ChatGPT export, Linear activity):

```python
# hindsight/collectors/cursor.py
from .base import Collector
from ..models import Event

class CursorCollector(Collector):
    name = "cursor"
    def collect(self, since, until):
        for record in my_parser():
            yield Event(source=self.name, kind="message", ts_start=..., ...)
```

Register it in `collectors/__init__.py` and `cli._collectors()`.

## Privacy

Everything runs locally. The only network calls are:

- ActivityWatch HTTP (localhost)
- Your chosen LLM provider (only when you run `summarize`)
- Notion API (only when you run `export notion`)

The SQLite DB lives outside the repo by default, in the OS-appropriate data dir:

- macOS: `~/Library/Application Support/hindsight/hindsight.sqlite`
- Linux: `$XDG_DATA_HOME/hindsight/` or `~/.local/share/hindsight/`

The data dir is created with mode `0700` and the DB file with `0600` — raw transcripts are treated as private. `./out/` (Markdown exports) and `.env` are in `.gitignore`. Override the DB path with `HINDSIGHT_DB=/some/path.sqlite`.

## Roadmap

- [ ] Cursor / VS Code chat collector
- [ ] ChatGPT export (`conversations.json`) collector
- [ ] Weekly / monthly rollup summaries
- [ ] Obsidian exporter
- [ ] Watch mode (continuous collect + daily cron summarize)

## License

MIT
