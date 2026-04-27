from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..models import Event
from .base import Collector


class ClaudeHistoryCollector(Collector):
    """~/.claude/history.jsonl — every user-entered prompt, project-tagged."""

    name = "claude_history"

    def __init__(self, claude_home: Path) -> None:
        self.path = claude_home / "history.jsonl"

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_ms = rec.get("timestamp")
                    if not isinstance(ts_ms, (int, float)):
                        continue
                    ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                    if since and ts < since:
                        continue
                    if until and ts > until:
                        continue
                    display = rec.get("display") or ""
                    yield Event(
                        source=self.name,
                        kind="user_prompt",
                        ts_start=ts,
                        ts_end=None,
                        title=display[:200],
                        project=rec.get("project"),
                        body=display,
                        meta={"session_id": rec.get("sessionId")},
                    )
        except OSError:
            return


class CodexHistoryCollector(Collector):
    """~/.codex/history.jsonl — user prompts to Codex."""

    name = "codex_history"

    def __init__(self, codex_home: Path) -> None:
        self.path = codex_home / "history.jsonl"

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_s = rec.get("ts")
                    if not isinstance(ts_s, (int, float)):
                        continue
                    ts = datetime.fromtimestamp(ts_s, tz=timezone.utc)
                    if since and ts < since:
                        continue
                    if until and ts > until:
                        continue
                    text = rec.get("text", "") or ""
                    yield Event(
                        source=self.name,
                        kind="user_prompt",
                        ts_start=ts,
                        ts_end=None,
                        title=text.splitlines()[0][:200] if text else "",
                        project=None,
                        body=text,
                        meta={"session_id": rec.get("session_id")},
                    )
        except OSError:
            return
