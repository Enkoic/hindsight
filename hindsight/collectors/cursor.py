from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

from ..models import Event
from .base import Collector


def _resolve_project(workspace_dir: Path) -> str | None:
    """Decode workspace folder URI from workspace.json next to state.vscdb."""
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


class CursorCollector(Collector):
    """Reads Cursor IDE chat history from per-workspace SQLite stores.

    Layout (macOS):
        ~/Library/Application Support/Cursor/User/workspaceStorage/<hash>/state.vscdb
    Each state.vscdb has an `ItemTable` with key/value rows, JSON-encoded.
    Useful keys:
        aiService.generations   — array of {unixMs, generationUUID, type, textDescription}
        composer.composerData   — array of composer threads with createdAt/lastUpdatedAt
    """

    name = "cursor"

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
            yield from self._parse_db(db, project, since, until)

    def _parse_db(
        self,
        db: Path,
        project: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Iterable[Event]:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return
        try:
            for row in conn.execute(
                "SELECT key, value FROM ItemTable "
                "WHERE key IN ('aiService.generations','composer.composerData')"
            ):
                key, raw = row
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if key == "aiService.generations":
                    yield from self._from_generations(payload, project, since, until, db.parent.name)
                elif key == "composer.composerData":
                    yield from self._from_composers(payload, project, since, until, db.parent.name)
        finally:
            conn.close()

    @staticmethod
    def _ts(unix_ms: int | float | None) -> datetime | None:
        if not isinstance(unix_ms, (int, float)) or unix_ms <= 0:
            return None
        return datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)

    def _from_generations(
        self,
        items: list,
        project: str | None,
        since: datetime | None,
        until: datetime | None,
        ws_id: str,
    ) -> Iterable[Event]:
        if not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            ts = self._ts(it.get("unixMs"))
            if ts is None:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            text = it.get("textDescription") or ""
            kind = f"generation:{it.get('type','?')}"
            yield Event(
                source=self.name,
                kind=kind,
                ts_start=ts,
                ts_end=None,
                title=text.splitlines()[0][:200] if text else kind,
                project=project,
                body=text,
                meta={"workspace_id": ws_id, "uuid": it.get("generationUUID")},
            )

    def _from_composers(
        self,
        payload,
        project: str | None,
        since: datetime | None,
        until: datetime | None,
        ws_id: str,
    ) -> Iterable[Event]:
        composers = payload.get("allComposers") if isinstance(payload, dict) else None
        if not isinstance(composers, list):
            return
        for c in composers:
            if not isinstance(c, dict):
                continue
            ts = self._ts(c.get("lastUpdatedAt") or c.get("createdAt"))
            if ts is None:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            name = c.get("name") or "(untitled composer)"
            subtitle = c.get("subtitle") or ""
            yield Event(
                source=self.name,
                kind="composer_thread",
                ts_start=ts,
                ts_end=None,
                title=f"[composer] {name}"[:200],
                project=project,
                body=f"{name}\n{subtitle}".strip(),
                meta={
                    "workspace_id": ws_id,
                    "composer_id": c.get("composerId"),
                    "lines_added": c.get("totalLinesAdded"),
                    "lines_removed": c.get("totalLinesRemoved"),
                    "files_changed": c.get("filesChangedCount"),
                },
            )
