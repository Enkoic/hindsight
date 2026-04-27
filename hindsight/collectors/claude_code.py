from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..models import Event
from .base import Collector


def _decode_project_dir(dir_name: str) -> str:
    """Claude stores '/Users/cab/Documents/GitHub/myproj' as '-Users-cab-Documents-GitHub-myproj'."""
    if dir_name.startswith("-"):
        return "/" + dir_name[1:].replace("-", "/")
    return dir_name


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _mtime_utc(p: Path) -> datetime:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)


def _parse_memory_frontmatter(body: str) -> tuple[str | None, str | None, str | None]:
    """Returns (name, type, description) from a --- YAML-ish frontmatter block."""
    if not body.startswith("---"):
        return None, None, None
    end = body.find("\n---", 3)
    if end < 0:
        return None, None, None
    fm = body[3:end]
    name = mtype = desc = None
    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line[5:].strip()
        elif line.startswith("type:"):
            mtype = line[5:].strip()
        elif line.startswith("description:"):
            desc = line[12:].strip()
    return name, mtype, desc


class ClaudeCodeCollector(Collector):
    """Parses Claude Code data under ~/.claude:
    - projects/<slug>/*.jsonl session transcripts (messages & tool use)
    - projects/<slug>/memory/*.md long-term memories (user/project/feedback/reference)
    - plans/*.md design plans
    - tasks/<session>/*.json TaskCreate snapshots
    """

    name = "claude_code"

    def __init__(self, root: Path) -> None:
        self.root = root                          # ~/.claude/projects
        self.claude_home = root.parent            # ~/.claude

    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        if self.root.exists():
            for project_dir in sorted(self.root.iterdir()):
                if not project_dir.is_dir():
                    continue
                project = _decode_project_dir(project_dir.name)
                for jsonl in project_dir.glob("*.jsonl"):
                    yield from self._parse_file(jsonl, project, since, until)
                yield from self._collect_memory(project_dir / "memory", project, since, until)

        yield from self._collect_plans(since, until)
        yield from self._collect_tasks(since, until)

    def _parse_file(
        self,
        path: Path,
        project: str,
        since: datetime | None,
        until: datetime | None,
    ) -> Iterable[Event]:
        session_id = path.stem
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
                    ev = self._record_to_event(rec, project, session_id)
                    if ev is None:
                        continue
                    if since and ev.ts_start < since:
                        continue
                    if until and ev.ts_start > until:
                        continue
                    yield ev
        except OSError:
            return

    def _record_to_event(
        self, rec: dict, project: str, session_id: str
    ) -> Event | None:
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None:
            return None

        rec_type = rec.get("type", "")
        msg = rec.get("message") or {}
        role = msg.get("role") or rec_type
        content = msg.get("content")
        body = self._stringify_content(content)
        title = body.splitlines()[0][:200] if body else rec_type

        return Event(
            source=self.name,
            kind=f"{rec_type}:{role}" if role else rec_type,
            ts_start=ts,
            ts_end=None,
            title=title or f"{rec_type}",
            project=project,
            body=body,
            meta={"session_id": session_id, "uuid": rec.get("uuid")},
        )

    def _collect_memory(
        self, mem_dir: Path, project: str, since: datetime | None, until: datetime | None
    ) -> Iterable[Event]:
        if not mem_dir.exists():
            return
        for md in mem_dir.glob("*.md"):
            try:
                ts = _mtime_utc(md)
            except OSError:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            try:
                body = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            name, mtype, desc = _parse_memory_frontmatter(body)
            title = f"[memory:{mtype or '?'}] {name or md.stem}"
            yield Event(
                source=self.name,
                kind=f"memory:{mtype or 'note'}",
                ts_start=ts,
                ts_end=None,
                title=title[:200],
                project=project,
                body=body,
                meta={"file": str(md), "mem_name": name, "mem_desc": desc},
            )

    def _collect_plans(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        plans_dir = self.claude_home / "plans"
        if not plans_dir.exists():
            return
        for md in plans_dir.glob("*.md"):
            try:
                ts = _mtime_utc(md)
            except OSError:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            try:
                body = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            first_heading = next(
                (line[2:].strip() for line in body.splitlines() if line.startswith("# ")),
                md.stem,
            )
            yield Event(
                source=self.name,
                kind="plan",
                ts_start=ts,
                ts_end=None,
                title=f"[plan] {first_heading}"[:200],
                project=None,
                body=body,
                meta={"file": str(md)},
            )

    def _collect_tasks(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        tasks_dir = self.claude_home / "tasks"
        if not tasks_dir.exists():
            return
        for session_dir in tasks_dir.iterdir():
            if not session_dir.is_dir():
                continue
            for jf in session_dir.glob("*.json"):
                try:
                    ts = _mtime_utc(jf)
                except OSError:
                    continue
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
                try:
                    data = json.loads(jf.read_text(encoding="utf-8", errors="replace"))
                except (OSError, json.JSONDecodeError):
                    continue
                subject = data.get("subject", "")
                status = data.get("status", "?")
                desc = data.get("description", "")
                yield Event(
                    source=self.name,
                    kind=f"task:{status}",
                    ts_start=ts,
                    ts_end=None,
                    title=f"[task:{status}] {subject}"[:200],
                    project=None,
                    body=f"{subject}\n\n{desc}".strip(),
                    meta={
                        "session_id": session_dir.name,
                        "task_id": data.get("id"),
                        "file": str(jf),
                    },
                )

    @staticmethod
    def _stringify_content(content) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    t = block.get("type")
                    if t == "text":
                        parts.append(block.get("text", ""))
                    elif t == "tool_use":
                        name = block.get("name", "tool")
                        parts.append(f"[tool:{name}]")
                    elif t == "tool_result":
                        parts.append("[tool_result]")
                    else:
                        parts.append(f"[{t}]")
                else:
                    parts.append(str(block))
            return "\n".join(p for p in parts if p)
        return str(content)
