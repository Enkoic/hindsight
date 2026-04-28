# Architecture

## High-level pipeline

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  collectors  │───▶│    Store     │───▶│  summarizer  │───▶ exporters
│ (per source) │    │  (SQLite)    │    │ (LLM client) │
└──────────────┘    └──────────────┘    └──────────────┘
```

Every layer trades in the same primitive — `Event` (`hindsight/models.py`). A collector emits `Event`s; the store deduplicates them by fingerprint; the summarizer renders a digest from rows in the store and asks an LLM to produce a Markdown narrative; the exporter writes the narrative to disk / Notion / Obsidian.

The boundary between layers is intentionally narrow:

| Layer | Output type | Knows about |
| --- | --- | --- |
| Collector | `Iterable[Event]` | one source's on-disk format |
| Store | `sqlite3.Row` | events table, summary cache, rollup cache |
| Summarizer | `str` (Markdown) | how to compress events into an LLM prompt |
| Exporter | `Path` / URL | sink format (Notion blocks, Obsidian vault layout) |

A new collector or a new exporter only touches *one* of those rows; the others don't change.

## The Event schema

Defined in `hindsight/models.py`:

```python
@dataclass
class Event:
    source: str              # "claude_code" | "cursor" | …
    kind: str                # free-form sub-type within a source
    ts_start: datetime       # **UTC**
    ts_end: datetime | None  # UTC; None for point-in-time events
    title: str               # short human-readable label (≤ 200 chars)
    project: str | None      # cwd / project identifier when known
    body: str                # full payload (e.g. message text)
    meta: dict[str, Any]     # source-specific extras (session_id, urls, …)
```

### Time

All timestamps are **UTC** at the schema boundary. Each collector is responsible for converting source-local timestamps to UTC. The CLI converts UTC back to local-day buckets when filtering by `--day`. Mixing timezones inside the store would silently break `events_for_day`.

### Fingerprinting (dedup)

`Event.fingerprint()` is `sha1(source, kind, ts_start.isoformat(), title, project, body[:256])`. Notably it excludes `meta` and ignores body content past 256 chars. The reason:

- Re-collecting from a transcript that got *extended* (a session is still being written) shouldn't double-insert the earlier turns.
- Adding `meta.duration_sec` on a re-pass shouldn't dirty the row.

The store uses `INSERT OR IGNORE` keyed on `fingerprint`, so re-running `hindsight collect` is idempotent.

## Storage

`hindsight/store.py` owns three tables:

| Table | Purpose |
| --- | --- |
| `events` | normalized events, `fingerprint` PK |
| `summaries` | cached daily summaries keyed by `(day, provider, model)` |
| `rollups` | cached multi-day summaries keyed by `(start_day, end_day, provider, model)` |

The DB lives outside the repo at `~/Library/Application Support/hindsight/hindsight.sqlite` (macOS) / `$XDG_DATA_HOME/hindsight/` (Linux), with mode `0700/0600`. See `docs/configuration.md`.

The cache key includes provider+model so switching from `deepseek-v3-2` to `claude-sonnet-4-6` produces a *new* row instead of overwriting; you can run both side by side and diff.

## Summarizer

Two stages:

1. **`render_digest`** — pure Python. Compacts events into a structured Markdown document. ActivityWatch rows are aggregated into per-app minutes; Claude Code / Codex rows are grouped by session; memory / plan / task artefacts get their own section; histories are listed chronologically. The point is to get the LLM input down from "thousands of raw window switches" to "a paragraph per source".
2. **`Summarizer.complete(system, user, max_tokens)`** — abstract over Anthropic and OpenAI-compatible endpoints. Two thin concrete classes; both wrap the call in `_retry()` to absorb rate limits and 5xx.

Daily summarization uses `SYSTEM_PROMPT`. Rollup uses `ROLLUP_SYSTEM_PROMPT` and consumes already-cached daily summaries (not raw events) via `summarize_rollup`. That makes weekly/monthly cheap and avoids re-spending tokens on data the LLM has already seen.

## CLI

`hindsight/cli.py` is a Typer app. Each top-level command is a thin orchestrator:

- `collect` → `_collectors(cfg)` → `Store.upsert_events`
- `report` → `Store.events_for_day` → terminal table
- `summarize` → `render_digest` → `Summarizer.complete` → `Store.save_summary`
- `rollup` → `Store.summaries_in_range` → `summarize_rollup` → `Store.save_rollup`
- `export <target>` → reads cached summary or rollup → exporter
- `run` → orchestrates `collect → summarize → export`
- `schedule install/uninstall/show` → macOS launchd glue

`_resolve_range(--week / --month / --since/--until)` is shared by `rollup` and `export` so the same range syntax works in both places.

## Schedule (macOS launchd / Linux systemd)

`hindsight/schedule.py` exposes a platform-aware `install()` / `uninstall()` / `show_paths()` triple:

- **macOS**: writes `~/Library/LaunchAgents/io.github.enkoic.hindsight.plist`, tries `launchctl bootstrap gui/$UID …` (modern), falls back to `launchctl load`. Logs go to `~/Library/Logs/hindsight/`.
- **Linux**: writes `~/.config/systemd/user/hindsight.service` + `hindsight.timer`, then runs `systemctl --user daemon-reload && systemctl --user enable --now hindsight.timer`. Logs go to `~/.local/state/hindsight/` (created up-front because systemd's `append:` doesn't `mkdir -p`).

Both run `hindsight run --day yesterday --targets <…>` daily. The CLI uses the façade (`schedule_mod.install()`) so it works on either OS without branching logic in `cli.py`.

## Redaction

`hindsight/redact.py` defines `DEFAULT_RULES` (Anthropic / OpenAI / Ark / GitHub / AWS / Slack / Google API keys, JWTs, bearer headers, private IPv4, emails, `sshpass -p`). Each rule has a stable placeholder so the LLM still knows *something* was there.

The redactor runs on the **digest** (the prompt we POST to the LLM), not on the events table — keeping raw text in the store is intentional, since you might want to grep for it later. Both `summarize` and `rollup` have `--redact/--no-redact` flags; default is on. Users can extend with `HINDSIGHT_REDACT_FILE=path.tsv` (`name<TAB>regex<TAB>placeholder`); user rules go *first* so they pre-empt defaults.

When a redaction fires, the CLI prints `[yellow]redacted[/yellow] {rule_name: count}` so you can audit what got stripped.

## Maintenance

`hindsight purge` accepts `--older-than DAYS` and/or `--source NAME[,NAME…]`, refuses an unfiltered call, and runs `VACUUM` after the delete (skip with `--no-vacuum`). Cached daily summaries and rollups are *not* touched — they're cheap to keep and let you reconstruct what was deleted from the events. The `--yes` confirmation gate is mandatory.

## What not to put in this repo

- Raw transcripts: stay in the SQLite DB, never committed.
- API keys: only in `.env` (git-ignored). `.env.example` is the public template.
- Per-machine paths in code: derive at runtime from `XDG_DATA_HOME` / `os.uname()` / env vars.
