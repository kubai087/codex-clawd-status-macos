# Codex, CodeBuddy, and WorkBuddy v0.2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a self-contained Apple silicon v0.2.0 release that configures Codex, CodeBuddy, and WorkBuddy in one installation and sends their lifecycle events to one non-blocking ESP32 delivery queue.

**Architecture:** Keep one LaunchAgent, Hub, and Codex watcher. Add a shared CodeBuddy-compatible hook adapter and configure it separately in `~/.codebuddy/settings.json` and `~/.workbuddy/settings.json`. Normal platform events use a latest-state-wins Hub queue, while manual `/send` remains synchronous for transport verification.

**Tech Stack:** Python 3.9+, pytest, PyInstaller, macOS LaunchAgent, JSON user settings, local HTTP Hub, BLE and pyserial transport, Bash release packaging.

---

## File Structure

- Create `src/codex_clawd_status_macos/buddy_hooks_config.py`: CodeBuddy/WorkBuddy hook schema, managed-command detection, merge, and removal.
- Modify `src/codex_clawd_status_macos/installer.py`: three platform paths, atomic settings installation, three skill links, migration, status, and uninstall.
- Modify `src/codex_clawd_status_macos/cli.py`: expose the bundled buddy hook role.
- Create `vendor/codex-status-LED/scripts/buddy_clawd_hook.py`: normalize CodeBuddy-compatible events and reuse the shared Codex mapping/Hub client.
- Modify `vendor/codex-status-LED/scripts/codex_clawd_hook.py`: submit normal events to `/enqueue` with caller-specific identity and without full payload storage.
- Modify `vendor/codex-status-LED/scripts/clawd_status_hub.py`: latest-state queue, `/enqueue`, platform configuration modules, and dashboard cards.
- Modify `packaging/clawd-status.spec`: bundle the buddy adapter.
- Modify `src/codex_clawd_status_macos/__init__.py` and `pyproject.toml`: version 0.2.0.
- Modify `README.md` and create `docs/releases/v0.2.0.md`: public multi-platform documentation.
- Create `tests/test_buddy_hooks_config.py`: settings merge/migration/removal tests.
- Expand `tests/test_installer.py`: three settings and three skill lifecycle tests.
- Create `tests/test_buddy_hook.py`: event mapping and client identity tests.
- Create `tests/test_hub_queue.py`: enqueue latency, coalescing, and serialized delivery tests.
- Expand `tests/test_hub_compat.py`, `tests/test_cli.py`, and `tests/test_payload.py`: platform status, role, version, and packaging tests.

### Task 1: CodeBuddy-compatible settings merge

**Files:**
- Create: `tests/test_buddy_hooks_config.py`
- Create: `src/codex_clawd_status_macos/buddy_hooks_config.py`

- [ ] **Step 1: Write the failing settings tests**

```python
from codex_clawd_status_macos.buddy_hooks_config import (
    BUDDY_HOOK_EVENTS,
    merge_buddy_hooks,
    remove_managed_buddy_hooks,
)


def commands(data: dict, event: str) -> list[str]:
    return [
        hook["command"]
        for entry in data["hooks"][event]
        for hook in entry["hooks"]
        if hook.get("type") == "command"
    ]


def test_merge_preserves_unrelated_settings_and_is_idempotent():
    original = {
        "enabledPlugins": {"keep@market": True},
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "/tmp/other"}]}]
        },
    }
    command = "/opt/clawd-status buddy-hook --platform codebuddy"
    first = merge_buddy_hooks(original, command)
    second = merge_buddy_hooks(first, command)
    assert second == first
    assert second["enabledPlugins"] == {"keep@market": True}
    assert commands(second, "Stop") == ["/tmp/other", command]
    assert set(second["hooks"]) >= set(BUDDY_HOOK_EVENTS)


def test_merge_replaces_legacy_python_adapter():
    legacy = (
        "~/.codebuddy/hooks/codex-status-led/.venv/bin/python "
        "~/.codebuddy/hooks/codex-status-led/scripts/workbuddy_clawd_hook.py"
    )
    current = "/opt/clawd-status buddy-hook --platform workbuddy"
    merged = merge_buddy_hooks(
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": legacy}]}]}},
        current,
    )
    assert commands(merged, "Stop") == [current]


def test_remove_keeps_unrelated_commands():
    current = "/opt/clawd-status buddy-hook --platform codebuddy"
    merged = merge_buddy_hooks({"hooks": {}}, current)
    merged["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "/tmp/other"}]}
    )
    cleaned = remove_managed_buddy_hooks(merged, current)
    assert commands(cleaned, "Stop") == ["/tmp/other"]
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest tests/test_buddy_hooks_config.py -v`

