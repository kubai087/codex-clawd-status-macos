# Multi-Client Status Arbitration Design

## Summary

The status-light runtime will replace global latest-event-wins behavior with a
per-session state registry and a deterministic global arbiter. Codex,
CodeBuddy, and WorkBuddy will still submit lifecycle events to one local Hub,
and the Hub will remain the only process allowed to write to the ESP32. The
difference is that an event will update its own session state first; only the
arbiter's selected aggregate state will enter the physical delivery queue.

This prevents a completed or sleeping task in one IDE from hiding a working or
waiting task in another IDE. It also preserves non-blocking hooks, serialized
BLE/USB writes, and the existing public installer contract.

## Goals

- Track concurrent lifecycle state independently by platform session.
- Show the most actionable aggregate state on the single ESP32 display.
- Never let one session's completion or sleep event hide another active task.
- Continue returning from native hooks before device I/O completes.
- Keep one Hub, one delivery worker, and BLE-to-USB fallback.
- Avoid display flicker when several IDEs emit rapid events.
- Support concurrent Codex Desktop and VS Code session logs in one watcher.
- Keep existing `/enqueue`, `/send`, `/state`, and `/modules` consumers working.
- Expose enough state to explain which session currently owns the display.

## Non-goals

- Showing all task details simultaneously on the three physical LEDs.
- Reading prompt or response content to infer priority.
- Synchronizing state across different Macs.
- Persisting active task state across a Hub restart.
- Adding more Hub processes, per-IDE daemons, or direct hardware writers.
- Changing ESP32 firmware.

## Approaches Considered

### Global latest-state wins

Keep the current one-in-flight plus one-replaceable-pending queue. This is
transport-safe and simple, but a late `Stop` or `SessionEnd` from one IDE can
hide work still running elsewhere. It does not meet the multi-IDE requirement.

### Per-platform state

Keep one state for Codex, one for CodeBuddy, and one for WorkBuddy. This fixes
cross-platform completion races but still collapses multiple windows or tasks
within the same platform. It is an improvement, but it does not model the unit
the user cares about: a running task.

### Per-session state with aggregate arbitration

Keep one state per platform session and select one effective state by explicit
priority, recency, and expiry rules. This is the selected approach because it
handles both cross-platform and same-platform concurrency while retaining one
physical writer.

## Runtime Architecture

```text
Codex native hooks ───────────────┐
Codex multi-session log watcher ──┤
CodeBuddy native hooks ───────────┼── POST /enqueue
WorkBuddy native hooks ───────────┘        │
                                           ▼
                                  per-session registry
                                           │
                                      global arbiter
                                           │
                              effective-state change only
                                           │
                                           ▼
                              latest physical-state queue
                                           │
                                 single delivery worker
                                           │
                                BLE → USB serial fallback
                                           │
                                           ▼
                                       Clawd ESP32
```

Normal lifecycle adapters never write to BLE or serial when the Hub is
required. `/send` remains a synchronous diagnostic endpoint that intentionally
bypasses arbitration.

## Session Identity

Every lifecycle submission will carry these identity fields:

- `client_id`: stable platform sender such as `codex-desktop`, `codex-vscode`,
  `codex-code`, `codebuddy`, or `workbuddy`;
- `client_kind`: platform family such as `codex`, `codebuddy`, or `workbuddy`;
- `session_id`: platform-provided task/session identity when available;
- `client_key`: Hub-derived registry key, formatted as
  `<client_id>:<session_id>` when a session ID exists, otherwise `client_id`.

Native adapters will extract session identity from the first non-empty value
among `session_id`, `sessionId`, `conversation_id`, `conversationId`,
`thread_id`, and `threadId`. A transcript path may supply its filename stem as
a final platform-specific fallback. Missing session identity is valid and
retains the current platform-level behavior.

The Codex watcher will read `session_meta.payload.id` from each JSONL file and
will continue deriving `codex-desktop` versus `codex-vscode` from `originator`
and `source`. It will no longer collapse all files into only the newest session.

## Session State Model

The Hub registry entry for each `client_key` contains:

```text
client_key
client_id
client_kind
session_id
source
semantic_status
anim
event
tool
updated_at
attention_until
stale_at
display_role
delivered_count
failed_count
```

`display_role` is `effective` for the selected entry and `masked` for a valid
entry hidden by a higher-priority session. A masked client is not
`superseded`: its state remains eligible when the current owner clears or
expires.

## Arbitration Policy

The arbiter chooses the highest-ranked eligible session:

| Rank | Semantic state | Behavior |
| --- | --- | --- |
| 50 | `waiting` | Remains effective until that session resumes, ends, or becomes stale. |
| 40 | `error` | Holds attention for 10 seconds, then transitions to idle unless updated. |
| 30 | `working` | Remains eligible while active; stale protection prevents permanent lock. |
| 25 | `waiting_connection` | Shows connection-related attention below task work. |
| 20 | `complete` | Holds for 3 seconds, then transitions to idle. |
| 10 | `idle` | Eligible only when no actionable or active session exists; transitions to sleeping after 30 seconds. |
| 0 | `sleeping` | Eligible only when every known session is inactive or sleeping. |

Within the same rank, the most recently updated session wins. The selected
state has a one-second minimum display hold to reduce flicker, but a strictly
higher-priority state may preempt immediately. Equal- or lower-priority changes
are evaluated when the hold expires.

