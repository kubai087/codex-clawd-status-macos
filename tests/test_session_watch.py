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


def turn_aborted():
    return {"type": "event_msg", "payload": {"type": "turn_aborted"}}


def function_call(name, arguments):
    return {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": name,
            "arguments": arguments,
        },
    }


def custom_tool_call(name, tool_input):
    return {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": name,
            "input": tool_input,
        },
    }


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


def test_turn_aborted_deactivates_only_its_session(tmp_path):
    aborted = tmp_path / "aborted.jsonl"
    completed = tmp_path / "completed.jsonl"
    write_session(aborted, "A")
    write_session(completed, "B")
    tracker = watch.SessionTracker(replay=False)
    tracker.discover([aborted, completed], now=0)

    append_item(aborted, turn_aborted())
    append_item(completed, task_complete())

    events = tracker.read_available(now=1)

    assert [(event.identity.session_id, event.anim) for event in events] == [
        ("A", "sleeping"),
        ("B", "happy"),
    ]
    assert events[0].reason == "session turn_aborted"


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


def test_legacy_exec_command_escalation_maps_to_waiting():
    item = function_call(
        "exec_command",
        json.dumps(
            {
                "cmd": "installer --system",
                "sandbox_permissions": "require_escalated",
            }
        ),
    )

    assert watch.item_to_anim(item) == (
        "confused",
        "session permission_request tool='exec_command'",
    )


def test_nested_exec_command_escalation_maps_to_waiting():
    item = custom_tool_call(
        "exec",
        "const r = await tools.exec_command("
        '{"cmd":"installer --system",'
        '"sandbox_permissions":"require_escalated"}'
        "); text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "confused",
        "session permission_request tool='exec'",
    )


def test_nested_exec_command_javascript_object_escalation_maps_to_waiting():
    item = custom_tool_call(
        "exec",
        "const r = await tools.exec_command({\n"
        '  cmd: "curl -fsS http://127.0.0.1:8765/state",\n'
        '  workdir: "/tmp",\n'
        '  "sandbox_permissions": "require_escalated",\n'
        '  justification: "Allow localhost access?"\n'
        "});\n"
        "text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "confused",
        "session permission_request tool='exec'",
    )


def test_nested_request_permissions_maps_to_waiting():
    item = custom_tool_call(
        "exec",
        "const r = await tools.request_permissions({\n"
        "  permissions: { network: { enabled: true } },\n"
        '  reason: "Test network access."\n'
        "});\n"
        "text(r);",
    )

    assert watch.item_to_anim(item) == (
        "confused",
        "session permission_request tool='exec'",
    )


def test_direct_request_permissions_maps_to_waiting():
    item = custom_tool_call(
        "request_permissions",
        '{"permissions":{"network":{"enabled":true}}}',
    )

    assert watch.item_to_anim(item) == (
        "confused",
        "session permission_request tool='request_permissions'",
    )


def test_all_direct_user_approval_tools_map_to_waiting():
    for tool_name in (
        "request_user_input",
        "functions.request_user_input",
        "request_plugin_install",
        "functions.request_plugin_install",
        "AskUserQuestion",
        "AskFollowup",
        "ExitPlanMode",
    ):
        assert watch.item_to_anim(custom_tool_call(tool_name, "{}")) == (
            "confused",
            f"session user_approval tool={tool_name!r}",
        )


def test_nested_user_approval_tools_map_to_waiting():
    for tool_name in (
        "request_user_input",
        "request_plugin_install",
    ):
        item = custom_tool_call(
            "exec",
            f"const r = await tools.{tool_name}({{}}); text(r);",
        )

        assert watch.item_to_anim(item) == (
            "confused",
            "session user_approval tool='exec'",
        )


def test_explicit_approval_and_elicitation_items_map_to_waiting():
    for payload_type in (
        "approval_request",
        "permission_request",
        "elicitation_request",
        "mcp_approval_request",
    ):
        item = {"type": "response_item", "payload": {"type": payload_type}}

        assert watch.item_to_anim(item) == (
            "confused",
            f"session {payload_type}",
        )


def test_explicit_approval_responses_resume_thinking():
    for payload_type in (
        "approval_response",
        "permission_response",
        "elicitation_response",
        "mcp_approval_response",
    ):
        item = {"type": "response_item", "payload": {"type": payload_type}}

        assert watch.item_to_anim(item) == (
            "thinking",
            f"session {payload_type}",
        )


def test_explicit_approval_event_messages_map_to_waiting():
    for payload_type in (
        "approval_request",
        "permission_request",
        "elicitation_request",
        "mcp_approval_request",
        "user_input_request",
    ):
        item = {"type": "event_msg", "payload": {"type": payload_type}}

        assert watch.item_to_anim(item) == (
            "confused",
            f"session {payload_type}",
        )


def test_request_permissions_text_inside_command_is_not_a_permission_request():
    item = custom_tool_call(
        "exec",
        "const r = await tools.exec_command({\n"
        '  cmd: "rg \\"tools.request_permissions(\\" source"\n'
        "});\n"
        "text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )


def test_request_permissions_text_inside_comment_is_not_a_permission_request():
    item = custom_tool_call(
        "exec",
        "// tools.request_permissions({ permissions: {} });\n"
        'const r = await tools.exec_command({ cmd: "pwd" });\n'
        "text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )


def test_approval_tools_inside_strings_and_comments_do_not_map_to_waiting():
    item = custom_tool_call(
        "exec",
        'const docs = "tools.request_user_input({})";\n'
        "/* tools.request_plugin_install({}); */\n"
        'const r = await tools.exec_command({"cmd":"pwd"}); text(r.output);',
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )


def test_escalated_exec_inside_comment_does_not_map_to_waiting():
    item = custom_tool_call(
        "exec",
        '/* tools.exec_command({"cmd":"pwd",'
        '"sandbox_permissions":"require_escalated"}); */\n'
        'const r = await tools.exec_command({"cmd":"pwd"}); text(r.output);',
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )


def test_escalation_property_inside_javascript_command_is_not_waiting():
    item = custom_tool_call(
        "exec",
        "const r = await tools.exec_command({\n"
        '  cmd: "echo sandbox_permissions: require_escalated",\n'
        '  sandbox_permissions: "use_default"\n'
        "});\n"
        "text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )


def test_escalation_text_inside_nested_command_is_not_a_permission_request():
    item = custom_tool_call(
        "exec",
        "const r = await tools.exec_command("
        '{"cmd":"rg \\u0022sandbox_permissions\\u0022:'
        '\\u0022require_escalated\\u0022 source"}'
        "); text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )


def test_non_escalated_nested_exec_remains_regular_tool_activity():
    item = custom_tool_call(
        "exec",
        "const r = await tools.exec_command("
        '{"cmd":"pwd","sandbox_permissions":"use_default"}'
        "); text(r.output);",
    )

    assert watch.item_to_anim(item) == (
        "typing",
        "session custom_tool_call tool='exec'",
    )
