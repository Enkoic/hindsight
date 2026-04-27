# Writing a new collector

Adding a data source means writing one Python file and registering it in two places.

## The contract

```python
# hindsight/collectors/base.py
class Collector(ABC):
    name: str
    @abstractmethod
    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        ...
```

- **`name`** — stable lowercase identifier. This becomes the `source` column in the events table and the section heading in the digest. Don't rename it once you have stored data.
- **`collect`** — generator yielding `Event` objects. `since`/`until` are inclusive UTC bounds; if your source is small you can ignore them and emit everything (the store dedupes), but for chatty sources you want to filter inline.

## Walkthrough: writing a Linear collector

Suppose Linear ships a `linear-cli` that writes JSON activity logs to `~/.linear/activity.jsonl`.

```python
# hindsight/collectors/linear.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..models import Event
from .base import Collector


class LinearCollector(Collector):
    name = "linear"

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    def collect(self, since, until) -> Iterable[Event]:
        if not self.log_path.exists():
            return
        with self.log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_raw = rec.get("createdAt")
                if not ts_raw:
                    continue
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
                if since and ts < since: continue
                if until and ts > until: continue
                yield Event(
                    source=self.name,
                    kind=f"linear:{rec.get('type','update')}",
                    ts_start=ts,
                    ts_end=None,
                    title=rec.get("title", "")[:200],
                    project=rec.get("teamKey"),
                    body=rec.get("body", ""),
                    meta={"issue_id": rec.get("id")},
                )
```

## Registering

1. Add the import to `hindsight/collectors/__init__.py`.
2. Append a line in `hindsight/cli.py::_collectors()` so `hindsight collect` instantiates it. Keep it gated on the relevant config attribute so the collector is silently skipped when the user hasn't pointed at a path.
3. Add the env var(s) you want users to set in `hindsight/config.py::Config` and `Config.load()`, plus a stub line in `.env.example`.
4. Add the new `name` to `KNOWN_SOURCES` in `cli.py` so `--sources` validation accepts it.

## Style rules

| Rule | Why |
| --- | --- |
| **UTC at the boundary.** Convert local times before emitting. | Mixing tz silently breaks `events_for_day`. |
| **Yield, don't materialize.** | Some sources have months of history; we're streaming. |
| **Keep `body` raw, keep `title` short.** | The digest re-aggregates `title`; the LLM sees `body`. |
| **`meta` is for opaque source extras**, not for fields the digest cares about. | `meta` is excluded from the fingerprint. |
| **Skip silently if the path doesn't exist.** | Collectors should be optional, not blocking. |
| **Open SQLite sources read-only** (`sqlite3.connect("file:...?mode=ro", uri=True)`). | Don't fight the source app for the write lock. |

## Time-stamping artefacts that have no timestamp

For files like Claude Code memory `.md` (no header timestamp), use `Path.stat().st_mtime` and document it in the docstring. It means re-saving a file looks like a "new event"; that's an acceptable trade because mtime moves only when the user's intent changes.

## Testing locally

```bash
# Limit to your collector while you iterate:
hindsight collect --since 2026-04-01 --until 2026-04-22 --sources linear

# See raw rows without spending an LLM call:
hindsight report --day 2026-04-22

# See exactly what the LLM will receive:
hindsight summarize --day 2026-04-22 --save-digest
```

The digest's catch-all renders any unknown source name as `## <name>` with `- [kind] title` lines, so a freshly registered collector shows up immediately. Once it's earning its keep, add a dedicated section to `summarizer/llm.py::render_digest` (mirroring `cursor` / `chatgpt`) for nicer per-source compaction.
