from status_arbiter import StatusArbiter, client_key


def event(
    client: str,
    session: str,
    status: str,
    anim: str,
    *,
    event_name: str = "TestEvent",
) -> dict:
    return {
        "source": client,
        "client_id": client,
        "client_kind": client.split("-", 1)[0],
        "session_id": session,
        "status": status,
        "anim": anim,
        "event": event_name,
        "tool": "",
    }


def test_client_key_uses_session_when_present():
    assert client_key(event("codex-desktop", "A", "working", "thinking")) == (
        "codex-desktop:A"
    )
    assert client_key(event("codebuddy", "", "working", "thinking")) == "codebuddy"


def test_working_survives_another_sessions_completion():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)

    decision = arbiter.update(event("codebuddy", "B", "complete", "happy"), now=1)

    assert decision.client_key == "codex-desktop:A"
    assert decision.status == "working"
    assert arbiter.clients["codebuddy:B"].display_role == "masked"


def test_waiting_preempts_working_and_only_its_session_can_clear_it():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    decision = arbiter.update(
        event("workbuddy", "C", "waiting", "confused"), now=0.1
    )
    assert decision.client_key == "workbuddy:C"

    decision = arbiter.update(event("codebuddy", "B", "complete", "happy"), now=1)
    assert decision.client_key == "workbuddy:C"

    decision = arbiter.update(
        event("workbuddy", "C", "working", "thinking"), now=1.2
    )
    assert decision.status == "working"
    assert decision.client_key == "workbuddy:C"


def test_error_preempts_working_but_waiting_preempts_error():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    decision = arbiter.update(event("codebuddy", "B", "error", "dizzy"), now=0.1)
    assert decision.client_key == "codebuddy:B"
    decision = arbiter.update(
        event("workbuddy", "C", "waiting", "confused"), now=0.2
    )
    assert decision.client_key == "workbuddy:C"


def test_complete_expires_and_reveals_underlying_work():
    arbiter = StatusArbiter()
    arbiter.update(event("codebuddy", "B", "complete", "happy"), now=0)
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0.1)

    assert arbiter.evaluate(now=3.01).client_key == "codex-desktop:A"


def test_error_expires_to_idle_then_sleeping():
    arbiter = StatusArbiter()
    arbiter.update(event("workbuddy", "C", "error", "dizzy"), now=0)

    assert arbiter.evaluate(now=9.9).status == "error"
    assert arbiter.evaluate(now=10.1).status == "idle"
    assert arbiter.evaluate(now=40.2).status == "sleeping"


def test_waiting_connection_expires_to_idle_then_sleeping():
    arbiter = StatusArbiter()
    arbiter.update(event("workbuddy", "", "waiting_connection", "beacon"), now=0)

    assert arbiter.evaluate(now=9.9).status == "waiting_connection"
    assert arbiter.evaluate(now=10.1).status == "idle"
    assert arbiter.evaluate(now=40.2).status == "sleeping"


def test_idle_transitions_to_sleeping_after_thirty_seconds():
    arbiter = StatusArbiter()
    arbiter.update(event("codebuddy", "B", "idle", "idle"), now=5)

    assert arbiter.evaluate(now=34.9).status == "idle"
    assert arbiter.evaluate(now=35.1).status == "sleeping"


def test_stale_working_and_waiting_sessions_release_the_display():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    assert arbiter.evaluate(now=899.9).status == "working"
    assert arbiter.evaluate(now=900.1).status == "sleeping"

    arbiter.update(event("workbuddy", "C", "waiting", "confused"), now=1000)
    assert arbiter.evaluate(now=2799.9).status == "waiting"
    assert arbiter.evaluate(now=2800.1).status == "sleeping"


def test_equal_priority_respects_hold_then_switches_to_more_recent_session():
    arbiter = StatusArbiter(hold_seconds=1.0)
    first = arbiter.update(
        event("codex-desktop", "A", "working", "thinking"), now=0
    )
    assert first.client_key == "codex-desktop:A"

    held = arbiter.update(event("workbuddy", "B", "working", "building"), now=0.5)
    assert held.client_key == "codex-desktop:A"

    switched = arbiter.evaluate(now=1.01)
    assert switched.client_key == "workbuddy:B"


def test_higher_priority_preempts_during_hold():
    arbiter = StatusArbiter(hold_seconds=1.0)
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)

    decision = arbiter.update(
        event("workbuddy", "B", "waiting", "confused"), now=0.1
    )

    assert decision.client_key == "workbuddy:B"


def test_snapshot_reports_effective_and_masked_clients_and_counts():
    arbiter = StatusArbiter()
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=0)
    arbiter.update(event("codebuddy", "B", "complete", "happy"), now=1)
    arbiter.update(event("workbuddy", "C", "waiting", "confused"), now=2)

    snapshot = arbiter.snapshot(now=2)

    assert snapshot["aggregate"]["effective_client_key"] == "workbuddy:C"
    assert snapshot["aggregate"]["effective_status"] == "waiting"
    assert snapshot["aggregate"]["active_count"] == 3
    assert snapshot["aggregate"]["waiting_count"] == 1
    assert snapshot["aggregate"]["working_count"] == 1
    assert snapshot["clients"]["workbuddy:C"]["display_role"] == "effective"
    assert snapshot["clients"]["codex-desktop:A"]["display_role"] == "masked"


def test_next_deadline_includes_hold_phase_and_stale_times():
    arbiter = StatusArbiter(hold_seconds=1.0)
    arbiter.update(event("codex-desktop", "A", "working", "thinking"), now=10)
    assert arbiter.next_deadline(now=10) == 11
    assert arbiter.next_deadline(now=11.1) == 910
