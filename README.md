# hindsight

> *"What did I actually do today? Which AI did I ask for help? What got solved? What's still open?"*

`hindsight` aggregates your daily activity across **ActivityWatch**, **Claude Code**, **Codex CLI**, and other AI-dialog sources into a single local SQLite store, then asks an LLM to turn the raw mess into a readable daily digest. Export to Markdown, JSON, Notion, Obsidian, or Slack/Discord-compatible webhooks.

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
| Cursor IDE | `~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb` + `globalStorage/state.vscdb` | per-workspace prompts + global `cursorDiskKV` bubbles (full user + assistant turns) |
| VS Code Copilot Chat | `~/Library/Application Support/Code/User/workspaceStorage/*/state.vscdb` | `interactive.sessions` + `inlineChat.history` (auto-detects Code-Insiders / VSCodium) |
| ChatGPT export | `<export>/conversations.json` | OpenAI data-export conversations (point at the unzipped folder) |
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

## Support status

This project is usable today, but the support level is not identical across platforms:

| Area | macOS | Linux | Windows |
| --- | --- | --- | --- |
| collect / summarize / export | first-class | supported | not supported yet |
| schedule install/show/uninstall | `launchd` | `systemd --user` | not supported |
| auto-detect Cursor / VS Code paths | supported | partially supported | not supported |

If you want Windows support or another source/export target, open an issue with the exact local data format and expected workflow.

## Usage

```bash
# 1. pull recent events from all sources into the local SQLite store
hindsight collect

# 2. terminal sanity check — no LLM call
hindsight report --day today

# 3. LLM digest (cached in SQLite by provider/model)
hindsight summarize --day today

# 4. export
hindsight export markdown --day today      # <data-dir>/exports/2026-04-22.md
hindsight export json     --day today      # <data-dir>/exports/2026-04-22.json
hindsight export notion   --day today      # new page in your Notion DB
hindsight export obsidian --day today      # daily note in your Obsidian vault
hindsight export webhook  --day today      # POST to a Slack/Discord incoming webhook

# one-shot: collect → summarize → export markdown
hindsight run --day today --targets markdown,notion
```

`--day` accepts `today`, `yesterday`, or an ISO date (`2026-04-22`).

### Example output

The summary is meant to be compact and retrospective rather than a raw log dump. A typical output looks like:

```md
## 概览 / Overview
今天主要围绕 `hindsight` 的导出链路和调度支持收尾，集中处理了 webhook 导出、Linux 定时任务和文档补齐。

## 时间分布 / Time Breakdown
- 代码实现与调试：约 3.5 小时
- 文档与配置整理：约 1 小时
- AI 对话与排障：约 45 分钟

## 已解决 / Solved
- 接入 Slack / Discord webhook 导出
- 为 Linux 增加 `systemd --user` 调度支持
- 补齐 `.env.example` 与配置文档

## 进行中 / In Progress
- 优化 ChatGPT export 的导入体验
- 继续扩充 collector 测试夹具
```

### Weekly / monthly rollup

`rollup` synthesizes already-cached daily summaries into a multi-day narrative — throughlines, finished vs in-flight, recurring blockers — instead of just concatenating them.

```bash
hindsight rollup --week 2026-W17                   # ISO week
hindsight rollup --month 2026-04                   # full month
hindsight rollup --since 2026-04-20 --until 2026-04-26
hindsight rollup --week 2026-W17 --fill-missing    # auto-summarize any uncached day in range first
```

### Run on a daily schedule (macOS or Linux)

```bash
hindsight schedule install --hour 23 --minute 0 --targets markdown,obsidian
hindsight schedule show       # prints the unit/plist path(s) for this platform
hindsight schedule uninstall
```

The CLI auto-detects the platform:

- **macOS**: writes `~/Library/LaunchAgents/io.github.enkoic.hindsight.plist`, then `launchctl bootstrap`s it. Logs land in `~/Library/Logs/hindsight/`.
- **Linux**: writes `~/.config/systemd/user/hindsight.{service,timer}` and runs `systemctl --user enable --now hindsight.timer`. Logs land in `~/.local/state/hindsight/`.

Both paths run `hindsight run --day yesterday --targets <…>` once a day.

