from codex_clawd_status_macos.supervisor import is_wake_gap, next_backoff


def test_detects_wake_gap_after_long_pause():
    assert is_wake_gap(previous=100.0, current=125.1, threshold=20.0)
    assert not is_wake_gap(previous=100.0, current=105.0, threshold=20.0)


def test_backoff_is_bounded():
    assert [next_backoff(i) for i in range(6)] == [1, 2, 4, 8, 16, 30]
