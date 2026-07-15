# Local Apple Silicon Installer MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install a self-contained Apple silicon preview of the Codex Clawd status-light stack that survives login, reboot, process failure, and sleep/wake without relying on Homebrew or the target user's Python installation.

**Architecture:** Import the existing MIT-licensed status-light implementation as a vendored subtree, add one `clawd-status` command dispatcher, and package it as a PyInstaller `onedir` runtime. A per-user LaunchAgent owns a headless supervisor; the supervisor starts the existing Hub and watcher roles, detects wake gaps, and restores their health. The local installer atomically installs the runtime, skill symlink, managed hooks, and LaunchAgent without overwriting unrelated Codex configuration.

**Tech Stack:** Python 3.9+, PyInstaller, pytest, macOS `launchd`/LaunchAgent, standard-library HTTP and plist handling, existing `bleak` and `pyserial` transports.

---

## Scope

This plan produces a locally installable preview and proves the runtime architecture on the current Apple silicon Mac. It includes install, status, doctor, restart, and uninstall. Public GitHub Release automation, remote update resolution, version rollback, Developer ID signing, and notarization are intentionally handled in a later implementation plan after this local lifecycle is verified.

## File Map

- `vendor/codex-status-LED/`: vendored upstream MIT source and skill assets.
- `src/codex_clawd_status_macos/cli.py`: single command dispatcher and role entrypoint.
- `src/codex_clawd_status_macos/runtime_command.py`: source and frozen child-process command construction.
- `src/codex_clawd_status_macos/supervisor.py`: Hub/watcher lifecycle and wake recovery.
- `src/codex_clawd_status_macos/hooks_config.py`: safe, idempotent hooks merge and removal.
- `src/codex_clawd_status_macos/launch_agent.py`: deterministic LaunchAgent plist generation.
- `src/codex_clawd_status_macos/installer.py`: per-user install, restart, status, doctor, and uninstall orchestration.
- `packaging/clawd-status.spec`: PyInstaller `onedir` definition and bundled assets.
- `scripts/build-local.sh`: reproducible local arm64 build.
- `install.sh`: local payload install bootstrap and future public-download entrypoint.
- `tests/`: focused unit and integration tests for each new boundary.

### Task 1: Establish the source and test baseline

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Create: `src/codex_clawd_status_macos/__init__.py`
- Create: `tests/test_platform.py`
- Vendor: `vendor/codex-status-LED/`

- [ ] **Step 1: Add the upstream source as a squashed subtree**

Run:

```bash
git subtree add \
  --prefix vendor/codex-status-LED \
  https://github.com/GFlash6/codex-status-LED.git main --squash
```

Expected: the upstream files, including `LICENSE`, `SKILL.md`, `requirements.txt`, and `scripts/`, appear under `vendor/codex-status-LED/`.

- [ ] **Step 2: Write the failing platform test**

Create `tests/test_platform.py`:

```python
from codex_clawd_status_macos.cli import require_supported_platform


def test_accepts_apple_silicon():
    require_supported_platform(system="Darwin", machine="arm64")


def test_rejects_non_arm64():
    try:
        require_supported_platform(system="Darwin", machine="x86_64")
    except RuntimeError as exc:
        assert "Apple silicon" in str(exc)
    else:
        raise AssertionError("x86_64 must be rejected")
```

- [ ] **Step 3: Add project metadata and run the test to verify RED**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "codex-clawd-status-macos"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = ["bleak>=0.21", "pyserial>=3.5"]

[project.scripts]
clawd-status = "codex_clawd_status_macos.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src", "vendor/codex-status-LED/scripts"]
testpaths = ["tests"]
```

Create `requirements-dev.txt`:

```text
-e .
pytest>=8.3,<9
pyinstaller>=6.11,<7
```

Create `.gitignore`:

```text
.venv/
.worktrees/
__pycache__/
.pytest_cache/
build/
dist/
*.egg-info/
```

Create `src/codex_clawd_status_macos/__init__.py`:

```python
__version__ = "0.1.0"
```

Run:

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/test_platform.py -v
```

Expected: FAIL because `codex_clawd_status_macos.cli` does not exist.

- [ ] **Step 4: Implement the minimal platform guard**

