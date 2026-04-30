# Changelog

All notable changes to this project should be documented in this file.

The format is intentionally simple and follows the spirit of Keep a Changelog.

## [Unreleased]

### Added

- GitHub Actions CI for `pytest -q` and `ruff check` on Python 3.10 to 3.12.
- Community files for security reporting, code of conduct, issue templates, and pull request hygiene.
- `hindsight ask "<question>"` — RAG-style QA over cached daily and rollup summaries; pins date references in the question to the front of the context, trims the rest to a configurable budget.
- `hindsight doctor` — one-shot diagnostic of collector reachability, store integrity & permissions, LLM key validity (`--no-ping` to skip cost), Notion/Obsidian/webhook config, scheduled run state, and redaction rule compile.
- Cursor bubble-level collector — extends the per-workspace prompt collector with global `cursorDiskKV` mining so both user and assistant turns are captured (was only prompts before). Falls back through `timingInfo.clientRpcSendTime` → `clientStartTime/EndTime` → `createdAt` ISO → top-level `timestamp` for time resolution.

### Changed

- README and contributing docs now describe support status, privacy boundaries, and the public contribution workflow more explicitly.

## [0.1.0] - 2026-04-28

### Added

- Initial public CLI for collecting local activity into SQLite and summarizing it with an LLM.
- Collectors for ActivityWatch, Claude Code, Codex CLI, Cursor, VS Code Copilot Chat, and ChatGPT export.
- Exporters for Markdown, JSON, Notion, Obsidian, and Slack/Discord-compatible webhooks.
- Weekly and monthly rollups, secret redaction before LLM calls, and platform-aware scheduling.
