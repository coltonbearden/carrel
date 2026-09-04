"""Tests for `carrel completion` (spec 19-install-ergonomics).

Self-contained: no fixtures, no optional binaries — the minimal (no extras)
test shape runs this file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from carrel._product import PRODUCT
from carrel.cli import cli
from carrel.commands.completion import COMPLETE_VAR, SHELLS, completion_script, install_hint

PROG = PRODUCT["cli"]


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "carrel.cli", *args], capture_output=True, text=True, timeout=60
    )


def test_shells_are_the_documented_three():
    assert SHELLS == ("bash", "zsh", "fish")
    assert COMPLETE_VAR == "_CARREL_COMPLETE"


@pytest.mark.parametrize("shell", SHELLS)
def test_prints_script_with_complete_var(shell: str):
    result = CliRunner().invoke(cli, ["completion", shell])
    assert result.exit_code == 0, result.output
    assert "_CARREL_COMPLETE" in result.output
    assert PROG in result.output  # script targets the real program name
    assert "To enable" not in result.output  # hint only with --install-hint


@pytest.mark.parametrize("shell", SHELLS)
def test_matches_in_process_generator(shell: str):
    """The CLI prints exactly what click's completion class generates."""
    result = CliRunner().invoke(cli, ["completion", shell])
    assert result.output.rstrip("\n") == completion_script(shell).rstrip("\n")


@pytest.mark.parametrize("shell", SHELLS)
def test_json_output(shell: str):
    result = CliRunner().invoke(cli, ["completion", shell, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == {"shell", "script"}
    assert data["shell"] == shell
    assert "_CARREL_COMPLETE" in data["script"]


def test_json_global_flag_position():
    result = CliRunner().invoke(cli, ["--json", "completion", "bash"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["shell"] == "bash"


def test_json_with_install_hint_adds_key():
    result = CliRunner().invoke(cli, ["completion", "zsh", "--json", "--install-hint"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == {"shell", "script", "install_hint"}
    assert data["install_hint"] == install_hint("zsh")
    assert "compinit" in data["install_hint"]


@pytest.mark.parametrize("shell", SHELLS)
def test_install_hint_is_a_trailing_comment_block(shell: str):
    plain = CliRunner().invoke(cli, ["completion", shell]).output.rstrip("\n")
    hinted = CliRunner().invoke(cli, ["completion", shell, "--install-hint"]).output.rstrip("\n")
    assert hinted.startswith(plain)
    tail = hinted[len(plain) :].strip("\n").splitlines()
    assert tail, "no hint appended"
    assert all(line.startswith("#") for line in tail), tail
    assert any(f"{PROG} completion {shell}" in line for line in tail)


def test_hint_text_per_shell():
    assert f'eval "$({PROG} completion bash)"' in install_hint("bash")
    assert "~/.bashrc" in install_hint("bash")
    assert "compinit" in install_hint("zsh") and "~/.zshrc" in install_hint("zsh")
    assert f"~/.config/fish/completions/{PROG}.fish" in install_hint("fish")


def test_unknown_shell_exits_2():
    result = CliRunner().invoke(cli, ["completion", "powershell"])
    assert result.exit_code == 2
    assert "powershell" in result.output


def test_unknown_shell_exits_2_subprocess():
    proc = _cli("completion", "powershell")
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "powershell" in proc.stderr


def test_missing_shell_argument_exits_2():
    assert CliRunner().invoke(cli, ["completion"]).exit_code == 2


def test_shell_name_is_case_insensitive():
    result = CliRunner().invoke(cli, ["completion", "BASH", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["shell"] == "bash"


def test_library_generator_rejects_unknown_shell():
    with pytest.raises(click.BadParameter):
        completion_script("powershell")


def test_generation_never_reinvokes_carrel(monkeypatch: pytest.MonkeyPatch):
    """The script is generated in-process — carrel never spawns itself with
    `_CARREL_COMPLETE=<shell>_source`. (For bash, click's own source() probes
    `bash --version` to warn about bash < 4.4; that is click, not carrel.)"""
    calls: list[list[str]] = []
    real_popen = subprocess.Popen

    class SpyPopen(real_popen):  # every subprocess.* helper funnels through Popen
        def __init__(self, cmd, *a, **k):
            calls.append([str(c) for c in cmd])
            super().__init__(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    for shell in SHELLS:
        assert "_CARREL_COMPLETE" in completion_script(shell)
    for argv in calls:
        joined = " ".join(argv)
        assert PROG not in Path(argv[0]).name, argv
        assert "_CARREL_COMPLETE" not in joined, argv
        assert sys.executable not in joined, argv
    # zsh and fish need no probe at all
    calls.clear()
    completion_script("zsh")
    completion_script("fish")
    assert calls == []


def test_subprocess_entry_point_prints_script():
    proc = _cli("completion", "bash")
    assert proc.returncode == 0, proc.stderr
    assert "_CARREL_COMPLETE=bash_complete" in proc.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_bash_script_parses(tmp_path: Path):
    script = tmp_path / "carrel.bash"
    script.write_text(completion_script("bash"))
    proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_zsh_script_parses(tmp_path: Path):
    script = tmp_path / "carrel.zsh"
    script.write_text(completion_script("zsh"))
    proc = subprocess.run(["zsh", "-n", str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


def test_completion_is_registered_and_doctor_knows_it():
    from carrel.cli import COMMANDS
    from carrel.commands.doctor import CAPABILITIES

    assert COMMANDS["completion"] == "completion"
    assert CAPABILITIES["completion"]["required"] == ()
