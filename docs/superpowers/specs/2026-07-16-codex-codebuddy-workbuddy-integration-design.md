# Codex, CodeBuddy, and WorkBuddy Integration Design

## Summary

Version 0.2.0 will extend the Apple silicon installer from a Codex-only
integration into one self-contained status-light runtime for Codex, CodeBuddy,
and WorkBuddy. The installer will configure all three integrations on every
supported Mac, whether or not each application is currently installed. An
unused integration remains dormant until its platform starts.

The installer does not install Codex, CodeBuddy, WorkBuddy, or ESP32 firmware.
It installs only the shared background runtime, lifecycle adapters, user-level
skills, configuration entries, and LaunchAgent needed to connect those
platforms to an already-flashed Clawd/Mochi ESP32.

## Goals

- Keep the existing one-command public installation flow.
- Configure Codex, CodeBuddy, and WorkBuddy in one idempotent installation.
- Bundle every adapter and dependency in the release archive.
- Use native lifecycle hooks wherever the platform provides them.
- Keep Codex Desktop and Codex VS Code support through the session watcher.
- Give every platform a distinct client identity in the Hub dashboard.
- Preserve unrelated user hooks, settings, skills, and files.
- Keep lifecycle hooks fast enough that ESP32 delivery cannot delay an agent.
- Migrate the known legacy CodeBuddy/WorkBuddy Python hook commands.
- Remove only installer-managed state during uninstall.

## Non-goals

- Installing or updating Codex, CodeBuddy, or WorkBuddy applications.
- Supporting Claude Code, Cursor, Windsurf, Intel Macs, Windows, or Linux.
- Flashing or distributing ESP32 firmware.
- Reading conversation text for CodeBuddy or WorkBuddy.
- Depending on platform logs when a native hook contract is available.
- Apple notarization, automatic application updates, or a graphical installer.

## Platform Contracts

| Platform | User configuration | User skill | Event source |
| --- | --- | --- | --- |
| Codex CLI | `~/.codex/hooks.json` | `~/.codex/skills/codex-clawd-status` | Native hooks |
| Codex Desktop / VS Code | Same Codex skill | Same Codex skill | `~/.codex/sessions/**/*.jsonl` watcher |
| CodeBuddy | `~/.codebuddy/settings.json` | `~/.codebuddy/skills/codex-clawd-status` | Native CodeBuddy hooks |
| WorkBuddy | `~/.workbuddy/settings.json` | `~/.workbuddy/skills/codex-clawd-status` | Native CodeBuddy-compatible hooks |

CodeBuddy documents user-level hooks in `~/.codebuddy/settings.json` and
user-level skills in `~/.codebuddy/skills/`. Inspection of WorkBuddy 5.2.5 on
macOS shows that it bundles CodeBuddy Code 2.106.4, sets
`CODEBUDDY_CONFIG_DIR` to `~/.workbuddy`, stores session history beneath
`~/.workbuddy/projects`, and supports the same hook event payload. WorkBuddy
therefore receives its own configuration instead of sharing CodeBuddy's file.

## Runtime Architecture

```text
Codex CLI hooks ──────────────┐
Codex Desktop/VS Code watcher ├── POST /enqueue ──► Hook Hub queue
CodeBuddy native hooks ───────┤                         │
WorkBuddy native hooks ───────┘                         ▼
                                              single delivery worker
                                                       │
                                              BLE → USB serial fallback
                                                       │
                                                       ▼
                                                  Clawd ESP32
```

One LaunchAgent continues to supervise one Hub and one Codex session watcher.
CodeBuddy and WorkBuddy do not need additional background processes. Their
native hooks invoke the stable installed binary and submit normalized events to
the existing Hub.

The installed command identities are:

```text
clawd-status hook
clawd-status buddy-hook --platform codebuddy
clawd-status buddy-hook --platform workbuddy
```

`buddy-hook` reuses the existing transport-independent tool mapping while
setting `source`, `client_kind`, and `client_id` to the selected platform. It
does not start another Hub, watcher, Python process, or virtual environment.

