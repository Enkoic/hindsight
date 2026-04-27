from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Event:
    """Normalized activity event from any source."""

    source: str              # activitywatch | claude_code | codex | ...
    kind: str                # window | afk | user_message | assistant_message | tool_use | ...
    ts_start: datetime       # UTC
    ts_end: datetime | None  # UTC; None for point-in-time events
    title: str               # short human-readable label
    project: str | None      # cwd / project identifier when available
    body: str                # body text (user message, window title, etc.)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        if self.ts_end is None:
            return 0.0
        return max(0.0, (self.ts_end - self.ts_start).total_seconds())

    def fingerprint(self) -> str:
        """Stable id used for dedup on re-collect."""
        payload = json.dumps(
            {
                "source": self.source,
                "kind": self.kind,
                "ts": self.ts_start.isoformat(),
                "title": self.title,
                "project": self.project,
                "body_head": self.body[:256],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts_start"] = self.ts_start.astimezone(timezone.utc).isoformat()
        d["ts_end"] = self.ts_end.astimezone(timezone.utc).isoformat() if self.ts_end else None
        d["meta"] = json.dumps(self.meta, ensure_ascii=False)
        d["fingerprint"] = self.fingerprint()
        return d