### Inspect what's in the store

```bash
hindsight stats
```

Shows total events per source, time span, cached summary/rollup counts, current provider/model — useful before deciding whether to run a fresh `summarize` or `rollup`.

### Ask questions over your history

```bash
hindsight ask "上周还有哪些待办没解决，按紧急度排序"
hindsight ask "What did I solve on 2026-04-22?"
hindsight ask "When did I first start the theme project?"
```

`ask` uses your cached daily summaries and rollups as evidence (no extra LLM calls to re-summarize). Dates referenced in the question (`2026-04-22`) get pinned to the front of the context so they always survive the budget trim.

### Diagnose your setup

```bash
hindsight doctor                    # also pings the LLM (~5 tokens)
hindsight doctor --no-ping          # skip the LLM probe
```

Walks every collector path, every exporter config, store integrity & permissions, scheduler state, and redact rules — printing a status table so you can see what's wired up at a glance.

### Redaction (privacy before LLM)

`summarize` and `rollup` strip API keys, JWTs, bearer tokens, private IPs, emails, and `sshpass -p <secret>` from the digest *before* it hits the LLM. Defaults cover OpenAI / Anthropic / Volcengine Ark / GitHub / AWS / Slack / Google API keys and JWTs. Add your own:

```bash
# rules.tsv  — name<TAB>regex<TAB>placeholder
project_codename<TAB>Project Apollo<TAB><PROJECT>
internal_host<TAB>\bhost\d+\.corp\.internal\b<TAB><INTERNAL_HOST>
```

```bash
HINDSIGHT_REDACT_FILE=./rules.tsv hindsight summarize --day today
```

The store keeps raw transcripts intact — redaction only applies to what we send to the LLM. Disable per-call with `--no-redact`.

### Purge / clean up the store

```bash
hindsight purge --older-than 90 --yes              # drop events ts > 90d ago
hindsight purge --source cursor --yes              # forget one source entirely
hindsight purge --older-than 30 --source codex --yes
```

Cached daily summaries and rollups are kept; only raw events are removed. `VACUUM` runs after delete unless you pass `--no-vacuum`.

## Privacy and security model

`hindsight` is intentionally local-first:

- raw transcripts and normalized events stay in a local SQLite DB outside the repo by default
- the data dir is created with `0700` permissions and the DB file with `0600`
- LLM calls happen only when you run `summarize` or `rollup`
- exporters are sinks only: they do not mutate the store or re-run the LLM
- redaction runs on the digest before it is sent to the LLM; the store keeps the original source text

Network calls are limited to:

- ActivityWatch on `localhost`
- your configured LLM provider
- Notion API when you export to Notion
- Slack/Discord-compatible webhook endpoint when you export to webhook

If you find a privacy leak, missing redaction, unsafe file permission, or another security problem, follow [SECURITY.md](./SECURITY.md) and do not post the raw evidence publicly.

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
exporters/{markdown, json, notion, obsidian, webhook}
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

## Contributing

- Read [CONTRIBUTING.md](./CONTRIBUTING.md) for local setup and contribution conventions.
- Read [docs/architecture.md](./docs/architecture.md) first if you want the system overview.
- New collectors and exporters usually only need one file plus CLI/config/docs wiring.
- Public bug reports should avoid pasting secrets or raw transcripts; use redacted snippets and exact commands instead.

The repository includes GitHub issue templates, a pull request template, and CI for `pytest -q` plus `ruff check`.

## Roadmap

- [x] Cursor IDE chat collector
- [x] VS Code Copilot Chat collector (works on Code, Code-Insiders, VSCodium)
- [x] ChatGPT export (`conversations.json`) collector
- [x] Weekly / monthly rollup summaries
- [x] Obsidian exporter
- [x] Daily-schedule mode (macOS launchd + Linux systemd `--user` via `hindsight schedule`)
- [x] `hindsight stats` for store inspection
- [x] Slack / Discord webhook exporter
- [x] Regex-based redaction filter (default + user-extensible) for digest payloads
- [x] `hindsight purge` for store maintenance
- [ ] Auto-detect & unzip ChatGPT export ZIP
- [ ] Linear / Jira activity collector

## License

MIT
