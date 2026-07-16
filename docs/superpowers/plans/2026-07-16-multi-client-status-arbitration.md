# Multi-Client Status Arbitration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace global latest-event-wins behavior with per-session status tracking and deterministic aggregate display arbitration for concurrent Codex, CodeBuddy, and WorkBuddy tasks.

**Architecture:** Add a pure `StatusArbiter` module that owns session state, priority, hold, and expiry rules. The Hub updates the arbiter for every lifecycle event and sends only changed effective display decisions through the existing single delivery worker; adapters add session identity, and the Codex watcher tails multiple session files in one process.

**Tech Stack:** Python 3.9+, dataclasses, threading conditions, existing `http.server` Hub, pytest, PyInstaller, macOS LaunchAgent, BLE/USB serial.

---

## File Structure

- Create `vendor/codex-status-LED/scripts/status_arbiter.py`: pure session registry, priority selection, timed transitions, snapshots, and deadlines.
- Create `tests/test_status_arbiter.py`: deterministic arbiter tests with an injected clock.
- Modify `vendor/codex-status-LED/scripts/clawd_status_hub.py`: normalize session identity, apply arbitration, schedule expiry, and expose aggregate diagnostics.
- Modify `tests/test_hub_queue.py`: verify masked events, effective-state delivery, and timer recomputation.
- Modify `vendor/codex-status-LED/scripts/codex_clawd_hook.py`: extract and submit native-hook session identity; leave timed transitions to the Hub.
- Modify `vendor/codex-status-LED/scripts/buddy_clawd_hook.py`: pass CodeBuddy/WorkBuddy session identity through the shared adapter.
- Modify `tests/test_buddy_hook.py`: verify identity extraction and Hub-owned terminal transitions.
- Modify `vendor/codex-status-LED/scripts/codex_session_watch.py`: tail multiple recent session files and preserve independent offsets/identity.
- Create `tests/test_session_watch.py`: verify concurrent files, session metadata, offsets, and malformed-line isolation.
- Modify `packaging/clawd-status.spec`: include the new arbiter module in the self-contained binary.
- Modify `src/codex_clawd_status_macos/__init__.py`, `pyproject.toml`, `README.md`, and `docs/releases/v0.3.0.md`: describe and package version `0.3.0`.

### Task 1: Build the Pure Per-Session Arbiter

**Files:**
- Create: `vendor/codex-status-LED/scripts/status_arbiter.py`
- Create: `tests/test_status_arbiter.py`

- [ ] **Step 1: Write failing priority and session-isolation tests**

```python
from status_arbiter import StatusArbiter


def event(client, session, status, anim):
    return {
        "client_id": client,
        "client_kind": client,
        "session_id": session,
        "status": status,
        "anim": anim,
    }


def test_working_survives_another_sessions_completion():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    decision = arbiter.update(event("codebuddy", "B", "complete", "happy"), now=1)
    assert decision.client_key == "codex-desktop:A"
    assert decision.status == "working"


def test_waiting_preempts_working_and_only_its_session_can_clear_it():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    decision = arbiter.update(event("workbuddy", "C", "waiting", "confused"), now=1)
    assert decision.client_key == "workbuddy:C"
    decision = arbiter.update(event("codebuddy", "B", "complete", "happy"), now=2)
    assert decision.client_key == "workbuddy:C"
    decision = arbiter.update(event("workbuddy", "C", "working", "thinking"), now=3)
    assert decision.status == "working"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_status_arbiter.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'status_arbiter'`.

- [ ] **Step 3: Implement identity, state records, and priority selection**

