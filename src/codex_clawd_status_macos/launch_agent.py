from __future__ import annotations

import plistlib
from pathlib import Path

LABEL = "com.kubai087.codex-clawd-status"


def render_launch_agent(
    executable: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> bytes:
    for path in (executable, stdout_path, stderr_path):
        if not path.is_absolute():
            raise ValueError("LaunchAgent paths must be absolute")
    data = {
        "Label": LABEL,
        "ProgramArguments": [str(executable), "supervise"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
        "EnvironmentVariables": {
            "CLAWD_STATUS_SUPERVISED": "1",
            "CLAWD_TANK_TRANSPORT": "auto",
        },
    }
    return plistlib.dumps(data, sort_keys=True)