Expected: collection fails with `ModuleNotFoundError: codex_clawd_status_macos.buddy_hooks_config`.

- [ ] **Step 3: Implement the minimal settings module**

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

BUDDY_HOOK_EVENTS = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "PermissionRequest", "PreCompact", "PostCompact",
    "SubagentStart", "SubagentStop", "Stop", "StopFailure", "SessionEnd",
    "Notification",
)

LEGACY_BUDDY_MARKERS = (
    "/.codebuddy/hooks/codex-status-led/",
    "\\\\.codebuddy\\\\hooks\\\\codex-status-led\\\\",
    "workbuddy_clawd_hook.py",
)


def _entry(command: str, event: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "hooks": [{
            "type": "command",
            "command": command,
            "timeout": 2,
            "statusMessage": "Updating Clawd display",
        }]
    }
    if event == "SessionStart":
        value["matcher"] = "startup|resume|clear|compact"
    return value


def _managed(command: object, current: str) -> bool:
    return isinstance(command, str) and (
        command == current or any(marker in command for marker in LEGACY_BUDDY_MARKERS)
    )


def _clean(entries: list[Any], current: str) -> list[Any]:
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            result.append(entry)
            continue
        hooks = [
            hook for hook in entry["hooks"]
            if not (isinstance(hook, dict) and _managed(hook.get("command"), current))
        ]
        if hooks:
            copied = deepcopy(entry)
            copied["hooks"] = hooks
            result.append(copied)
    return result


def merge_buddy_hooks(data: dict[str, Any], command: str) -> dict[str, Any]:
    result = deepcopy(data)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be a JSON object")
    for event in BUDDY_HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f"hooks.{event} must be a JSON array")
        hooks[event] = [*_clean(entries, command), _entry(command, event)]
    return result


def remove_managed_buddy_hooks(data: dict[str, Any], command: str) -> dict[str, Any]:
    result = deepcopy(data)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event, entries in hooks.items():
        if isinstance(entries, list):
            hooks[event] = _clean(entries, command)
    return result
```

- [ ] **Step 4: Run the focused and existing hook tests**

Run: `.venv/bin/pytest tests/test_buddy_hooks_config.py tests/test_hooks_config.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/codex_clawd_status_macos/buddy_hooks_config.py tests/test_buddy_hooks_config.py
git commit -m "Configure CodeBuddy compatible hooks"
```

### Task 2: Three-platform installer lifecycle

**Files:**
- Modify: `tests/test_installer.py`
- Modify: `src/codex_clawd_status_macos/installer.py`

- [ ] **Step 1: Extend the path and lifecycle tests**

Add assertions that `InstallPaths.for_home(home)` exposes:

```python
assert paths.codex_skill == home / ".codex/skills/codex-clawd-status"
assert paths.codebuddy_skill == home / ".codebuddy/skills/codex-clawd-status"
assert paths.workbuddy_skill == home / ".workbuddy/skills/codex-clawd-status"
assert paths.codex_hooks == home / ".codex/hooks.json"
assert paths.codebuddy_settings == home / ".codebuddy/settings.json"
assert paths.workbuddy_settings == home / ".workbuddy/settings.json"
```

Extend the install/uninstall test to seed a previous directory at each skill
path, seed unrelated JSON keys and commands in all three settings files, run
`install(..., manage_service=False)`, and assert:

```python
for skill in paths.skill_paths():
    assert skill.is_symlink()
    assert (skill / "SKILL.md").read_text() == "status skill"

assert expected_codex_command in paths.codex_hooks.read_text()
assert expected_codebuddy_command in paths.codebuddy_settings.read_text()
assert expected_workbuddy_command in paths.workbuddy_settings.read_text()

uninstall(home=home, manage_service=False)
for skill in paths.skill_paths():
    assert not skill.is_symlink()
    assert (skill / "previous.txt").read_text() == "keep"