```python
from dataclasses import asdict, dataclass
import time
from typing import Any, Callable


PRIORITY = {
    "waiting": 50,
    "error": 40,
    "working": 30,
    "waiting_connection": 25,
    "complete": 20,
    "idle": 10,
    "sleeping": 0,
}


def client_key(delivery: dict[str, Any]) -> str:
    client_id = str(delivery.get("client_id") or delivery.get("source") or "manual")
    session_id = str(delivery.get("session_id") or "").strip()
    return f"{client_id}:{session_id}" if session_id else client_id


@dataclass
class ClientState:
    client_key: str
    client_id: str
    client_kind: str
    session_id: str
    source: str
    semantic_status: str
    anim: str
    event: str
    tool: str
    updated_at: float
    phase_deadline: float | None
    stale_at: float | None
    display_role: str = "masked"


@dataclass(frozen=True)
class Decision:
    client_key: str | None
    client_id: str | None
    session_id: str | None
    status: str
    anim: str
    delivery: dict[str, Any]


class StatusArbiter:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.clients: dict[str, ClientState] = {}
        self.current_key: str | None = None
        self.hold_until = 0.0

    def update(self, delivery: dict[str, Any], now: float | None = None) -> Decision:
        timestamp = self.clock() if now is None else now
        key = client_key(delivery)
        status = str(delivery.get("status") or "working")
        phase_deadline = timestamp + {"complete": 3.0, "error": 10.0, "idle": 30.0}.get(status, 0.0)
        if status not in {"complete", "error", "idle"}:
            phase_deadline = None
        stale_at = timestamp + {"working": 900.0, "waiting": 1800.0}.get(status, 0.0)
        if status not in {"working", "waiting"}:
            stale_at = None
        self.clients[key] = ClientState(
            client_key=key,
            client_id=str(delivery.get("client_id") or delivery.get("source") or "manual"),
            client_kind=str(delivery.get("client_kind") or delivery.get("source") or "manual"),
            session_id=str(delivery.get("session_id") or ""),
            source=str(delivery.get("source") or "manual"),
            semantic_status=status,
            anim=str(delivery.get("anim") or "idle"),
            event=str(delivery.get("event") or ""),
            tool=str(delivery.get("tool") or ""),
            updated_at=timestamp,
            phase_deadline=phase_deadline,
            stale_at=stale_at,
        )
        return self.evaluate(timestamp)
```

Complete `evaluate`, `next_deadline`, and `snapshot` in the same module. `evaluate`
must advance `complete -> idle`, `error -> idle`, `idle -> sleeping`, and stale
working/waiting entries to sleeping before ranking. It must select by
`(PRIORITY[status], updated_at, client_key)`, retain an equal/lower-priority
current owner until the one-second hold expires, immediately allow a strictly
higher priority, and set every entry's `display_role` to `effective` or
`masked`.

- [ ] **Step 4: Add deterministic expiry and hold tests**

```python
def test_complete_expires_and_reveals_underlying_work():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    arbiter.update(event("codebuddy", "B", "complete", "happy"), now=1)
    assert arbiter.evaluate(now=4.01).client_key == "codex-desktop:A"


def test_error_expires_to_idle_then_sleeping():
    arbiter = StatusArbiter()
    arbiter.update(event("workbuddy", "C", "error", "dizzy"), now=0)
    assert arbiter.evaluate(now=9.9).status == "error"
    assert arbiter.evaluate(now=10.1).status == "idle"
    assert arbiter.evaluate(now=40.2).status == "sleeping"


def test_missing_session_id_keeps_platform_compatibility():
    arbiter = StatusArbiter()
    decision = arbiter.update(event("codebuddy", "", "working", "thinking"), now=0)
    assert decision.client_key == "codebuddy"
```

- [ ] **Step 5: Run arbiter tests and commit**

Run: `.venv/bin/pytest tests/test_status_arbiter.py -q`

Expected: all arbiter tests pass.

```bash
git add vendor/codex-status-LED/scripts/status_arbiter.py tests/test_status_arbiter.py
git commit -m "Track status independently by session"
```

### Task 2: Propagate Session Identity Through Adapters

**Files:**
- Modify: `vendor/codex-status-LED/scripts/codex_clawd_hook.py`
- Modify: `vendor/codex-status-LED/scripts/buddy_clawd_hook.py`
- Modify: `tests/test_buddy_hook.py`

- [ ] **Step 1: Write failing session extraction and request-body tests**

```python
def test_payload_session_id_accepts_supported_platform_fields():
    assert shared.payload_session_id({"session_id": "a"}) == "a"
    assert shared.payload_session_id({"sessionId": "b"}) == "b"
    assert shared.payload_session_id({"conversation_id": "c"}) == "c"
    assert shared.payload_session_id({"threadId": "d"}) == "d"
    assert shared.payload_session_id({"transcript_path": "/tmp/session-e.jsonl"}) == "session-e"


def test_hub_enqueue_includes_session_id(monkeypatch):
    captured = install_fake_urlopen(monkeypatch)
    args = adapter_args(client_id="workbuddy", source="workbuddy")
    shared.send_anim_hub(
        "thinking",
        args,
        payload={"hook_event_name": "UserPromptSubmit", "session_id": "S1"},
    )
    assert captured["session_id"] == "S1"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_buddy_hook.py -q`

