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

Existing settings and unrelated hooks are preserved. The installer safely
migrates the earlier Python/venv CodeBuddy and WorkBuddy hook when present.

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
