# Apple Silicon One-Command Installer Design

Status: Draft for user review

Date: 2026-07-15

Repository: `kubai087/codex-clawd-status-macos`

## Summary

Build a public, one-command installer for the Codex Clawd status-light stack on Apple silicon Macs. A new user should not need a GitHub account, Homebrew, Python, pip, or prior knowledge of Codex hooks. The installer will deploy a self-contained arm64 runtime, the Codex skill, hook configuration, and a macOS LaunchAgent that keeps the Hub and session watcher healthy across login, reboot, and sleep/wake cycles.

The first release will be a headless background service. A signed `.pkg` or menu-bar application may be added later without changing the core runtime contract.

## Goals

- Install from a public GitHub repository with one shell command and no GitHub authentication.
- Support Apple silicon Macs only (`arm64`) in the first version.
- Bundle the runtime and Python dependencies so users do not install Python or Homebrew.
- Install the Codex skill and merge status-light hooks without overwriting unrelated hooks.
- Start automatically at user login and recover from process crashes.
- Recover Hub, watcher, and device transport after macOS wakes from sleep.
- Provide `status`, `doctor`, `restart`, `update`, and `uninstall` commands.
- Produce a clear final result: installed, background service online, and ESP32 delivered or waiting for connection.
- Preserve the upstream MIT license and GFlash copyright notice.

## Non-Goals

- Intel Mac, Windows, or Linux support in the first version.
- Installing or updating Codex Desktop itself.
- Flashing ESP32 firmware or distributing firmware images.
- A menu-bar UI, Dock application, signed `.pkg`, or Mac App Store distribution.
- Editing or removing hooks that are not owned by this package.
- Requiring administrator privileges for the normal install path.

## User Experience

The primary installation command will be:

```bash
curl -fsSL https://raw.githubusercontent.com/kubai087/codex-clawd-status-macos/main/install.sh | bash
```

The installer will:

1. Confirm the host is macOS on `arm64`.
2. Resolve the latest public GitHub Release, unless a version is explicitly pinned.
3. Download the arm64 archive and its SHA-256 manifest.
4. Verify the archive, unpack it into a staging directory, and run a local smoke check.
5. Install the versioned runtime and atomically select it as current.
6. Link the bundled skill into `~/.codex/skills/codex-clawd-status`.
7. Back up and idempotently merge package-owned hooks into `~/.codex/hooks.json`.
8. Install and bootstrap the user LaunchAgent.
9. Verify Hub health, watcher health, and ESP32 transport.
10. Send one test animation when a compatible ESP32 is available.

Expected final output:

```text
Runtime       installed v0.1.0
LaunchAgent   online
Hub           online at http://127.0.0.1:8765
Watcher       following Codex Desktop
ESP32         delivered via USB serial
```

An absent ESP32 is not an installation failure. The installer will report `waiting for connection` and print the exact `clawd-status doctor` command to run after connecting it.

## Distribution Model

Each GitHub Release will contain:

```text
codex-clawd-status-macos-arm64-vX.Y.Z.tar.gz
SHA256SUMS
```

The archive will contain:

```text
bin/clawd-status
share/codex-clawd-status/skill/
share/codex-clawd-status/templates/launchagent.plist
share/codex-clawd-status/LICENSE
share/codex-clawd-status/THIRD_PARTY_NOTICES
manifest.json
```

`bin/clawd-status` will be one self-contained Apple silicon executable built from the Python implementation with PyInstaller. It will expose role-based subcommands instead of shipping independent Python entrypoints:

```text
clawd-status supervise
clawd-status hub
clawd-status watch
clawd-status hook
clawd-status status
clawd-status doctor
clawd-status restart
clawd-status update
clawd-status uninstall
```

The release executable will be ad-hoc signed during the build. Developer ID signing and notarization are deferred until a signed package is justified. The command-line installer must detect and report any execution restriction rather than failing silently.

## Installation Layout

All runtime files are user-owned and require no `sudo`:

```text
~/Library/Application Support/CodexClawdStatus/
  releases/<version>/
  current -> releases/<version>/
  bin/clawd-status -> ../current/bin/clawd-status
  state/

~/Library/LaunchAgents/com.kubai087.codex-clawd-status.plist
~/Library/Logs/CodexClawdStatus/
~/.codex/skills/codex-clawd-status -> <current release skill directory>
~/.local/bin/clawd-status -> <stable runtime launcher>
```

If `~/.local/bin` is not already on `PATH`, the installer will add one marked, idempotent block to `~/.zprofile`. Uninstall will remove only that exact managed block.

The LaunchAgent plist will contain absolute expanded paths; it will not depend on shell expansion, the interactive user's `PATH`, or the current working directory.

## Runtime Architecture

### LaunchAgent

The LaunchAgent runs one headless supervisor with:

- `RunAtLoad = true`
- `KeepAlive = true`
- `ProcessType = Background`
- a restart throttle to prevent crash loops
- stdout and stderr directed to package-owned log files

Only the supervisor is owned directly by `launchd`. This avoids two independent agents racing to start the Hub and watcher.

### Supervisor

The supervisor owns the lifecycle of the Hub and watcher:

1. Acquire a single-instance lock.
2. Ensure the Hub is reachable on `127.0.0.1:8765`.
3. Start the watcher only after Hub health succeeds.
4. Poll process and HTTP health every five seconds.
5. Restart a failed child with bounded exponential backoff.
6. Detect a likely sleep/wake cycle when wall-clock time advances by more than 20 seconds between five-second checks.
7. After wake, wait briefly for macOS device enumeration, recycle transport state, ensure the watcher follows the newest Codex session, and resume health checks.

The supervisor will not continuously send animations. It reconnects transport state after wake and lets the next Codex event control the display.

### Hub