Expected: FAIL because `payload_session_id` and the request's `session_id` do not exist.

- [ ] **Step 3: Implement normalized session identity**

```python
SESSION_ID_FIELDS = (
    "session_id",
    "sessionId",
    "conversation_id",
    "conversationId",
    "thread_id",
    "threadId",
)


def payload_session_id(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in SESSION_ID_FIELDS:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    transcript = str(payload.get("transcript_path") or payload.get("transcriptPath") or "").strip()
    return Path(transcript).stem if transcript else ""
```

Add `"session_id": payload_session_id(payload)` to `send_anim_hub`. Keep
`client_id` platform-stable. Do not add another process or direct transport.

- [ ] **Step 4: Make Hub delivery own terminal timers**

Change Codex and buddy hook `Stop` handling so `spawn_timed_transition` runs
only when Hub delivery was not accepted. Preserve the legacy transition in
`--no-hub` mode.

```python
delivered_by_hub = deliver_anim(anim, args, payload=payload, event_time=event_time)
if event == "Stop" and not delivered_by_hub:
    spawn_timed_transition(event_time, args)
```

Refine `deliver_anim` to return whether the Hub accepted the event separately
from direct fallback success, so Hub mode never spawns a global timer.

- [ ] **Step 5: Run adapter tests and commit**

Run: `.venv/bin/pytest tests/test_buddy_hook.py -q`

Expected: all adapter tests pass.

```bash
git add vendor/codex-status-LED/scripts/codex_clawd_hook.py vendor/codex-status-LED/scripts/buddy_clawd_hook.py tests/test_buddy_hook.py
git commit -m "Propagate platform session identity"
```

### Task 3: Integrate Arbitration Into the Hub

**Files:**
- Modify: `vendor/codex-status-LED/scripts/clawd_status_hub.py`
- Modify: `tests/test_hub_queue.py`

- [ ] **Step 1: Write failing masked-state and effective-delivery tests**

```python
def test_lower_priority_event_is_recorded_without_replacing_effective_work():
    hub, queued = hub_with_captured_queue()
    hub.enqueue({"client_id": "codex-desktop", "session_id": "A", "anim": "thinking"})
    hub.enqueue({"client_id": "codebuddy", "session_id": "B", "anim": "happy"})
    assert [item["client_key"] for item in queued] == ["codex-desktop:A"]
    state = hub.snapshot()
    assert state["clients"]["codebuddy:B"]["display_role"] == "masked"
    assert state["aggregate"]["effective_client_key"] == "codex-desktop:A"


def test_waiting_preempts_working_and_is_the_only_new_physical_command():
    hub, queued = hub_with_captured_queue()
    hub.enqueue({"client_id": "codex-desktop", "session_id": "A", "anim": "thinking"})
    hub.enqueue({"client_id": "workbuddy", "session_id": "C", "anim": "confused"})
    assert [item["client_key"] for item in queued] == ["codex-desktop:A", "workbuddy:C"]
```

- [ ] **Step 2: Run Hub tests and verify RED**

Run: `.venv/bin/pytest tests/test_hub_queue.py -q`

Expected: FAIL because Hub clients are still keyed by platform and raw events are queued directly.

- [ ] **Step 3: Add arbiter-owned enqueue flow**

Import `StatusArbiter`, create it in `HubState.__init__`, and replace raw-event
queueing with this sequence:

```python
semantic_status = str(delivery.get("status") or status_for_anim(anim))
normalized = {
    **delivery,
    "status": semantic_status,
    "client_id": client_id,
    "client_kind": client_kind,
    "session_id": str(delivery.get("session_id") or ""),
}
decision = self.arbiter.update(normalized, now=timestamp)
display_changed = self._publish_decision_locked(decision)
client_key = status_arbiter.client_key(normalized)
return {
    "ok": True,
    "status": "queued",
    "client_key": client_key,
    "display_role": self.arbiter.clients[client_key].display_role,
    "display_changed": display_changed,
}
```

`_publish_decision_locked` compares `(client_key, status, anim)` with the last
published fingerprint. Only changes enter `LatestDeliveryQueue`. Queue
replacement may mark a physical event coalesced, but must not mutate the
registry entry to `superseded`.

- [ ] **Step 4: Add an expiry scheduler and diagnostics snapshot**

Start one daemon arbitration thread in `HubState`. It waits on a condition
until `arbiter.next_deadline()`, recomputes, and publishes a changed decision.
Signal the condition after every update. Do not poll continuously.

