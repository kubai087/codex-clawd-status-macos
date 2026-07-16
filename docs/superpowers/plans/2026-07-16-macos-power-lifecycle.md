# macOS Power Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make macOS sleep force the status light off, and make wake, login, and Hub restart clear stale tasks and publish idle.

**Architecture:** Add a Hub-level system power override above per-session arbitration, controlled through a local HTTP endpoint. Add a dependency-free IOKit monitor in the supervisor that posts sleep/wake states and acknowledges required notifications; retain wake-gap restart as fallback.

**Tech Stack:** Python 3.9+, ctypes, IOKit, CoreFoundation, existing Hub HTTP API, threading, pytest, PyInstaller, macOS LaunchAgent.

---

### Task 1: Add the Hub System Power Override

**Files:**
- Modify: `vendor/codex-status-LED/scripts/clawd_status_hub.py`
- Modify: `tests/test_hub_queue.py`

- [ ] **Step 1: Write failing sleep/wake override tests**

```python
def test_system_sleep_clears_sessions_and_enqueues_sleeping():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.enqueue({"client_id": "codex-desktop", "session_id": "A", "anim": "thinking"})

    result = hub.set_system_power_state("sleeping", "system-will-sleep")

    state = hub.snapshot()
    assert result["ok"] is True
    assert state["system_power_state"] == "sleeping"
    assert state["system_override"] is True
    assert state["clients"] == {}
    assert queue.items[-1]["anim"] == "sleeping"


def test_lifecycle_event_is_masked_while_sleeping():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.set_system_power_state("sleeping", "test")

    result = hub.enqueue({"client_id": "workbuddy", "session_id": "B", "anim": "confused"})

    assert result["display_role"] == "system-masked"
    assert result["display_changed"] is False
    assert hub.snapshot()["clients"] == {}


def test_system_wake_publishes_idle_without_restoring_old_work():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.enqueue({"client_id": "codex-desktop", "session_id": "A", "anim": "thinking"})
    hub.set_system_power_state("sleeping", "test")

    hub.set_system_power_state("awake", "system-has-powered-on")

    state = hub.snapshot()
    assert state["system_override"] is False
    assert state["clients"] == {}
    assert state["current_client_id"] == "macos-power"
    assert state["current_status"] == "idle"
    assert queue.items[-1]["anim"] == "idle"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_hub_queue.py -q`

Expected: FAIL because `set_system_power_state` and system state fields do not exist.

- [ ] **Step 3: Implement system state reset and publishing**

Add state fields `system_power_state`, `system_override`, `system_reason`, and
`system_changed_at`. Implement:

```python
def set_system_power_state(self, state: str, reason: str = "") -> dict[str, Any]:
    if state not in {"awake", "sleeping"}:
        return {"ok": False, "error": "expected state awake or sleeping"}
    with self.arbitration_condition:
        self.arbiter = StatusArbiter(clock=self.clock)
        self.clients.clear()
        self.hooks.clear()
        self.last_published_fingerprint = None
        sleeping = state == "sleeping"
        self.state.update({
            "system_power_state": state,
            "system_override": sleeping,
            "system_reason": reason,
            "system_changed_at": self.clock(),
        })
        delivery = {
            "source": "system",
            "client_id": "macos-power",
            "client_kind": "system",
            "client_key": "macos-power",
            "status": "sleeping" if sleeping else "idle",
            "anim": "sleeping" if sleeping else "idle",
            "event": reason,
        }
        self.delivery_queue.enqueue(delivery)
        self._set_system_current_locked(delivery)
        self.arbitration_condition.notify_all()
    return {"ok": True, "state": state, "status": "queued"}
```

While `system_override` is true, `/enqueue` must return an acknowledged
`system-masked` result before touching the arbiter.

- [ ] **Step 4: Add the local HTTP route and startup idle**

Route `POST /system/state` to the new method. After the HTTP server successfully
binds, call `HubHandler.hub.set_system_power_state("awake", "startup")` once so
every fresh Hub asynchronously publishes idle.

- [ ] **Step 5: Run Hub tests and commit**

Run: `.venv/bin/pytest tests/test_status_arbiter.py tests/test_hub_queue.py -q`

Expected: all focused tests pass.

```bash
git add vendor/codex-status-LED/scripts/clawd_status_hub.py tests/test_hub_queue.py
git commit -m "Override task state for system power"
```

### Task 2: Add Testable Supervisor-to-Hub Power Control

**Files:**
- Modify: `src/codex_clawd_status_macos/supervisor.py`
- Modify: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing Hub request and notification tests**

```python
def test_post_system_power_state_uses_local_endpoint(monkeypatch):
    captured = fake_urlopen(monkeypatch, {"ok": True, "status": "queued"})
    assert post_system_power_state("sleeping", "system-will-sleep") is True
    assert captured["url"].endswith("/system/state")
    assert captured["body"] == {"state": "sleeping", "reason": "system-will-sleep"}


def test_power_callbacks_send_sleep_and_wake(monkeypatch):
    calls = []
    callbacks = power_callbacks(lambda state, reason: calls.append((state, reason)) or True)
    callbacks.on_sleep()
    callbacks.on_wake()
    assert calls == [
        ("sleeping", "system-will-sleep"),
        ("awake", "system-has-powered-on"),
    ]
```

- [ ] **Step 2: Run supervisor tests and verify RED**

