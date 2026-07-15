from __future__ import annotations

import platform
from collections.abc import Sequence


def require_supported_platform(
    system: str | None = None,
    machine: str | None = None,
) -> None:
    current_system = system or platform.system()
    current_machine = machine or platform.machine()
    if current_system != "Darwin" or current_machine != "arm64":
        raise RuntimeError("clawd-status requires an Apple silicon Mac")


def main(argv: Sequence[str] | None = None) -> int:
    require_supported_platform()
    return 0
