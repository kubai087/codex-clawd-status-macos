from __future__ import annotations

import os
import signal
import subprocess
import time
import urllib.request
from dataclasses import dataclass

from .runtime_command import role_command


def is_wake_gap(previous: float, current: float, threshold: float = 20.0) -> bool:
    return current - previous > threshold


def next_backoff(failures: int) -> int:
    return min(30, 2**failures)


def hub_is_healthy(timeout: float = 1.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8765/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


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
        watcher.stop()
        hub.stop()
    return 0
