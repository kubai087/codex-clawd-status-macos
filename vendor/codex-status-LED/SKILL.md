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
events use `/enqueue`; the Hub coalesces rapid events and owns BLE-to-serial
fallback. Platform hooks must exit zero and must never wait for device I/O.

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
- completion: `happy`, then `idle`, then `sleeping`

## Common Mistakes

- Do not start separate Hubs for different platforms; port 8765 has one owner.
- Do not install Python, Homebrew, or a virtual environment; the release is
  self-contained.
- Do not hard-code a USB device path; serial discovery is intentional.
- Do not delete unrelated hook entries or platform settings during repair.
- Do not treat `Hub online` as delivery proof; inspect `/state` and `/modules`.

The installer configures all three platforms even when an application is not
yet installed. Unused integrations remain dormant and activate later.
