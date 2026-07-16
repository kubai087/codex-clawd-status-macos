import argparse
import threading
import time

from clawd_status_hub import HubState, LatestDeliveryQueue


def hub_args():
    return argparse.Namespace(
        ble_name="Claude-Mochi-Tank",
        ble_address=None,
        port=None,
        baud=None,
        transport="auto",
    )


class CaptureQueue:
    def __init__(self):
        self.items = []

    def enqueue(self, delivery):
        self.items.append(delivery)
        return None


def test_queue_returns_before_delivery_finishes():
    release = threading.Event()
    started = threading.Event()

    def deliver(_item):
        started.set()
        release.wait(1)

    queue = LatestDeliveryQueue(deliver)
    before = time.perf_counter()

    queue.enqueue({"anim": "thinking"})

    assert time.perf_counter() - before < 0.1
    assert started.wait(1)
    release.set()


def test_queue_keeps_only_newest_pending_state():
    release = threading.Event()
    started = threading.Event()
    delivered = []

    def deliver(item):
        delivered.append(item["anim"])
        if len(delivered) == 1:
            started.set()
            release.wait(1)

    queue = LatestDeliveryQueue(deliver)
    queue.enqueue({"anim": "building"})
    assert started.wait(1)

    queue.enqueue({"anim": "thinking"})
    queue.enqueue({"anim": "happy"})
    release.set()

    deadline = time.time() + 1
    while delivered != ["building", "happy"] and time.time() < deadline:
        time.sleep(0.01)
    assert delivered == ["building", "happy"]


def test_queue_never_delivers_concurrently():
    lock = threading.Lock()
    first_started = threading.Event()
    release = threading.Event()
    active = 0
    maximum = 0
    delivered = []

    def deliver(item):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        delivered.append(item["anim"])
        if len(delivered) == 1:
            first_started.set()
            release.wait(1)
        with lock:
            active -= 1

    queue = LatestDeliveryQueue(deliver)
    queue.enqueue({"anim": "building"})
    assert first_started.wait(1)
    queue.enqueue({"anim": "happy"})
    release.set()

    deadline = time.time() + 1
    while len(delivered) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert delivered == ["building", "happy"]
    assert maximum == 1


def test_hub_enqueue_marks_platform_queued_without_delivery():
    args = argparse.Namespace(
        ble_name="Claude-Mochi-Tank",
        ble_address=None,
        port=None,
        baud=None,
        transport="auto",
    )
    hub = HubState(args)
    captured = []
    hub.delivery_queue = argparse.Namespace(enqueue=captured.append)

    result = hub.enqueue(
        {
            "source": "workbuddy",
            "client_id": "workbuddy",
            "client_kind": "workbuddy",
            "anim": "confused",
            "event": "PermissionRequest",
            "tool": "Bash",
        }
    )

    assert result == {
        "ok": True,
        "status": "queued",
        "client_key": "workbuddy",
        "display_role": "effective",
        "display_changed": True,
    }
    assert captured[0]["client_id"] == "workbuddy"
    state = hub.snapshot()
    assert state["transport_status"] == "queued"
    assert state["clients"]["workbuddy"]["status"] == "queued"
    assert state["current_event"] == "PermissionRequest"


def test_hub_enqueue_rejects_missing_display_command():
    args = argparse.Namespace(
        ble_name="Claude-Mochi-Tank",
        ble_address=None,
        port=None,
        baud=None,
        transport="auto",
    )
    hub = HubState(args)
    assert hub.enqueue({"client_id": "codebuddy"}) == {
        "ok": False,
        "error": "missing anim or effect",
    }


def test_queue_returns_the_pending_state_it_replaces():
    release = threading.Event()
    started = threading.Event()

    def deliver(_item):
        started.set()
        release.wait(1)

    queue = LatestDeliveryQueue(deliver)
    assert queue.enqueue({"client_id": "in-flight", "anim": "building"}) is None
    assert started.wait(1)
    assert queue.enqueue({"client_id": "old", "anim": "thinking"}) is None

    replaced = queue.enqueue({"client_id": "new", "anim": "happy"})

    assert replaced == {"client_id": "old", "anim": "thinking"}
    release.set()