Create `src/codex_clawd_status_macos/cli.py`:

```python
from __future__ import annotations

import platform
from collections.abc import Sequence


def require_supported_platform(system: str | None = None, machine: str | None = None) -> None:
    current_system = system or platform.system()
    current_machine = machine or platform.machine()
    if current_system != "Darwin" or current_machine != "arm64":
        raise RuntimeError("clawd-status requires an Apple silicon Mac")


def main(argv: Sequence[str] | None = None) -> int:
    require_supported_platform()
    return 0
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
.venv/bin/pytest tests/test_platform.py -v
```

Expected: 2 passed.

Commit:

```bash
git add .gitignore pyproject.toml requirements-dev.txt src tests vendor
git commit -m "Set up Apple silicon runtime project"
```

### Task 2: Make child-process commands work in source and frozen runtimes

**Files:**
- Create: `src/codex_clawd_status_macos/runtime_command.py`
- Create: `tests/test_runtime_command.py`
- Modify: `vendor/codex-status-LED/scripts/codex_clawd_hook.py`
- Modify: `vendor/codex-status-LED/scripts/clawd_status_hub.py`

- [ ] **Step 1: Write the failing runtime-command tests**

Create `tests/test_runtime_command.py`:

```python
from pathlib import Path

from codex_clawd_status_macos.runtime_command import role_command


def test_frozen_role_uses_single_cli():
    assert role_command(
        "watch",
        ["--follow-latest"],
        executable=Path("/tmp/clawd-status"),
        frozen=True,
    ) == ["/tmp/clawd-status", "watch", "--follow-latest"]


def test_source_role_uses_module_dispatcher():
    assert role_command(
        "hub",
        ["--transport", "auto"],
        executable=Path("/usr/bin/python3"),
        frozen=False,
    ) == [
        "/usr/bin/python3",
        "-m",
        "codex_clawd_status_macos.cli",
        "hub",
        "--transport",
        "auto",
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/test_runtime_command.py -v
```

Expected: FAIL because `runtime_command` does not exist.

- [ ] **Step 3: Implement the command builder**

Create `src/codex_clawd_status_macos/runtime_command.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


def role_command(
    role: str,
    args: Iterable[str] = (),
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
) -> list[str]:
    exe = executable or Path(sys.executable)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    prefix = [str(exe), role] if is_frozen else [
        str(exe), "-m", "codex_clawd_status_macos.cli", role
    ]
    return [*prefix, *list(args)]
```

- [ ] **Step 4: Patch vendored subprocess creation to honor the dispatcher**

Add this import to the hook and Hub modules:

```python
from codex_clawd_status_macos.runtime_command import role_command
```

Replace watcher, Hub, timed-transition, and Hub-restart command construction with role commands. The required shapes are:

```python
cmd = role_command("watch", ["--follow-latest"])
cmd = role_command("hub", hub_args)
cmd = role_command("hook", ["--timed-transition", f"{event_time:.6f}"])
```

When the Hub is supervised (`CLAWD_STATUS_SUPERVISED=1`), `/module/restart` for the Hub must shut down the current server and let the supervisor restart it instead of launching `python -c`:

```python
if os.environ.get("CLAWD_STATUS_SUPERVISED") == "1":
    threading.Thread(target=server.shutdown, daemon=True).start()
    return
```

- [ ] **Step 5: Verify GREEN and existing imports**

Run:

```bash
.venv/bin/pytest tests/test_runtime_command.py -v
.venv/bin/python -c 'import codex_clawd_hook, clawd_status_hub, codex_session_watch'
```

Expected: 2 passed and import command exits 0.

- [ ] **Step 6: Commit**

```bash
git add src/codex_clawd_status_macos/runtime_command.py tests/test_runtime_command.py vendor/codex-status-LED/scripts
git commit -m "Support unified runtime child commands"
```

### Task 3: Add safe hook configuration management

**Files:**
- Create: `src/codex_clawd_status_macos/hooks_config.py`
- Create: `tests/test_hooks_config.py`

- [ ] **Step 1: Write failing merge and removal tests**

Create `tests/test_hooks_config.py`:

