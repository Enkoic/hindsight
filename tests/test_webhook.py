from hindsight.exporters.webhook import _chunks, _is_discord


def test_is_discord_detection():
    assert _is_discord("https://discord.com/api/webhooks/123/abc")
    assert _is_discord("https://discordapp.com/api/webhooks/123/abc")
    assert not _is_discord("https://hooks.slack.com/services/T/B/X")
    assert not _is_discord("https://example.com/webhook")


def test_chunks_short_text_unchanged():
    out = _chunks("hello", 1000)
    assert out == ["hello"]


def test_chunks_breaks_on_newline_when_possible():
    text = ("aaa\n" * 10).strip()  # 39 chars, lots of newlines
    out = _chunks(text, 16)
    # No chunk can exceed the limit
    assert all(len(c) <= 16 for c in out)
    # Reassembly preserves all characters (modulo trimmed leading newlines)
    assert "".join(out).replace("\n", "") == text.replace("\n", "")


def test_chunks_long_continuous_text_falls_back_to_hard_cut():
    text = "x" * 5000
    out = _chunks(text, 1000)
    assert len(out) == 5
    assert all(len(c) == 1000 for c in out)
