from datetime import datetime, timezone

from hindsight.models import Event


def _ev(**overrides):
    base = dict(
        source="claude_code",
        kind="message:user",
        ts_start=datetime(2026, 4, 22, 14, 30, tzinfo=timezone.utc),
        ts_end=None,
        title="hello",
        project="/Users/me/proj",
        body="hello world",
        meta={},
    )
    base.update(overrides)
    return Event(**base)


def test_fingerprint_is_stable_across_instances():
    a = _ev()
    b = _ev()
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_changes_on_ts_change():
    a = _ev()
    b = _ev(ts_start=datetime(2026, 4, 22, 14, 31, tzinfo=timezone.utc))
    assert a.fingerprint() != b.fingerprint()


def test_fingerprint_ignores_meta():
    """Fingerprint excludes meta so re-collection is idempotent when only side
    metadata (e.g. duration_sec, session_id) gets added on a re-pass."""
    a = _ev(meta={"x": 1})
    b = _ev(meta={"x": 2})
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_ignores_body_past_first_256_chars():
    """Long bodies are hashed only up to body[:256] to keep dedup stable when
    transcripts grow with content appended later."""
    head = "x" * 256
    a = _ev(body=head + "AAA")
    b = _ev(body=head + "BBB")
    assert a.fingerprint() == b.fingerprint()


def test_to_row_serializes_meta_and_iso_dates():
    a = _ev(meta={"k": "v"})
    row = a.to_row()
    assert row["meta"] == '{"k": "v"}'
    assert row["ts_start"].endswith("+00:00")
    assert row["ts_end"] is None
    assert row["fingerprint"] == a.fingerprint()


def test_duration_zero_when_no_end():
    assert _ev().duration_sec == 0.0


def test_duration_positive_with_end():
    a = _ev(ts_end=datetime(2026, 4, 22, 14, 35, tzinfo=timezone.utc))
    assert a.duration_sec == 300.0