def test_hub_coalescing_does_not_erase_masked_platform_state():
    class HoldingQueue:
        def __init__(self):
            self.pending = None

        def enqueue(self, delivery):
            replaced = self.pending
            self.pending = delivery
            return replaced

    args = argparse.Namespace(
        ble_name="Claude-Mochi-Tank",
        ble_address=None,
        port=None,
        baud=None,
        transport="auto",
    )
    hub = HubState(args)
    hub.delivery_queue = HoldingQueue()
    hub.enqueue(
        {
            "source": "codebuddy",
            "client_id": "codebuddy",
            "client_kind": "codebuddy",
            "anim": "thinking",
            "event": "UserPromptSubmit",
        }
    )

    hub.enqueue(
        {
            "source": "workbuddy",
            "client_id": "workbuddy",
            "client_kind": "workbuddy",
            "anim": "confused",
            "event": "PermissionRequest",
        }
    )

    state = hub.snapshot()
    assert state["clients"]["codebuddy"]["status"] == "queued"
    assert state["clients"]["codebuddy"]["display_role"] == "masked"
    assert state["hooks"]["codebuddy:UserPromptSubmit"]["status"] == "queued"
    assert state["hooks"]["codebuddy:UserPromptSubmit"]["display_role"] == (
        "masked"
    )
    assert state["clients"]["workbuddy"]["status"] == "queued"
    assert state["clients"]["workbuddy"]["display_role"] == "effective"
    assert any(
        event["status"] == "coalesced" and event["client_id"] == "codebuddy"
        for event in hub.recent_events()
    )


def test_lower_priority_event_is_recorded_without_replacing_effective_work():
    hub = HubState(hub_args())
    queue = CaptureQueue()
    hub.delivery_queue = queue

    first = hub.enqueue(
        {
            "source": "codex",
            "client_id": "codex-desktop",
            "client_kind": "codex",
            "session_id": "A",
            "anim": "thinking",
            "event": "UserPromptSubmit",
        }
    )
    second = hub.enqueue(
        {
            "source": "codebuddy",
            "client_id": "codebuddy",
            "client_kind": "codebuddy",
            "session_id": "B",
            "anim": "happy",
            "event": "Stop",
        }
    )

    assert [item["client_key"] for item in queue.items] == ["codex-desktop:A"]
    assert first["display_changed"] is True
    assert second["display_changed"] is False
    assert second["display_role"] == "masked"
    state = hub.snapshot()
    assert state["aggregate"]["effective_client_key"] == "codex-desktop:A"
    assert state["clients"]["codex-desktop:A"]["semantic_status"] == "working"
    assert state["clients"]["codebuddy:B"]["semantic_status"] == "complete"
    assert state["clients"]["codebuddy:B"]["display_role"] == "masked"


def test_waiting_preempts_working_and_is_the_only_new_physical_command():
    hub = HubState(hub_args())
    queue = CaptureQueue()
    hub.delivery_queue = queue

    hub.enqueue(
        {
            "source": "codex",
            "client_id": "codex-desktop",
            "client_kind": "codex",
            "session_id": "A",
            "anim": "thinking",
        }
    )
    result = hub.enqueue(
        {
            "source": "workbuddy",
            "client_id": "workbuddy",
            "client_kind": "workbuddy",
            "session_id": "C",
            "anim": "confused",
            "event": "PermissionRequest",
        }
    )

    assert [item["client_key"] for item in queue.items] == [
        "codex-desktop:A",
        "workbuddy:C",
    ]
    assert result["display_role"] == "effective"
    assert hub.snapshot()["current_client_key"] == "workbuddy:C"


