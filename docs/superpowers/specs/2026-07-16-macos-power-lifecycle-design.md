# macOS Power Lifecycle Design

## Summary

The status-light runtime will treat macOS sleep as a system-level display
override above every IDE session. Before non-abortable sleep, the supervisor
will ask the Hub to clear active session state and enqueue `sleeping`/all-off,
then wait briefly for delivery before acknowledging the power notification.
After wake or a fresh Hub start, the runtime will clear old work and enqueue
`idle`; only a new lifecycle event may restore working or waiting.

This is a host-side best-effort guarantee. If the Mac loses power abruptly
while the ESP32 has independent power, only a firmware inactivity watchdog can
guarantee that the device eventually turns off. Firmware changes remain out of
scope because the repository contains no firmware source or flash image.

## Goals

- Make system sleep override waiting, error, working, and every task state.
- Send `sleeping` before macOS powers down hardware when time permits.
- Clear pre-sleep sessions so wake never restores stale work.
- Send `idle` on wake, login, Hub restart, and fresh installation.
- Keep one Hub and one serialized physical delivery queue.
- Preserve the existing wake-gap restart fallback and LaunchAgent supervision.
- Expose the current system power state through `/state`.

## Non-goals

- Preventing macOS from sleeping.
- Treating screen lock or display sleep as full system sleep.
- Restoring a task that was active before sleep.
- Persisting session state across Hub restarts.
- Guaranteeing an all-off command after sudden host power loss.
- Modifying or distributing ESP32 firmware.

## Approaches Considered

### Wake-gap restart only

The current supervisor notices a wall-clock gap after wake, restarts Hub and
watcher, and thereby clears their memory. This recovers processes but cannot
send all-off before sleep and does not immediately reset an independently
powered ESP32 after the new Hub starts.

### Polling `pmset` logs

A helper could repeatedly inspect `pmset -g log`. This depends on text output,
detects events late, and cannot reliably acknowledge the non-abortable sleep
notification. It is rejected.

### Native IOKit notification plus Hub override

Use `IORegisterForSystemPower` from the built-in IOKit framework. A dedicated
supervisor thread receives sleep/wake notifications without PyObjC or another
runtime dependency. The Hub owns display policy and physical queueing. This is
the selected approach.

## Components

### Native power monitor

`src/codex_clawd_status_macos/macos_power.py` will wrap the following built-in
macOS APIs through `ctypes`:

- `IORegisterForSystemPower`;
- `IONotificationPortGetRunLoopSource`;
- `IOAllowPowerChange`;
- `IODeregisterForSystemPower`;
- `IONotificationPortDestroy`;
- `CFRunLoopAddSource` and `CFRunLoopRun`.

It handles these IOKit message values from the local macOS SDK:

| Message | Value | Action |
| --- | --- | --- |
| `kIOMessageCanSystemSleep` | `0xE0000270` | Acknowledge immediately; do not change the light yet. |
| `kIOMessageSystemWillSleep` | `0xE0000280` | Request `sleeping`, wait up to 5 seconds, then acknowledge. |
| `kIOMessageSystemHasPoweredOn` | `0xE0000300` | Request `awake` after hardware wake completes. |
| `kIOMessageSystemWillPowerOn` | `0xE0000320` | Return immediately; hardware may not be usable yet. |

Registration failure disables only native notifications. The existing
supervisor wake-gap restart remains the fallback.

### Supervisor-to-Hub control

The supervisor will call:

```text
POST http://127.0.0.1:8765/system/state
{"state":"sleeping","reason":"system-will-sleep"}

POST http://127.0.0.1:8765/system/state
{"state":"awake","reason":"system-has-powered-on"}
```

For sleep, it polls `/state` for up to 5 seconds and considers the operation
complete when `system_power_state == "sleeping"` and either the sleeping
command was delivered or device delivery has already become impossible. It
never vetoes sleep. `IOAllowPowerChange` is called for both can-sleep and
will-sleep notifications as required by IOKit.

The supervisor also posts `sleeping` during graceful SIGTERM shutdown before
stopping its Hub and watcher children. IOKit registration itself does not
provide shutdown or restart notifications, so this remains best effort.

### Hub system override

The Hub adds `set_system_power_state(state, reason)` and accepts only `awake`
or `sleeping`.

On `sleeping`, the Hub will:

1. set `system_power_state` to `sleeping` and enable the hard override;
2. clear the arbiter registry, client table, and hook table;
3. reset the last aggregate fingerprint;
4. enqueue one system delivery with semantic status and animation `sleeping`;
5. mask later lifecycle events until wake.

On `awake`, the Hub will:

1. clear any events accumulated behind the sleeping override;
2. set `system_power_state` to `awake` and remove the override;
3. reset the arbiter registry, client table, hook table, and fingerprint;
4. enqueue one system delivery with semantic status and animation `idle`.

The system delivery uses the existing `LatestDeliveryQueue`; no second BLE or
serial writer is introduced. `/send` remains a manual synchronous diagnostic.

While the override is active, `/enqueue` validates and acknowledges lifecycle
traffic with `display_role: "system-masked"` and `display_changed: false`, but
does not retain it. This prevents events racing with sleep from reappearing on
wake.

## Startup and Wake Behavior

After the HTTP server is created, every new Hub publishes `awake`/`idle` once.
This covers login, reboot, supervisor restart, installer upgrade, and wake-gap
fallback. The startup delivery is asynchronous so Hub readiness is not delayed
by BLE discovery.

On a normal wake, the IOKit callback requests `awake` after hardware has
powered on. The existing wake-gap loop may then restart Hub and watcher; the
replacement Hub publishes the same idempotent idle state.

The watcher starts from current file offsets and does not replay pre-sleep
events. A later fresh IDE event creates a new session entry and drives the
display again.

## State Contract

`/state` adds:

```json
{
  "system_power_state": "awake",
  "system_override": false,
  "system_reason": "startup",
  "system_changed_at": 1784175000.0
}
```

During sleep, top-level current display fields describe the system client:

```text
current_client_id = macos-power
current_status = sleeping
current_anim = sleeping
```

After wake, they describe `macos-power` and `idle` until a new task becomes
effective.

## Error Handling

- Invalid system state values return an error without changing Hub state.
- A missing Hub during sleep is tolerated; the monitor acknowledges sleep.
- A failed sleeping delivery is recorded but does not delay sleep beyond the
  five-second budget.
- IOKit load or registration failure leaves wake-gap supervision active.
- Wake sends idle even if sleep delivery failed, clearing stale display state
  when transport becomes available again.
- Sudden power loss cannot be handled after the fact by host software.

## Testing

Pure power-message tests will verify callback mapping and required
acknowledgements without putting the test Mac to sleep. Supervisor tests will
verify Hub POST payloads, delivery polling, wake callbacks, and graceful
shutdown behavior with local fakes.

Hub tests will verify that sleep clears all sessions, enqueues sleeping, masks
events, and wake enqueues idle without restoring old work. HTTP route tests will
verify validation and state output.

Release verification will rebuild the arm64 self-contained package, reinstall
it locally, invoke the Hub system-state endpoint directly, verify
sleeping/awake transitions in `/state`, and perform a real synchronous ESP32
delivery when the device is available. A real Mac sleep cycle is a final manual
acceptance test because automating host sleep would interrupt the active Codex
task.
