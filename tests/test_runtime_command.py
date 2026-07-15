from pathlib import Path

from codex_clawd_status_macos.runtime_command import role_command


def test_frozen_role_uses_single_cli():
    assert role_command(
        "watch",
        ["--follow-latest"],
        executable=Path("/tmp/clawd-status"),
        frozen=True,
    ) == ["/tmp/clawd-status", "watch", "--follow-latest"]


def test_source_role_uses_module_dispatcher():
    assert role_command(
        "hub",
        ["--transport", "auto"],
        executable=Path("/usr/bin/python3"),
        frozen=False,
    ) == [
        "/usr/bin/python3",
        "-m",
        "codex_clawd_status_macos.cli",
        "hub",
        "--transport",
        "auto",
    ]
