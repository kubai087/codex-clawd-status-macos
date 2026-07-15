import pytest

from codex_clawd_status_macos.cli import require_supported_platform


def test_accepts_apple_silicon():
    require_supported_platform(system="Darwin", machine="arm64")


def test_rejects_non_arm64():
    with pytest.raises(RuntimeError, match="Apple silicon"):
        require_supported_platform(system="Darwin", machine="x86_64")
