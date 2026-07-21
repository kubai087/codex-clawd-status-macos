import argparse
import json
import sys

import buddy_clawd_hook as buddy
import codex_clawd_hook as shared


def test_buddy_extended_event_mapping():
    assert buddy.payload_to_anim({"hook_event_name": "PostToolUseFailure"}) == (
        "dizzy"
    )
    assert buddy.payload_to_anim({"hook_event_name": "StopFailure"}) == "dizzy"
    assert buddy.payload_to_anim({"hook_event_name": "SessionEnd"}) == "sleeping"
    assert buddy.payload_to_anim(
        {
            "hook_event_name": "Notification",
            "notification_type": "permission_prompt",
        }
    ) == "confused"
    assert buddy.payload_to_anim(
        {
            "hook_event_name": "Notification",
            "notification_type": "elicitation_dialog",
        }
    ) == "confused"
    assert buddy.payload_to_anim(
        {
            "hook_event_name": "Notification",
            "notification_type": "idle_prompt",
        }
    ) == "happy"
    assert buddy.payload_to_anim(
        {"hook_event_name": "Notification", "notification_type": "auth_success"}
    ) == "beacon"


def test_buddy_all_user_approval_event_variants_map_to_waiting():
    for event in (
        "PermissionRequest",
        "ApprovalRequest",
        "ElicitationRequest",
        "UserInputRequest",
    ):
        assert buddy.payload_to_anim({"hook_event_name": event}) == "confused"

    for notification in (
        "permission_prompt",
        "permission_request",
        "approval_prompt",
        "approval_request",
        "elicitation_dialog",
        "elicitation_prompt",
        "user_input_prompt",
        "tool_permission_prompt",
        "Approval-Prompt",
    ):
        assert buddy.payload_to_anim(
            {
                "hook_event_name": "Notification",
                "notification_type": notification,
            }
        ) == "confused"


def test_shared_tool_mapping_covers_user_facing_approval_tools_only():
    for tool_name in (
        "AskUserQuestion",
        "AskFollowup",
        "ExitPlanMode",
        "request_user_input",
        "functions.request_user_input",
        "request_permissions",
        "functions.request_permissions",
        "request_plugin_install",
        "functions.request_plugin_install",
    ):
        assert shared.tool_to_anim(tool_name) == "confused"

    assert shared.tool_to_anim("mcp__plugin__update_app_permissions") == "beacon"


def test_buddy_shared_mapping_reuses_tool_categories():
    assert buddy.payload_to_anim(
        {"hook_event_name": "PreToolUse", "tool_name": "Write"}
    ) == "typing"
    assert buddy.payload_to_anim(
        {"hook_event_name": "UserPromptSubmit"}
    ) == "thinking"


def test_payload_session_id_accepts_supported_platform_fields():
    assert shared.payload_session_id({"session_id": "a"}) == "a"
    assert shared.payload_session_id({"sessionId": "b"}) == "b"
    assert shared.payload_session_id({"conversation_id": "c"}) == "c"
    assert shared.payload_session_id({"conversationId": "d"}) == "d"
    assert shared.payload_session_id({"thread_id": "e"}) == "e"
    assert shared.payload_session_id({"threadId": "f"}) == "f"
    assert shared.payload_session_id(
        {"transcript_path": "/tmp/session-g.jsonl"}
    ) == "session-g"
    assert shared.payload_session_id(None) == ""


def test_build_args_uses_platform_as_client_identity(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["buddy-hook", "--platform", "workbuddy", "--print-mapping"],
    )

    args = buddy.build_args()

    assert args.platform == "workbuddy"
    assert args.client_id == "workbuddy"
    assert args.source == "workbuddy"
    assert args.client_kind == "workbuddy"
    assert args.transition_role == "buddy-hook"


