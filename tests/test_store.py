from datetime import date, datetime, timezone

from hindsight.models import Event
from hindsight.store import Store


def _ev(ts: datetime, body: str = "x", source: str = "claude_code", kind: str = "message:user"):
    return Event(
        source=source,
        kind=kind,
        ts_start=ts,
        ts_end=None,
        title=body[:50],
        project=None,
        body=body,
        meta={},
    )


def test_upsert_dedup_by_fingerprint(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    ts = datetime(2026, 4, 22, 12, tzinfo=timezone.utc)
    n1 = s.upsert_events([_ev(ts, "a"), _ev(ts, "a")])
    assert n1 == 1
    n2 = s.upsert_events([_ev(ts, "a")])
    assert n2 == 0


def test_events_for_day_filters_by_utc(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    s.upsert_events(
        [
            _ev(datetime(2026, 4, 22, 0, 0, tzinfo=timezone.utc), "morning"),
            _ev(datetime(2026, 4, 22, 23, 59, tzinfo=timezone.utc), "night"),
            _ev(datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc), "next"),
        ]
    )
    rows = s.events_for_day(date(2026, 4, 22))
    assert len(rows) == 2


def test_stats_reports_counts_and_range(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    s.upsert_events(
        [
            _ev(datetime(2026, 4, 22, 0, 0, tzinfo=timezone.utc), "a", source="claude_code"),
            _ev(datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc), "b", source="claude_code"),
            _ev(datetime(2026, 4, 23, 0, 0, tzinfo=timezone.utc), "c", source="cursor"),
        ]
    )
    s.save_summary(date(2026, 4, 22), "openai", "x", "content")
    s.save_rollup(date(2026, 4, 20), date(2026, 4, 26), "openai", "x", "rollup content")

    out = s.stats()
    assert out["events_total"] == 3
    assert out["events_per_source"] == {"claude_code": 2, "cursor": 1}
    assert out["summaries_total"] == 1
    assert out["rollups_total"] == 1
    assert out["last_summary_day"] == "2026-04-22"
    assert out["first_event"].startswith("2026-04-22")
    assert out["last_event"].startswith("2026-04-23")


def test_purge_by_age(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    s.upsert_events(
        [
            _ev(datetime(2026, 1, 1, tzinfo=timezone.utc), "old"),
            _ev(datetime(2026, 4, 22, tzinfo=timezone.utc), "new"),
        ]
    )
    out = s.purge(before=date(2026, 4, 1))
    assert out["deleted"] == 1
    rows = s.events_for_day(date(2026, 4, 22))
    assert len(rows) == 1


def test_purge_by_source(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    ts = datetime(2026, 4, 22, tzinfo=timezone.utc)
    s.upsert_events([_ev(ts, "a", source="cursor"), _ev(ts, "b", source="claude_code")])
    out = s.purge(sources=["cursor"])
    assert out["deleted"] == 1
    remaining = [r["source"] for r in s.events_for_day(date(2026, 4, 22))]
    assert remaining == ["claude_code"]


def test_purge_requires_a_filter(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    try:
        s.purge()
        raised = False
    except ValueError:
        raised = True
    assert raised, "no-arg purge must raise"


def test_summary_and_rollup_round_trip(tmp_path):
    s = Store(tmp_path / "t.sqlite")
    s.save_summary(date(2026, 4, 22), "openai", "x", "daily content")
    s.save_summary(date(2026, 4, 23), "openai", "x", "daily content 23")
    assert s.get_summary(date(2026, 4, 22), "openai", "x") == "daily content"

    in_range = s.summaries_in_range(date(2026, 4, 22), date(2026, 4, 23), "openai", "x")
    assert [d.day for d, _ in in_range] == [22, 23]

    s.save_rollup(date(2026, 4, 22), date(2026, 4, 28), "openai", "x", "rollup content")
    assert s.get_rollup(date(2026, 4, 22), date(2026, 4, 28), "openai", "x") == "rollup content"
