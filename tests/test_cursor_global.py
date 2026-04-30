"""Synthesize a Cursor globalStorage layout and verify the bubble-level
collector pulls both user and assistant turns and links them to a workspace project."""

import json
import sqlite3

from hindsight.collectors.cursor import CursorCollector


def _make_workspace_with_composer(root, ws_id, folder, composer_id):
    ws = root / ws_id
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(
        json.dumps({"folder": folder}), encoding="utf-8"
    )
    db = ws / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    composer_data = {"allComposers": [{"composerId": composer_id, "lastUpdatedAt": 1762150000000}]}
    conn.execute(
        "INSERT INTO ItemTable (key, value) VALUES ('composer.composerData', ?)",
        (json.dumps(composer_data),),
    )
    conn.commit()
    conn.close()


def _make_global_db(global_db, bubbles):
    """bubbles: list of (composer_id, bubble_id, type, text, ts_ms)"""
    global_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(global_db)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    for cid, bid, btype, text, ts_ms in bubbles:
        payload = {
            "type": btype,
            "text": text,
            "bubbleId": bid,
            "timingInfo": {"clientRpcSendTime": ts_ms},
        }
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"bubbleId:{cid}:{bid}", json.dumps(payload)),
        )
    conn.commit()
    conn.close()


def test_global_collector_emits_user_and_assistant_with_project(tmp_path):
    ws_root = tmp_path / "User" / "workspaceStorage"
    composer_id = "comp-1"
    _make_workspace_with_composer(ws_root, "ws1", "file:///proj/x", composer_id)

    global_db = tmp_path / "User" / "globalStorage" / "state.vscdb"
    _make_global_db(
        global_db,
        [
            (composer_id, "b1", 1, "hello", 1762152233845),
            (composer_id, "b2", 2, "hi back", 1762152234000),
        ],
    )

    coll = CursorCollector(ws_root)
    events = list(coll.collect(None, None))
    bubble_events = [e for e in events if e.kind.startswith("bubble:")]
    assert len(bubble_events) == 2
    kinds = sorted(e.kind for e in bubble_events)
    assert kinds == ["bubble:assistant", "bubble:user"]
    assert all(e.project == "/proj/x" for e in bubble_events)
    assert {e.body for e in bubble_events} == {"hello", "hi back"}


def test_bubble_without_timing_skipped(tmp_path):
    ws_root = tmp_path / "User" / "workspaceStorage"
    _make_workspace_with_composer(ws_root, "ws1", "file:///proj/y", "comp-x")
    global_db = tmp_path / "User" / "globalStorage" / "state.vscdb"
    global_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(global_db)
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    conn.execute(
        "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
        ("bubbleId:comp-x:b1", json.dumps({"type": 1, "text": "no time"})),
    )
    conn.commit()
    conn.close()

    coll = CursorCollector(ws_root)
    events = [e for e in coll.collect(None, None) if e.kind.startswith("bubble:")]
    assert events == []


def test_orphan_bubble_no_project_mapping(tmp_path):
    """A bubble whose composer is not registered in any workspace state.vscdb
    should still be emitted, just without a project tag."""
    ws_root = tmp_path / "User" / "workspaceStorage"
    ws_root.mkdir(parents=True)
    global_db = tmp_path / "User" / "globalStorage" / "state.vscdb"
    _make_global_db(
        global_db,
        [("orphan-comp", "b1", 1, "lonely", 1762152233845)],
    )

    coll = CursorCollector(ws_root)
    events = [e for e in coll.collect(None, None) if e.kind.startswith("bubble:")]
    assert len(events) == 1
    assert events[0].project is None
    assert events[0].body == "lonely"