Working sessions become stale after 15 minutes without an event. Waiting
sessions become stale after 30 minutes. A stale session transitions to
sleeping. These leases are defensive recovery for an IDE crash or missed
terminal event; normal `Stop`, `SessionEnd`, and resumed activity update the
entry before the lease expires.

When a timed state expires, a Hub arbitration clock recomputes the effective
state even if no new platform event arrives. This is required for a completed
task to yield back to another working task after three seconds.

## Lifecycle Semantics

Existing animation mapping remains unchanged. The semantic state is derived
from the animation unless an adapter supplies an explicit state:

- tool activity, prompts, model output, and compaction map to `working`;
- permission or elicitation events map to `waiting`;
- tool or stop failure maps to `error`;
- `Stop` and idle-prompt completion map to `complete`;
- `SessionStart` maps to `idle`;
- `SessionEnd` maps to `sleeping`.

Adapter-side `complete -> idle -> sleeping` timers will not run while the Hub
is in use. The Hub owns these transitions per session. Direct no-Hub diagnostic
mode may retain the legacy timer because it has no multi-client state.

## Queue and Delivery Behavior

The existing `LatestDeliveryQueue` will continue to serialize hardware writes,
but it will receive only aggregate display commands. Raw lifecycle events will
never replace each other in the physical queue before arbitration.

On `/enqueue`, the Hub will:

1. validate and normalize the event;
2. derive `client_key` and update that session's registry entry;
3. recompute the aggregate state;
4. enqueue a physical command only if the effective display fingerprint
   changed;
5. return `{ok: true, status: "queued"}` immediately, with diagnostic fields
   for `client_key`, `display_role`, and `display_changed`.

If a queued aggregate command is replaced by a newer aggregate command, only
the physical command is coalesced. The source session remains represented in
the registry and must not be marked `superseded` merely because it is masked.

## Codex Multi-Session Watcher

The watcher will maintain file offsets for all recently active Codex session
JSONL files instead of tailing only the newest file. It scans the session tree
once per second for files modified within the last 24 hours and reads tracked
files every 250 milliseconds. On each polling cycle it will:

1. discover new or modified JSONL files;
2. initialize a newly discovered file at EOF unless replay was requested;
3. read newly appended complete lines from each tracked file;
4. derive platform and session identity from `session_meta`;
5. submit mapped events using that session identity;
6. close file handles after 15 minutes without a change while retaining their
   last byte offsets, so a later append resumes without losing its first event;
7. remove tracking metadata only when a file is deleted.

One watcher process remains sufficient. It must not start one process per
session.

## State and Diagnostics Contract

Existing top-level state fields remain for compatibility and describe the
effective display owner. The Hub will add:

```json
{
  "aggregate": {
    "effective_client_key": "workbuddy:session-456",
    "effective_status": "waiting",
    "active_count": 3,
    "waiting_count": 1,
    "working_count": 1,
    "error_count": 0,
    "next_deadline": 1784170000.0
  }
}
```

Each `clients` entry exposes `session_id`, `client_key`, `semantic_status`, and
`display_role`. `/events` records whether each event was displayed, masked, or
coalesced. `/modules` continues reporting one Hub, one watcher, and one device.

## Error Handling and Recovery

- A malformed event is rejected without changing the registry.
- A missing session ID falls back to the platform-level client key.
- A Hub restart starts with an empty registry and an idle display; new platform
  events repopulate state.
- A delivery failure increments only the effective client's failure count and
  keeps the aggregate state available for a later retry/update.
- A platform hook still exits zero if enqueue fails, preserving IDE behavior.
- A watcher parse error affects only that line and does not stop other files.
- Stale leases prevent abandoned sessions from owning the display forever.

## Compatibility and Migration

No installer configuration format changes are required. Existing hook commands
continue invoking the same stable binary. Older adapters that omit `session_id`
remain valid and appear as one platform-level session.

The public HTTP routes remain on `127.0.0.1:8765`. `/send` remains synchronous;
`/enqueue` remains non-blocking. Existing consumers of `current_client_id`,
`current_status`, and `clients` continue to receive those fields, with additive
session and aggregate metadata.

## Testing Strategy

Pure arbiter tests will cover:

- waiting preempts error, working, complete, idle, and sleeping;
- error preempts working but expires after 10 seconds;
- working survives another session's completion;
- completion expires after 3 seconds and reveals an underlying working task;
- equal-priority recency and one-second hold behavior;
- session end affects only its own session;
- stale working and waiting sessions release ownership;
- missing session IDs preserve platform-level compatibility.

Hub integration tests will verify that masked events do not write hardware,
aggregate changes remain serialized, queue coalescing does not erase session
state, and timer-driven expiry publishes the next effective state.

Adapter and watcher tests will verify session-ID extraction, composite client
keys, multiple concurrently appended Codex JSONL files, parse-error isolation,
and disabled adapter-side timers when Hub delivery succeeds.

Release verification will run the complete test suite, build the Apple silicon
self-contained package, reinstall it locally, submit overlapping synthetic
Codex/CodeBuddy/WorkBuddy sessions, and require a final synchronous `/send`
delivery to the real ESP32 with `failed_count == 0`.

## Acceptance Scenario

Given these independent session states:

```text
codex-desktop:A   working
codebuddy:B       complete
workbuddy:C       waiting
```

the ESP32 shows `waiting`. When WorkBuddy C resumes and becomes working, the
ESP32 shows `working`. CodeBuddy B's completion expires without sending the
device to sleep. Only after every active session completes, ends, or becomes
stale may the aggregate display become idle or sleeping.
