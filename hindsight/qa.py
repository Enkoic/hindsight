"""Question-answering over cached daily/rollup summaries."""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from .summarizer.llm import Summarizer

QA_SYSTEM_PROMPT = """You answer questions about a user's recent activity using the
cached daily and weekly digests they provide. Rules:

1. Use ONLY the digests as evidence. If the answer is not in the digests, say so plainly.
2. Quote dates explicitly (e.g. "on 2026-04-22") so the user can drill into the source.
3. When several days are relevant, prefer a tight chronological summary over a list.
4. Reply in the user's language.
5. If the user asks about today/yesterday/this week, interpret relative dates against the
   most recent digest date present in the data.
"""


def _trim_to_budget(items: list[str], total_budget_chars: int) -> list[str]:
    """Most recent first; keep adding until budget is hit. Crude but predictable."""
    out: list[str] = []
    used = 0
    for s in items:
        if used + len(s) > total_budget_chars and out:
            break
        out.append(s)
        used += len(s)
    return out


_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def _extract_dates(question: str) -> list[date]:
    out = []
    for m in _DATE_RE.finditer(question):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    return out


def build_context(
    summaries: Iterable[tuple[date, str]],
    rollups: Iterable[tuple[date, date, str]],
    question: str,
    char_budget: int = 80_000,
) -> str:
    """Compose digests into one prompt body, newest first.

    If the question explicitly mentions one or more dates, the corresponding daily
    summaries are pinned to the front so they always make it under the budget.
    """
    summaries = list(summaries)
    rollups = list(rollups)

    pinned_keys: set[date] = set(_extract_dates(question))
    pinned: list[str] = []
    rest: list[str] = []
    for d, content in summaries:
        block = f"\n## DAILY {d.isoformat()}\n{content.strip()}\n"
        if d in pinned_keys:
            pinned.append(block)
        else:
            rest.append(block)

    rollup_blocks = [
        f"\n## ROLLUP {s.isoformat()} … {e.isoformat()}\n{content.strip()}\n"
        for s, e, content in rollups
    ]

    pinned_text = "".join(pinned)
    remaining = max(0, char_budget - len(pinned_text))
    selected = _trim_to_budget(rest, remaining)
    rollup_remaining = max(0, remaining - sum(len(s) for s in selected))
    selected_rollups = _trim_to_budget(rollup_blocks, rollup_remaining)

    parts = [pinned_text, "".join(selected_rollups), "".join(selected)]
    return "\n".join(p for p in parts if p)


def ask(
    summarizer: Summarizer,
    summaries: list[tuple[date, str]],
    rollups: list[tuple[date, date, str]],
    question: str,
    char_budget: int = 80_000,
) -> str:
    context = build_context(summaries, rollups, question, char_budget=char_budget)
    if not context.strip():
        return "(no cached summaries — run `hindsight summarize` first)"
    user = f"<digests>\n{context}\n</digests>\n\nQuestion: {question}"
    return summarizer.complete(QA_SYSTEM_PROMPT, user, max_tokens=2000)