def test_recompute_after_completion_expiry_restores_working_session():
    now = [0.0]
    hub = HubState(hub_args(), clock=lambda: now[0], start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue

    hub.enqueue(
        {
            "source": "codebuddy",
            "client_id": "codebuddy",
            "client_kind": "codebuddy",
            "session_id": "B",
            "anim": "happy",
        }
    )
    now[0] = 0.1
    hub.enqueue(
        {
            "source": "codex",
            "client_id": "codex-desktop",
            "client_kind": "codex",
            "session_id": "A",
            "anim": "thinking",
        }
    )
    now[0] = 3.01

    changed = hub.recompute_aggregate(now=now[0])

    assert changed is False
    assert hub.snapshot()["aggregate"]["effective_client_key"] == (
        "codex-desktop:A"
    )


def test_system_sleep_clears_sessions_and_enqueues_sleeping():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.enqueue(
        {
            "client_id": "codex-desktop",
            "session_id": "A",
            "anim": "thinking",
        }
    )

    result = hub.set_system_power_state("sleeping", "system-will-sleep")

    state = hub.snapshot()
    assert result["ok"] is True
    assert state["system_power_state"] == "sleeping"
    assert state["system_override"] is True
    assert state["clients"] == {}
    assert queue.items[-1]["anim"] == "sleeping"


def test_lifecycle_event_is_masked_while_sleeping():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.set_system_power_state("sleeping", "test")

    result = hub.enqueue(
        {
            "client_id": "workbuddy",
            "session_id": "B",
            "anim": "confused",
        }
    )

    assert result["display_role"] == "system-masked"
    assert result["display_changed"] is False
    assert hub.snapshot()["clients"] == {}


def test_system_wake_publishes_idle_without_restoring_old_work():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.enqueue(
        {
            "client_id": "codex-desktop",
            "session_id": "A",
            "anim": "thinking",
        }
    )
    hub.set_system_power_state("sleeping", "test")

    hub.set_system_power_state("awake", "system-has-powered-on")

    state = hub.snapshot()
    assert state["system_override"] is False
    assert state["clients"] == {}
    assert state["current_client_id"] == "macos-power"
    assert state["current_status"] == "idle"
    assert queue.items[-1]["anim"] == "idle"


def test_invalid_system_power_state_is_rejected_without_resetting_tasks():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.enqueue(
        {
            "client_id": "codex-desktop",
            "session_id": "A",
            "anim": "thinking",
        }
    )

    result = hub.set_system_power_state("unknown", "test")

    assert result == {
        "ok": False,
        "error": "expected state awake or sleeping",
    }
    assert "codex-desktop:A" in hub.snapshot()["clients"]
    assert [item["anim"] for item in queue.items] == ["thinking"]


def test_system_delivery_does_not_create_a_task_client():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    hub.send_by_transport = lambda _command, transport: (True, transport)
    hub.set_system_power_state("sleeping", "test")

    result = hub.deliver(queue.items[-1])

    assert result["status"] == "delivered"
    assert hub.snapshot()["clients"] == {}


def test_in_flight_task_cannot_restore_state_after_system_sleep():
    hub = HubState(hub_args(), start_scheduler=False)
    queue = CaptureQueue()
    hub.delivery_queue = queue
    started = threading.Event()
    release = threading.Event()

    def delayed_send(_command, transport):
        started.set()
        release.wait(1)
        return True, transport

    hub.send_by_transport = delayed_send
    delivery = {
        "source": "codex",
        "client_id": "codex-desktop",
        "client_kind": "codex",
        "session_id": "A",
        "anim": "thinking",
    }
    thread = threading.Thread(target=hub.deliver, args=(delivery,))
    thread.start()
    assert started.wait(1)

    hub.set_system_power_state("sleeping", "test")
    release.set()
    thread.join(1)

    state = hub.snapshot()
    assert state["clients"] == {}
    assert state["current_status"] == "sleeping"
    assert state["current_client_id"] == "macos-power"
