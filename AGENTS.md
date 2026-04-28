# AGENTS.md

Notes for Codex (or any AI agent) working in this repo. Humans should read [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [`docs/`](./docs) instead.

## What this repo is

`hindsight` aggregates per-machine activity across **ActivityWatch / Codex / Codex CLI / Cursor / ChatGPT export** into a local SQLite store, then asks an LLM to write a daily digest. Output goes to Markdown / JSON / Notion / Obsidian. There is also a weekly/monthly rollup and a macOS launchd schedule helper. See `docs/architecture.md`.

## Where things live

```
hindsight/
├── cli.py             # typer entry points; one command per pipeline stage
├── config.py          # env vars → Config; data dir resolution; 0700/0600 perms
├── models.py          # Event + fingerprint
├── store.py           # 3 tables: events / summaries / rollups
├── schedule.py        # macOS launchd plist + bootstrap
├── collectors/{base,activitywatch,Codex,codex,cursor,chatgpt,history}.py
├── summarizer/llm.py  # render_digest + render_rollup_digest + Anthropic/OpenAI clients
└── exporters/{markdown,json,notion,obsidian}.py
tests/                 # pytest, no network, runs in <0.1s
docs/                  # architecture / collectors / exporters / configuration
```

## Hard constraints (don't violate without explicit user say-so)

- **All timestamps stored as UTC.** Each collector must convert source-local time → UTC before yielding. `events_for_day` filters on UTC bounds.
- **`Event.fingerprint()` excludes `meta` and only hashes `body[:256]`.** Re-collection must be idempotent — don't add fields that change every pass.
- **Cache key is `(day, provider, model)` (or `(start, end, provider, model)` for rollups).** Switching models does not overwrite; it inserts a parallel row.
- **DB lives outside the repo**, mode `0700/0600`. Never default an output path inside the working tree.
- **Exporters are pure sinks.** No LLM calls, no store mutations.
- **`.env` is git-ignored.** Real keys never go anywhere else. `.env.example` is the public template — only put placeholders there.

## When extending

Read `docs/collectors.md` for adding a source, `docs/exporters.md` for adding a sink, `docs/configuration.md` for env-var conventions. The TL;DR:

1. New file in `collectors/` or `exporters/`.
2. Register in the `__init__.py` of that subpackage.
3. Wire into `cli.py::_collectors()` (collector) or `cli.py::export()` (exporter).
4. Stub line in `.env.example`, field in `Config`, line in `docs/configuration.md`.
5. Add a test in `tests/`.

## Provider gotchas

- The user's `.env` currently points at **Volcengine Ark coding plan** (`OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3`). That endpoint *only accepts certain models*; `doubao-seed-*` is rejected as `UnsupportedModel`. Use `deepseek-v3-2-251201` or check `/v3/models` before changing `HINDSIGHT_LLM_MODEL`.
- macOS sandboxes set `UF_HIDDEN` on `_editable_impl_hindsight.pth` so `pip install -e .` can become invisible to Python's `site`. Recover with `chflags nohidden …/site-packages/*.pth` or just use a non-editable install (`uv pip install .`).

## Running tests

```bash
pytest -q                          # 19 tests, all offline
hindsight summarize --save-digest  # see render_digest output without spending tokens
```

## What not to do

- Don't add a "TODAY" timezone pun; the project name is `hindsight`. Old paths (`todaydo`) only survive in commit history.
- Don't auto-install the launchd plist on macOS unless the user asked — `schedule install` is opt-in for a reason.
- Don't introduce a sync server. Local-first is a non-negotiable invariant.
