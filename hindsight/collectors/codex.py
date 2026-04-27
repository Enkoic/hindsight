from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..models import Event
from .base import Collector


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class CodexCollector(Collector):
    """Parses ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl session rollouts."""

    name = "codex"

    def __init__(self, root: Path) -> None:
        self.root = root

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        if not self.root.exists():
            return
        for jsonl in sorted(self.root.rglob("rollout-*.jsonl")):
            yield from self._parse_file(jsonl, since, until)

    def _parse_file(
        self, path: Path, since: datetime | None, until: datetime | None
    ) -> Iterable[Event]:
        session_id = path.stem
        cwd: str | None = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = _parse_ts(rec.get("timestamp"))
                    if ts is None:
                        continue

                    rec_type = rec.get("type", "")
                    payload = rec.get("payload") or {}

                    if rec_type == "session_meta":
                        cwd = payload.get("cwd") or cwd
                        continue

                    ev = self._payload_to_event(rec_type, payload, ts, session_id, cwd)
                    if ev is None:
                        continue
                    if since and ev.ts_start < since:
                        continue
                    if until and ev.ts_start > until:
                        continue
                    yield ev
        except OSError:
            return

    def _payload_to_event(
        self,
        rec_type: str,
        payload: dict,
        ts: datetime,
        session_id: str,
        cwd: str | None,
    ) -> Event | None:
        kind = rec_type
        body = ""

        if rec_type == "response_item":
            ptype = payload.get("type", "")
            kind = f"response_item:{ptype}"
            if ptype == "message":
                role = payload.get("role", "")
                kind = f"message:{role}"
                body = self._content_text(payload.get("content"))
            elif ptype == "function_call":
                name = payload.get("name", "")
                kind = f"function_call:{name}"
                body = payload.get("arguments", "")
            elif ptype == "function_call_output":
                body = str(payload.get("output", ""))[:4000]
            elif ptype == "reasoning":
                body = self._content_text(payload.get("summary") or payload.get("content"))
            else:
                body = json.dumps(payload, ensure_ascii=False)[:2000]
        elif rec_type == "event_msg":
            body = json.dumps(payload, ensure_ascii=False)[:2000]
        else:
            body = json.dumps(payload, ensure_ascii=False)[:2000]

        if not body:
            return None

        title = body.splitlines()[0][:200]
        return Event(
            source=self.name,
            kind=kind,
            ts_start=ts,
            ts_end=None,
            title=title,
            project=cwd,
            body=body,
            meta={"session_id": session_id},
        )

    @staticmethod
    def _content_text(content) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    out.append(block.get("text") or block.get("content") or "")
                else:
                    out.append(str(block))
            return "\n".join(p for p in out if p)
        return str(content)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
