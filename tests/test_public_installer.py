from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

ASSET = "codex-clawd-status-macos-arm64.tar.gz"


def fake_payload(root: Path) -> Path:
    payload = root / "payload"
    binary = payload / "bin/clawd-status"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$CLAWD_TEST_OUTPUT"\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return payload


def run_installer(tmp_path: Path, *args: str, base: str | None = None):
    output = tmp_path / "args.txt"
    env = {**os.environ, "CLAWD_TEST_OUTPUT": str(output)}
    if base:
        env["CLAWD_STATUS_DOWNLOAD_BASE"] = base
    result = subprocess.run(
        ["bash", "install.sh", *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return result, output


def test_local_payload_mode_is_preserved(tmp_path: Path):
    payload = fake_payload(tmp_path)
    result, output = run_installer(tmp_path, "--payload", str(payload))
    assert result.returncode == 0, result.stderr
    assert output.read_text().splitlines() == ["install", "--payload", str(payload)]


def test_remote_mode_downloads_verifies_and_installs(tmp_path: Path):
    source = tmp_path / "source"
    payload = fake_payload(source)
    release = tmp_path / "release"
    release.mkdir()
    archive = release / ASSET
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(payload, arcname="payload")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{ASSET}.sha256").write_text(
        f"{digest}  {ASSET}\n",
        encoding="utf-8",
    )

    result, output = run_installer(tmp_path, base=release.as_uri())

    assert result.returncode == 0, result.stderr
    installed_args = output.read_text().splitlines()
    assert installed_args[0:2] == ["install", "--payload"]
    assert installed_args[2].endswith("/payload")


def test_remote_mode_rejects_bad_checksum(tmp_path: Path):
    source = tmp_path / "source"
    payload = fake_payload(source)
    release = tmp_path / "release"
    release.mkdir()
    archive = release / ASSET
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(payload, arcname="payload")
    (release / f"{ASSET}.sha256").write_text(
        f"{'0' * 64}  {ASSET}\n",
        encoding="utf-8",
    )

    result, output = run_installer(tmp_path, base=release.as_uri())

    assert result.returncode != 0
    assert "FAILED" in result.stdout + result.stderr
    assert not output.exists()


def test_remote_mode_rejects_archive_path_traversal(tmp_path: Path):
    release = tmp_path / "release"
    release.mkdir()
    archive = release / ASSET
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("../escape")
        content = b"unsafe"
        info.size = len(content)
        bundle.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{ASSET}.sha256").write_text(
        f"{digest}  {ASSET}\n",
        encoding="utf-8",
    )

    result, output = run_installer(tmp_path, base=release.as_uri())

    assert result.returncode != 0
    assert "unsafe archive path" in result.stderr
    assert not output.exists()
