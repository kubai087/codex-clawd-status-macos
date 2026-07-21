---
name: codex-clawd-status
description: Use when installing, checking, or debugging the Clawd/Mochi ESP32 status light with Codex, CodeBuddy, or WorkBuddy on an Apple silicon Mac.
---

# Clawd Status for macOS

## Overview

One local runtime connects Codex, CodeBuddy, and WorkBuddy lifecycle events to
one Clawd/Mochi ESP32. Always verify both the platform integration and the
transport result; a running process alone does not prove device delivery.

## Supported Inputs

| Platform | Configuration | Client identity |
| --- | --- | --- |
| Codex CLI | `~/.codex/hooks.json` | `codex-code` |
| Codex Desktop / VS Code | `~/.codex/sessions/**/*.jsonl` watcher | `codex-desktop` / `codex-vscode` |
| CodeBuddy | `~/.codebuddy/settings.json` | `codebuddy` |
| WorkBuddy | `~/.workbuddy/settings.json` | `workbuddy` |

The shared Hub listens only on `http://127.0.0.1:8765`. Normal lifecycle
events use `/enqueue`; the Hub tracks platform sessions independently,
arbitrates one aggregate state, coalesces only physical display updates, and
owns BLE-to-serial fallback. Platform hooks must exit zero and must never wait
for device I/O.

For Codex Desktop, user-blocking actions may appear as the current
`tools.request_permissions` API, legacy escalated `exec_command` calls,
interactive questions, plugin-install or plan-exit confirmation, and explicit
MCP approval/elicitation items. Calls may be direct or nested inside an outer
`exec`. All formats map to `confused` / `waiting`; the matching response or
next lifecycle event resumes the session's normal state. CodeBuddy and
WorkBuddy map native permission events and approval/elicitation notifications
to the same waiting state.

Aggregate priority is `waiting > error > working > waiting_connection >
complete > idle > sleeping`. A completed or sleeping session cannot hide
another session that is still working. Codex Desktop and VS Code session logs
are tailed concurrently by the one supervised watcher.

Completion is conditional: it remains transient while another actionable
session exists, but the final task's `complete` state stays latched green until
new activity, an explicit end for that session, macOS sleep, or Hub restart.
Codex `turn_aborted` deactivates only the aborted session immediately, rather
than leaving its previous working state active until the stale timeout.

## System Power Semantics

macOS sleep is a hard override above aggregate task priority. On a normal
system-will-sleep notification, the Hub clears all sessions and sends
`sleeping` (`leds: 000`). All non-manual sleeping states use this explicit
all-off command even when custom status effects are disabled. While that
override is active, lifecycle events are
acknowledged as `system-masked` and are not retained. Wake, login, supervisor
restart, and Hub restart publish `idle` with an empty client table; do not try
to restore pre-sleep tasks.

`waiting_connection` is transient: it holds for ten seconds, then transitions
to idle and follows the normal idle-to-sleeping timeout. A generic notification
must not occupy the display indefinitely.

Failed wake-time `idle` delivery retries in the background with bounded
backoff, and any newer display state cancels the old retry. The Hub caches the
last successful CoreBluetooth address and keeps a healthy Hub alive across a
wake gap; it restarts the children only when the Hub cannot accept the wake
reset.

An abrupt Mac power loss cannot send a final command. If the ESP32 is powered
independently, only a firmware watchdog that clears the LEDs after host
heartbeats stop can guarantee that stale state is removed.

## Quick Reference

```bash
clawd-status status
clawd-status doctor
clawd-status restart
clawd-status uninstall
```

Inspect live truth:

```bash
curl -fsS http://127.0.0.1:8765/modules
curl -fsS http://127.0.0.1:8765/state
```

Send a synchronous transport test:

```bash
curl -fsS -H 'Content-Type: application/json' \
  -d '{"anim":"thinking","client_id":"manual-check"}' \
  http://127.0.0.1:8765/send
```

Success requires `status=delivered`. In `/state`, check
`transport_status=delivered` and inspect `transport_message`; BLE failure with
successful USB serial fallback is valid.

## Event Semantics

- prompt or model work: `thinking`
- editing: `typing`
- shell/build: `building`
- read/search: `debugger`
- permission or elicitation: `confused`
- tool/stop failure: `dizzy`
- completion while another task is actionable: transient `happy`
- final task completion: latched `happy` until new activity, explicit session
  end, macOS sleep, or Hub restart

## Common Mistakes

- Do not start separate Hubs for different platforms; port 8765 has one owner.
- Do not interpret one session's completion as global completion; inspect the
  `/state` aggregate and client table.
- Do not restore client state after wake; the system power reset is intentional.
- Do not install Python, Homebrew, or a virtual environment; the release is
  self-contained.
- Do not hard-code a USB device path; serial discovery is intentional.
- Do not delete unrelated hook entries or platform settings during repair.
- Do not treat `Hub online` as delivery proof; inspect `/state` and `/modules`.

The installer configures all three platforms even when an application is not
yet installed. Unused integrations remain dormant and activate later.
