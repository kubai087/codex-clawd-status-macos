from pathlib import Path


def test_payload_contains_runtime_skill_and_license():
    payload = Path("dist/payload")
    assert (payload / "bin/clawd-status").is_file()
    assert (payload / "share/codex-clawd-status/skill/SKILL.md").is_file()
    assert (payload / "share/codex-clawd-status/LICENSE").is_file()