```

Add a focused test that a malformed `~/.workbuddy/settings.json` remains
byte-for-byte unchanged and aborts install before replacement.

- [ ] **Step 2: Run the installer tests and verify RED**

Run: `.venv/bin/pytest tests/test_installer.py -v`

Expected: failures for the missing path fields, skill links, and buddy settings.

- [ ] **Step 3: Implement platform paths and helpers**

Add the six platform paths to `InstallPaths`, keep `skill` and `hooks` read-only
properties pointing to the Codex paths for compatibility, and add:

```python
def skill_paths(self) -> tuple[Path, Path, Path]:
    return self.codex_skill, self.codebuddy_skill, self.workbuddy_skill


def _install_json(path: Path, command: str, merge) -> None:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        backups = list(path.parent.glob(f"{path.name}.codex-clawd-status.bak.*"))
        if not backups:
            backup = path.with_name(
                f"{path.name}.codex-clawd-status.bak.{int(time.time())}"
            )
            shutil.copy2(path, backup)
    else:
        data = {}
    _atomic_json(path, merge(data, command))


def _install_skill(skill: Path, target: Path) -> None:
    skill.parent.mkdir(parents=True, exist_ok=True)
    if skill.is_symlink():
        skill.unlink()
    elif skill.exists():
        os.replace(
            skill,
            skill.with_name(f"{skill.name}.pre-macos-installer.{int(time.time())}"),
        )
    skill.symlink_to(target)


def _remove_skill(skill: Path) -> None:
    if not skill.is_symlink():
        return
    skill.unlink()
    backups = sorted(skill.parent.glob(f"{skill.name}.pre-macos-installer.*"))
    if backups:
        os.replace(backups[-1], skill)
```

Use stable commands:

```python
codex = f"{quoted_binary} hook"
codebuddy = f"{quoted_binary} buddy-hook --platform codebuddy"
workbuddy = f"{quoted_binary} buddy-hook --platform workbuddy"
```

Install all three JSON configurations and all three skill links regardless of
application detection. During uninstall, apply the matching remove function to
each settings file and call `_remove_skill` for each skill path.

- [ ] **Step 4: Run installer regression tests**

Run: `.venv/bin/pytest tests/test_installer.py tests/test_hooks_config.py tests/test_buddy_hooks_config.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/codex_clawd_status_macos/installer.py tests/test_installer.py
git commit -m "Install Codex CodeBuddy and WorkBuddy integrations"
```

### Task 3: Shared buddy lifecycle adapter

**Files:**
- Create: `tests/test_buddy_hook.py`
- Create: `vendor/codex-status-LED/scripts/buddy_clawd_hook.py`
- Modify: `tests/test_cli.py`
- Modify: `src/codex_clawd_status_macos/cli.py`
- Modify: `vendor/codex-status-LED/scripts/codex_clawd_hook.py`

- [ ] **Step 1: Write failing adapter and CLI tests**

```python
import buddy_clawd_hook as buddy


def test_buddy_extended_event_mapping():
    assert buddy.payload_to_anim({"hook_event_name": "PostToolUseFailure"}) == "dizzy"
    assert buddy.payload_to_anim({"hook_event_name": "StopFailure"}) == "dizzy"
    assert buddy.payload_to_anim({"hook_event_name": "SessionEnd"}) == "sleeping"
    assert buddy.payload_to_anim({
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
    }) == "confused"
    assert buddy.payload_to_anim({
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
    }) == "happy"


def test_buddy_shared_mapping_reuses_tool_categories():
    assert buddy.payload_to_anim({
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
    }) == "typing"
```

Add to `tests/test_cli.py`:

```python
def test_buddy_hook_role_dispatches_platform_mapping(capsys):
    assert main(["buddy-hook", "--platform", "codebuddy", "--print-mapping"]) == 0
    assert "PostToolUseFailure: dizzy" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest tests/test_buddy_hook.py tests/test_cli.py -v`

Expected: import failure for `buddy_clawd_hook` and parser rejection of
`buddy-hook`.

- [ ] **Step 3: Implement the buddy adapter and identity-aware enqueue client**

Create `buddy_clawd_hook.py` as a thin adapter over `codex_clawd_hook` with:

```python
def payload_to_anim(payload: dict) -> str | None:
    event = payload.get("hook_event_name") or payload.get("event") or ""
    if event in {"PostToolUseFailure", "StopFailure"}:
        return "dizzy"
    if event == "SessionEnd":
        return shared.SLEEP_ANIM
    if event == "Notification":
        kind = str(payload.get("notification_type") or "")
        if kind in {"permission_prompt", "elicitation_dialog"}:
            return "confused"
        if kind == "idle_prompt":
            return shared.TASK_COMPLETE_ANIM
        return "beacon"
    return shared.payload_to_anim(payload)
