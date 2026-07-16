from pathlib import Path

import pytest


def test_pyinstaller_bundles_buddy_hook():
    spec = Path("packaging/clawd-status.spec").read_text(encoding="utf-8")
    assert '"buddy_clawd_hook"' in spec


def test_bundled_skill_describes_all_supported_platforms():
    skill = Path("vendor/codex-status-LED/SKILL.md").read_text(encoding="utf-8")
    assert "Codex" in skill
    assert "CodeBuddy" in skill
    assert "WorkBuddy" in skill


def test_bundled_readme_describes_all_supported_platforms():
    readme = Path("vendor/codex-status-LED/README.md").read_text(encoding="utf-8")
    assert "Codex" in readme
    assert "CodeBuddy" in readme
    assert "WorkBuddy" in readme


def test_payload_contains_runtime_skill_and_license():
    payload = Path("dist/payload")
    if not payload.exists():
        pytest.skip("self-contained payload has not been built")
    assert (payload / "bin/clawd-status").is_file()
    assert (payload / "share/codex-clawd-status/skill/SKILL.md").is_file()
    assert (
        payload
        / "share/codex-clawd-status/skill/scripts/buddy_clawd_hook.py"
    ).is_file()
    assert (payload / "share/codex-clawd-status/LICENSE").is_file()
