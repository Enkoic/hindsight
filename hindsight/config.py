from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _path(env: str, default: str) -> Path:
    raw = os.getenv(env) or default
    return Path(os.path.expanduser(raw))


def _default_data_dir() -> Path:
    """XDG data dir; falls back to ~/Library/Application Support on macOS, ~/.local/share elsewhere."""
    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "hindsight"
    if os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "hindsight"
    return Path.home() / ".local" / "share" / "hindsight"


def _ensure_private_dir(p: Path) -> None:
    """Create the data dir with 0700 so raw transcripts stay user-readable only."""
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(stat.S_IRWXU)
    except OSError:
        pass


@dataclass(frozen=True)
class Config:
    llm_provider: str
    llm_model: str
    anthropic_key: str | None
    openai_key: str | None
    openai_base_url: str | None
    aw_server_url: str
    claude_projects_dir: Path
    codex_sessions_dir: Path
    notion_token: str | None
    notion_database_id: str | None
    obsidian_vault_dir: Path | None
    cursor_storage_dir: Path | None
    chatgpt_export_path: Path | None
    db_path: Path


def _opt_path(env: str) -> Path | None:
    raw = os.getenv(env)
    return Path(os.path.expanduser(raw)) if raw else None


def _default_cursor_dir() -> Path | None:
    if os.uname().sysname == "Darwin":
        p = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
        return p if p.exists() else None
    return None


def load() -> Config:
    db_env = os.getenv("HINDSIGHT_DB")
    if db_env:
        db_path = Path(os.path.expanduser(db_env))
    else:
        data_dir = _default_data_dir()
        _ensure_private_dir(data_dir)
        db_path = data_dir / "hindsight.sqlite"

    return Config(
        llm_provider=os.getenv("HINDSIGHT_LLM_PROVIDER", "anthropic").lower(),
        llm_model=os.getenv("HINDSIGHT_LLM_MODEL", "claude-sonnet-4-6"),
        anthropic_key=os.getenv("ANTHROPIC_API_KEY") or None,
        openai_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        aw_server_url=os.getenv("AW_SERVER_URL", "http://localhost:5600"),
        claude_projects_dir=_path("CLAUDE_PROJECTS_DIR", "~/.claude/projects"),
        codex_sessions_dir=_path("CODEX_SESSIONS_DIR", "~/.codex/sessions"),
        notion_token=os.getenv("NOTION_TOKEN") or None,
        notion_database_id=os.getenv("NOTION_DATABASE_ID") or None,
        obsidian_vault_dir=_opt_path("OBSIDIAN_VAULT_DIR"),
        cursor_storage_dir=_opt_path("CURSOR_STORAGE_DIR") or _default_cursor_dir(),
        chatgpt_export_path=_opt_path("CHATGPT_EXPORT_PATH"),
        db_path=db_path,
    )
