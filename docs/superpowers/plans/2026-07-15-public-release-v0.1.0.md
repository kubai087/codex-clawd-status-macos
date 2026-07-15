# Public v0.1.0 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a public Apple silicon `v0.1.0` Release that unauthenticated users can install with one `curl | bash` command.

**Architecture:** Keep `install.sh --payload PATH` for local development and add a no-argument mode that downloads a fixed-name Release archive and checksum, verifies SHA-256, extracts into a temporary directory, and invokes the bundled installer. Add a repeatable release-packaging script, publish the artifacts from the verified local build, then run the public raw-GitHub installer end to end.

**Tech Stack:** Bash, `curl`, `tar`, macOS `shasum`, Python pytest for shell integration tests, GitHub Releases through `gh`.

---

### Task 1: Add a tested public-download mode to `install.sh`

**Files:**
- Create: `tests/test_public_installer.py`
- Modify: `install.sh`

- [ ] **Step 1: Write failing local, remote, and checksum tests**

Create `tests/test_public_installer.py`:

```python
from __future__ import annotations

import hashlib
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
    (release / f"{ASSET}.sha256").write_text(f"{digest}  {ASSET}\n")

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
    (release / f"{ASSET}.sha256").write_text(f"{'0' * 64}  {ASSET}\n")

    result, output = run_installer(tmp_path, base=release.as_uri())

    assert result.returncode != 0
    assert not output.exists()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_public_installer.py -v
```

Expected: local mode passes; both no-argument remote-mode tests fail because `install.sh` still requires `--payload`.

- [ ] **Step 3: Implement the no-argument public installer**

Replace `install.sh` with:

```bash
#!/bin/bash
set -euo pipefail

repo="kubai087/codex-clawd-status-macos"
asset="codex-clawd-status-macos-arm64.tar.gz"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "clawd-status requires an Apple silicon Mac" >&2
  exit 1
fi

install_payload() {
  local payload="$1"
  "$payload/bin/clawd-status" install --payload "$payload"
}

if [[ "${1:-}" == "--payload" ]]; then
  if [[ -z "${2:-}" || -n "${3:-}" ]]; then
    echo "usage: ./install.sh [--payload PATH]" >&2
    exit 2
  fi
  payload="$(cd "$2" && pwd -P)"
  install_payload "$payload"
  exit $?
fi

if [[ -n "${1:-}" ]]; then
  echo "usage: ./install.sh [--payload PATH]" >&2
  exit 2
fi

base="${CLAWD_STATUS_DOWNLOAD_BASE:-https://github.com/$repo/releases/latest/download}"
temporary="$(mktemp -d "${TMPDIR:-/tmp}/codex-clawd-status.XXXXXX")"
trap 'rm -rf "$temporary"' EXIT

curl -fsSL "$base/$asset" -o "$temporary/$asset"
curl -fsSL "$base/$asset.sha256" -o "$temporary/$asset.sha256"
(
  cd "$temporary"
  shasum -a 256 -c "$asset.sha256"
)
tar -xzf "$temporary/$asset" -C "$temporary"
install_payload "$temporary/payload"
```

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
.venv/bin/pytest tests/test_public_installer.py -v
.venv/bin/pytest -v
git diff --check
```

Expected: 3 public-installer tests pass; full suite passes with the payload test skipped before a build.

Commit:

```bash
git add install.sh tests/test_public_installer.py
git commit -m "Install from public GitHub releases"
```

### Task 2: Package reproducible Release assets

**Files:**
- Create: `scripts/package-release.sh`
- Create: `tests/test_release_archive.py`

- [ ] **Step 1: Write the failing Release-archive test**

Create `tests/test_release_archive.py`:

```python
from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path

import pytest


ASSET = "codex-clawd-status-macos-arm64.tar.gz"


def test_release_archive_and_checksum():
    release = Path("dist/release")
    archive = release / ASSET
    checksum = release / f"{ASSET}.sha256"
    if not release.exists():
        pytest.skip("release assets have not been packaged")
    expected = checksum.read_text().split()[0]
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert actual == expected
    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())
    assert "payload/bin/clawd-status" in names
    assert "payload/share/codex-clawd-status/skill/SKILL.md" in names
    assert "payload/share/codex-clawd-status/LICENSE" in names
```

- [ ] **Step 2: Verify the unbuilt test skips**

Run:

```bash
rm -rf dist/release
.venv/bin/pytest tests/test_release_archive.py -v
```

Expected: 1 skipped.

- [ ] **Step 3: Implement release packaging**

Create `scripts/package-release.sh`:

```bash
#!/bin/bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd -P)"
asset="codex-clawd-status-macos-arm64.tar.gz"

