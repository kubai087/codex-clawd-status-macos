from pathlib import Path

from clawd_status_hub import codex_hook_configured


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
