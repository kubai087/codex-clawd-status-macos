import pytest

from codex_clawd_status_macos.cli import main


def test_version_prints_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.3.4"


def test_hook_role_dispatches_to_upstream_mapping(capsys):
    assert main(["hook", "--print-mapping"]) == 0
    assert "apply_patch: typing" in capsys.readouterr().out


def test_buddy_hook_role_dispatches_platform_mapping(capsys):
    assert main(
        ["buddy-hook", "--platform", "codebuddy", "--print-mapping"]
    ) == 0
    assert "PostToolUseFailure: dizzy" in capsys.readouterr().out
