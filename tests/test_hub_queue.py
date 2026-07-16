import argparse
import threading
import time

from clawd_status_hub import HubState, LatestDeliveryQueue


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

    assert result == {"ok": True, "status": "queued"}
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
