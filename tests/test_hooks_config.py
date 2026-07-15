from codex_clawd_status_macos.hooks_config import merge_hooks, remove_managed_hooks


def _commands(data: dict, event: str) -> list[str]:
    return [
        hook["command"]
        for entry in data["hooks"][event]
        for hook in entry["hooks"]
    ]


def test_merge_preserves_unrelated_hooks_and_is_idempotent():
    original = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "/tmp/other"}]}],
        },
        "custom": {"keep": True},
    }
    first = merge_hooks(original, "/opt/clawd-status hook")
    second = merge_hooks(first, "/opt/clawd-status hook")
    assert second == first
    assert second["custom"] == {"keep": True}
    assert _commands(second, "Stop") == ["/tmp/other", "/opt/clawd-status hook"]


def test_merge_replaces_legacy_status_light_hook():
    legacy = (
        "/Users/test/.codex/skills/codex-clawd-status/.venv/bin/python "
        "/Users/test/.codex/skills/codex-clawd-status/scripts/codex_clawd_hook.py"
    )
    original = {"hooks": {"Stop": [{"hooks": [{"command": legacy}]}]}}
    merged = merge_hooks(original, "/opt/clawd-status hook")
    assert _commands(merged, "Stop") == ["/opt/clawd-status hook"]


def test_remove_deletes_only_managed_commands():
    merged = merge_hooks({"hooks": {}}, "/opt/clawd-status hook")
    merged["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "/tmp/other"}]}
    )
    cleaned = remove_managed_hooks(merged, "/opt/clawd-status hook")
    assert cleaned["hooks"]["Stop"] == [
        {"hooks": [{"type": "command", "command": "/tmp/other"}]}
    ]