```python
from codex_clawd_status_macos.hooks_config import merge_hooks, remove_managed_hooks


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
    commands = [
        hook["command"]
        for entry in second["hooks"]["Stop"]
        for hook in entry["hooks"]
    ]
    assert commands == ["/tmp/other", "/opt/clawd-status hook"]


def test_remove_deletes_only_managed_commands():
    merged = merge_hooks({"hooks": {}}, "/opt/clawd-status hook")
    merged["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "/tmp/other"}]}
    )
    cleaned = remove_managed_hooks(merged, "/opt/clawd-status hook")
    assert cleaned["hooks"]["Stop"] == [
        {"hooks": [{"type": "command", "command": "/tmp/other"}]}
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/test_hooks_config.py -v
```

Expected: FAIL because `hooks_config` does not exist.

- [ ] **Step 3: Implement deterministic hook merge/removal**

Create `src/codex_clawd_status_macos/hooks_config.py` with the upstream ten event names and these public functions:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

HOOK_EVENTS = (
    "SessionStart", "PreToolUse", "PermissionRequest", "PostToolUse",
    "PreCompact", "PostCompact", "UserPromptSubmit", "SubagentStart",
    "SubagentStop", "Stop",
)


def _entry(command: str, event: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hooks": [{
            "type": "command",
            "command": command,
            "timeout": 5,
            "statusMessage": "Updating Clawd display",
        }]
    }
    if event == "SessionStart":
        value["matcher"] = "startup|resume|clear|compact"
    return value


def _contains(entry: dict[str, Any], command: str) -> bool:
    return any(
        isinstance(hook, dict) and hook.get("command") == command
        for hook in entry.get("hooks", [])
    )


def merge_hooks(data: dict[str, Any], command: str) -> dict[str, Any]:
    result = deepcopy(data)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be a JSON object")
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"hooks.{event} must be a JSON array")
        if not any(isinstance(entry, dict) and _contains(entry, command) for entry in entries):
            entries.append(_entry(command, event))
    return result


def remove_managed_hooks(data: dict[str, Any], command: str) -> dict[str, Any]:
    result = deepcopy(data)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        hooks[event] = [
            entry for entry in entries
            if not (isinstance(entry, dict) and _contains(entry, command))
        ]
    return result
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_hooks_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/codex_clawd_status_macos/hooks_config.py tests/test_hooks_config.py
git commit -m "Manage Codex hooks safely"
```

### Task 4: Add the LaunchAgent and headless supervisor

**Files:**
- Create: `src/codex_clawd_status_macos/launch_agent.py`
- Create: `src/codex_clawd_status_macos/supervisor.py`
- Create: `tests/test_launch_agent.py`
- Create: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing plist and wake-gap tests**

Create `tests/test_launch_agent.py`:

```python
import plistlib
from pathlib import Path

from codex_clawd_status_macos.launch_agent import render_launch_agent


def test_launch_agent_runs_supervisor_and_keeps_it_alive():
    payload = render_launch_agent(
        executable=Path("/Users/test/Library/Application Support/CodexClawdStatus/bin/clawd-status"),
        stdout_path=Path("/Users/test/Library/Logs/CodexClawdStatus/supervisor.out.log"),
        stderr_path=Path("/Users/test/Library/Logs/CodexClawdStatus/supervisor.err.log"),
    )
    data = plistlib.loads(payload)
    assert data["Label"] == "com.kubai087.codex-clawd-status"
    assert data["ProgramArguments"][-1] == "supervise"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is True
```

Create `tests/test_supervisor.py`:

```python
from codex_clawd_status_macos.supervisor import is_wake_gap, next_backoff


def test_detects_wake_gap_after_long_pause():
    assert is_wake_gap(previous=100.0, current=125.1, threshold=20.0)
    assert not is_wake_gap(previous=100.0, current=105.0, threshold=20.0)


def test_backoff_is_bounded():
    assert [next_backoff(i) for i in range(6)] == [1, 2, 4, 8, 16, 30]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/test_launch_agent.py tests/test_supervisor.py -v
```

Expected: FAIL because both modules are missing.

- [ ] **Step 3: Implement deterministic plist rendering**

Create `src/codex_clawd_status_macos/launch_agent.py`:

```python
from __future__ import annotations

