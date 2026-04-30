"""Diagnostic checks: collector reachability, LLM key validity, scheduler state, redact compile."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .redact import DEFAULT_RULES
from .store import Store


@dataclass
class Check:
    area: str
    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    detail: str


def _ok(area: str, name: str, detail: str = "") -> Check:
    return Check(area, name, "ok", detail)


def _warn(area: str, name: str, detail: str) -> Check:
    return Check(area, name, "warn", detail)


def _fail(area: str, name: str, detail: str) -> Check:
    return Check(area, name, "fail", detail)


def _skip(area: str, name: str, detail: str) -> Check:
    return Check(area, name, "skip", detail)


# ─────────── checks ───────────


def _check_collectors(cfg: Config) -> list[Check]:
    out: list[Check] = []
    pairs: list[tuple[str, Path | None, str]] = [
        ("activitywatch", None, "Live HTTP probe below"),
        ("claude_code", cfg.claude_projects_dir, "session transcripts"),
        ("codex", cfg.codex_sessions_dir, "session rollouts"),
        ("cursor", cfg.cursor_storage_dir, "Cursor workspaceStorage"),
        ("vscode", cfg.vscode_storage_dir, "VS Code Copilot Chat workspaceStorage"),
        ("chatgpt", cfg.chatgpt_export_path, "OpenAI data export"),
    ]
    for name, path, label in pairs:
        if name == "activitywatch":
            continue
        if path is None:
            out.append(_skip("collectors", name, "not configured"))
        elif path.exists():
            out.append(_ok("collectors", name, str(path)))
        else:
            out.append(_warn("collectors", name, f"{label} path does not exist: {path}"))

    # ActivityWatch live probe
    try:
        import httpx

        r = httpx.get(f"{cfg.aw_server_url.rstrip('/')}/api/0/info", timeout=2.0)
        if r.status_code == 200:
            ver = r.json().get("version", "?")
            out.append(_ok("collectors", "activitywatch", f"v{ver} at {cfg.aw_server_url}"))
        else:
            out.append(_warn("collectors", "activitywatch", f"HTTP {r.status_code}"))
    except Exception as e:  # noqa: BLE001
        out.append(_warn("collectors", "activitywatch", f"unreachable: {type(e).__name__}"))
    return out


def _check_llm(cfg: Config) -> list[Check]:
    if cfg.llm_provider == "anthropic":
        if not cfg.anthropic_key:
            return [_fail("llm", "anthropic_key", "ANTHROPIC_API_KEY not set")]
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=cfg.anthropic_key)
            client.messages.create(
                model=cfg.llm_model,
                max_tokens=4,
                messages=[{"role": "user", "content": "ping"}],
            )
            return [_ok("llm", f"anthropic/{cfg.llm_model}", "ping ok")]
        except Exception as e:  # noqa: BLE001
            return [_fail("llm", f"anthropic/{cfg.llm_model}", f"{type(e).__name__}: {str(e)[:120]}")]

    if cfg.llm_provider == "openai":
        if not cfg.openai_key:
            return [_fail("llm", "openai_key", "OPENAI_API_KEY not set")]
        try:
            from openai import OpenAI

            client = (
                OpenAI(api_key=cfg.openai_key, base_url=cfg.openai_base_url)
                if cfg.openai_base_url
                else OpenAI(api_key=cfg.openai_key)
            )
            client.chat.completions.create(
                model=cfg.llm_model,
                max_tokens=4,
                messages=[{"role": "user", "content": "ping"}],
            )
            label = (
                f"openai/{cfg.llm_model} @ {cfg.openai_base_url}"
                if cfg.openai_base_url
                else f"openai/{cfg.llm_model}"
            )
            return [_ok("llm", label, "ping ok")]
        except Exception as e:  # noqa: BLE001
            return [_fail("llm", f"openai/{cfg.llm_model}", f"{type(e).__name__}: {str(e)[:120]}")]

    return [_fail("llm", "provider", f"unknown provider: {cfg.llm_provider}")]


def _check_notion(cfg: Config) -> list[Check]:
    if not cfg.notion_token or not cfg.notion_database_id:
        return [_skip("exporters", "notion", "not configured")]
    try:
        import httpx

        r = httpx.get(
            f"https://api.notion.com/v1/databases/{cfg.notion_database_id}",
            headers={
                "Authorization": f"Bearer {cfg.notion_token}",
                "Notion-Version": "2022-06-28",
            },
            timeout=10.0,
        )
        if r.status_code != 200:
            return [_fail("exporters", "notion", f"HTTP {r.status_code}: {r.text[:120]}")]
        props = r.json().get("properties", {})
        has_title = any(v.get("type") == "title" for v in props.values())
        if not has_title:
            return [_fail("exporters", "notion", "database has no title property")]
        has_date = any(v.get("type") == "date" for v in props.values())
        msg = "title✓" + (" date✓" if has_date else " (no date prop — exports still work)")
        return [_ok("exporters", "notion", msg)]
    except Exception as e:  # noqa: BLE001
        return [_fail("exporters", "notion", f"{type(e).__name__}: {str(e)[:120]}")]


def _check_obsidian(cfg: Config) -> list[Check]:
    if not cfg.obsidian_vault_dir:
        return [_skip("exporters", "obsidian", "not configured")]
    if cfg.obsidian_vault_dir.exists() and (cfg.obsidian_vault_dir / ".obsidian").exists():
        return [_ok("exporters", "obsidian", f"vault at {cfg.obsidian_vault_dir}")]
    if cfg.obsidian_vault_dir.exists():
        return [_warn("exporters", "obsidian", f"dir exists but no .obsidian/ inside: {cfg.obsidian_vault_dir}")]
    return [_fail("exporters", "obsidian", f"not found: {cfg.obsidian_vault_dir}")]


def _check_webhook(cfg: Config) -> list[Check]:
    if not cfg.webhook_url:
        return [_skip("exporters", "webhook", "not configured")]
    return [_ok("exporters", "webhook", "configured (live POST not tested)")]


def _check_schedule() -> list[Check]:
    sysname = os.uname().sysname
    if sysname == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "io.github.enkoic.hindsight.plist"
        if not plist.exists():
            return [_skip("schedule", "launchd", "no plist installed")]
        # Check launchctl knows about it
        try:
            res = subprocess.run(
                ["launchctl", "list", "io.github.enkoic.hindsight"],
                capture_output=True, text=True, timeout=2,
            )
            if res.returncode == 0:
                return [_ok("schedule", "launchd", f"loaded: {plist}")]
            return [_warn("schedule", "launchd", "plist exists but not loaded")]
        except Exception as e:  # noqa: BLE001
            return [_warn("schedule", "launchd", f"plist exists; launchctl probe failed: {e}")]

    if sysname == "Linux":
        timer = Path.home() / ".config" / "systemd" / "user" / "hindsight.timer"
        if not timer.exists():
            return [_skip("schedule", "systemd", "no timer installed")]
        try:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", "hindsight.timer"],
                capture_output=True, text=True, timeout=2,
            )
            if res.stdout.strip() == "active":
                return [_ok("schedule", "systemd", f"active: {timer}")]
            return [_warn("schedule", "systemd", f"timer not active: {res.stdout.strip()}")]
        except Exception as e:  # noqa: BLE001
            return [_warn("schedule", "systemd", f"timer exists; probe failed: {e}")]

    return [_skip("schedule", sysname.lower(), "platform not supported")]


def _check_store(cfg: Config) -> list[Check]:
    out: list[Check] = []
    if not cfg.db_path.exists():
        return [_warn("store", "sqlite", f"DB does not exist yet: {cfg.db_path}")]
    size_mb = cfg.db_path.stat().st_size / 1024 / 1024
    out.append(_ok("store", "path", f"{cfg.db_path} ({size_mb:.1f} MB)"))
    # Permission check
    mode = oct(cfg.db_path.stat().st_mode & 0o777)
    if mode == "0o600":
        out.append(_ok("store", "permissions", "0600"))
    else:
        out.append(_warn("store", "permissions", f"expected 0600, got {mode}"))
    # Open + integrity check
    try:
        store = Store(cfg.db_path)
        try:
            row = store._conn.execute("PRAGMA integrity_check").fetchone()  # noqa: SLF001
            ok = row and row[0] == "ok"
            out.append(
                _ok("store", "integrity", "ok") if ok
                else _fail("store", "integrity", str(row[0] if row else "no result"))
            )
            s = store.stats()
            out.append(_ok("store", "events", f"{s['events_total']} total, {len(s['events_per_source'])} sources"))
        finally:
            store.close()
    except Exception as e:  # noqa: BLE001
        out.append(_fail("store", "open", f"{type(e).__name__}: {str(e)[:120]}"))
    return out


def _check_redact() -> list[Check]:
    return [_ok("redact", "rules", f"{len(DEFAULT_RULES)} default patterns compile")]


def run_checks(cfg: Config, ping_llm: bool = True) -> list[Check]:
    checks: list[Check] = []
    checks += _check_store(cfg)
    checks += _check_collectors(cfg)
    if ping_llm:
        checks += _check_llm(cfg)
    else:
        checks += [_skip("llm", "ping", "skipped (--no-ping)")]
    checks += _check_notion(cfg)
    checks += _check_obsidian(cfg)
    checks += _check_webhook(cfg)
    checks += _check_schedule()
    checks += _check_redact()
    return checks
