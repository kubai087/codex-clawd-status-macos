from pathlib import Path

import pytest


def test_payload_contains_runtime_skill_and_license():
    payload = Path("dist/payload")
    if not payload.exists():
        pytest.skip("self-contained payload has not been built")
    assert (payload / "bin/clawd-status").is_file()
    assert (payload / "share/codex-clawd-status/skill/SKILL.md").is_file()
    assert (payload / "share/codex-clawd-status/LICENSE").is_file()
