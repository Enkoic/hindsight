from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx

from ..models import Event
from .base import Collector


class ActivityWatchCollector(Collector):
    """Pulls window + afk buckets from ActivityWatch's REST API."""

    name = "activitywatch"

    def __init__(self, server_url: str, timeout: float = 10.0) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def _buckets(self) -> list[str]:
        try:
            r = httpx.get(f"{self.server_url}/api/0/buckets", timeout=self.timeout)
            r.raise_for_status()
            return list(r.json().keys())
        except (httpx.HTTPError, httpx.ConnectError):
            return []

    def _events(self, bucket: str, since: datetime, until: datetime) -> list[dict]:
        params = {"start": since.isoformat(), "end": until.isoformat(), "limit": 5000}
        try:
            r = httpx.get(
                f"{self.server_url}/api/0/buckets/{bucket}/events",
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return []

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        now = datetime.now(timezone.utc)
        since = since or (now - timedelta(days=1))
        until = until or now

        for bucket in self._buckets():
            is_window = "window" in bucket.lower()
            is_afk = "afk" in bucket.lower()
            is_web = "web" in bucket.lower() or "browser" in bucket.lower()
            if not (is_window or is_afk or is_web):
                continue

            for ev in self._events(bucket, since, until):
                try:
                    ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    continue
                dur = float(ev.get("duration", 0))
                end = ts + timedelta(seconds=dur) if dur > 0 else None
                data = ev.get("data", {})

                if is_afk:
                    status = data.get("status", "unknown")
                    yield Event(
                        source=self.name,
                        kind=f"afk:{status}",
                        ts_start=ts,
                        ts_end=end,
                        title=f"afk={status}",
                        project=None,
                        body="",
                        meta={"bucket": bucket, "duration_sec": dur},
                    )
                elif is_web:
                    title = data.get("title") or data.get("url") or ""
                    yield Event(
                        source=self.name,
                        kind="web",
                        ts_start=ts,
                        ts_end=end,
                        title=title[:200],
                        project=data.get("url"),
                        body=data.get("url", ""),
                        meta={"bucket": bucket, "duration_sec": dur, **data},
                    )
                else:
                    app = data.get("app", "")
                    title = data.get("title", "")
                    yield Event(
                        source=self.name,
                        kind="window",
                        ts_start=ts,
                        ts_end=end,
                        title=f"{app} — {title}"[:200],
                        project=app,
                        body=title,
                        meta={"bucket": bucket, "duration_sec": dur, **data},
                    )
