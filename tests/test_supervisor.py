import json

from codex_clawd_status_macos import supervisor
from codex_clawd_status_macos.supervisor import (
    is_wake_gap,
    next_backoff,
    post_system_power_state,
    power_callbacks,
)


def test_detects_wake_gap_after_long_pause():
    assert is_wake_gap(previous=100.0, current=125.1, threshold=20.0)
    assert not is_wake_gap(previous=100.0, current=105.0, threshold=20.0)


def test_backoff_is_bounded():
    assert [next_backoff(i) for i in range(6)] == [1, 2, 4, 8, 16, 30]


def test_post_system_power_state_uses_local_endpoint(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.body).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            captured.setdefault("timeouts", []).append(timeout)
            if isinstance(request, str):
                captured["state_url"] = request
                return Response({"system_power_state": "sleeping"})
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            return Response({"ok": True, "status": "queued"})

    monkeypatch.setattr(
        supervisor.urllib.request,
        "build_opener",
        lambda *_handlers: Opener(),
    )

    assert post_system_power_state("sleeping", "system-will-sleep") is True
    assert captured["url"].endswith("/system/state")
    assert captured["state_url"].endswith("/state")
    assert captured["body"] == {
        "state": "sleeping",
        "reason": "system-will-sleep",
    }
    assert captured["timeouts"][0] == 1.0


def test_power_callbacks_send_sleep_and_wake():
    calls = []
    callbacks = power_callbacks(
        lambda state, reason: calls.append((state, reason)) or True
    )

    assert callbacks.on_sleep() is True
    assert callbacks.on_wake() is True

    assert calls == [
        ("sleeping", "system-will-sleep"),
        ("awake", "system-has-powered-on"),
    ]
