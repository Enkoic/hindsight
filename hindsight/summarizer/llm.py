from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Iterable

from ..config import Config

SYSTEM_PROMPT = """You are a personal activity analyst. The user gives you raw events
collected from multiple tools (ActivityWatch window/afk/web logs, Claude Code session
transcripts, Codex CLI rollouts, and other AI dialog exports). Your job is to produce
a crisp daily digest in Markdown so the user can see, retrospectively:

1. How time was spent (rough blocks, not per-minute).
2. Which AI tools were used and for what purposes.
3. What problems were worked on, which were solved, which remain open.
4. Notable insights, blockers, decisions, or commitments.

Write in the user's language (detect from the messages). Be concrete: quote short
snippets when they add signal. Do not invent activity not present in the data.
Output must be valid Markdown with these sections (keep exact order):

## 概览 / Overview
## 时间分布 / Time Breakdown
## AI 对话 / AI Sessions
## 已解决 / Solved
## 进行中 / In Progress
## 待办 & 承诺 / Open Threads
## 备注 / Notes
"""

ROLLUP_SYSTEM_PROMPT = """You are a personal activity analyst producing a multi-day rollup
(weekly or monthly). The user gives you a sequence of already-written daily digests for
consecutive days. Your job is to synthesize them — not concatenate them — into a higher-
order narrative that highlights what only becomes visible across days.

Focus on:
1. Multi-day initiatives & projects (where time was actually invested).
2. Throughlines & decisions: choices made earlier that played out later.
3. Recurring blockers, debt, or unanswered questions still open at the end.
4. What's clearly *finished* vs *abandoned* vs *still in flight*.
5. Patterns in tool/AI usage, time-of-day rhythms if obvious.

Write in the user's language. Be concrete and reference dates. Skip trivial details that
appeared in only one day if they were resolved that same day. Output must be valid Markdown
with these sections (keep order):

## 总览 / Rollup Overview
## 主线项目 / Major Threads
## 已完成 / Completed
## 进行中 / Still In Flight
## 未决 & 风险 / Open Questions & Risk
## 关键决策与洞察 / Decisions & Insights
## 度量速记 / Quick Stats
"""


