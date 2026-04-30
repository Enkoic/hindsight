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

CREATE TABLE IF NOT EXISTS rollups (
    start_day   TEXT NOT NULL,
    end_day     TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    content     TEXT NOT NULL,
    PRIMARY KEY (start_day, end_day, provider, model)
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

    def events_in_range(self, start_day: date, end_day: date) -> list[sqlite3.Row]:
        start = datetime.combine(start_day, time.min, tzinfo=timezone.utc).isoformat()
        end = datetime.combine(end_day, time.max, tzinfo=timezone.utc).isoformat()
        cur = self._conn.execute(
            "SELECT * FROM events WHERE ts_start >= ? AND ts_start <= ? ORDER BY ts_start",
            (start, end),
        )
        return list(cur.fetchall())

    def summaries_in_range(
        self, start_day: date, end_day: date, provider: str, model: str
    ) -> list[tuple[date, str]]:
        cur = self._conn.execute(
            "SELECT day, content FROM summaries "
            "WHERE day >= ? AND day <= ? AND provider = ? AND model = ? ORDER BY day",
            (start_day.isoformat(), end_day.isoformat(), provider, model),
        )
        return [(date.fromisoformat(r["day"]), r["content"]) for r in cur.fetchall()]

    def save_rollup(
        self, start_day: date, end_day: date, provider: str, model: str, content: str
    ) -> None:
        with self.tx() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO rollups
                    (start_day, end_day, provider, model, created_at, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    start_day.isoformat(),
                    end_day.isoformat(),
                    provider,
                    model,
                    datetime.now(timezone.utc).isoformat(),
                    content,
                ),
            )

    def get_rollup(
        self, start_day: date, end_day: date, provider: str, model: str
    ) -> str | None:
        cur = self._conn.execute(
            "SELECT content FROM rollups "
            "WHERE start_day = ? AND end_day = ? AND provider = ? AND model = ?",
            (start_day.isoformat(), end_day.isoformat(), provider, model),
        )
        row = cur.fetchone()
        return row["content"] if row else None

    def purge(
        self,
        before: date | None = None,
        sources: list[str] | None = None,
    ) -> dict:
        """Delete events matching filters. Returns row counts before/after.
        At least one filter must be passed; no-arg purge is intentionally rejected.
        """
        if before is None and not sources:
            raise ValueError("purge requires at least one filter (before or sources)")
        before_n = self._conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]

        where = []
        params: list = []
        if before is not None:
            where.append("ts_start < ?")
            params.append(
                datetime.combine(before, time.min, tzinfo=timezone.utc).isoformat()
            )
        if sources:
            where.append("source IN ({})".format(",".join("?" * len(sources))))
            params.extend(sources)
        sql = f"DELETE FROM events WHERE {' AND '.join(where)}"

        with self.tx() as c:
            c.execute(sql, params)
        after_n = self._conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        return {"before": before_n, "after": after_n, "deleted": before_n - after_n}

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")

    def all_summaries(
        self, provider: str, model: str, limit: int | None = None
    ) -> list[tuple[date, str]]:
        sql = (
            "SELECT day, content FROM summaries "
            "WHERE provider = ? AND model = ? ORDER BY day DESC"
        )
        params: list = [provider, model]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cur = self._conn.execute(sql, params)
        return [(date.fromisoformat(r["day"]), r["content"]) for r in cur.fetchall()]

    def all_rollups(
        self, provider: str, model: str
    ) -> list[tuple[date, date, str]]:
        cur = self._conn.execute(
            "SELECT start_day, end_day, content FROM rollups "
            "WHERE provider = ? AND model = ? ORDER BY end_day DESC",
            (provider, model),
        )
        return [
            (date.fromisoformat(r["start_day"]), date.fromisoformat(r["end_day"]), r["content"])
            for r in cur.fetchall()
        ]

    def stats(self) -> dict:
        c = self._conn
        per_source = {
            r["source"]: r["n"]
            for r in c.execute("SELECT source, COUNT(*) AS n FROM events GROUP BY source")
        }
        first = c.execute("SELECT MIN(ts_start) AS m FROM events").fetchone()["m"]
        last = c.execute("SELECT MAX(ts_start) AS m FROM events").fetchone()["m"]
        n_events = c.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        n_summaries = c.execute("SELECT COUNT(*) AS n FROM summaries").fetchone()["n"]
        n_rollups = c.execute("SELECT COUNT(*) AS n FROM rollups").fetchone()["n"]
        last_summary = c.execute(
            "SELECT MAX(day) AS m FROM summaries"
        ).fetchone()["m"]
        return {
            "events_total": n_events,
            "events_per_source": per_source,
            "first_event": first,
            "last_event": last,
            "summaries_total": n_summaries,
            "last_summary_day": last_summary,
            "rollups_total": n_rollups,
        }
