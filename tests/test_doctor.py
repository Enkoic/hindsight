"""Doctor checks that don't need network: collector path detection, redact compile,
store integrity. LLM/Notion paths are exercised only as 'skip when not configured'."""

from pathlib import Path

from hindsight.config import Config
from hindsight.doctor import (
    _check_collectors,
    _check_notion,
    _check_obsidian,
    _check_redact,
    _check_store,
    _check_webhook,
)


def _cfg(tmp_path: Path, **overrides) -> Config:
    base = dict(
        llm_provider="openai",
        llm_model="x",
        anthropic_key=None,
        openai_key=None,
        openai_base_url=None,
        aw_server_url="http://localhost:1",
        claude_projects_dir=tmp_path / "claude",
        codex_sessions_dir=tmp_path / "codex",
        notion_token=None,
        notion_database_id=None,
        obsidian_vault_dir=None,
        cursor_storage_dir=None,
        vscode_storage_dir=None,
        chatgpt_export_path=None,
        webhook_url=None,
        db_path=tmp_path / "db.sqlite",
    )
    base.update(overrides)
    return Config(**base)


def test_collectors_skip_when_unconfigured(tmp_path):
    cfg = _cfg(tmp_path)
    checks = _check_collectors(cfg)
    by_name = {c.name: c for c in checks}
    # Only paths we did NOT configure are evaluated against existence;
    # claude_code/codex have a default tmp path that doesn't exist → warn.
    assert by_name["claude_code"].status == "warn"
    assert by_name["cursor"].status == "skip"
    assert by_name["vscode"].status == "skip"
    assert by_name["chatgpt"].status == "skip"


def test_collectors_ok_when_path_exists(tmp_path):
    (tmp_path / "claude").mkdir()
    (tmp_path / "codex").mkdir()
    cfg = _cfg(tmp_path)
    checks = _check_collectors(cfg)
    by_name = {c.name: c for c in checks}
    assert by_name["claude_code"].status == "ok"
    assert by_name["codex"].status == "ok"


def test_notion_skip_without_creds(tmp_path):
    cfg = _cfg(tmp_path)
    checks = _check_notion(cfg)
    assert len(checks) == 1
    assert checks[0].status == "skip"


def test_obsidian_warns_for_non_vault_dir(tmp_path):
    plain = tmp_path / "not-a-vault"
    plain.mkdir()
    cfg = _cfg(tmp_path, obsidian_vault_dir=plain)
    checks = _check_obsidian(cfg)
    assert checks[0].status == "warn"


def test_obsidian_ok_with_marker(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    cfg = _cfg(tmp_path, obsidian_vault_dir=vault)
    assert _check_obsidian(cfg)[0].status == "ok"


def test_webhook_skip_when_unset(tmp_path):
    assert _check_webhook(_cfg(tmp_path))[0].status == "skip"


def test_redact_reports_rule_count():
    checks = _check_redact()
    assert checks[0].status == "ok"
    assert "patterns" in checks[0].detail


def test_store_warns_when_db_missing(tmp_path):
    cfg = _cfg(tmp_path)
    checks = _check_store(cfg)
    assert checks[0].status == "warn"


def test_store_ok_with_real_db(tmp_path):
    from hindsight.store import Store

    cfg = _cfg(tmp_path)
    Store(cfg.db_path).close()
    checks = _check_store(cfg)
    statuses = [c.status for c in checks]
    assert "fail" not in statuses
    integrity = next((c for c in checks if c.name == "integrity"), None)
    assert integrity is not None and integrity.status == "ok"