def render_digest(events: Iterable[sqlite3.Row], day: date) -> str:
    """Compact the events list into a digest the LLM can actually reason over."""
    events = list(events)
    by_source: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for e in events:
        by_source[e["source"]].append(e)

    lines: list[str] = [f"# Raw events for {day.isoformat()}", ""]

    # ActivityWatch: aggregate by app/title to keep payload small
    aw = by_source.get("activitywatch", [])
    if aw:
        app_time: Counter[str] = Counter()
        title_time: Counter[str] = Counter()
        web_time: Counter[str] = Counter()
        afk: Counter[str] = Counter()
        for row in aw:
            meta = json.loads(row["meta"] or "{}")
            dur = float(meta.get("duration_sec", 0))
            kind = row["kind"]
            if kind.startswith("afk:"):
                afk[kind] += dur
            elif kind == "web":
                web_time[row["title"][:80]] += dur
            else:
                app_time[row["project"] or "unknown"] += dur
                title_time[row["title"][:80]] += dur

        lines.append("## ActivityWatch")
        lines.append("### Apps (minutes)")
        for app, sec in app_time.most_common(20):
            lines.append(f"- {app}: {sec / 60:.1f}m")
        lines.append("### Top windows")
        for t, sec in title_time.most_common(25):
            lines.append(f"- {t} — {sec / 60:.1f}m")
        if web_time:
            lines.append("### Web")
            for t, sec in web_time.most_common(15):
                lines.append(f"- {t} — {sec / 60:.1f}m")
        lines.append("### AFK")
        for k, sec in afk.most_common():
            lines.append(f"- {k}: {sec / 60:.1f}m")
        lines.append("")

    for source in ("claude_code", "codex"):
        rows = by_source.get(source, [])
        if not rows:
            continue
        lines.append(f"## {source}")

        # Split into transcript messages vs memory/plan/task artefacts.
        session_rows_list = [r for r in rows if r["kind"].startswith(("user", "assistant", "message"))]
        memory_rows = [r for r in rows if r["kind"].startswith("memory")]
        plan_rows = [r for r in rows if r["kind"] == "plan"]
        task_rows = [r for r in rows if r["kind"].startswith("task")]

        if session_rows_list:
            by_session: dict[str, list[sqlite3.Row]] = defaultdict(list)
            for row in session_rows_list:
                meta = json.loads(row["meta"] or "{}")
                by_session[meta.get("session_id", "unknown")].append(row)
            for sid, session_rows in by_session.items():
                project = session_rows[0]["project"] or "?"
                first = datetime.fromisoformat(session_rows[0]["ts_start"]).strftime("%H:%M")
                last = datetime.fromisoformat(session_rows[-1]["ts_start"]).strftime("%H:%M")
                lines.append(f"### session {sid[:8]} — {project} — {first}→{last}")
                shown = 0
                for r in session_rows:
                    body = (r["body"] or "").strip().replace("\n", " ")
                    if not body:
                        continue
                    lines.append(f"- [{r['kind']}] {body[:300]}")
                    shown += 1
                    if shown >= 40:
                        lines.append("- …(truncated)")
                        break

        if memory_rows:
            lines.append("### memories (written/updated today)")
            for r in memory_rows[:30]:
                meta = json.loads(r["meta"] or "{}")
                desc = meta.get("mem_desc") or ""
                name = meta.get("mem_name") or r["title"]
                lines.append(f"- [{r['kind']}] {name} — {desc[:200]}")

        if plan_rows:
            lines.append("### plans (written/updated today)")
            for r in plan_rows[:20]:
                lines.append(f"- {r['title']}")

        if task_rows:
            lines.append("### tasks (state changes today)")
            by_status: Counter[str] = Counter()
            for r in task_rows:
                by_status[r["kind"]] += 1
            for k, n in by_status.most_common():
                lines.append(f"- {k}: {n}")
            for r in task_rows[:25]:
                lines.append(f"  - {r['title']}")
        lines.append("")

    for source in ("claude_history", "codex_history"):
        rows = by_source.get(source, [])
        if not rows:
            continue
        lines.append(f"## {source} (user prompts in chronological order)")
        by_project: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            by_project[r["project"] or "-"].append(r)
        for proj, prows in by_project.items():
            lines.append(f"### {proj}")
            for r in prows[:60]:
                t = datetime.fromisoformat(r["ts_start"]).strftime("%H:%M")
                body = (r["body"] or "").strip().replace("\n", " ")
                if not body:
                    continue
                lines.append(f"- {t} {body[:260]}")
            if len(prows) > 60:
                lines.append(f"- …(+{len(prows) - 60} more)")
        lines.append("")

    # Catch-all for other sources
    for source, rows in by_source.items():
        if source in {"activitywatch", "claude_code", "codex", "claude_history", "codex_history"}:
            continue
        lines.append(f"## {source}")
        for r in rows[:50]:
            lines.append(f"- [{r['kind']}] {r['title']}")
        lines.append("")

    return "\n".join(lines)


class Summarizer(ABC):
    provider: str
    model: str

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str: ...

    def summarize(self, digest: str, day: date) -> str:
        return self.complete(SYSTEM_PROMPT, f"Date: {day.isoformat()}\n\n{digest}")


class AnthropicSummarizer(Summarizer):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "\n".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        ).strip()


class OpenAISummarizer(Summarizer):
    provider = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()


def render_rollup_digest(daily_summaries: list[tuple[date, str]]) -> str:
    """Concatenate cached daily summaries into a single payload for the rollup LLM call."""
    lines: list[str] = []
    for day, content in daily_summaries:
        lines.append(f"\n=========================\n# {day.isoformat()}\n=========================\n")
        lines.append(content.strip())
    return "\n".join(lines).strip()


def summarize_rollup(
    summarizer: Summarizer,
    daily_summaries: list[tuple[date, str]],
    start_day: date,
    end_day: date,
) -> str:
    digest = render_rollup_digest(daily_summaries)
    user = (
        f"Period: {start_day.isoformat()} … {end_day.isoformat()} "
        f"({len(daily_summaries)} days with cached summaries)\n\n{digest}"
    )
    return summarizer.complete(ROLLUP_SYSTEM_PROMPT, user, max_tokens=6000)


def build_summarizer(cfg: Config) -> Summarizer:
    if cfg.llm_provider == "anthropic":
        if not cfg.anthropic_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        return AnthropicSummarizer(cfg.anthropic_key, cfg.llm_model)
    if cfg.llm_provider == "openai":
        if not cfg.openai_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        return OpenAISummarizer(cfg.openai_key, cfg.llm_model, cfg.openai_base_url)
    raise RuntimeError(f"Unknown provider: {cfg.llm_provider}")