Expose:

```python
"aggregate": {
    "effective_client_key": decision.client_key,
    "effective_status": decision.status,
    "active_count": counts["active"],
    "waiting_count": counts["waiting"],
    "working_count": counts["working"],
    "error_count": counts["error"],
    "next_deadline": self.arbiter.next_deadline(),
}
```

Keep top-level `current_*` fields describing the effective decision for
backward compatibility.

- [ ] **Step 5: Add timer-driven fallback test**

Use an injected fake clock and an explicit `hub.recompute_aggregate(now=...)`
test seam. Verify a complete state expires and the next working state enters
the captured queue without another platform event.

- [ ] **Step 6: Run Hub and arbiter tests and commit**

Run: `.venv/bin/pytest tests/test_status_arbiter.py tests/test_hub_queue.py -q`

Expected: all tests pass, no concurrent physical deliveries.

```bash
git add vendor/codex-status-LED/scripts/clawd_status_hub.py tests/test_hub_queue.py
git commit -m "Arbitrate aggregate display state"
```

### Task 4: Tail Multiple Codex Sessions in One Watcher

**Files:**
- Modify: `vendor/codex-status-LED/scripts/codex_session_watch.py`
- Create: `tests/test_session_watch.py`

- [ ] **Step 1: Write failing metadata and concurrent-file tests**

```python
def write_session(path, session_id, originator="Codex Desktop", source="vscode"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"id": session_id, "originator": originator, "source": source},
    }) + "\n")


def test_session_identity_includes_meta_id(tmp_path):
    path = tmp_path / "a.jsonl"
    write_session(path, "S1")
    identity = watch.session_identity(path, "codex-watch")
    assert identity.client_id == "codex-desktop"
    assert identity.session_id == "S1"


def test_tracker_reads_appends_from_two_sessions(tmp_path):
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    write_session(first, "A")
    write_session(second, "B", originator="VS Code", source="vscode")
    tracker = watch.SessionTracker(replay=False)
    tracker.discover([first, second])
    append_task_complete(first)
    append_user_message(second)
    events = tracker.read_available()
    assert {(event.identity.session_id, event.anim) for event in events} == {
        ("A", "happy"),
        ("B", "thinking"),
    }
```

- [ ] **Step 2: Run watcher tests and verify RED**

Run: `.venv/bin/pytest tests/test_session_watch.py -q`

Expected: FAIL because `session_identity` and `SessionTracker` do not exist.

- [ ] **Step 3: Implement the multi-file tracker**

Add `SessionIdentity`, `TrackedSession`, and `WatchedEvent` dataclasses. The
tracker stores path, byte offset, identity, last mtime, last activity, and an
optional open handle. First discovery starts at EOF unless replay is enabled.
Reopened files resume at the stored offset. Malformed JSON advances the offset
and affects no other file.

Replace the `follow_file` loop with one loop that:

```python
if now >= next_scan:
    tracker.discover(recent_session_files(SESSIONS_DIR, now, horizon=86400.0))
    next_scan = now + 1.0
for watched in tracker.read_available(now):
    send_watched_anim(watched.anim, watched.reason, args_for(watched.identity, args))
tracker.close_inactive(now, inactive_seconds=900.0)
time.sleep(args.poll)
```

`args_for` must set platform `client_id`, `client_kind="codex"`, and the
session's `session_id` without creating more watcher processes.

- [ ] **Step 4: Test malformed lines, retained offsets, and inactive handles**

Add tests proving one malformed file does not block the other, a closed handle
reopens from its previous offset, and deleting a file removes tracking metadata.

- [ ] **Step 5: Run watcher and adapter tests and commit**

Run: `.venv/bin/pytest tests/test_session_watch.py tests/test_buddy_hook.py -q`

Expected: all tests pass.

```bash
git add vendor/codex-status-LED/scripts/codex_session_watch.py tests/test_session_watch.py
git commit -m "Watch concurrent Codex sessions"
```

### Task 5: Package and Document Version 0.3.0

**Files:**
- Modify: `packaging/clawd-status.spec`
- Modify: `src/codex_clawd_status_macos/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Create: `docs/releases/v0.3.0.md`
- Modify: `tests/test_payload.py`
- Modify: `tests/test_release_archive.py`

- [ ] **Step 1: Write failing payload inclusion and version tests**

```python
def test_payload_contains_status_arbiter(payload):
    assert (payload / "share/codex-clawd-status/skill/scripts/status_arbiter.py").is_file()


