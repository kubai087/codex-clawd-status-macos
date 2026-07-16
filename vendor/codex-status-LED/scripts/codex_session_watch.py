#!/usr/bin/env python3
"""Watch Codex VS Code session JSONL and drive Clawd status animations.

Codex CLI hooks use ~/.codex/hooks.json. Some VS Code-originated Codex sessions
record tool activity in session JSONL without invoking those hooks. This watcher
tails the same local session log and reuses the colocated Clawd hook bridge's
mapping and transport code as a fallback live bridge.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

try:
    import codex_clawd_hook as hook
except ImportError:
    import claude_clawd_hook as hook


CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SESSIONS_DIR = CODEX_HOME / "sessions"
WATCH_PID_PATH = hook.LOG_DIR / "session-watch.pid"
WATCH_RUN_LOCK_PATH = hook.LOG_DIR / "session-watch.run.lock"


@dataclass(frozen=True)
class SessionIdentity:
    client_id: str
    session_id: str


@dataclass
class TrackedSession:
    path: Path
    identity: SessionIdentity
    offset: int
    mtime: float
    last_activity: float
    handle: TextIO | None = None


@dataclass(frozen=True)
class WatchedEvent:
    identity: SessionIdentity
    anim: str
    reason: str


def originator_client_id(originator: str, source: str, fallback: str) -> str:
    text = f"{originator} {source}".lower()
    if "desktop" in text:
        return "codex-desktop"
    if "vscode" in text or "vs code" in text:
        return "codex-vscode"
    return fallback


def session_client_id(path: Path, fallback: str) -> str:
    return session_identity(path, fallback).client_id


def session_identity(path: Path, fallback: str) -> SessionIdentity:
    try:
        first = path.open("r", encoding="utf-8", errors="replace").readline()
        item = json.loads(first)
    except (OSError, json.JSONDecodeError):
        return SessionIdentity(fallback, path.stem)
    if not isinstance(item, dict) or item.get("type") != "session_meta":
        return SessionIdentity(fallback, path.stem)
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return SessionIdentity(
        originator_client_id(
            str(payload.get("originator") or ""),
            str(payload.get("source") or ""),
            fallback,
        ),
        str(payload.get("id") or path.stem),
    )


def path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def recent_session_files(
    root: Path,
    *,
    now: float | None = None,
    horizon: float = 24.0 * 60.0 * 60.0,
) -> list[Path]:
    timestamp = time.time() if now is None else float(now)
    try:
        files = [
            path
            for path in root.rglob("*.jsonl")
            if path.is_file() and path_mtime(path) >= timestamp - horizon
        ]
    except OSError:
        return []
    return sorted(files)


class SessionTracker:
    def __init__(self, *, replay: bool = False, fallback: str = "codex-watch") -> None:
        self.replay = replay
        self.fallback = fallback
        self.sessions: dict[Path, TrackedSession] = {}

    def discover(self, paths: list[Path], *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else float(now)
        self.remove_deleted()
        for path in sorted(set(paths)):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            mtime = path_mtime(path)
            tracked = self.sessions.get(path)
            if tracked is None:
                self.sessions[path] = TrackedSession(
                    path=path,
                    identity=session_identity(path, self.fallback),
                    offset=0 if self.replay else size,
                    mtime=mtime,
                    last_activity=timestamp,
                )
            elif mtime > tracked.mtime:
                tracked.mtime = mtime

    def read_available(self, *, now: float | None = None) -> list[WatchedEvent]:
        timestamp = time.time() if now is None else float(now)
        events: list[WatchedEvent] = []
        for path, tracked in list(sorted(self.sessions.items())):
            if not path.exists():
                self._remove(path)
                continue
            try:
                if tracked.handle is None:
                    tracked.handle = path.open(
                        "r", encoding="utf-8", errors="replace"
                    )
                    tracked.handle.seek(tracked.offset)
                while True:
                    line = tracked.handle.readline()
                    if not line:
                        break
                    tracked.offset = tracked.handle.tell()
                    tracked.last_activity = timestamp
                    tracked.mtime = path_mtime(path)
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    anim, reason = item_to_anim(item)
                    if anim:
                        events.append(WatchedEvent(tracked.identity, anim, reason))
            except OSError:
                self._close(tracked)
        return events

    def close_inactive(self, *, now: float, inactive_seconds: float) -> None:
        for tracked in self.sessions.values():
            if now - tracked.last_activity >= inactive_seconds:
                self._close(tracked)

    def remove_deleted(self) -> None:
        for path in list(self.sessions):
            if not path.exists():
                self._remove(path)

    def close(self) -> None:
        for tracked in self.sessions.values():
            self._close(tracked)

    def _remove(self, path: Path) -> None:
        tracked = self.sessions.pop(path, None)
        if tracked is not None:
            self._close(tracked)

    @staticmethod
    def _close(tracked: TrackedSession) -> None:
        if tracked.handle is not None:
            try:
                tracked.handle.close()
            except OSError:
                pass
            tracked.handle = None


def latest_session_file() -> Path | None:
    try:
        files = [p for p in SESSIONS_DIR.rglob("*.jsonl") if p.is_file()]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def parse_tool_input(raw: Any) -> object | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def wants_escalated_permission(tool_name: str, tool_input: object | None) -> bool:
    if tool_name not in {"shell_command", "functions.shell_command"}:
        return False
    if not isinstance(tool_input, dict):
        return False
    value = str(tool_input.get("sandbox_permissions") or "")
    return value == "require_escalated"


def item_to_anim(item: dict[str, Any]) -> tuple[str | None, str]:
    item_type = item.get("type")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}

    if item_type == "event_msg":
        event_type = payload.get("type")
        if event_type == "user_message":
            return "thinking", "session user_message"
        if event_type == "agent_message":
            return "thinking", "session agent_message"
        if event_type == "task_complete":
            return hook.TASK_COMPLETE_ANIM, "session task_complete"
        return None, ""

    if item_type != "response_item":
        return None, ""

    payload_type = payload.get("type")
    if payload_type in {"function_call", "custom_tool_call"}:
        name = str(payload.get("name") or "")
        tool_input = parse_tool_input(payload.get("arguments") or payload.get("input"))
        if wants_escalated_permission(name, tool_input):
            return "confused", f"session permission_request tool={name!r}"
        anim = hook.tool_to_anim(name, tool_input)
        return anim, f"session {payload_type} tool={name!r}"

    if payload_type in {"function_call_output", "custom_tool_call_output"}:
        return "thinking", f"session {payload_type}"

    return None, ""


def send_watched_anim(anim: str, reason: str, args: argparse.Namespace) -> None:
    event_time = hook.touch_last_event()
    hook.log(f"watch mapped {reason} anim={anim}")
    payload = {
        "hook_event_name": "SessionWatch",
        "tool_name": reason,
        "session_id": str(getattr(args, "session_id", "")),
    }
    delivery_mode = hook.deliver_anim(
        anim, args, payload=payload, event_time=event_time
    )
    if anim == hook.TASK_COMPLETE_ANIM and delivery_mode == "direct":
        hook.spawn_timed_transition(event_time, args)


def args_for(
    identity: SessionIdentity, args: argparse.Namespace
) -> argparse.Namespace:
    session_args = argparse.Namespace(**vars(args))
    session_args.client_id = identity.client_id
    session_args.source = "codex"
    session_args.client_kind = "codex"
    session_args.session_id = identity.session_id
    return session_args


def follow_file(path: Path, args: argparse.Namespace) -> None:
    identity = session_identity(path, args.client_id)
    session_args = args_for(identity, args)
    hook.log(f"watch following session={path} client_id={session_args.client_id}")
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        if not args.replay:
            fh.seek(0, os.SEEK_END)

        while True:
            line = fh.readline()
            if not line:
                if args.follow_latest or args.session is None:
                    latest = latest_session_file()
                    if latest and latest != path and latest.stat().st_mtime > path.stat().st_mtime:
                        hook.log(f"watch switching session={latest}")
                        return
                time.sleep(args.poll)
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            anim, reason = item_to_anim(item)
            if anim:
                send_watched_anim(anim, reason, session_args)


def watch_sessions(args: argparse.Namespace) -> None:
    tracker = SessionTracker(replay=args.replay, fallback=args.client_id)
    next_scan = 0.0
    try:
        while True:
            now = time.time()
            if args.session:
                tracker.discover([args.session], now=now)
            elif now >= next_scan:
                tracker.discover(
                    recent_session_files(SESSIONS_DIR, now=now),
                    now=now,
                )
                next_scan = now + 1.0

            for watched in tracker.read_available(now=now):
                session_args = args_for(watched.identity, args)
                send_watched_anim(
                    watched.anim,
                    watched.reason,
                    session_args,
                )
            tracker.close_inactive(now=now, inactive_seconds=15.0 * 60.0)
            time.sleep(args.poll)
    finally:
        tracker.close()


def write_pid() -> None:
    try:
        hook.LOG_DIR.mkdir(parents=True, exist_ok=True)
        WATCH_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def acquire_run_lock(path: Path, stale_seconds: float = 30.0) -> bool:
    try:
        hook.LOG_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {time.time():.6f}\n")
        return True
    except FileExistsError:
        try:
            parts = path.read_text(encoding="utf-8", errors="replace").split()
            pid = int(parts[0]) if parts else 0
            if pid and not hook.pid_is_running(pid):
                path.unlink(missing_ok=True)
                return acquire_run_lock(path, stale_seconds)
            if time.time() - path.stat().st_mtime > stale_seconds:
                path.unlink(missing_ok=True)
                return acquire_run_lock(path, stale_seconds)
        except OSError:
            pass
        return False
    except OSError:
        return False


def release_run_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, help="session JSONL to follow; defaults to newest")
    parser.add_argument("--follow-latest", action="store_true", help="switch to newer session files")
    parser.add_argument("--replay", action="store_true", help="process existing lines before tailing")
    parser.add_argument("--poll", type=float, default=0.25)
    parser.add_argument("--transport")
    parser.add_argument("--port")
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--ble-address")
    parser.add_argument("--ble-name", default=None)
    parser.add_argument("--hub-url", default=None)
    parser.add_argument("--no-hub", action="store_true")
    parser.add_argument("--hub-required", action="store_true")
    parser.add_argument("--client-id", default=os.environ.get("CLAWD_TANK_WATCH_CLIENT_ID", "codex-watch"))
    args = parser.parse_args()

    if not acquire_run_lock(WATCH_RUN_LOCK_PATH):
        hook.log("watch start skipped; run lock is active")
        return 0

    try:
        write_pid()
        hook.log("watch started")

        watch_sessions(args)
        return 0
    finally:
        release_run_lock(WATCH_RUN_LOCK_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
