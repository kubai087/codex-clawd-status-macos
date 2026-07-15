from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


def role_command(
    role: str,
    args: Iterable[str] = (),
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
) -> list[str]:
    exe = executable or Path(sys.executable)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    prefix = (
        [str(exe), role]
        if is_frozen
        else [str(exe), "-m", "codex_clawd_status_macos.cli", role]
    )
    return [*prefix, *list(args)]