"$root/scripts/build-local.sh"
rm -rf "$root/dist/release"
mkdir -p "$root/dist/release"
tar -czf "$root/dist/release/$asset" -C "$root/dist" payload
(
  cd "$root/dist/release"
  shasum -a 256 "$asset" > "$asset.sha256"
)
```

- [ ] **Step 4: Build and verify GREEN**

Run:

```bash
chmod +x scripts/package-release.sh
scripts/package-release.sh
.venv/bin/pytest tests/test_payload.py tests/test_release_archive.py -v
shasum -a 256 -c dist/release/codex-clawd-status-macos-arm64.tar.gz.sha256
```

Expected: 2 tests pass and checksum reports `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/package-release.sh tests/test_release_archive.py
git commit -m "Package verified release assets"
```

### Task 3: Document public installation and release scope

**Files:**
- Modify: `README.md`
- Create: `docs/releases/v0.1.0.md`

- [ ] **Step 1: Update the README**

Add these sections before the local-preview verification section:

````markdown
## Install

```bash
curl -fsSL https://raw.githubusercontent.com/kubai087/codex-clawd-status-macos/main/install.sh | bash
```

Requirements:

- Apple silicon Mac
- Codex Desktop, Codex CLI, or the Codex VS Code extension
- A Clawd/Mochi ESP32 with compatible status-light firmware

The installer includes its own runtime. Python, Homebrew, and GitHub login are
not required.

## Manage

```bash
clawd-status status
clawd-status doctor
clawd-status restart
clawd-status uninstall
```
````

- [ ] **Step 2: Add release notes**

Create `docs/releases/v0.1.0.md`:

```markdown
# v0.1.0

Initial Apple silicon preview release.

- One-command public installation with no GitHub login.
- Self-contained arm64 runtime; no Python or Homebrew dependency.
- Per-user LaunchAgent with Hub and watcher supervision.
- Login, crash, and simulated sleep/wake recovery.
- Safe migration of existing Codex status-light hooks and skill files.
- BLE transport with ESP32 USB serial fallback.
- Status, doctor, restart, and uninstall commands.

Not included: Intel Mac support, Windows support, ESP32 firmware flashing,
Developer ID notarization, or automatic runtime updates.
```

- [ ] **Step 3: Verify docs and commit**

Run:

```bash
rg -n "curl -fsSL|clawd-status doctor|Apple silicon" README.md docs/releases/v0.1.0.md
git diff --check
```

Commit:

```bash
git add README.md docs/releases/v0.1.0.md
git commit -m "Document public v0.1.0 installation"
```

### Task 4: Publish and verify v0.1.0

**Files:**
- No source changes expected.

- [ ] **Step 1: Run the release gate**

Run:

```bash
.venv/bin/pytest -v
scripts/package-release.sh
.venv/bin/pytest tests/test_payload.py tests/test_release_archive.py -v
shasum -a 256 -c dist/release/codex-clawd-status-macos-arm64.tar.gz.sha256
file dist/payload/runtime/clawd-status
codesign --verify --deep --strict dist/payload/runtime/clawd-status
git diff --check
git status -sb
```

Expected: unit suite passes with integration tests skipped before packaging; both artifact tests pass after packaging; checksum, arm64 binary, and code signature verify; worktree is clean.

- [ ] **Step 2: Merge to main and push**

From the primary checkout:

```bash
git checkout main
git merge agent/public-release-v0.1.0
.venv/bin/pytest -v
git push origin main
```

- [ ] **Step 3: Create the public Release**

Run:

```bash
gh release create v0.1.0 \
  dist/release/codex-clawd-status-macos-arm64.tar.gz \
  dist/release/codex-clawd-status-macos-arm64.tar.gz.sha256 \
  --repo kubai087/codex-clawd-status-macos \
  --title "v0.1.0" \
  --notes-file docs/releases/v0.1.0.md
```

Expected: public Release URL is returned and both assets are listed.

- [ ] **Step 4: Verify the unauthenticated public install path**

Run:

```bash
curl -fsSL https://raw.githubusercontent.com/kubai087/codex-clawd-status-macos/main/install.sh | bash
zsh -lc 'clawd-status --version && clawd-status doctor'
curl -fsS http://127.0.0.1:8765/modules
curl -fsS -H 'Content-Type: application/json' \
  -d '{"anim":"thinking","client_id":"public-release-check","event":"ReleaseInstalled"}' \
  http://127.0.0.1:8765/send
curl -fsS http://127.0.0.1:8765/state
```

Expected: version is `0.1.0`; LaunchAgent, Hub, and watcher are online; `/send` and `/state` report `delivered` via BLE or USB serial.
