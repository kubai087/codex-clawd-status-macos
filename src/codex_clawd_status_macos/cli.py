from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__

ROLES = {
    "hub": "clawd_status_hub",
    "watch": "codex_session_watch",
    "hook": "codex_clawd_hook",
}


def require_supported_platform(
    system: str | None = None,
    machine: str | None = None,
) -> None:
    current_system = system or platform.system()
    current_machine = machine or platform.machine()
    if current_system != "Darwin" or current_machine != "arm64":
        raise RuntimeError("clawd-status requires an Apple silicon Mac")


def _run_role(role: str, args: list[str]) -> int:
    module = importlib.import_module(ROLES[role])
    previous = sys.argv
    try:
        sys.argv = [role, *args]
        return int(module.main())
    finally:
        sys.argv = previous


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clawd-status")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--payload", type=Path, required=True)
    commands.add_parser("supervise")
    commands.add_parser("status")
    commands.add_parser("doctor")
    commands.add_parser("restart")
    uninstall_parser = commands.add_parser("uninstall")
    uninstall_parser.add_argument("--purge", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    require_supported_platform()
    values = list(argv if argv is not None else sys.argv[1:])
    if values and values[0] in ROLES:
        return _run_role(values[0], values[1:])

    args = _parser().parse_args(values)
    if args.command == "supervise":
        from .supervisor import run

        return run()

    from . import installer

    if args.command == "install":
        result = installer.install(args.payload, __version__)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(installer.status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "doctor":
        return installer.doctor()
    if args.command == "restart":
        return installer.restart()
    if args.command == "uninstall":
        return installer.uninstall(purge=args.purge)
    raise AssertionError(f"unhandled command: {args.command}")
