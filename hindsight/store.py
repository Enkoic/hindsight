from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    fingerprint TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    ts_start    TEXT NOT NULL,
    ts_end      TEXT,
    title       TEXT NOT NULL,
    project     TEXT,
    body        TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_ts_idx ON events(ts_start);
CREATE INDEX IF NOT EXISTS events_source_idx ON events(source);

CREATE TABLE IF NOT EXISTS summaries (
    day         TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    content     TEXT NOT NULL,
    PRIMARY KEY (day, provider, model)
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        new_db = not path.exists()
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        if new_db:
            try:
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — raw transcripts are private.
            except OSError:
                pass

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_events(self, events: Iterable[Event]) -> int:
        inserted = 0
        with self.tx() as c:
            for e in events:
                r = e.to_row()
                cur = c.execute(
                    """
                    INSERT OR IGNORE INTO events
                        (fingerprint, source, kind, ts_start, ts_end, title, project, body, meta)
                    VALUES
                        (:fingerprint, :source, :kind, :ts_start, :ts_end, :title, :project, :body, :meta)
                    """,
                    r,
                )
                inserted += cur.rowcount
        return inserted

    def events_for_day(self, day: date) -> list[sqlite3.Row]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc).isoformat()
        end = datetime.combine(day, time.max, tzinfo=timezone.utc).isoformat()
        cur = self._conn.execute(
            "SELECT * FROM events WHERE ts_start >= ? AND ts_start <= ? ORDER BY ts_start",
            (start, end),
        )
        return list(cur.fetchall())

    def latest_ts(self, source: str) -> datetime | None:
        cur = self._conn.execute(
            "SELECT ts_start FROM events WHERE source = ? ORDER BY ts_start DESC LIMIT 1",
            (source,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return datetime.fromisoformat(row["ts_start"])

    def save_summary(self, day: date, provider: str, model: str, content: str) -> None:
        with self.tx() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO summaries (day, provider, model, created_at, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (day.isoformat(), provider, model, datetime.now(timezone.utc).isoformat(), content),
            )

    def get_summary(self, day: date, provider: str, model: str) -> str | None:
        cur = self._conn.execute(
            "SELECT content FROM summaries WHERE day = ? AND provider = ? AND model = ?",
            (day.isoformat(), provider, model),
        )
        row = cur.fetchone()
        return row["content"] if row else None
