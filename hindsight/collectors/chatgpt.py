from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..models import Event
from .base import Collector


class ChatGPTExportCollector(Collector):
    """Parses an OpenAI/ChatGPT data export.

    The export ZIP unpacks to a folder containing `conversations.json` (a list of
    conversation objects). Each conversation has a `mapping` of message nodes with:
        - id
        - message: { author: {role}, content: {parts: [...]}, create_time: float (epoch s) }
        - parent / children

    We emit one Event per non-empty user/assistant message.
    """

    name = "chatgpt"

    def __init__(self, export_path: Path) -> None:
        # `export_path` may be the conversations.json file or its parent dir.
        if export_path.is_dir():
            self.path = export_path / "conversations.json"
        else:
            self.path = export_path

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, list):
            return
        for conv in data:
            if not isinstance(conv, dict):
                continue
            yield from self._iter_conv(conv, since, until)

    @staticmethod
    def _ts(epoch_s) -> datetime | None:
        if not isinstance(epoch_s, (int, float)) or epoch_s <= 0:
            return None
        return datetime.fromtimestamp(float(epoch_s), tz=timezone.utc)

    def _iter_conv(
        self, conv: dict, since: datetime | None, until: datetime | None
    ) -> Iterable[Event]:
        title = conv.get("title") or "(untitled)"
        conv_id = conv.get("id") or conv.get("conversation_id") or ""
        mapping = conv.get("mapping") or {}
        if not isinstance(mapping, dict):
            return
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            msg = node.get("message")
            if not isinstance(msg, dict):
                continue
            ts = self._ts(msg.get("create_time"))
            if ts is None:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            author = (msg.get("author") or {}).get("role") or "?"
            if author == "system":
                continue
            content = msg.get("content") or {}
            body = self._content_text(content)
            if not body:
                continue
            yield Event(
                source=self.name,
                kind=f"message:{author}",
                ts_start=ts,
                ts_end=None,
                title=f"[{title}] {body.splitlines()[0][:160]}"[:200],
                project=title,
                body=body,
                meta={"conversation_id": conv_id, "message_id": msg.get("id")},
            )

    @staticmethod
    def _content_text(content: dict) -> str:
        parts = content.get("parts")
        if isinstance(parts, list):
            out = []
            for p in parts:
                if isinstance(p, str):
                    out.append(p)
                elif isinstance(p, dict):
                    out.append(p.get("text") or json.dumps(p, ensure_ascii=False)[:200])
            return "\n".join(s for s in out if s).strip()
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
        return ""
