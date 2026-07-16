from __future__ import annotations

from copy import deepcopy
from typing import Any

BUDDY_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PreCompact",
    "PostCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
    "SessionEnd",
    "Notification",
)

LEGACY_BUDDY_MARKERS = (
    "/.codebuddy/hooks/codex-status-led/",
    "\\.codebuddy\\hooks\\codex-status-led\\",
    "workbuddy_clawd_hook.py",
)


def _entry(command: str, event: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 2,
                "statusMessage": "Updating Clawd display",
            }
        ]
    }
    if event == "SessionStart":
        value["matcher"] = "startup|resume|clear|compact"
    return value


def _is_managed(command: object, current: str) -> bool:
    if not isinstance(command, str):
        return False
    return command == current or any(
        marker in command for marker in LEGACY_BUDDY_MARKERS
    )


def _remove_managed_entries(entries: list[Any], command: str) -> list[Any]:
    cleaned: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            cleaned.append(entry)
            continue
        remaining = [
            hook
            for hook in entry["hooks"]
            if not (
                isinstance(hook, dict)
                and _is_managed(hook.get("command"), command)
            )
        ]
        if remaining:
            copied = deepcopy(entry)
            copied["hooks"] = remaining
            cleaned.append(copied)
    return cleaned


def merge_buddy_hooks(data: dict[str, Any], command: str) -> dict[str, Any]:
    result = deepcopy(data)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be a JSON object")
    for event in BUDDY_HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"hooks.{event} must be a JSON array")
        hooks[event] = [
            *_remove_managed_entries(entries, command),
            _entry(command, event),
        ]
    return result


def remove_managed_buddy_hooks(
    data: dict[str, Any], command: str
) -> dict[str, Any]:
    result = deepcopy(data)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event, entries in hooks.items():
        if isinstance(entries, list):
            hooks[event] = _remove_managed_entries(entries, command)
    return result
