from datetime import date

from hindsight.qa import _extract_dates, build_context


def test_extract_dates_finds_iso_dates():
    assert _extract_dates("what did I do on 2026-04-22 and 2026-04-23?") == [
        date(2026, 4, 22),
        date(2026, 4, 23),
    ]
    assert _extract_dates("nothing here") == []


def test_build_context_pins_referenced_dates():
    summaries = [
        (date(2026, 4, 28), "april 28 content"),
        (date(2026, 4, 22), "april 22 content"),
        (date(2026, 4, 21), "april 21 content"),
    ]
    out = build_context(summaries, [], "what did I do on 2026-04-22?", char_budget=10_000)
    # Pinned date appears first regardless of recency order
    pos_22 = out.index("april 22")
    pos_28 = out.index("april 28")
    assert pos_22 < pos_28


def test_build_context_respects_budget():
    summaries = [(date(2026, 4, d), "x" * 1000) for d in range(1, 11)]
    out = build_context(summaries, [], "summary?", char_budget=2500)
    # Should keep at least 1 but well under everything
    assert len(out) <= 5000
    assert "x" in out


def test_build_context_handles_no_data():
    out = build_context([], [], "anything", char_budget=10_000)
    assert out == ""


def test_build_context_includes_rollups():
    rollups = [(date(2026, 4, 21), date(2026, 4, 27), "ROLLUP_TEXT")]
    out = build_context([], rollups, "what happened?", char_budget=10_000)
    assert "ROLLUP_TEXT" in out
    assert "2026-04-21" in out and "2026-04-27" in out
