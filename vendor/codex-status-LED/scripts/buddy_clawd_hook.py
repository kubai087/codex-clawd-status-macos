#!/usr/bin/env python3
"""CodeBuddy-compatible lifecycle hook to Clawd status adapter."""

from __future__ import annotations

import argparse
import os

import codex_clawd_hook as shared

PLATFORMS = ("codebuddy", "workbuddy")
WAITING_NOTIFICATION_TYPES = {
    "permission_prompt",
    "permission_request",
    "approval_prompt",
    "approval_request",
    "elicitation_dialog",
    "elicitation_prompt",
    "user_input_prompt",
    "tool_permission_prompt",
}


def payload_to_anim(payload: dict) -> str | None:
    event = payload.get("hook_event_name") or payload.get("event") or ""
    if event in shared.USER_APPROVAL_EVENTS:
        return "confused"
    if event in {"PostToolUseFailure", "StopFailure"}:
        return "dizzy"
    if event == "SessionEnd":
        return shared.SLEEP_ANIM
    if event == "Notification":
        notification = (
            str(payload.get("notification_type") or "")
            .strip()
            .lower()
            .replace("-", "_")
        )
        if notification in WAITING_NOTIFICATION_TYPES:
            return "confused"
        if notification == "idle_prompt":
            return shared.TASK_COMPLETE_ANIM
        return "beacon"
    return shared.payload_to_anim(payload)


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--test", help="send a specific animation and exit")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--print-mapping", action="store_true")
    parser.add_argument("--transport")
    parser.add_argument("--port")
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--ble-address")
    parser.add_argument("--ble-name", default=None)
    parser.add_argument("--hub-url", default=None)
    parser.add_argument("--no-hub", action="store_true")
    parser.add_argument("--hub-required", action="store_true")
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--timed-transition", type=float, default=None)
    args = parser.parse_args()
    args.client_id = (
        args.client_id
        or os.environ.get("CLAWD_TANK_CLIENT_ID")
        or args.platform
    )
    args.source = args.platform
    args.client_kind = args.platform
    args.transition_role = "buddy-hook"
    return args


def print_mapping() -> None:
    for event, anim in (
        ("SessionStart", "idle"),
        ("UserPromptSubmit", "thinking"),
        ("PreToolUse", "tool-specific"),
        ("PostToolUse", "thinking"),
        ("PostToolUseFailure", "dizzy"),
        ("PermissionRequest", "confused"),
        ("PreCompact", "sweeping"),
        ("PostCompact", "thinking"),
        ("SubagentStart", "conducting"),
        ("SubagentStop", "thinking"),
        ("Stop", "happy"),
        ("StopFailure", "dizzy"),
        ("SessionEnd", "sleeping"),
        ("Notification", "notification-specific"),
    ):
        print(f"{event}: {anim}")


def main() -> int:
    args = build_args()
    if args.doctor:
        return shared.doctor()
    if args.print_mapping:
        print_mapping()
        return 0
    if args.timed_transition is not None:
        shared.run_timed_transition(
            args.timed_transition,
            args.transport,
            args.port,
            args.baud,
            args.ble_address,
            args.ble_name,
            source=args.source,
            client_kind=args.client_kind,
            client_id_value=args.client_id,
        )
        return 0
    if args.test:
        shared.deliver_anim(args.test, args)
        return 0

    payload = shared.read_payload()
    if payload is None:
        return 0
    event_time = shared.touch_last_event()
    anim = payload_to_anim(payload)
    if anim:
        event = payload.get("hook_event_name") or payload.get("event") or ""
        tool = payload.get("tool_name") or payload.get("toolName") or ""
        shared.log(
            f"[{args.platform}] mapped event={event!r} tool={tool!r} anim={anim}"
        )
        delivery_mode = shared.deliver_anim(
            anim, args, payload=payload, event_time=event_time
        )
        if event == "Stop" and delivery_mode == "direct":
            shared.spawn_timed_transition(event_time, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
