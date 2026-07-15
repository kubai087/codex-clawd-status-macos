from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .hooks_config import merge_hooks, remove_managed_hooks
from .launch_agent import LABEL, render_launch_agent


@dataclass(frozen=True)
class InstallPaths:
    home: Path
    root: Path
    current: Path
    stable_binary: Path
    cli_link: Path
    launch_agent: Path
    logs: Path
    skill: Path
    hooks: Path

    @classmethod
    def for_home(cls, home: Path) -> "InstallPaths":
        root = home / "Library/Application Support/CodexClawdStatus"
        return cls(
            home=home,
            root=root,
            current=root / "current",
            stable_binary=root / "bin/clawd-status",
            cli_link=home / ".local/bin/clawd-status",
            launch_agent=(
                home / "Library/LaunchAgents/com.kubai087.codex-clawd-status.plist"
            ),
            logs=home / "Library/Logs/CodexClawdStatus",
            skill=home / ".codex/skills/codex-clawd-status",
            hooks=home / ".codex/hooks.json",
        )


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install_hooks_file(path: Path, command: str) -> None:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        existing_backups = list(
            path.parent.glob("hooks.json.codex-clawd-status.bak.*")
        )
        if not existing_backups:
            backup = path.with_name(
                f"{path.name}.codex-clawd-status.bak.{int(time.time())}"
            )
            shutil.copy2(path, backup)
    else:
        data = {}
    _atomic_json(path, merge_hooks(data, command))


def _replace_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(link.name + ".new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _stop_legacy_processes(home: Path) -> None:
    for name in ("status-hub.pid", "session-watch.pid", "hub-app.pid"):
        path = home / ".clawd-mochi" / name
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            check=False,
        )
        command = result.stdout
        if "codex-clawd-status" not in command and "CodexClawdStatus" not in command:
            continue
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            continue
        for _ in range(20):
            if subprocess.run(
                ["kill", "-0", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode != 0:
                break
            time.sleep(0.1)


def _service_domain() -> str:
    return f"gui/{os.getuid()}"


def _managed_hook_command(paths: InstallPaths) -> str:
    return f"{shlex.quote(str(paths.stable_binary))} hook"


def install(
    payload: Path,
    version: str,
    *,
    home: Path | None = None,
    manage_service: bool = True,
) -> dict:
    paths = InstallPaths.for_home(home or Path.home())
    payload = payload.resolve()
    payload_binary = payload / "bin/clawd-status"
    payload_skill = payload / "share/codex-clawd-status/skill"
    if not payload_binary.is_file() or not (payload_skill / "SKILL.md").is_file():
        raise RuntimeError("payload is missing runtime or skill assets")

    if manage_service:
        _launchctl(
            "bootout",
            _service_domain(),
            str(paths.launch_agent),
            check=False,
        )
        _stop_legacy_processes(paths.home)

    release = paths.root / "releases" / version
    staging = paths.root / "releases" / f".{version}.staging"
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(payload, staging, symlinks=True)
    if release.exists():
        shutil.rmtree(release)
    os.replace(staging, release)
    _replace_symlink(paths.current, release)
    _replace_symlink(paths.stable_binary, paths.current / "bin/clawd-status")
    _replace_symlink(paths.cli_link, paths.stable_binary)

    paths.skill.parent.mkdir(parents=True, exist_ok=True)
    if paths.skill.is_symlink():
        paths.skill.unlink()
    elif paths.skill.exists():
        backup = paths.skill.with_name(
            f"{paths.skill.name}.pre-macos-installer.{int(time.time())}"
        )
        os.replace(paths.skill, backup)
    paths.skill.symlink_to(paths.current / "share/codex-clawd-status/skill")

    install_hooks_file(paths.hooks, _managed_hook_command(paths))
    paths.logs.mkdir(parents=True, exist_ok=True)
    paths.launch_agent.parent.mkdir(parents=True, exist_ok=True)
    paths.launch_agent.write_bytes(
        render_launch_agent(
            paths.stable_binary,
            paths.logs / "supervisor.out.log",
            paths.logs / "supervisor.err.log",
        )
    )

    if manage_service:
        _launchctl("bootstrap", _service_domain(), str(paths.launch_agent))
        _launchctl("kickstart", "-k", f"{_service_domain()}/{LABEL}")
        _wait_for_service_ready()
    return status(home=paths.home, query_live=manage_service)


def _http_json(path: str, timeout: float = 2.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:8765{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def service_ready(modules: dict) -> bool:
    return (
        modules.get("hub", {}).get("status") == "online"
        and modules.get("codex-watcher", {}).get("status") == "online"
    )


def _wait_for_service_ready(timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if service_ready(_http_json("/modules", timeout=0.5)):
                return
        except Exception:
            pass
        time.sleep(0.25)


def status(*, home: Path | None = None, query_live: bool = True) -> dict:
    paths = InstallPaths.for_home(home or Path.home())
    result: dict = {"installed": paths.current.is_symlink()}
    if not query_live:
        return result
    launch = _launchctl(
        "print",
        f"{_service_domain()}/{LABEL}",
        check=False,
    )
    result["launch_agent"] = "online" if launch.returncode == 0 else "offline"
    try:
        result["modules"] = _http_json("/modules")
        result["state"] = _http_json("/state")
    except Exception as exc:
        result["hub_error"] = str(exc)
    return result


def doctor() -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def restart() -> int:
    _launchctl("kickstart", "-k", f"{_service_domain()}/{LABEL}")
    return 0


def uninstall(
    *,
    home: Path | None = None,
    purge: bool = False,
    manage_service: bool = True,
) -> int:
    paths = InstallPaths.for_home(home or Path.home())
    if manage_service:
        _launchctl(
            "bootout",
            _service_domain(),
            str(paths.launch_agent),
            check=False,
        )
        _stop_legacy_processes(paths.home)

    if paths.hooks.exists():
        data = json.loads(paths.hooks.read_text(encoding="utf-8"))
        _atomic_json(
            paths.hooks,
            remove_managed_hooks(data, _managed_hook_command(paths)),
        )

    if paths.skill.is_symlink():
        paths.skill.unlink()
        backups = sorted(
            paths.skill.parent.glob(
                f"{paths.skill.name}.pre-macos-installer.*"
            )
        )
        if backups:
            os.replace(backups[-1], paths.skill)
    paths.cli_link.unlink(missing_ok=True)
    paths.launch_agent.unlink(missing_ok=True)
    shutil.rmtree(paths.root, ignore_errors=True)
    if purge:
        shutil.rmtree(paths.logs, ignore_errors=True)
    return 0
