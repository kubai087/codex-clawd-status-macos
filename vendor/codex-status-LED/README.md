# Clawd Status Integration

This bundled integration maps Codex, CodeBuddy, and WorkBuddy lifecycle events
to a Clawd/Mochi ESP32 status display.

## Architecture

```text
Codex hooks ────────────────┐
Codex Desktop/VS Code watch ├─► localhost Hub queue ─► BLE / USB serial ─► ESP32
CodeBuddy hooks ────────────┤
WorkBuddy hooks ────────────┘
```

The public Apple silicon installer owns the background LaunchAgent and
self-contained runtime. These source files are bundled for the runtime and the
installed user-level skill; users do not need Python or a virtual environment.

## Platform configuration

- Codex: `~/.codex/hooks.json`
- CodeBuddy: `~/.codebuddy/settings.json`
- WorkBuddy: `~/.workbuddy/settings.json`
- Hub: `http://127.0.0.1:8765`

Normal platform events are submitted to `/enqueue` so ESP32 connection time
cannot block an agent. `/send` remains synchronous for device verification.

## Runtime files

```text
scripts/codex_clawd_hook.py    Codex lifecycle mapping
scripts/buddy_clawd_hook.py    CodeBuddy and WorkBuddy lifecycle mapping
scripts/codex_session_watch.py Codex Desktop and VS Code session watcher
scripts/clawd_status_hub.py    queue, dashboard, and ESP32 transport owner
SKILL.md                       installed maintenance and diagnostic guide
```

Use `clawd-status doctor` and inspect `/state`; process liveness alone is not
proof that the ESP32 received a status.
