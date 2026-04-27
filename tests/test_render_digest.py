"""Render-digest smoke test using a real SQLite Store so rows match production shape."""

from datetime import date, datetime, timezone

from hindsight.models import Event
from hindsight.store import Store
from hindsight.summarizer import render_digest, render_rollup_digest


def _populate(store: Store, day: date) -> None:
    ts = lambda h, m: datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc)  # noqa: E731

    store.upsert_events(
        [
            Event(
                source="activitywatch",
                kind="window",
                ts_start=ts(9, 0),
                ts_end=ts(9, 30),
                title="VSCode — main.py",
                project="VSCode",
                body="main.py",
                meta={"bucket": "win", "duration_sec": 1800.0},
            ),
            Event(
                source="claude_code",
                kind="message:user",
                ts_start=ts(10, 0),
                ts_end=None,
                title="how do I parse jsonl?",
                project="/Users/me/proj",
                body="how do I parse jsonl?",
                meta={"session_id": "sess1"},
            ),
            Event(
                source="claude_code",
                kind="message:assistant",
                ts_start=ts(10, 0),
                ts_end=None,
                title="Use json.loads per line.",
                project="/Users/me/proj",
                body="Use json.loads per line.",
                meta={"session_id": "sess1"},
            ),
            Event(
                source="cursor",
                kind="generation:composer",
                ts_start=ts(11, 0),
                ts_end=None,
                title="Fix import error",
                project="/Users/me/proj",
                body="Fix the missing import",
                meta={"workspace_id": "abc"},
            ),
            Event(
                source="claude_history",
                kind="user_prompt",
                ts_start=ts(12, 0),
                ts_end=None,
                title="ship it",
                project="/Users/me/proj",
                body="ship it",
                meta={},
            ),
        ]
    )


def test_render_digest_includes_each_source_section(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    d = date(2026, 4, 22)
    _populate(s, d)
    out = render_digest(s.events_for_day(d), d)

    assert "## ActivityWatch" in out
    assert "VSCode" in out
    assert "## claude_code" in out
    assert "session sess1" in out  # 8-char session prefix
    assert "## cursor" in out
    assert "Fix import error" in out or "Fix the missing import" in out
    assert "## claude_history" in out


def test_render_rollup_digest_concatenates_with_dividers():
    out = render_rollup_digest(
        [(date(2026, 4, 22), "AAA"), (date(2026, 4, 23), "BBB")]
    )
    assert "2026-04-22" in out and "AAA" in out
    assert "2026-04-23" in out and "BBB" in out
    assert out.count("=========================") >= 4
