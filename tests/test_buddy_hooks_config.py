from codex_clawd_status_macos.buddy_hooks_config import (
    BUDDY_HOOK_EVENTS,
    merge_buddy_hooks,
    remove_managed_buddy_hooks,
)


def _commands(data: dict, event: str) -> list[str]:
    return [
        hook["command"]
        for entry in data["hooks"][event]
        for hook in entry["hooks"]
        if hook.get("type") == "command"
    ]


def test_merge_preserves_unrelated_settings_and_is_idempotent():
    original = {
        "enabledPlugins": {"keep@market": True},
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "/tmp/other"}]}
            ]
        },
    }
    command = "/opt/clawd-status buddy-hook --platform codebuddy"

    first = merge_buddy_hooks(original, command)
    second = merge_buddy_hooks(first, command)

    assert second == first
    assert second["enabledPlugins"] == {"keep@market": True}
    assert _commands(second, "Stop") == ["/tmp/other", command]
    assert set(second["hooks"]) >= set(BUDDY_HOOK_EVENTS)


def test_merge_replaces_legacy_python_adapter():
    legacy = (
        "~/.codebuddy/hooks/codex-status-led/.venv/bin/python "
        "~/.codebuddy/hooks/codex-status-led/scripts/workbuddy_clawd_hook.py"
    )
    current = "/opt/clawd-status buddy-hook --platform workbuddy"

    merged = merge_buddy_hooks(
        {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": legacy}]}
                ]
            }
        },
        current,
    )

    assert _commands(merged, "Stop") == [current]


def test_remove_keeps_unrelated_commands():
    current = "/opt/clawd-status buddy-hook --platform codebuddy"
    merged = merge_buddy_hooks({"hooks": {}}, current)
    merged["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "/tmp/other"}]}
    )

    cleaned = remove_managed_buddy_hooks(merged, current)

    assert _commands(cleaned, "Stop") == ["/tmp/other"]


def test_merge_rejects_non_object_hooks():
    try:
        merge_buddy_hooks({"hooks": []}, "/opt/clawd-status buddy-hook")
    except ValueError as exc:
        assert str(exc) == "hooks must be a JSON object"
    else:
        raise AssertionError("non-object hooks must be rejected")
