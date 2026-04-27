"""Synthesize a VS Code workspaceStorage tree on disk to exercise VSCodeCopilotCollector
without requiring VS Code to be installed."""

import json
import sqlite3
from datetime import datetime, timezone

from hindsight.collectors.vscode import VSCodeCopilotCollector


def _make_workspace(root, ws_id, folder, payload):
    ws = root / ws_id
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(
        json.dumps({"folder": folder}), encoding="utf-8"
    )
    db = ws / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    conn.execute(
        "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
        ("interactive.sessions", json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def test_parses_session_with_ms_timestamp(tmp_path):
    root = tmp_path / "ws"
    payload = [
        {
            "sessionId": "abc",
            "requests": [
                {"role": "user", "timestamp": 1762152233845, "message": "hello"},
                {
                    "role": "assistant",
                    "timestamp": 1762152234000,
                    "response": {"text": "hi back"},
                },
            ],
        }
    ]
    _make_workspace(root, "ws1", "file:///proj/x", payload)

    coll = VSCodeCopilotCollector(root)
    events = list(coll.collect(None, None))

    assert len(events) == 2
    assert {e.body for e in events} == {"hello", "hi back"}
    assert all(e.project == "/proj/x" for e in events)
    assert all(e.source == "vscode" for e in events)
    # Both timestamps are ms-scale → should resolve to 2025-11-03 UTC
    for e in events:
        assert e.ts_start.tzinfo == timezone.utc
        assert e.ts_start.year == 2025


def test_skips_db_without_chat_keys(tmp_path):
    root = tmp_path / "ws"
    ws = root / "ws1"
    ws.mkdir(parents=True)
    db = ws / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT, value BLOB)")
    conn.execute("INSERT INTO ItemTable (key, value) VALUES ('chat.unrelated', '{}')")
    conn.commit()
    conn.close()

    assert list(VSCodeCopilotCollector(root).collect(None, None)) == []


def test_filters_by_since_until(tmp_path):
    root = tmp_path / "ws"
    payload = [
        {
            "sessionId": "abc",
            "requests": [
                {"role": "user", "timestamp": 1700000000000, "message": "old"},
                {"role": "user", "timestamp": 1762152233845, "message": "new"},
            ],
        }
    ]
    _make_workspace(root, "ws1", "file:///proj/x", payload)
    cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
    events = list(VSCodeCopilotCollector(root).collect(cutoff, None))
    assert {e.body for e in events} == {"new"}
