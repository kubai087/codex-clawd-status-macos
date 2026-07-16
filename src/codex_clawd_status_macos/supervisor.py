from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .runtime_command import role_command


HUB_URL = "http://127.0.0.1:8765"


def is_wake_gap(previous: float, current: float, threshold: float = 20.0) -> bool:
    return current - previous > threshold


def next_backoff(failures: int) -> int:
    return min(30, 2**failures)


def hub_is_healthy(timeout: float = 1.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{HUB_URL}/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def post_system_power_state(
    state: str,
    reason: str,
    *,
    timeout: float = 1.0,
    confirm_timeout: float = 5.0,
) -> bool:
    if state not in {"awake", "sleeping"}:
        return False

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"{HUB_URL}/system/state",
        data=json.dumps({"state": state, "reason": reason}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or not result.get("ok"):
            return False
    except Exception:
        return False

    if state != "sleeping":
        return True

    deadline = time.monotonic() + confirm_timeout
    while True:
        try:
            with opener.open(f"{HUB_URL}/state", timeout=timeout) as response:
                snapshot = json.loads(response.read().decode("utf-8"))
            if snapshot.get("system_power_state") == "sleeping":
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


@dataclass(frozen=True)
class PowerCallbacks:
    sender: Callable[[str, str], bool]

    def on_sleep(self) -> bool:
        return self.sender("sleeping", "system-will-sleep")

    def on_wake(self) -> bool:
        return self.sender("awake", "system-has-powered-on")


def power_callbacks(
    sender: Callable[[str, str], bool] = post_system_power_state,
) -> PowerCallbacks:
    return PowerCallbacks(sender)


def start_power_monitor(callbacks: PowerCallbacks) -> threading.Thread:
    def monitor() -> None:
        from .macos_power import run_power_monitor

        run_power_monitor(callbacks.on_sleep, callbacks.on_wake)

    thread = threading.Thread(
        target=monitor,
        name="clawd-status-power-monitor",
        daemon=True,
    )
    thread.start()
    return thread


@dataclass
class Child:
    role: str
    args: tuple[str, ...]
    process: subprocess.Popen[bytes] | None = None
    failures: int = 0

    def ensure(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.failures = 0
            return
        if self.process is not None:
            time.sleep(next_backoff(self.failures))
            self.failures += 1
        self.process = subprocess.Popen(
            role_command(self.role, self.args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "CLAWD_STATUS_SUPERVISED": "1"},
        )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def run(poll_seconds: float = 5.0, wake_threshold: float = 20.0) -> int:
    hub = Child("hub", ("--transport", "auto"))
    watcher = Child("watch", ("--follow-latest",))
    running = True

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    callbacks = power_callbacks()
    start_power_monitor(callbacks)
    previous = time.time()
    try:
        while running:
            current = time.time()
            woke = is_wake_gap(previous, current, wake_threshold)
            previous = current
            if woke:
                watcher.stop()
                hub.stop()
                time.sleep(2)
            hub.ensure()
            if hub_is_healthy():
                watcher.ensure()
            time.sleep(poll_seconds)
    finally:
        post_system_power_state("sleeping", "supervisor-shutdown")
        watcher.stop()
        hub.stop()
    return 0
