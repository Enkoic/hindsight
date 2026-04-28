# Configuration

All configuration is read from environment variables (or a `.env` file in the cwd, which `python-dotenv` loads on import). `hindsight/config.py::Config` is a frozen dataclass — that's the canonical list.

## Env vars

| Variable | Default | Used by |
| --- | --- | --- |
| `HINDSIGHT_LLM_PROVIDER` | `anthropic` | `summarize`, `rollup` — `anthropic` or `openai` |
| `HINDSIGHT_LLM_MODEL` | `claude-sonnet-4-6` | model id passed to the SDK |
| `HINDSIGHT_DB` | `~/Library/Application Support/hindsight/hindsight.sqlite` (macOS) / `$XDG_DATA_HOME/hindsight/hindsight.sqlite` | SQLite path |
| `ANTHROPIC_API_KEY` | — | required when provider=anthropic |
| `OPENAI_API_KEY` | — | required when provider=openai |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | override for OpenAI-compatible endpoints (Volcengine Ark, DeepSeek, local llama.cpp, …) |
| `AW_SERVER_URL` | `http://localhost:5600` | ActivityWatch REST root |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Claude Code transcripts root |
| `CODEX_SESSIONS_DIR` | `~/.codex/sessions` | Codex CLI rollouts root |
| `CURSOR_STORAGE_DIR` | `~/Library/Application Support/Cursor/User/workspaceStorage` (macOS only) | Cursor `state.vscdb` per-workspace dir |
| `CODE_STORAGE_DIR` | auto: macOS `~/Library/Application Support/{Code,Code - Insiders,VSCodium}/User/workspaceStorage`; Linux `~/.config/{...}/User/workspaceStorage` | VS Code Copilot Chat workspaceStorage |
| `CHATGPT_EXPORT_PATH` | — | path to the unzipped data export folder, or directly to `conversations.json` |
| `NOTION_TOKEN` | — | Notion internal-integration secret |
| `NOTION_DATABASE_ID` | — | target Notion database |
| `OBSIDIAN_VAULT_DIR` | — | enables `hindsight export obsidian` |
| `HINDSIGHT_WEBHOOK_URL` | — | Slack/Discord incoming webhook for `hindsight export webhook` |
| `HINDSIGHT_REDACT_FILE` | — | path to a TSV (`name<TAB>regex<TAB>placeholder`) of extra redaction rules merged before defaults |

## Filesystem layout

```
$DATA_DIR/                      # ~/Library/Application Support/hindsight on macOS
├── hindsight.sqlite            # 0600 — events, summaries, rollups
└── exports/                    # default --out for `hindsight export markdown|json`
    └── 2026-04-22.md
~/Library/LaunchAgents/io.github.enkoic.hindsight.plist   # if `schedule install` was run
~/Library/Logs/hindsight/                                  # launchd stdout/stderr
```

The data dir is created with mode `0700` (`_ensure_private_dir`) and the SQLite file with `0600`. Raw transcripts live there permanently, so this matters.

## Choosing a provider

- **Anthropic** — set `HINDSIGHT_LLM_PROVIDER=anthropic`, `HINDSIGHT_LLM_MODEL=claude-sonnet-4-6` (or `claude-haiku-4-5-20251001` to cut cost), `ANTHROPIC_API_KEY=sk-ant-…`.
- **OpenAI** — `HINDSIGHT_LLM_PROVIDER=openai`, `HINDSIGHT_LLM_MODEL=gpt-4o-mini`, `OPENAI_API_KEY=sk-…`.
- **OpenAI-compatible (Volcengine Ark, DeepSeek, Together, local)** — same as OpenAI but set `OPENAI_BASE_URL` to the provider's base. The Ark coding plan only accepts certain models — `deepseek-v3-2-251201` works at the time of writing.

The cache key is `(day, provider, model)`. Switching providers does **not** invalidate the previous cache; the new run produces a parallel row, so you can compare digests between models on the same day.

## Switching the data directory

Set `HINDSIGHT_DB=/some/abs/path.sqlite` if you want to keep the DB in iCloud / Dropbox / a TrueCrypt volume. The parent directory is created on demand. Don't put it inside the repo — `.gitignore` carries `*.sqlite` as a belt-and-suspenders rule but you really shouldn't.

## Adding a new env var

1. Add a field to `Config`.
2. Add the read in `Config.load()` (use `_path` / `_opt_path` helpers when it's a filesystem path).
3. Add a stub line in `.env.example` with a one-line comment explaining the purpose.
4. Document it in this file and reference it from the relevant collector/exporter doc.
