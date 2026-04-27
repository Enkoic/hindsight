# Contributing to hindsight

Short guide; the long form lives in [`docs/`](./docs).

## Setup

```bash
git clone https://github.com/Enkoic/hindsight.git
cd hindsight
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'         # pulls pytest + ruff
cp .env.example .env                # set at least one API key for summarizer tests
```

> **macOS quirk**: the editable-install marker `_editable_impl_hindsight.pth` sometimes inherits the `UF_HIDDEN` flag inside Apple sandboxes, which makes Python's `site` module skip it. If `hindsight: command not found` after `pip install -e .`, run `chflags nohidden .venv/lib/python*/site-packages/*.pth` or use `pip install .` (non-editable).

## Project layout

```
hindsight/
├── cli.py             # typer entry points
├── config.py          # env-var → Config dataclass
├── models.py          # Event schema + fingerprint
├── store.py           # SQLite (events, summaries, rollups)
├── schedule.py        # macOS launchd glue
├── collectors/        # one per data source — see docs/collectors.md
├── summarizer/        # render_digest + LLM clients — see docs/architecture.md
└── exporters/         # markdown / json / notion / obsidian — see docs/exporters.md
tests/                 # pytest, no external services touched
docs/                  # design rationale + extension guides
```

## Workflow

```bash
pytest -q                              # 19 tests, runs in <0.1s
ruff check hindsight tests             # if you want lint
hindsight collect --days 1             # smoke pull from your real machine
hindsight summarize --day yesterday --save-digest   # see prompt without spending tokens
```

## Conventions

| Rule | Reason |
| --- | --- |
| **UTC at every interface boundary** (collector → store → cli filter) | Local-time mixing breaks `events_for_day`. |
| **Yield, don't materialize, in collectors.** | Some sources span months; we iterate rows, don't load them. |
| **`meta` is opaque source-specific extras**; the digest must not look at it. | Lets us add fields without breaking dedup or rendering. |
| **Cache is keyed on `(day, provider, model)`**; switching models does not invalidate. | Lets you A/B model output on the same data. |
| **Exporters are pure sinks** — no LLM calls, no store mutations. | Re-running an export must be cheap and deterministic. |
| **Skip silently when an optional source's path doesn't exist.** | A user without Cursor shouldn't see error noise. |
| **Default outputs go inside the data dir, not cwd.** | Avoids accidentally committing exports. |

## What goes in a PR

1. The change.
2. A test that pins the new behaviour (or a sentence in the PR description if the change is purely scaffolding).
3. A README/docs touch if you added a CLI flag, env var, or roadmap item.
4. **Do not** commit `.env`, `*.sqlite`, `out/`, `data/`. They are git-ignored, but verify `git diff --cached` before pushing.

## Reading order for new contributors

1. `docs/architecture.md` — how the layers connect
2. `docs/collectors.md` — the most common contribution path
3. `docs/exporters.md` — second most common
4. `docs/configuration.md` — env vars you'll touch when adding either of the above
5. `hindsight/cli.py` — the orchestration is small; read it last, with the rest as context

## Filing issues

Concrete reproduction beats theory. A useful bug report includes:

- the exact `hindsight <subcmd> --flags…` you ran
- which provider+model is in use
- the source(s) you collected (`--sources …`)
- what `hindsight report --day <d>` shows for the affected day

If you have a privacy-sensitive transcript, do **not** paste it; the digest's structure is enough to debug most rendering issues.