Run: `.venv/bin/pytest tests/test_supervisor.py -q`

Expected: FAIL because the power request and callback helpers do not exist.

- [ ] **Step 3: Implement the local power-state client**

Use a proxy-free urllib opener and a one-second POST timeout. For sleeping, poll
`/state` for no more than five seconds and return after the Hub reports
`system_power_state == "sleeping"`; delivery failure is accepted once the
system state has been recorded because sleep must not be vetoed.

- [ ] **Step 4: Integrate callbacks and graceful termination**

Start the native monitor in one daemon thread. On supervisor SIGTERM/INT, set
the loop flag; in `finally`, post sleeping with reason `supervisor-shutdown`
before terminating watcher and Hub. Keep wake-gap child restart unchanged.

- [ ] **Step 5: Run supervisor tests and commit**

Run: `.venv/bin/pytest tests/test_supervisor.py -q`

Expected: all tests pass.

```bash
git add src/codex_clawd_status_macos/supervisor.py tests/test_supervisor.py
git commit -m "Coordinate Hub power state from supervisor"
```

### Task 3: Register Native macOS Power Notifications

**Files:**
- Create: `src/codex_clawd_status_macos/macos_power.py`
- Create: `tests/test_macos_power.py`

- [ ] **Step 1: Write failing message-dispatch tests**

```python
def test_can_sleep_is_acknowledged_without_changing_display():
    calls = []
    dispatch_power_message(K_IO_MESSAGE_CAN_SYSTEM_SLEEP, 7, calls.append, lambda: calls.append("sleep"), lambda: calls.append("wake"))
    assert calls == [7]


def test_will_sleep_sends_sleep_then_acknowledges():
    calls = []
    dispatch_power_message(K_IO_MESSAGE_SYSTEM_WILL_SLEEP, 9, lambda value: calls.append(("allow", value)), lambda: calls.append("sleep"), lambda: calls.append("wake"))
    assert calls == ["sleep", ("allow", 9)]


def test_has_powered_on_sends_wake_without_acknowledgement():
    calls = []
    dispatch_power_message(K_IO_MESSAGE_SYSTEM_HAS_POWERED_ON, 0, lambda value: calls.append(("allow", value)), lambda: calls.append("sleep"), lambda: calls.append("wake"))
    assert calls == ["wake"]
```

- [ ] **Step 2: Run native monitor tests and verify RED**

Run: `.venv/bin/pytest tests/test_macos_power.py -q`

Expected: collection fails because `codex_clawd_status_macos.macos_power` does not exist.

- [ ] **Step 3: Implement pure dispatch and ctypes registration**

Define the four SDK-confirmed message constants, a pure
`dispatch_power_message`, and `run_power_monitor(on_sleep, on_wake)`. Load
IOKit and CoreFoundation by absolute framework path, define exact `argtypes` and
`restype`, retain the C callback for the run-loop lifetime, register with
`IORegisterForSystemPower`, add the notification source to
`kCFRunLoopCommonModes`, and call `CFRunLoopRun`.

The callback must call `IOAllowPowerChange(root_port, notification_id)` only
for can-sleep and will-sleep. If registration returns zero, return `False`
without invoking callbacks.

- [ ] **Step 4: Run native monitor and full tests, then commit**

Run:

```bash
.venv/bin/pytest tests/test_macos_power.py tests/test_supervisor.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

```bash
git add src/codex_clawd_status_macos/macos_power.py tests/test_macos_power.py
git commit -m "Listen for native macOS power events"
```

### Task 4: Package, Install, and Verify Power Transitions

**Files:**
- Modify: `README.md`
- Modify: `vendor/codex-status-LED/SKILL.md`
- Modify: `docs/releases/v0.3.0.md`

- [ ] **Step 1: Document deterministic power behavior**

Document that sleep forces all-off, wake/restart publishes idle, stale tasks are
not restored, and abrupt host power loss with an independently powered ESP32
still requires a firmware watchdog.

- [ ] **Step 2: Build and run post-build tests**

Run:

```bash
rm -rf build dist
scripts/package-release.sh
(cd dist/release && shasum -a 256 -c codex-clawd-status-macos-arm64.tar.gz.sha256)
codesign --verify --deep --strict dist/payload/runtime/clawd-status
.venv/bin/pytest -q
```

Expected: checksum and signing succeed; all source and archive tests pass.

- [ ] **Step 3: Upgrade the local installation**

Run:

```bash
dist/payload/bin/clawd-status install --payload "$PWD/dist/payload"
zsh -lc 'clawd-status --version'
```

Expected: version `0.3.0`; Hub and watcher online.

- [ ] **Step 4: Verify system-state transitions without sleeping the active Mac**

Post a synthetic working session, then `sleeping`, a lifecycle event during the
override, and `awake`. Require sleeping to clear clients, the racing event to be
`system-masked`, and wake to publish idle with an empty client table.

- [ ] **Step 5: Verify real device delivery when available**

Use synchronous `/send` and require `status=delivered` via BLE or USB serial.
Do not claim hardware completion when the device cannot connect.

- [ ] **Step 6: Run final tests and commit documentation**

Run: `.venv/bin/pytest -q && git diff --check`

```bash
git add README.md vendor/codex-status-LED/SKILL.md docs/releases/v0.3.0.md
git commit -m "Document macOS power lifecycle"
```
