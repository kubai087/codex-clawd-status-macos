from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path

import pytest

ASSET = "codex-clawd-status-macos-arm64.tar.gz"


def test_release_packaging_script_exists_and_is_executable():
    script = Path("scripts/package-release.sh")
    assert script.is_file()
    assert os.access(script, os.X_OK)


def test_release_archive_and_checksum():
    release = Path("dist/release")
    archive = release / ASSET
    checksum = release / f"{ASSET}.sha256"
    if not release.exists():
        pytest.skip("release assets have not been packaged")
    expected = checksum.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert actual == expected
    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())
    assert "payload/bin/clawd-status" in names
    assert "payload/share/codex-clawd-status/skill/SKILL.md" in names
    assert "payload/share/codex-clawd-status/LICENSE" in names
