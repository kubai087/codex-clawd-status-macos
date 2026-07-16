from codex_clawd_status_macos.macos_power import (
    K_IO_MESSAGE_CAN_SYSTEM_SLEEP,
    K_IO_MESSAGE_SYSTEM_HAS_POWERED_ON,
    K_IO_MESSAGE_SYSTEM_WILL_POWER_ON,
    K_IO_MESSAGE_SYSTEM_WILL_SLEEP,
    dispatch_power_message,
)


def test_can_sleep_is_acknowledged_without_changing_display():
    calls = []

    dispatch_power_message(
        K_IO_MESSAGE_CAN_SYSTEM_SLEEP,
        7,
        calls.append,
        lambda: calls.append("sleep"),
        lambda: calls.append("wake"),
    )

    assert calls == [7]


def test_will_sleep_sends_sleep_then_acknowledges():
    calls = []

    dispatch_power_message(
        K_IO_MESSAGE_SYSTEM_WILL_SLEEP,
        9,
        lambda value: calls.append(("allow", value)),
        lambda: calls.append("sleep"),
        lambda: calls.append("wake"),
    )

    assert calls == ["sleep", ("allow", 9)]


def test_will_sleep_is_acknowledged_even_if_sleep_callback_fails():
    calls = []

    def fail_sleep():
        calls.append("sleep")
        raise RuntimeError("failed")

    try:
        dispatch_power_message(
            K_IO_MESSAGE_SYSTEM_WILL_SLEEP,
            11,
            lambda value: calls.append(("allow", value)),
            fail_sleep,
            lambda: calls.append("wake"),
        )
    except RuntimeError:
        pass

    assert calls == ["sleep", ("allow", 11)]


def test_will_power_on_waits_for_completed_wake():
    calls = []

    dispatch_power_message(
        K_IO_MESSAGE_SYSTEM_WILL_POWER_ON,
        0,
        lambda value: calls.append(("allow", value)),
        lambda: calls.append("sleep"),
        lambda: calls.append("wake"),
    )

    assert calls == []


def test_has_powered_on_sends_wake_without_acknowledgement():
    calls = []

    dispatch_power_message(
        K_IO_MESSAGE_SYSTEM_HAS_POWERED_ON,
        0,
        lambda value: calls.append(("allow", value)),
        lambda: calls.append("sleep"),
        lambda: calls.append("wake"),
    )

    assert calls == ["wake"]
