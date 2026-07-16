from pathlib import Path

from clawd_status_hub import buddy_hook_configured, codex_hook_configured


def test_dashboard_recognizes_unified_binary_hook(tmp_path: Path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(
        '{"hooks":{"Stop":[{"hooks":[{"command":"/opt/clawd-status hook"}]}]}}',
        encoding="utf-8",
    )
    assert codex_hook_configured(hooks)


def test_dashboard_keeps_recognizing_legacy_hook(tmp_path: Path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(
        '{"command":"/tmp/codex_clawd_hook.py"}',
        encoding="utf-8",
    )
    assert codex_hook_configured(hooks)


def test_buddy_config_detection_requires_matching_platform(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"hooks":{"Stop":[{"hooks":[{"command":'
        '"/opt/clawd-status buddy-hook --platform codebuddy"}]}]}}',
        encoding="utf-8",
    )

    assert buddy_hook_configured(settings, "codebuddy")
    assert not buddy_hook_configured(settings, "workbuddy")


def test_buddy_config_detection_recognizes_legacy_adapter(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"command":"~/.codebuddy/hooks/codex-status-led/scripts/'
        'workbuddy_clawd_hook.py"}',
        encoding="utf-8",
    )

    assert buddy_hook_configured(settings, "codebuddy")
    assert buddy_hook_configured(settings, "workbuddy")