```

Its parser requires `--platform` in `{codebuddy,workbuddy}`, sets
`client_id`, `source`, and `client_kind` to that value, reads one stdin object,
maps it, and calls the shared delivery helper. It mirrors the current test,
doctor, print-mapping, and timed-transition modes.

Add `"buddy-hook": "buddy_clawd_hook"` to `ROLES`.

Change `send_anim_hub` to use `/enqueue` and caller identity. Remove its
`ensure_hub(args)` call so a missing Hub is logged immediately instead of
starting processes or waiting inside a platform hook. The LaunchAgent is the
only Hub/watcher supervisor in this package. Remove the Codex hook's
`ensure_session_watcher(args)` call for the same reason.

```python
source = str(getattr(args, "source", "codex"))
kind = str(getattr(args, "client_kind", source))
body = json.dumps({
    "source": source,
    "client_id": client_id(getattr(args, "client_id", None)),
    "client_kind": kind,
    "anim": anim,
    "event": event,
    "tool": tool,
    "event_time": event_time,
}, separators=(",", ":")).encode("utf-8")
```

Use a one-second local HTTP timeout. Do not include the original payload in the
Hub request. Since `CLAWD_TANK_HUB_REQUIRED` defaults to true, an unavailable
Hub logs the failure and exits zero without a direct BLE/serial attempt. Update
timed-transition spawning so buddy events retain their platform role and
identity.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_buddy_hook.py tests/test_cli.py tests/test_runtime_command.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_buddy_hook.py tests/test_cli.py src/codex_clawd_status_macos/cli.py vendor/codex-status-LED/scripts/buddy_clawd_hook.py vendor/codex-status-LED/scripts/codex_clawd_hook.py
git commit -m "Bridge CodeBuddy compatible lifecycle events"
```

### Task 4: Latest-state Hub queue and platform diagnostics

**Files:**
- Create: `tests/test_hub_queue.py`
- Modify: `tests/test_hub_compat.py`
- Modify: `vendor/codex-status-LED/scripts/clawd_status_hub.py`

- [ ] **Step 1: Write failing queue and module tests**

```python
import threading
import time

from clawd_status_hub import LatestDeliveryQueue, buddy_hook_configured


def test_queue_returns_before_delivery_finishes():
    release = threading.Event()
    started = threading.Event()

    def deliver(item):
        started.set()
        release.wait(1)

    queue = LatestDeliveryQueue(deliver)
    before = time.perf_counter()
    queue.enqueue({"anim": "thinking"})
    elapsed = time.perf_counter() - before
    assert elapsed < 0.1
    assert started.wait(1)
    release.set()


def test_queue_keeps_only_newest_pending_state():
    release = threading.Event()
    started = threading.Event()
    delivered = []

    def deliver(item):
        delivered.append(item["anim"])
        if len(delivered) == 1:
            started.set()
            release.wait(1)

    queue = LatestDeliveryQueue(deliver)
    queue.enqueue({"anim": "building"})
    assert started.wait(1)
    queue.enqueue({"anim": "thinking"})
    queue.enqueue({"anim": "happy"})
    release.set()
    deadline = time.time() + 1
    while delivered != ["building", "happy"] and time.time() < deadline:
        time.sleep(0.01)
    assert delivered == ["building", "happy"]


def test_buddy_config_detection_requires_platform_command(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"hooks":{"Stop":[{"hooks":[{"command":"/opt/clawd-status buddy-hook --platform codebuddy"}]}]}}'
    )
    assert buddy_hook_configured(settings, "codebuddy")
    assert not buddy_hook_configured(settings, "workbuddy")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_hub_queue.py tests/test_hub_compat.py -v`

Expected: import failures for the queue and buddy configuration helper.

- [ ] **Step 3: Implement queue, endpoint, and modules**

