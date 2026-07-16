import json
import shlex
from pathlib import Path

from codex_clawd_status_macos.installer import (
    InstallPaths,
    ensure_cli_path,
    install,
    install_hooks_file,
    remove_cli_path,
    service_ready,
    uninstall,
)


def test_paths_are_user_scoped(tmp_path: Path):
    paths = InstallPaths.for_home(tmp_path)
    assert paths.root == tmp_path / "Library/Application Support/CodexClawdStatus"
    assert paths.launch_agent == (
        tmp_path / "Library/LaunchAgents/com.kubai087.codex-clawd-status.plist"
    )
    assert paths.codex_skill == tmp_path / ".codex/skills/codex-clawd-status"
    assert paths.codebuddy_skill == (
        tmp_path / ".codebuddy/skills/codex-clawd-status"
    )
    assert paths.workbuddy_skill == (
        tmp_path / ".workbuddy/skills/codex-clawd-status"
    )
    assert paths.codex_hooks == tmp_path / ".codex/hooks.json"
    assert paths.codebuddy_settings == tmp_path / ".codebuddy/settings.json"
    assert paths.workbuddy_settings == tmp_path / ".workbuddy/settings.json"
    assert paths.skill_paths() == (
        paths.codex_skill,
        paths.codebuddy_skill,
        paths.workbuddy_skill,
    )


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
    for skill in paths.skill_paths():
        skill.mkdir(parents=True)
        (skill / "previous.txt").write_text("keep", encoding="utf-8")
    for settings in (
        paths.codex_hooks,
        paths.codebuddy_settings,
        paths.workbuddy_settings,
    ):
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            json.dumps(
                {
                    "custom": {"keep": True},
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {"type": "command", "command": "/tmp/other"}
                                ]
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
    payload = _payload(tmp_path)

    result = install(payload, "0.1.0", home=home, manage_service=False)

    assert result["installed"] is True
    assert paths.current.resolve() == paths.root / "releases/0.1.0"
    assert paths.stable_binary.read_text(encoding="utf-8") == "preview-binary"
    for skill in paths.skill_paths():
        assert skill.is_symlink()
        assert (skill / "SKILL.md").read_text(encoding="utf-8") == "status skill"
        backups = list(
            skill.parent.glob("codex-clawd-status.pre-macos-installer.*")
        )
        assert len(backups) == 1

    quoted_binary = shlex.quote(str(paths.stable_binary))
    expected_codex = f"{quoted_binary} hook"
    expected_codebuddy = f"{quoted_binary} buddy-hook --platform codebuddy"
    expected_workbuddy = f"{quoted_binary} buddy-hook --platform workbuddy"
    expected = (
        (paths.codex_hooks, expected_codex),
        (paths.codebuddy_settings, expected_codebuddy),
        (paths.workbuddy_settings, expected_workbuddy),
    )
    for settings, command in expected:
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["custom"] == {"keep": True}
        assert "/tmp/other" in json.dumps(data)
        assert command in json.dumps(data)
        assert len(
            list(
                settings.parent.glob(
                    f"{settings.name}.codex-clawd-status.bak.*"
                )
            )
        ) == 1

    uninstall(home=home, manage_service=False)

    assert not paths.root.exists()
    for skill in paths.skill_paths():
        assert not skill.is_symlink()
        assert (skill / "previous.txt").read_text(encoding="utf-8") == "keep"
    for settings, command in expected:
        text = settings.read_text(encoding="utf-8")
        assert command not in text
        assert "/tmp/other" in text


def test_malformed_workbuddy_settings_abort_without_overwrite(tmp_path: Path):
    home = tmp_path / "home"
    paths = InstallPaths.for_home(home)
    paths.workbuddy_settings.parent.mkdir(parents=True)
    paths.workbuddy_settings.write_text("{not-json", encoding="utf-8")

    try:
        install(_payload(tmp_path), "0.1.0", home=home, manage_service=False)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("malformed WorkBuddy settings must stop installation")

    assert paths.workbuddy_settings.read_text(encoding="utf-8") == "{not-json"


def test_service_ready_requires_online_watcher():
    modules = {
        "hub": {"status": "online"},
        "codex-watcher": {"status": "offline"},
    }
    assert not service_ready(modules)
    modules["codex-watcher"]["status"] = "online"
    assert service_ready(modules)


def test_cli_path_block_is_idempotent_and_removable(tmp_path: Path):
    zprofile = tmp_path / ".zprofile"
    zprofile.write_text("export EXISTING=1\n", encoding="utf-8")

    ensure_cli_path(zprofile)
    first = zprofile.read_text(encoding="utf-8")
    ensure_cli_path(zprofile)

    assert zprofile.read_text(encoding="utf-8") == first
    assert 'export PATH="$HOME/.local/bin:$PATH"' in first

    remove_cli_path(zprofile)
    assert zprofile.read_text(encoding="utf-8") == "export EXISTING=1\n"