def test_package_version_is_0_3_0():
    assert project_version() == "0.3.0"
```

- [ ] **Step 2: Run packaging tests and verify RED**

Run: `.venv/bin/pytest tests/test_payload.py tests/test_release_archive.py tests/test_cli.py -q`

Expected: FAIL because the new module is not packaged and version remains `0.2.0`.

- [ ] **Step 3: Include the module and bump version**

Add `"status_arbiter"` to `packaging/clawd-status.spec` hidden imports. Update
both version declarations to `0.3.0`. Ensure payload assembly copies the new
script alongside the other bundled skill scripts.

- [ ] **Step 4: Document behavior and release notes**

README must state that concurrent IDE sessions are tracked independently,
terminal states cannot sleep over active work, and only aggregate states write
the ESP32. `docs/releases/v0.3.0.md` must list multi-session arbitration,
Codex multi-file watching, timing rules, and unchanged Apple silicon install
command.

- [ ] **Step 5: Run the complete source test suite and commit**

Run: `.venv/bin/pytest -q`

Expected: every source test passes; release-archive-only checks may skip before build.

```bash
git add packaging/clawd-status.spec src/codex_clawd_status_macos/__init__.py pyproject.toml README.md docs/releases/v0.3.0.md tests/test_payload.py tests/test_release_archive.py tests/test_cli.py
git commit -m "Prepare multi-client v0.3.0 package"
```

### Task 6: Build, Upgrade Locally, and Verify Real Arbitration

**Files:**
- Modify only if verification exposes a reproducible defect covered by a new failing test.

- [ ] **Step 1: Build a clean Apple silicon release**

Run:

```bash
rm -rf build dist
scripts/package-release.sh
(cd dist/release && shasum -a 256 -c codex-clawd-status-macos-arm64.tar.gz.sha256)
file dist/payload/runtime/clawd-status
codesign --verify --deep --strict dist/payload/runtime/clawd-status
```

Expected: checksum `OK`, binary reports Mach-O arm64, and code-sign verification exits zero.

- [ ] **Step 2: Run post-build tests**

Run: `.venv/bin/pytest -q`

Expected: every test passes, including release archive inspection.

- [ ] **Step 3: Install the local payload and verify supervision**

Run:

```bash
dist/payload/bin/clawd-status install --payload dist/payload
zsh -lc 'clawd-status --version && clawd-status doctor'
curl -fsS http://127.0.0.1:8765/modules
```

Expected: version `0.3.0`; Hub and watcher online; Codex, CodeBuddy, and
WorkBuddy integrations configured; ESP32 transport available.

- [ ] **Step 4: Submit overlapping sessions and verify aggregate ownership**

Post synthetic events with unique session IDs:

```bash
curl -fsS -H 'Content-Type: application/json' -d '{"source":"codex","client_id":"codex-desktop","client_kind":"codex","session_id":"A","anim":"thinking","event":"UserPromptSubmit"}' http://127.0.0.1:8765/enqueue
curl -fsS -H 'Content-Type: application/json' -d '{"source":"codebuddy","client_id":"codebuddy","client_kind":"codebuddy","session_id":"B","anim":"happy","event":"Stop"}' http://127.0.0.1:8765/enqueue
curl -fsS -H 'Content-Type: application/json' -d '{"source":"workbuddy","client_id":"workbuddy","client_kind":"workbuddy","session_id":"C","anim":"confused","event":"PermissionRequest"}' http://127.0.0.1:8765/enqueue
curl -fsS http://127.0.0.1:8765/state
```

Expected: clients A, B, and C remain separately visible; C is effective and
waiting; B is masked; A remains working. Submit WorkBuddy C `thinking`, wait
past CodeBuddy B's three-second completion deadline, and require A or C to stay
effective as working rather than sleeping.

- [ ] **Step 5: Verify synchronous physical delivery**

Run:

```bash
curl -fsS -H 'Content-Type: application/json' \
  -d '{"anim":"thinking","client_id":"v0.3.0-hardware-check"}' \
  http://127.0.0.1:8765/send
curl -fsS http://127.0.0.1:8765/state
```

Expected: `/send` returns `status=delivered` through BLE or USB serial and
`/state` reports `failed_count == 0`.

- [ ] **Step 6: Review branch state**

Run:

```bash
git status -sb
git log --oneline --decorate -8
```

Expected: clean feature branch with only the planned commits. Do not push or
publish `v0.3.0` until explicitly requested.