The Hub keeps the existing HTTP contract on `http://127.0.0.1:8765`, including `/health`, `/modules`, `/state`, `/events`, `/hook`, `/send`, scan, connect, and restart endpoints.

If port 8765 is already occupied, the supervisor will inspect `/health` and `/modules`:

- Reuse a compatible Clawd Hub.
- Stop with an actionable error if the port belongs to an unrelated service.

### Watcher

The watcher follows the newest `~/.codex/sessions/**/*.jsonl`, detects Codex Desktop origin, maps session items to animations, and posts them to the Hub. It remains the primary event source for Codex Desktop.

### Native Hooks

Hooks invoke the stable command:

```text
<absolute stable runtime path> hook
```

The hook handler remains non-blocking: device failures are logged but never cause Codex work to fail.

## Hook Configuration Safety

The installer will parse `~/.codex/hooks.json` as JSON and preserve all unknown keys and unrelated hook entries.

- Writes are atomic: write a temporary file, validate it, then rename it.
- A timestamped backup is created before the first mutation.
- Repeated installation produces no duplicate entries.
- Upgrade replaces only entries whose command matches this package's managed command.
- Uninstall removes only managed entries and leaves unrelated hooks intact.
- Malformed JSON causes the hook step to stop with an error; the installer will not replace the user's file with an empty configuration.

## Device and Transport Behavior

Transport remains `auto`, preferring BLE and falling back to ESP32 USB serial.

- USB ports are discovered from device metadata; the installer does not persist a hard-coded `/dev/cu.*` path.
- A disconnected ESP32 changes status to `waiting for connection` rather than crashing the service.
- Wake recovery rescans BLE and serial after macOS has had time to enumerate devices.
- `doctor` reports detected ports, BLE availability, Hub state, watcher state, current Codex session, and the most recent delivery result.
- Installation success and device delivery success are reported separately.

## Updating and Rollback

`clawd-status update` will:

1. Resolve the requested or latest public release.
2. Download and verify it into a staging directory.
3. Install a new version directory without modifying the active version.
4. Run an offline smoke check.
5. Atomically switch the `current` symlink.
6. Restart the LaunchAgent and run live health checks.
7. Roll back the symlink and restart the previous version if health checks fail.

The most recent previous version remains available for rollback. Older versions may be pruned after a successful update.

## Uninstall

`clawd-status uninstall` will:

1. Boot out and remove the LaunchAgent.
2. Stop package-owned Hub, watcher, and supervisor processes.
3. Remove only package-owned hook entries.
4. Remove the skill symlink only when it points into this package.
5. Remove runtime versions and the managed `PATH` block.
6. Preserve logs by default and remove them only with `--purge`.

The command will be idempotent and safe to rerun after a partial installation.

## Error Handling

- Unsupported architecture: stop before writing files.
- Download or checksum failure: leave the active installation unchanged.
- Malformed hooks file: preserve it and stop the hook mutation step.
- LaunchAgent bootstrap failure: retain diagnostics and print the exact `launchctl` failure.
- Hub crash loop: apply backoff and surface the last exit reason.
- Watcher crash: restart it without restarting a healthy Hub.
- Missing Codex session directory: remain online and wait for Codex to create it.
- Missing ESP32: complete installation but report `waiting for connection`.
- BLE failure with working serial: report successful serial delivery.
- Port 8765 conflict with an unrelated service: do not start a Hub and explain the conflict.

## Security and Privacy

- The default install is per-user and does not request `sudo`.
- Downloads use HTTPS from the public `kubai087/codex-clawd-status-macos` repository.
- Release archives are verified with SHA-256 before extraction.
- Archive extraction rejects absolute paths and path traversal entries.
- The runtime listens only on `127.0.0.1`.
- The watcher reads local Codex session files only to map lifecycle items to animation states; it does not upload session content.
- Logs avoid storing full prompt or response bodies.
- The repository includes the upstream MIT license and third-party notices.

## Testing Strategy

### Automated Tests

- Hook merge, upgrade, and uninstall preservation tests.
- Install layout and atomic symlink switch tests using a temporary home directory.
- LaunchAgent plist generation and validation with `plutil`.
- Unsupported architecture and malformed configuration tests.
- Supervisor child restart, backoff, and duplicate-instance tests.
- Simulated wake-gap recovery tests.
- Serial/BLE selection and fallback tests with mocked transports.
- Update rollback tests when post-switch health checks fail.
- Archive traversal and checksum failure tests.

### Apple Silicon Integration Tests

- Install on a clean Apple silicon user account without Homebrew or Python.
- Confirm skill, hooks, LaunchAgent, Hub, and watcher are installed and online.
- Kill Hub and watcher independently and confirm recovery.
- Log out and back in and confirm automatic startup.
- Sleep and wake the Mac and confirm watcher and transport recovery.
- Unplug and replug the ESP32 and confirm rediscovery without a fixed port.
- Run update and rollback between two test releases.
- Run uninstall twice and confirm unrelated Codex hooks remain unchanged.

### Release Gate

A release is publishable only when:

- the archive checksum matches;
- the executable reports `arm64` and passes its offline self-check;
- the installer succeeds in a clean temporary home;
- LaunchAgent, Hub, and watcher health checks pass on Apple silicon;
- device delivery either succeeds or is explicitly reported as waiting for connection;
- update rollback and uninstall tests pass.

## Implementation Boundaries

The first implementation should adapt the existing MIT-licensed Hub, hook mapper, and session watcher rather than rewrite their behavior. Refactoring should focus on exposing one command dispatcher and a headless supervisor while preserving the current Hub HTTP and animation contracts.

The first release is complete when a public user with an Apple silicon Mac can run the one-line installer, open Codex Desktop, and receive status-light updates after login, reboot, and sleep/wake without installing a separate runtime.