Add a daemon worker with one replaceable pending item:

```python
class LatestDeliveryQueue:
    def __init__(self, deliver):
        self.deliver = deliver
        self.condition = threading.Condition()
        self.pending = None
        threading.Thread(target=self._run, daemon=True).start()

    def enqueue(self, delivery: dict[str, Any]) -> None:
        with self.condition:
            self.pending = dict(delivery)
            self.condition.notify()

    def _run(self) -> None:
        while True:
            with self.condition:
                while self.pending is None:
                    self.condition.wait()
                delivery = self.pending
                self.pending = None
            try:
                self.deliver(delivery)
            except Exception as exc:
                log(f"queued delivery failed: {exc}")
```

Create the queue after Hub state initialization and expose:

```python
def enqueue(self, delivery: dict[str, Any]) -> dict[str, Any]:
    if not self.device_command(delivery).get("anim") and not any(
        key in delivery for key in ("effect", "steps", "leds", "led", "mask")
    ):
        return {"ok": False, "error": "missing anim or effect"}
    source = str(delivery.get("source") or "manual")
    client_id = str(delivery.get("client_id") or source)
    client_kind = str(delivery.get("client_kind") or source)
    event = str(delivery.get("event") or "")
    tool = str(delivery.get("tool") or "")
    anim = str(delivery.get("anim") or "custom")
    with self.lock:
        client = self.clients.setdefault(client_id, {
            "client_id": client_id,
            "kind": client_kind,
            "source": source,
            "hooks": {},
            "delivered_count": 0,
            "failed_count": 0,
        })
        client.update({"status": "queued", "last_anim": anim, "last_event": event})
        self.state.update({
            "current_anim": anim,
            "current_source": source,
            "current_client_id": client_id,
            "current_client_kind": client_kind,
            "current_event": event,
            "current_tool": tool,
            "transport_status": "queued",
        })
    self.delivery_queue.enqueue(delivery)
    return {"ok": True, "status": "queued"}
```

Route `POST /enqueue` to this method while keeping `/hook` and `/send`
synchronous. Add `buddy_hook_configured(path, platform)` and modules for
`codebuddy-hook` and `workbuddy-hook`; remove the unrelated Claude module.
Update the dashboard status bar to show Codex, CodeBuddy, WorkBuddy, watcher,
and device cards.

- [ ] **Step 4: Run queue, Hub, and full tests**

Run: `.venv/bin/pytest tests/test_hub_queue.py tests/test_hub_compat.py -v`

Then: `.venv/bin/pytest -q`

Expected: all tests pass and no worker-thread exception is printed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hub_queue.py tests/test_hub_compat.py vendor/codex-status-LED/scripts/clawd_status_hub.py
git commit -m "Queue multi-platform status deliveries"
```

### Task 5: Versioned payload and public documentation

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_payload.py`
- Modify: `src/codex_clawd_status_macos/__init__.py`
- Modify: `pyproject.toml`
- Modify: `packaging/clawd-status.spec`
- Modify: `README.md`
- Create: `docs/releases/v0.2.0.md`

- [ ] **Step 1: Update tests first**

Change the version expectation to `0.2.0`. Add this payload assertion:

```python
assert (
    payload / "share/codex-clawd-status/skill/scripts/buddy_clawd_hook.py"
).is_file()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/test_cli.py tests/test_payload.py -v`

Expected: the version test fails with `0.1.0`; the payload test either skips on
a clean tree or fails against the existing 0.1.0 build.

- [ ] **Step 3: Bump and document v0.2.0**

Set both package version declarations to `0.2.0`. Add
`buddy_clawd_hook` to PyInstaller hidden imports. Update the README platform
requirements and one-command behavior. Create release notes containing:

```markdown
# v0.2.0

- One installation configures Codex, CodeBuddy, and WorkBuddy.
- Shared self-contained runtime and user-level skill for all three platforms.
- Native CodeBuddy-compatible lifecycle hooks with distinct dashboard clients.
- Non-blocking latest-state queue prevents device transport from delaying agents.
- Safe migration of the legacy WorkBuddy/CodeBuddy Python hook.
- Idempotent upgrades and managed uninstall across all three settings files.

Not included: platform application installation, Intel Mac support, Windows,
ESP32 firmware flashing, Developer ID notarization, or automatic runtime updates.
```

