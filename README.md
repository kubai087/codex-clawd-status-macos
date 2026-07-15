# Codex Clawd Status for Apple Silicon

One-command macOS background runtime for the Codex Clawd status-light stack.

## Local preview verification

- Platform: Apple silicon, macOS 27.0
- Install: `./install.sh --payload "$PWD/dist/payload"`
- LaunchAgent: online
- Hub: online
- Watcher: online
- ESP32 transport: delivered over BLE, with USB serial fallback verified

The preview does not include public Release automation yet. It validates the
self-contained runtime, managed hooks, LaunchAgent lifecycle, process recovery,
and device transport path.