def test_hub_enqueue_uses_platform_identity_without_full_payload(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true,"status":"queued"}'

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    def unexpected_autostart(_args):
        raise AssertionError("platform hooks must not start the Hub")

    monkeypatch.setattr(shared, "hub_urlopen", open_request)
    monkeypatch.setattr(shared, "ensure_hub", unexpected_autostart)
    args = argparse.Namespace(
        source="codebuddy",
        client_kind="codebuddy",
        client_id="codebuddy",
        hub_url="http://127.0.0.1:8765",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "session_id": "session-123",
        "tool_input": {"file_path": "/private/secret"},
        "prompt": "private prompt",
    }

    assert shared.send_anim_hub("typing", args, payload=payload)
    assert captured["url"].endswith("/enqueue")
    assert captured["timeout"] == 1.0
    assert captured["body"] == {
        "source": "codebuddy",
        "client_id": "codebuddy",
        "client_kind": "codebuddy",
        "session_id": "session-123",
        "anim": "typing",
        "event": "PreToolUse",
        "tool": "Write",
        "event_time": None,
    }


def test_buddy_stop_does_not_spawn_global_timer_after_hub_accepts(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["buddy-hook", "--platform", "workbuddy"],
    )
    monkeypatch.setattr(
        shared,
        "read_payload",
        lambda: {"hook_event_name": "Stop", "session_id": "session-1"},
    )
    monkeypatch.setattr(shared, "touch_last_event", lambda: 123.0)
    monkeypatch.setattr(shared, "deliver_anim", lambda *_a, **_kw: "hub")
    monkeypatch.setattr(
        shared,
        "spawn_timed_transition",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Hub-owned completion must not spawn a global timer")
        ),
    )

    assert buddy.main() == 0


def test_buddy_stop_keeps_legacy_timer_for_direct_delivery(monkeypatch):
    captured = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["buddy-hook", "--platform", "codebuddy", "--no-hub"],
    )
    monkeypatch.setattr(
        shared,
        "read_payload",
        lambda: {"hook_event_name": "Stop", "session_id": "session-2"},
    )
    monkeypatch.setattr(shared, "touch_last_event", lambda: 456.0)
    monkeypatch.setattr(shared, "deliver_anim", lambda *_a, **_kw: "direct")
    monkeypatch.setattr(
        shared,
        "spawn_timed_transition",
        lambda event_time, args: captured.append((event_time, args.platform)),
    )

    assert buddy.main() == 0
    assert captured == [(456.0, "codebuddy")]


def test_timed_transition_preserves_buddy_role_and_platform(monkeypatch):
    captured = {}

    def role_command(role, args):
        captured["role"] = role
        captured["args"] = args
        return ["clawd-status", role, *args]

    monkeypatch.setattr(shared, "role_command", role_command)
    monkeypatch.setattr(shared.subprocess, "Popen", lambda *_a, **_kw: object())
    args = argparse.Namespace(
        transition_role="buddy-hook",
        platform="workbuddy",
        transport=None,
        port=None,
        baud=None,
        ble_address=None,
        ble_name=None,
    )

    shared.spawn_timed_transition(123.0, args)

    assert captured["role"] == "buddy-hook"
    assert captured["args"][-2:] == ["--platform", "workbuddy"]


def test_codex_hook_uses_launch_agent_instead_of_watcher_autostart(monkeypatch):
    captured = {}

    def unexpected_watcher_start(_args):
        raise AssertionError("native hooks must not start the watcher")

    def deliver(_anim, args, **_kwargs):
        captured["source"] = args.source
        captured["client_kind"] = args.client_kind
        captured["transition_role"] = args.transition_role
        return True

    monkeypatch.setattr(sys, "argv", ["hook"])
    monkeypatch.setattr(
        shared,
        "read_payload",
        lambda: {"hook_event_name": "UserPromptSubmit"},
    )
    monkeypatch.setattr(shared, "ensure_session_watcher", unexpected_watcher_start)
    monkeypatch.setattr(shared, "touch_last_event", lambda: 123.0)
    monkeypatch.setattr(shared, "deliver_anim", deliver)

    assert shared.main() == 0
    assert captured == {
        "source": "codex",
        "client_kind": "codex",
        "transition_role": "hook",
    }
