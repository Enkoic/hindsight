from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

from ..models import Event
from .base import Collector

# VS Code is the upstream parent of Cursor, so the storage layout is identical.
# What differs is the *content* of `ItemTable` keys: VS Code Copilot Chat writes to
# `interactive.sessions` and (for newer versions) `chat.history.copilot.*`. Inline
# chat (the keystroke-level edit assistant) writes to `inlineChat.history`.
#
# We don't try to be exhaustive — we yield what we recognize and skip what we don't.
# Unknown shapes appear as empty Iterables rather than errors.

_CHAT_KEYS = {
    "interactive.sessions",
    "inlineChat.history",
}


def _resolve_project(workspace_dir: Path) -> str | None:
    meta = workspace_dir / "workspace.json"
    if not meta.exists():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    folder = data.get("folder") or data.get("workspace")
    if not folder:
        return None
    try:
        return unquote(urlparse(folder).path) or folder
    except Exception:
        return folder


def _ts(unix_ms) -> datetime | None:
    if not isinstance(unix_ms, (int, float)) or unix_ms <= 0:
        return None
    # VS Code stores ms; some Copilot fields use seconds. Pick the right unit
    # by magnitude: < year-2300 → seconds, otherwise ms.
    if unix_ms < 1e12:
        return datetime.fromtimestamp(unix_ms, tz=timezone.utc)
    return datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)


class VSCodeCopilotCollector(Collector):
    """VS Code (and Code Insiders / VSCodium) Copilot Chat history.

    Default root is `~/Library/Application Support/Code/User/workspaceStorage`
    on macOS. Pass `CODE_STORAGE_DIR` to point at Insiders or another build.
    """

    name = "vscode"

    def __init__(self, root: Path) -> None:
        self.root = root  # workspaceStorage dir

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        if not self.root.exists():
            return
        for ws in sorted(self.root.iterdir()):
            db = ws / "state.vscdb"
            if not db.is_file():
                continue
            project = _resolve_project(ws)
            yield from self._parse_db(db, project, since, until, ws.name)

    def _parse_db(
        self,
        db: Path,
        project: str | None,
        since: datetime | None,
        until: datetime | None,
        ws_id: str,
    ) -> Iterable[Event]:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return
        try:
            placeholders = ",".join("?" for _ in _CHAT_KEYS)
            for key, raw in conn.execute(
                f"SELECT key, value FROM ItemTable WHERE key IN ({placeholders})",
                tuple(_CHAT_KEYS),
            ):
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                yield from self._from_payload(key, payload, project, since, until, ws_id)
        finally:
            conn.close()

    def _from_payload(
        self,
        key: str,
        payload,
        project: str | None,
        since: datetime | None,
        until: datetime | None,
        ws_id: str,
    ) -> Iterable[Event]:
        # `interactive.sessions` is a list (or wrapper {entries: [...]}) of session objects;
        # each session has nested messages with `timestamp` (epoch ms or ISO).
        sessions = payload
        if isinstance(payload, dict):
            sessions = payload.get("entries") or payload.get("sessions") or []
        if not isinstance(sessions, list):
            return
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_id = session.get("sessionId") or session.get("id") or ""
            requests = (
                session.get("requests")
                or session.get("messages")
                or session.get("turns")
                or []
            )
            if not isinstance(requests, list):
                continue
            for turn in requests:
                if not isinstance(turn, dict):
                    continue
                ts_raw = turn.get("timestamp") or turn.get("requestTimestamp") or turn.get("createdAt")
                ts = self._parse_ts(ts_raw)
                if ts is None:
                    continue
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
                role = turn.get("role") or ("user" if turn.get("message") else "assistant")
                body = self._extract_text(turn)
                if not body:
                    continue
                yield Event(
                    source=self.name,
                    kind=f"{key.split('.')[0]}:{role}",
                    ts_start=ts,
                    ts_end=None,
                    title=body.splitlines()[0][:200],
                    project=project,
                    body=body,
                    meta={
                        "workspace_id": ws_id,
                        "session_id": session_id,
                        "key": key,
                    },
                )

    @staticmethod
    def _parse_ts(raw) -> datetime | None:
        if isinstance(raw, (int, float)):
            return _ts(raw)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_text(turn: dict) -> str:
        for key in ("message", "request", "response", "prompt", "content", "text"):
            v = turn.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                t = v.get("text") or v.get("content")
                if isinstance(t, str) and t.strip():
                    return t.strip()
            if isinstance(v, list):
                parts = []
                for item in v:
                    if isinstance(item, dict):
                        t = item.get("text") or item.get("content") or ""
                        if isinstance(t, str):
                            parts.append(t)
                    elif isinstance(item, str):
                        parts.append(item)
                joined = "\n".join(p for p in parts if p).strip()
                if joined:
                    return joined
        return ""
