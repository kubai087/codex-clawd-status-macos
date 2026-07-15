# Codex Clawd Status for Apple Silicon

One-command macOS background runtime for the Codex Clawd status-light stack.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/kubai087/codex-clawd-status-macos/main/install.sh | bash
```

Requirements:

- Apple silicon Mac
- Codex Desktop, Codex CLI, or the Codex VS Code extension
- A Clawd/Mochi ESP32 with compatible status-light firmware

The installer includes its own runtime. Python, Homebrew, and GitHub login are
not required. It verifies the Release archive checksum before installing.

## Manage

```bash
clawd-status status
clawd-status doctor
clawd-status restart
clawd-status uninstall
```

## Local preview verification

- Platform: Apple silicon, macOS 27.0
- Install: `./install.sh --payload "$PWD/dist/payload"`
- LaunchAgent: online
- Hub: online
- Watcher: online
- ESP32 transport: delivered over BLE, with USB serial fallback verified

The preview validates the self-contained runtime, managed hooks, LaunchAgent
lifecycle, process recovery, and device transport path.
