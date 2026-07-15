import plistlib
from pathlib import Path

from codex_clawd_status_macos.launch_agent import render_launch_agent


def test_launch_agent_runs_supervisor_and_keeps_it_alive():
    payload = render_launch_agent(
        executable=Path(
            "/Users/test/Library/Application Support/CodexClawdStatus/bin/clawd-status"
        ),
        stdout_path=Path(
            "/Users/test/Library/Logs/CodexClawdStatus/supervisor.out.log"
        ),
        stderr_path=Path(
            "/Users/test/Library/Logs/CodexClawdStatus/supervisor.err.log"
        ),
    )
    data = plistlib.loads(payload)
    assert data["Label"] == "com.kubai087.codex-clawd-status"
    assert data["ProgramArguments"][-1] == "supervise"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is True
    assert data["ProcessType"] == "Background"


def test_launch_agent_uses_absolute_paths():
    payload = render_launch_agent(
        executable=Path("/tmp/clawd-status"),
        stdout_path=Path("/tmp/supervisor.out.log"),
        stderr_path=Path("/tmp/supervisor.err.log"),
    )
    data = plistlib.loads(payload)
    assert data["ProgramArguments"] == ["/tmp/clawd-status", "supervise"]
    assert data["StandardOutPath"].startswith("/")
    assert data["StandardErrorPath"].startswith("/")