- [ ] **Step 4: Build and test the payload**

Run: `scripts/package-release.sh`

Then: `.venv/bin/pytest -q`

Then, from `dist/release`:

```bash
shasum -a 256 -c codex-clawd-status-macos-arm64.tar.gz.sha256
```

Expected: all tests pass, archive checksum is `OK`, the bundled binary prints
`0.2.0`, and `file dist/payload/runtime/clawd-status` reports arm64.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py tests/test_payload.py src/codex_clawd_status_macos/__init__.py pyproject.toml packaging/clawd-status.spec README.md docs/releases/v0.2.0.md
git commit -m "Prepare multi-platform v0.2.0 release"
```

### Task 6: Local upgrade and end-to-end verification

**Files:**
- No source changes expected

- [ ] **Step 1: Record the current managed integration state**

Run a read-only script that records, without printing unrelated commands or
settings values, the existence of all three settings files, managed-command
counts, and the existing legacy marker count.

- [ ] **Step 2: Upgrade through the locally packaged installer**

Run: `./install.sh --payload "$PWD/dist/payload"`

Expected: installer JSON reports version 0.2.0, LaunchAgent online, Hub online,
watcher online, and all three native integrations configured.

- [ ] **Step 3: Verify settings and skills**

Assert programmatically:

```text
~/.codex/hooks.json             one managed Codex command per Codex event
~/.codebuddy/settings.json      one v0.2.0 codebuddy command per buddy event
~/.workbuddy/settings.json      one v0.2.0 workbuddy command per buddy event
~/.codex/skills/codex-clawd-status       symlink into current release
~/.codebuddy/skills/codex-clawd-status   symlink into current release
~/.workbuddy/skills/codex-clawd-status   symlink into current release
```

Also assert that the legacy Python command count in both buddy settings files
is zero while unrelated top-level keys remain present.

- [ ] **Step 4: Submit synthetic platform events**

Pipe official-shaped JSON to each installed command:

```bash
printf '%s' '{"hook_event_name":"UserPromptSubmit"}' | clawd-status hook
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Write"}' | clawd-status buddy-hook --platform codebuddy
printf '%s' '{"hook_event_name":"PermissionRequest"}' | clawd-status buddy-hook --platform workbuddy
```

Poll `/state` until Hub clients contain `codex-code`, `codebuddy`, and
`workbuddy`. Confirm the hook processes return quickly and the worker eventually
records delivery.

- [ ] **Step 5: Verify ESP32 and supervision**

POST a synchronous manual `thinking` animation to `/send`; require
`status=delivered`. Record the successful transport and confirm
`failed_count == 0`. Force-stop the supervised Hub process, wait for the
LaunchAgent to restart it, and confirm both Hub and watcher return online.

### Task 7: Finish branch and publish v0.2.0

**Files:**
- No new source files expected

- [ ] **Step 1: Run the complete release gate fresh**

Run:

```bash
.venv/bin/pytest -q
scripts/package-release.sh
.venv/bin/pytest -q
```

Verify SHA-256, arm64 Mach-O type, ad-hoc signature, clean Git status, and the
local v0.2.0 doctor output.

- [ ] **Step 2: Invoke the finishing-a-development-branch workflow**

Present the required integration options. For local merge, merge the feature
branch into `main`, rerun the complete test suite and package gate on merged
`main`, then remove the owned worktree and branch.

- [ ] **Step 3: Push main and publish the release after merge authorization**

Push `main`, create tag and GitHub Release `v0.2.0`, and upload:

```text
dist/release/codex-clawd-status-macos-arm64.tar.gz
dist/release/codex-clawd-status-macos-arm64.tar.gz.sha256
```

Use `docs/releases/v0.2.0.md` as release notes.

- [ ] **Step 4: Verify the true public upgrade path**

Run the public command:

```bash
curl -fsSL https://raw.githubusercontent.com/kubai087/codex-clawd-status-macos/main/install.sh | bash
```

Confirm it downloads the public v0.2.0 asset, verifies its checksum, preserves
all three integrations, and passes the same Hub/watcher/ESP32 checks.

- [ ] **Step 5: Final evidence**

Record the public repository visibility, release URL, asset digests, test count,
installed version, platform integration states, transport result, delivered
count, failed count, and clean `main...origin/main` status.
