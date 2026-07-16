import argparse
import json

import codex_session_watch as watch


def append_item(path, item):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item) + "\n")


def write_session(path, session_id, originator="Codex Desktop", source="vscode"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "originator": originator,
                    "source": source,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def user_message():
    return {"type": "event_msg", "payload": {"type": "user_message"}}


def task_complete():
    return {"type": "event_msg", "payload": {"type": "task_complete"}}


def test_session_identity_includes_meta_id_and_originator(tmp_path):
    desktop = tmp_path / "desktop.jsonl"
    vscode = tmp_path / "vscode.jsonl"
    write_session(desktop, "S1")
    write_session(vscode, "S2", originator="VS Code", source="vscode")

    desktop_identity = watch.session_identity(desktop, "codex-watch")
    vscode_identity = watch.session_identity(vscode, "codex-watch")

    assert desktop_identity.client_id == "codex-desktop"
    assert desktop_identity.session_id == "S1"
    assert vscode_identity.client_id == "codex-vscode"
    assert vscode_identity.session_id == "S2"


def test_tracker_reads_appends_from_two_sessions(tmp_path):
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    write_session(first, "A")
    write_session(second, "B", originator="VS Code", source="vscode")
    tracker = watch.SessionTracker(replay=False)
    tracker.discover([first, second], now=0)

    append_item(first, task_complete())
    append_item(second, user_message())
    events = tracker.read_available(now=1)

    assert {(event.identity.session_id, event.anim) for event in events} == {
        ("A", "happy"),
        ("B", "thinking"),
    }


def test_malformed_line_in_one_session_does_not_block_another(tmp_path):
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    write_session(first, "A")
    write_session(second, "B")
    tracker = watch.SessionTracker(replay=False)
    tracker.discover([first, second], now=0)

    with first.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")
    append_item(second, user_message())

    events = tracker.read_available(now=1)

    assert [(event.identity.session_id, event.anim) for event in events] == [
        ("B", "thinking")
    ]


def test_closed_inactive_handle_reopens_at_retained_offset(tmp_path):
    path = tmp_path / "a.jsonl"
    write_session(path, "A")
    tracker = watch.SessionTracker(replay=False)
    tracker.discover([path], now=0)
    append_item(path, user_message())
    assert [event.anim for event in tracker.read_available(now=1)] == ["thinking"]

    tracker.close_inactive(now=902, inactive_seconds=900)
    assert tracker.sessions[path].handle is None
    append_item(path, task_complete())

    assert [event.anim for event in tracker.read_available(now=903)] == ["happy"]


def test_deleted_file_removes_tracking_metadata(tmp_path):
    path = tmp_path / "a.jsonl"
    write_session(path, "A")
    tracker = watch.SessionTracker(replay=False)
    tracker.discover([path], now=0)

    path.unlink()
    tracker.remove_deleted()

    assert path not in tracker.sessions


def test_session_args_and_payload_keep_platform_and_session_identity(monkeypatch):
    path = argparse.Namespace(
        client_id="codex-watch",
        source="codex",
        client_kind="codex",
    )
    identity = watch.SessionIdentity("codex-desktop", "S1")

    args = watch.args_for(identity, path)

    assert args.client_id == "codex-desktop"
    assert args.client_kind == "codex"
    assert args.session_id == "S1"


def test_recent_session_files_respects_horizon(tmp_path, monkeypatch):
    recent = tmp_path / "recent.jsonl"
    old = tmp_path / "old.jsonl"
    write_session(recent, "R")
    write_session(old, "O")
    monkeypatch.setattr(watch, "path_mtime", lambda path: 95 if path == recent else 10)

    assert watch.recent_session_files(tmp_path, now=100, horizon=20) == [recent]