import plistlib
from pathlib import Path

LABEL = "com.kubai087.codex-clawd-status"


def render_launch_agent(executable: Path, stdout_path: Path, stderr_path: Path) -> bytes:
    data = {
        "Label": LABEL,
        "ProgramArguments": [str(executable), "supervise"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {
            "CLAWD_STATUS_SUPERVISED": "1",
            "CLAWD_TANK_TRANSPORT": "auto",
        },
    }
    return plistlib.dumps(data, sort_keys=True)
```

- [ ] **Step 4: Implement supervisor primitives and loop**

Create `src/codex_clawd_status_macos/supervisor.py` with these public primitives and a loop that owns Hub and watcher subprocesses:

```python
from __future__ import annotations

import os
import signal
import subprocess
import time
import urllib.request
from dataclasses import dataclass

from .runtime_command import role_command


def is_wake_gap(previous: float, current: float, threshold: float = 20.0) -> bool:
    return current - previous > threshold


def next_backoff(failures: int) -> int:
    return min(30, 2 ** failures)


def hub_is_healthy(timeout: float = 1.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8765/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


@dataclass
class Child:
    role: str
    args: tuple[str, ...]
    process: subprocess.Popen[bytes] | None = None
    failures: int = 0

    def ensure(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if self.process is not None:
            time.sleep(next_backoff(self.failures))
            self.failures += 1
        self.process = subprocess.Popen(
            role_command(self.role, self.args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "CLAWD_STATUS_SUPERVISED": "1"},
        )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def run() -> int:
    hub = Child("hub", ("--transport", "auto"))
    watcher = Child("watch", ("--follow-latest",))
    running = True

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    previous = time.time()
    try:
        while running:
            current = time.time()
            woke = is_wake_gap(previous, current)
            previous = current
            hub.ensure()
            if hub_is_healthy():
                watcher.ensure()
            if woke:
                watcher.stop()
                hub.stop()
                time.sleep(2)
            time.sleep(5)
    finally:
        watcher.stop()
        hub.stop()
    return 0
```

- [ ] **Step 5: Verify GREEN and plist validity**

Run:

```bash
.venv/bin/pytest tests/test_launch_agent.py tests/test_supervisor.py -v
.venv/bin/python - <<'PY' >/tmp/com.kubai087.codex-clawd-status.plist
from pathlib import Path
from codex_clawd_status_macos.launch_agent import render_launch_agent
import sys
sys.stdout.buffer.write(render_launch_agent(Path('/tmp/clawd-status'), Path('/tmp/out'), Path('/tmp/err')))
PY
plutil -lint /tmp/com.kubai087.codex-clawd-status.plist
```

Expected: 4 passed and plist reports `OK`.

- [ ] **Step 6: Commit**

```bash
git add src/codex_clawd_status_macos/launch_agent.py src/codex_clawd_status_macos/supervisor.py tests/test_launch_agent.py tests/test_supervisor.py
git commit -m "Add macOS status-light supervisor"
```

### Task 5: Add installation, status, doctor, restart, and uninstall

**Files:**
- Create: `src/codex_clawd_status_macos/installer.py`
- Create: `src/codex_clawd_status_macos/__main__.py`
- Create: `tests/test_installer.py`
- Modify: `src/codex_clawd_status_macos/cli.py`

- [ ] **Step 1: Write failing install-layout and hook-write tests**

Create `tests/test_installer.py`:

```python
import json
from pathlib import Path

from codex_clawd_status_macos.installer import InstallPaths, install_hooks_file


def test_paths_are_user_scoped(tmp_path: Path):
    paths = InstallPaths.for_home(tmp_path)
    assert paths.root == tmp_path / "Library/Application Support/CodexClawdStatus"
    assert paths.launch_agent == tmp_path / "Library/LaunchAgents/com.kubai087.codex-clawd-status.plist"
    assert paths.skill == tmp_path / ".codex/skills/codex-clawd-status"


def test_install_hooks_is_idempotent_and_creates_backup(tmp_path: Path):
    hooks_path = tmp_path / ".codex/hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(json.dumps({"custom": True}), encoding="utf-8")
    command = "/tmp/clawd-status hook"
    install_hooks_file(hooks_path, command)
    first = hooks_path.read_text(encoding="utf-8")
    install_hooks_file(hooks_path, command)
    assert hooks_path.read_text(encoding="utf-8") == first
    assert list(hooks_path.parent.glob("hooks.json.codex-clawd-status.bak.*"))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/test_installer.py -v
```

Expected: FAIL because `installer` does not exist.

- [ ] **Step 3: Implement paths and atomic hook writes**

Create `src/codex_clawd_status_macos/installer.py` with:

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .hooks_config import merge_hooks, remove_managed_hooks
from .launch_agent import LABEL, render_launch_agent


@dataclass(frozen=True)
class InstallPaths:
    home: Path
    root: Path
    current: Path
    stable_binary: Path
    launch_agent: Path
    logs: Path
    skill: Path
    hooks: Path

    @classmethod
    def for_home(cls, home: Path) -> "InstallPaths":
        root = home / "Library/Application Support/CodexClawdStatus"
        return cls(
            home=home,
            root=root,
            current=root / "current",
            stable_binary=root / "bin/clawd-status",
            launch_agent=home / "Library/LaunchAgents/com.kubai087.codex-clawd-status.plist",
            logs=home / "Library/Logs/CodexClawdStatus",
            skill=home / ".codex/skills/codex-clawd-status",
            hooks=home / ".codex/hooks.json",
        )


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        json.loads(Path(temp_name).read_text(encoding="utf-8"))
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def install_hooks_file(path: Path, command: str) -> None:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        backup = path.with_name(f"{path.name}.codex-clawd-status.bak.{int(time.time())}")
        if not list(path.parent.glob("hooks.json.codex-clawd-status.bak.*")):
            shutil.copy2(path, backup)
    else:
        data = {}
    _atomic_json(path, merge_hooks(data, command))
```

Continue `installer.py` with the lifecycle functions below. They install an immutable payload version, migrate an existing non-symlink skill directory to a timestamped backup, stop only recognized legacy status-light processes, and use the per-user launchd domain:

```python
def _replace_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(link.name + ".new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _stop_legacy_processes(home: Path) -> None:
    for name in ("status-hub.pid", "session-watch.pid", "hub-app.pid"):
        path = home / ".clawd-mochi" / name
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            check=False,
        )
        if "codex-clawd-status" not in result.stdout and "CodexClawdStatus" not in result.stdout:
            continue
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass


def install(payload: Path, version: str, home: Path | None = None) -> dict:
    paths = InstallPaths.for_home(home or Path.home())
    payload = payload.resolve()
    payload_binary = payload / "bin/clawd-status"
    payload_skill = payload / "share/codex-clawd-status/skill"
    if not payload_binary.is_file() or not (payload_skill / "SKILL.md").is_file():
        raise RuntimeError("payload is missing runtime or skill assets")

    release = paths.root / "releases" / version
    staging = paths.root / "releases" / f".{version}.staging"
    paths.root.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(payload, staging, symlinks=True)
    if release.exists():
        shutil.rmtree(release)
    os.replace(staging, release)
    _replace_symlink(paths.current, release)
    _replace_symlink(paths.stable_binary, paths.current / "bin/clawd-status")

    paths.skill.parent.mkdir(parents=True, exist_ok=True)
    if paths.skill.is_symlink():
        paths.skill.unlink()
    elif paths.skill.exists():
        backup = paths.skill.with_name(
            f"{paths.skill.name}.pre-macos-installer.{int(time.time())}"
        )
        os.replace(paths.skill, backup)
    paths.skill.symlink_to(paths.current / "share/codex-clawd-status/skill")

    command = f"{shlex.quote(str(paths.stable_binary))} hook"
    install_hooks_file(paths.hooks, command)
    paths.logs.mkdir(parents=True, exist_ok=True)
    paths.launch_agent.parent.mkdir(parents=True, exist_ok=True)
    paths.launch_agent.write_bytes(render_launch_agent(
        paths.stable_binary,
        paths.logs / "supervisor.out.log",
        paths.logs / "supervisor.err.log",
    ))

    _stop_legacy_processes(paths.home)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(paths.launch_agent), check=False)
    _launchctl("bootstrap", domain, str(paths.launch_agent))
    _launchctl("kickstart", "-k", f"{domain}/{LABEL}")
    return status(home=paths.home)


def _http_json(path: str, timeout: float = 2.0) -> dict:
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:8765{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def status(home: Path | None = None) -> dict:
    paths = InstallPaths.for_home(home or Path.home())
    domain = f"gui/{os.getuid()}"
    launch = _launchctl("print", f"{domain}/{LABEL}", check=False)
    result = {
        "installed": paths.current.is_symlink(),
        "launch_agent": "online" if launch.returncode == 0 else "offline",
    }
    try:
        result["modules"] = _http_json("/modules")
        result["state"] = _http_json("/state")
    except Exception as exc:
        result["hub_error"] = str(exc)
    return result


def doctor(home: Path | None = None) -> int:
    print(json.dumps(status(home=home), ensure_ascii=False, indent=2))
    return 0


def restart() -> int:
    domain = f"gui/{os.getuid()}"
    _launchctl("kickstart", "-k", f"{domain}/{LABEL}")
    return 0


def uninstall(home: Path | None = None, purge: bool = False) -> int:
    paths = InstallPaths.for_home(home or Path.home())
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(paths.launch_agent), check=False)

    command = f"{shlex.quote(str(paths.stable_binary))} hook"
    if paths.hooks.exists():
        data = json.loads(paths.hooks.read_text(encoding="utf-8"))
        _atomic_json(paths.hooks, remove_managed_hooks(data, command))

    if paths.skill.is_symlink():
        paths.skill.unlink()
        backups = sorted(paths.skill.parent.glob(
            f"{paths.skill.name}.pre-macos-installer.*"
        ))
        if backups:
            os.replace(backups[-1], paths.skill)
    paths.launch_agent.unlink(missing_ok=True)
    shutil.rmtree(paths.root, ignore_errors=True)
    if purge:
        shutil.rmtree(paths.logs, ignore_errors=True)
    return 0
```

Add `import shlex` to the imports at the top of `installer.py`.

- [ ] **Step 4: Extend the CLI dispatcher**

Replace `src/codex_clawd_status_macos/cli.py` with this complete dispatcher:

```python
from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__

ROLES = {
    "hub": "clawd_status_hub",
    "watch": "codex_session_watch",
    "hook": "codex_clawd_hook",
}


def require_supported_platform(system: str | None = None, machine: str | None = None) -> None:
    current_system = system or platform.system()
    current_machine = machine or platform.machine()
    if current_system != "Darwin" or current_machine != "arm64":
        raise RuntimeError("clawd-status requires an Apple silicon Mac")


def _run_role(role: str, args: list[str]) -> int:
    module = importlib.import_module(ROLES[role])
    previous = sys.argv
    try:
        sys.argv = [role, *args]
        return int(module.main())
    finally:
        sys.argv = previous


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clawd-status")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--payload", type=Path, required=True)
    commands.add_parser("supervise")
    commands.add_parser("status")
    commands.add_parser("doctor")
    commands.add_parser("restart")
    uninstall_parser = commands.add_parser("uninstall")
    uninstall_parser.add_argument("--purge", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    require_supported_platform()
    values = list(argv if argv is not None else sys.argv[1:])
    if values and values[0] in ROLES:
        return _run_role(values[0], values[1:])

    args = _parser().parse_args(values)
    if args.command == "supervise":
        from .supervisor import run
        return run()
    from . import installer
    if args.command == "install":
        result = installer.install(args.payload, __version__)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(installer.status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "doctor":
        return installer.doctor()
    if args.command == "restart":
        return installer.restart()
    if args.command == "uninstall":
        return installer.uninstall(purge=args.purge)
    raise AssertionError(f"unhandled command: {args.command}")
```

Create `src/codex_clawd_status_macos/__main__.py`:

```python
from .cli import main


raise SystemExit(main())
```

- [ ] **Step 5: Verify GREEN and full tests**

Run:

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/codex_clawd_status_macos/cli.py src/codex_clawd_status_macos/installer.py tests/test_installer.py
git commit -m "Install and manage the local status-light service"
```

### Task 6: Build the self-contained Apple silicon payload

**Files:**
- Create: `packaging/clawd-status.spec`
- Create: `scripts/build-local.sh`
- Create: `install.sh`
- Create: `THIRD_PARTY_NOTICES`
- Create: `tests/test_payload.py`

- [ ] **Step 1: Write the failing payload-structure test**

Create `tests/test_payload.py`:

```python
from pathlib import Path


def test_payload_contains_runtime_skill_and_license():
    payload = Path("dist/payload")
    assert (payload / "bin/clawd-status").is_file()
    assert (payload / "share/codex-clawd-status/skill/SKILL.md").is_file()
    assert (payload / "share/codex-clawd-status/LICENSE").is_file()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/test_payload.py -v
```

Expected: FAIL because `dist/payload` does not exist.

- [ ] **Step 3: Add the PyInstaller specification**

Create `packaging/clawd-status.spec` that builds `src/codex_clawd_status_macos/cli.py` as a `onedir` executable, includes the vendored script modules as hidden imports, and collects `bleak` and `serial`:

```python
from PyInstaller.utils.hooks import collect_all

bleak_data, bleak_bins, bleak_hidden = collect_all("bleak")
serial_data, serial_bins, serial_hidden = collect_all("serial")

a = Analysis(
    ["src/codex_clawd_status_macos/cli.py"],
    pathex=["src", "vendor/codex-status-LED/scripts"],
    binaries=bleak_bins + serial_bins,
    datas=bleak_data + serial_data,
    hiddenimports=[
        "clawd_status_hub",
        "codex_session_watch",
        "codex_clawd_hook",
        *bleak_hidden,
        *serial_hidden,
    ],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="clawd-status", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="clawd-status")
```

- [ ] **Step 4: Add the reproducible build script**

Create `scripts/build-local.sh`:

```bash
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(uname -s)" = Darwin
test "$(uname -m)" = arm64
rm -rf build dist
.venv/bin/pyinstaller --noconfirm packaging/clawd-status.spec
codesign --force --deep --sign - dist/clawd-status/clawd-status
mkdir -p dist/payload/bin dist/payload/share/codex-clawd-status
cp -R dist/clawd-status dist/payload/runtime
ln -s ../runtime/clawd-status dist/payload/bin/clawd-status
cp -R vendor/codex-status-LED dist/payload/share/codex-clawd-status/skill
cp vendor/codex-status-LED/LICENSE dist/payload/share/codex-clawd-status/LICENSE
cp THIRD_PARTY_NOTICES dist/payload/share/codex-clawd-status/THIRD_PARTY_NOTICES
dist/payload/bin/clawd-status --version
```

Create `install.sh`:

```bash
#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "clawd-status requires an Apple silicon Mac" >&2
  exit 1
fi

if [[ "${1:-}" != "--payload" || -z "${2:-}" || -n "${3:-}" ]]; then
  echo "usage: ./install.sh --payload PATH" >&2
  exit 2
fi

payload="$(cd "$2" && pwd -P)"
exec "$payload/bin/clawd-status" install --payload "$payload"
```

Create `THIRD_PARTY_NOTICES`:

```text
This distribution includes software from GFlash6/codex-status-LED.
Copyright (c) 2026 GFlash. Licensed under the MIT License.

Python dependencies and their licenses are collected in the release build
metadata generated by PyInstaller. See the bundled package metadata for the
license terms of bleak, pyserial, and their transitive dependencies.
```

- [ ] **Step 5: Build and verify GREEN**

Run:

```bash
chmod +x scripts/build-local.sh install.sh
scripts/build-local.sh
.venv/bin/pytest tests/test_payload.py -v
file dist/payload/runtime/clawd-status
codesign --verify --deep --strict dist/payload/runtime/clawd-status
```

Expected: payload test passes; `file` reports arm64; code-sign verification exits 0 after the build script ad-hoc signs the runtime with `codesign --force --deep --sign -`.

- [ ] **Step 6: Run the full suite and commit**

Run:

```bash
.venv/bin/pytest -v
git diff --check
```

Expected: all tests pass and no whitespace errors.

Commit:

```bash
git add packaging scripts install.sh THIRD_PARTY_NOTICES tests/test_payload.py
git commit -m "Build self-contained Apple silicon payload"
```

### Task 7: Install on this Mac and verify the live lifecycle

**Files:**
- Modify only package-owned paths under the current user's home directory.

- [ ] **Step 1: Capture the pre-install state**

Run:

```bash
cp ~/.codex/hooks.json /tmp/hooks.before-clawd-install.json
launchctl print "gui/$(id -u)/com.kubai087.codex-clawd-status" >/tmp/clawd.launch.before 2>&1 || true
curl -sS --max-time 2 http://127.0.0.1:8765/state >/tmp/clawd.state.before.json || true
```

Expected: backups exist even if the service is not yet registered.

- [ ] **Step 2: Install the local payload**

Run:

```bash
./install.sh --payload "$PWD/dist/payload"
```

Expected: installer reports runtime installed, LaunchAgent online, Hub online, watcher online, and ESP32 delivered or waiting for connection.

- [ ] **Step 3: Verify launchd, Hub, watcher, hooks, and transport**

Run:

```bash
launchctl print "gui/$(id -u)/com.kubai087.codex-clawd-status"
curl -sS http://127.0.0.1:8765/health
curl -sS http://127.0.0.1:8765/modules
curl -sS http://127.0.0.1:8765/state
clawd-status doctor
python3 -m json.tool ~/.codex/hooks.json >/dev/null
```

Expected: LaunchAgent state is running; Hub and watcher are online; hooks JSON is valid; `/state` shows `transport_status=delivered` or an explicit waiting-for-connection state.

- [ ] **Step 4: Verify automatic process recovery**

Run:

```bash
hub_pid=$(curl -sS http://127.0.0.1:8765/health | python3 -c 'import json,sys; print(json.load(sys.stdin)["pid"])')
kill "$hub_pid"
for _ in {1..20}; do
  sleep 1
  curl -fsS http://127.0.0.1:8765/health && break
done
curl -fsS http://127.0.0.1:8765/health
```

Expected: a new Hub PID becomes healthy within 20 seconds without manual restart.

- [ ] **Step 5: Verify hook preservation**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

before = json.loads(Path('/tmp/hooks.before-clawd-install.json').read_text())
after = json.loads((Path.home() / '.codex/hooks.json').read_text())
command = str(Path.home() / 'Library/Application Support/CodexClawdStatus/bin/clawd-status') + ' hook'

for event, entries in after.get('hooks', {}).items():
    after['hooks'][event] = [
        entry for entry in entries
        if not any(hook.get('command') == command for hook in entry.get('hooks', []))
    ]

assert after == before, 'installer changed unrelated hooks'
print('unrelated hooks preserved')
PY
```

Expected: all pre-existing unrelated hooks remain byte-for-byte equivalent as parsed JSON.

- [ ] **Step 6: Record local verification and commit**

Create `README.md` with this initial verified-preview structure, replacing only the bracketed result values with the observed non-sensitive values:

```markdown
# Codex Clawd Status for Apple Silicon

One-command macOS background runtime for the Codex Clawd status-light stack.

## Local preview verification

- Platform: Apple silicon, macOS `[version]`
- Install: `./install.sh --payload "$PWD/dist/payload"`
- LaunchAgent: `[online/offline]`
- Hub: `[online/offline]`
- Watcher: `[online/offline]`
- ESP32 transport: `[delivered/waiting for connection]`

The preview does not include public Release automation yet. It validates the
self-contained runtime, managed hooks, LaunchAgent lifecycle, and device path.
```

Run:

```bash
.venv/bin/pytest -v
git diff --check
git status --short
```

Expected: tests pass, no whitespace errors, and only intended documentation changes remain.

Commit:

```bash
git add README.md
git commit -m "Document local Apple silicon verification"
```

## Completion Check

Before claiming completion, run fresh:

```bash
.venv/bin/pytest -v
scripts/build-local.sh
launchctl print "gui/$(id -u)/com.kubai087.codex-clawd-status"
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/modules
curl -fsS http://127.0.0.1:8765/state
clawd-status doctor
git status -sb
```

Completion requires all automated tests to pass, a fresh arm64 payload build, a running LaunchAgent, online Hub and watcher, valid preserved hooks, and a current transport result that is either delivered or explicitly waiting for the ESP32.