## Non-blocking Event Delivery

Native hook commands must not wait for BLE discovery or serial delivery. The
Hub will add `POST /enqueue` for normal lifecycle traffic:

1. Validate and normalize the JSON request.
2. Record the event as queued.
3. Replace the single pending display state with the newest accepted state.
4. Return a successful queued response immediately.
5. Let one background worker deliver states sequentially to the ESP32.

The queue has one in-flight item and one replaceable pending item. This
latest-state-wins behavior prevents rapid `PreToolUse` and `PostToolUse` events
from accumulating behind a slow BLE attempt. Terminal states such as waiting,
failure, completion, and session end naturally remain pending when no newer
event exists.

Codex native hooks, the Codex session watcher, CodeBuddy, and WorkBuddy will all
use `/enqueue`. The dashboard's manual `/send` endpoint remains synchronous so
`doctor` and release verification can prove actual ESP32 delivery.

Each configured hook has a two-second platform timeout, but the adapter is
expected to finish after the local enqueue acknowledgement. It always exits
zero. If the Hub is unavailable, it records a local diagnostic and exits zero;
the hook never blocks or fails the calling agent.

## Lifecycle Mapping

Shared events keep the current Codex semantics:

| Event | Display state |
| --- | --- |
| `SessionStart` | idle |
| `UserPromptSubmit` | thinking |
| `PreToolUse` | tool-specific working animation |
| `PostToolUse` | thinking |
| `PermissionRequest` | confused / waiting |
| `PreCompact` | sweeping |
| `PostCompact` | thinking |
| `SubagentStart` | conducting |
| `SubagentStop` | thinking |
| `Stop` | happy, then idle, then sleeping |

CodeBuddy and WorkBuddy add these events:

| Event | Display state |
| --- | --- |
| `PostToolUseFailure` | dizzy / error |
| `StopFailure` | dizzy / error |
| `SessionEnd` | sleeping |
| `Notification` with `permission_prompt` or `elicitation_dialog` | confused / waiting |
| `Notification` with `idle_prompt` | happy / complete |
| Other `Notification` values | beacon |

Unknown events are ignored and logged without failing the platform.

## Installation Behavior

The default installation always performs the following operations:

1. Install the versioned self-contained release and stable binary links.
2. Install the LaunchAgent and start the shared Hub and Codex watcher.
3. Incrementally merge managed Codex hook entries into
   `~/.codex/hooks.json`.
4. Incrementally merge managed CodeBuddy hook entries into
   `~/.codebuddy/settings.json`.
5. Incrementally merge managed WorkBuddy hook entries into
   `~/.workbuddy/settings.json`.
6. Link the bundled skill into all three user-level skill directories.
7. Wait for the Hub and Codex watcher to become ready.
8. Print machine-readable installation and integration status.

Application detection is diagnostic only. It reports whether the relevant
application or CLI is present, but does not decide whether to write an
integration. This makes a later platform installation work without rerunning
the status-light installer.

All JSON writes are atomic. An existing valid settings file receives one backup
before the first installer-managed change. Invalid JSON stops installation
before that file is overwritten and names the failing path. Repeated installs
produce the same managed entries and do not create duplicate backups.

If an existing skill directory is not the installer-managed symlink, it is
renamed to a timestamped `pre-macos-installer` backup before the shared skill is
linked. All three skill links point to the same versioned release asset.

## Legacy Migration

The installer recognizes the previously deployed commands that invoke:

```text
~/.codebuddy/hooks/codex-status-led/.venv/bin/python
~/.codebuddy/hooks/codex-status-led/scripts/workbuddy_clawd_hook.py
```

Equivalent absolute paths and commands containing the legacy
`workbuddy_clawd_hook.py` marker are managed legacy entries. During install,
they are removed from both CodeBuddy and WorkBuddy hook arrays before the new
stable binary entry is added. Other commands in the same event remain intact.

