# Clawd Status for Apple Silicon

One-command macOS background runtime for the Clawd/Mochi ESP32 status light.
One installation configures Codex, CodeBuddy, and WorkBuddy.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/kubai087/codex-clawd-status-macos/main/install.sh | bash
```

Requirements:

- Apple silicon Mac
- Codex, CodeBuddy, or WorkBuddy
- A Clawd/Mochi ESP32 with compatible status-light firmware

The installer includes its own runtime. Python, Homebrew, and GitHub login are
not required. It verifies the GitHub Release archive checksum before installing.
It does not install the three platform applications or flash ESP32 firmware.

## What it configures

| Platform | Integration |
| --- | --- |
| Codex CLI | Native hooks in `~/.codex/hooks.json` |
| Codex Desktop / VS Code | Supervised session watcher |
| CodeBuddy | Native hooks in `~/.codebuddy/settings.json` |
| WorkBuddy | Native hooks in `~/.workbuddy/settings.json` |

The bundled skill is linked into each platform's user-level skill directory.
All platforms share one LaunchAgent, Hub, self-contained runtime, and ESP32
transport. Uninstalled platforms remain dormant and work when installed later.

## Concurrent tasks

The Hub tracks each IDE session independently and sends only one aggregate
state to the ESP32. A task that completes or sleeps cannot hide another task
that is still working or waiting for confirmation. The display priority is:

```text
waiting > error > working > waiting connection > complete > idle > sleeping
```

Completion holds for three seconds, error holds for ten seconds, and only then
yields to another active session. Codex Desktop and VS Code session logs are
tailed concurrently by the same supervised watcher. BLE and USB writes remain
serialized through one delivery worker.

Connection notifications hold for ten seconds, then transition through idle to
sleeping instead of occupying the display indefinitely.

Existing settings and unrelated hooks are preserved. The installer safely
migrates the earlier Python/venv CodeBuddy and WorkBuddy hook when present.

## Mac sleep, wake, and restart

macOS power state overrides every task priority. Before normal system sleep,
the supervisor clears all task sessions and sends `sleeping` (`leds: 000`). All
non-manual sleeping states use this explicit all-off command even when custom
status effects are disabled.
Task events received during sleep are acknowledged but discarded. After wake,
login, service restart, or Hub restart, the runtime starts from `idle`; it never
restores task state captured before sleep.

When a wake-time `idle` command reaches macOS before Bluetooth is ready, the
delivery worker retries in the background with bounded backoff. A newer task
state supersedes that retry. The last successful CoreBluetooth device address
is cached so healthy wake cycles can reconnect directly without a fresh scan.
If macOS still owns the connection but the ESP32 is no longer advertising, the
Hub retrieves that system-connected peripheral and rebuilds its local GATT
session instead of waiting indefinitely for an advertising packet.

This behavior covers normal macOS sleep and graceful shutdown. If the Mac loses
power abruptly while the ESP32 has an independent power source, the Mac cannot
send a final command. A firmware watchdog that turns the LEDs off after host
heartbeats stop is required for an absolute stale-light guarantee in that case.

## Manage

```bash
clawd-status status
clawd-status doctor
clawd-status restart
clawd-status uninstall
```

Dashboard: <http://127.0.0.1:8765>

## Verification

Installation readiness requires the Hub and Codex watcher to be online. Device
delivery is verified separately through `/state` or a synchronous `/send` test.
BLE is tried first and USB serial is the automatic fallback.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
scripts/package-release.sh
./install.sh --payload "$PWD/dist/payload"
```
