import json
import shlex
from pathlib import Path

from codex_clawd_status_macos.installer import (
    InstallPaths,
    install,
    install_hooks_file,
    uninstall,
)


def test_paths_are_user_scoped(tmp_path: Path):
    paths = InstallPaths.for_home(tmp_path)
    assert paths.root == tmp_path / "Library/Application Support/CodexClawdStatus"
    assert paths.launch_agent == (
        tmp_path / "Library/LaunchAgents/com.kubai087.codex-clawd-status.plist"
    )
    assert paths.skill == tmp_path / ".codex/skills/codex-clawd-status"


def test_install_hooks_is_idempotent_and_creates_one_backup(tmp_path: Path):
    hooks_path = tmp_path / ".codex/hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(json.dumps({"custom": True}), encoding="utf-8")
    command = "/opt/clawd-status hook"

    install_hooks_file(hooks_path, command)
    first = hooks_path.read_text(encoding="utf-8")
    install_hooks_file(hooks_path, command)

    assert hooks_path.read_text(encoding="utf-8") == first
    assert len(list(hooks_path.parent.glob("hooks.json.codex-clawd-status.bak.*"))) == 1


def test_malformed_hooks_are_preserved(tmp_path: Path):
    hooks_path = tmp_path / ".codex/hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text("{not-json", encoding="utf-8")

    try:
        install_hooks_file(hooks_path, "/opt/clawd-status hook")
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("malformed hooks must stop installation")

    assert hooks_path.read_text(encoding="utf-8") == "{not-json"


def _payload(tmp_path: Path) -> Path:
    payload = tmp_path / "payload"
    binary = payload / "bin/clawd-status"
    binary.parent.mkdir(parents=True)
    binary.write_text("preview-binary", encoding="utf-8")
    binary.chmod(0o755)
    skill = payload / "share/codex-clawd-status/skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("status skill", encoding="utf-8")
    return payload


def test_install_and_uninstall_preserve_previous_skill(tmp_path: Path):
    home = tmp_path / "home"
    paths = InstallPaths.for_home(home)
    paths.skill.mkdir(parents=True)
    (paths.skill / "previous.txt").write_text("keep", encoding="utf-8")
    payload = _payload(tmp_path)

    result = install(payload, "0.1.0", home=home, manage_service=False)

    assert result["installed"] is True
    assert paths.current.resolve() == paths.root / "releases/0.1.0"
    assert paths.stable_binary.read_text(encoding="utf-8") == "preview-binary"
    assert (paths.skill / "SKILL.md").read_text(encoding="utf-8") == "status skill"
    backups = list(paths.skill.parent.glob("codex-clawd-status.pre-macos-installer.*"))
    assert len(backups) == 1
    hooks = json.loads(paths.hooks.read_text(encoding="utf-8"))
    expected_command = f"{shlex.quote(str(paths.stable_binary))} hook"
    assert expected_command in json.dumps(hooks)

    uninstall(home=home, manage_service=False)

    assert not paths.root.exists()
    assert not paths.skill.is_symlink()
    assert (paths.skill / "previous.txt").read_text(encoding="utf-8") == "keep"
    assert expected_command not in paths.hooks.read_text(encoding="utf-8")