The legacy `~/.codebuddy/hooks/codex-status-led` directory is not deleted. It
may contain user-modified files, so automatic deletion would exceed the
installer's ownership boundary.

## Uninstall Behavior

Uninstall will:

- stop and remove the LaunchAgent;
- remove only the current and recognized legacy managed hook commands;
- unlink the three installer-managed skills and restore the newest displaced
  skill backup for each platform when one exists;
- remove the CLI link, shell PATH block, and installed runtime;
- preserve unrelated settings, hooks, skills, legacy hook directories, and
  platform applications;
- preserve logs unless `--purge` is requested.

Settings files remain present after managed entries are removed. The uninstaller
does not delete a platform configuration file because another process may have
created or modified it after installation.

## Status and Diagnostics

`clawd-status status` and `clawd-status doctor` will report these integrations
separately:

- `codex-hook`
- `codex-desktop`
- `codex-vscode`
- `codex-watcher`
- `codebuddy-hook`
- `workbuddy-hook`

For each native integration, status distinguishes `configured`, `missing`, and
`delivered`. The Hub client table uses distinct client IDs:

```text
codex-code
codex-desktop
codex-vscode
codebuddy
workbuddy
```

Transport health remains independent from platform configuration. Release
verification must check both that integrations are configured and that
`transport_status` eventually becomes `delivered` with `failed_count == 0`.

## Security and Privacy

- Hook commands receive lifecycle metadata from each platform on standard
  input and submit it only to `127.0.0.1`.
- Mapping reads event name, tool name, notification type, and tool category.
- Prompt text, file contents, credentials, and full tool inputs are not written
  to the Hub state or status-light logs.
- Display failures never change platform permissions or tool decisions.
- Managed command detection uses exact commands and narrow legacy markers so
  unrelated user hooks are preserved.
- The public archive continues to be SHA-256 verified before installation.

## Testing Strategy

Implementation follows test-first development. Automated coverage must prove:

- CodeBuddy and WorkBuddy settings merges preserve unrelated keys and hooks;
- repeated merges are idempotent;
- malformed settings files are preserved and reported;
- legacy Python hook entries are replaced without deleting other hooks;
- uninstall removes only managed entries;
- all three skill links and displaced-skill restoration paths work;
- platform commands use distinct client identities;
- the buddy adapter maps shared and extended events correctly;
- `/enqueue` responds before transport completion;
- rapid events coalesce to the newest pending state;
- the delivery worker serializes ESP32 writes;
- status reports Codex, CodeBuddy, and WorkBuddy independently;
- the release payload contains the buddy adapter and updated skill;
- the public installer remains checksum-verified and idempotent.

## Release Acceptance

Version 0.2.0 is ready to publish only when all of the following are true:

1. The full automated test suite passes from a clean checkout.
2. The release archive contains an arm64 self-contained runtime and passes its
   checksum and signature checks.
3. The public `curl | bash` command upgrades an existing 0.1.0 installation.
4. Codex, CodeBuddy, and WorkBuddy settings each contain exactly one managed
   hook per supported event.
5. Existing unrelated settings and hook commands remain byte-for-byte
   equivalent in meaning.
6. Synthetic official-shaped lifecycle payloads create distinct Hub clients
   for `codex-code`, `codebuddy`, and `workbuddy`.
7. A synchronous manual animation is delivered to the connected ESP32.
8. Hub and watcher recover after forced termination under the LaunchAgent.
9. The repository `main` branch, public release metadata, and local install all
   report version 0.2.0.

## Public Documentation

The README and release notes will state that one command configures Codex,
CodeBuddy, and WorkBuddy. They will also make the boundaries explicit: Apple
silicon only, compatible ESP32 firmware required, platform applications not
included, and no Python, Homebrew, or GitHub login required.

## References

- CodeBuddy Hooks Guide: <https://www.codebuddy.ai/docs/cli/hooks>
- CodeBuddy Skills System: <https://www.codebuddy.ai/docs/cli/skills>
- WorkBuddy macOS installation: <https://www.workbuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Installation-Mac-Guide>
