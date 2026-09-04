"""Unit tests for the carrel umbrella CLI (spec 00-core Acceptance)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from carrel._product import PRODUCT
from carrel.cli import COMMANDS, cli

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cli(*args: str) -> subprocess.CompletedProcess:
    """Drive the real entry point (carrel.cli.main) in a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "carrel.cli", *args],
        capture_output=True, text=True, timeout=60,
    )


def test_version_prints_product_identity():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert PRODUCT["name"] in result.output
    assert PRODUCT["version"] in result.output
    # and it genuinely matches product.json, not a hardcoded copy
    product = json.loads((REPO_ROOT / "product.json").read_text())
    assert product["version"] in result.output
    assert product["name"] in result.output


def test_version_subprocess():
    proc = _cli("--version")
    assert proc.returncode == 0
    assert PRODUCT["version"] in proc.stdout




def test_help_works():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    for flag in ("--json", "--debug", "--root"):
        assert flag in result.output


def test_help_lists_registered_commands():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in COMMANDS:
        assert name in result.output


def test_bad_command_exits_2():
    proc = _cli("badcmd")
    assert proc.returncode == 2
    assert "badcmd" in proc.stderr
    assert proc.stdout == ""


def test_bad_command_cli_runner():
    result = CliRunner().invoke(cli, ["badcmd"])
    assert result.exit_code == 2


def test_bad_flag_exits_2():
    proc = _cli("--no-such-flag")
    assert proc.returncode == 2


# --- every command: --help works, --json accepted after the subcommand -----------

@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_every_command_help(name: str):
    result = CliRunner().invoke(cli, [name, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "--json" in result.output, f"{name}: --json must be accepted after the subcommand"


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_json_flag_after_subcommand_is_accepted(name: str):
    # --help wins before any argument validation, so exit 0 proves the flag parsed
    result = CliRunner().invoke(cli, [name, "--json", "--help"])
    assert result.exit_code == 0, result.output


def test_json_after_subcommand_emits_json(tmp_path: Path):
    (tmp_path / "a.md").write_text("# hi\n")
    proc = _cli("--root", str(tmp_path), "index", "--json", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["indexed"] == 1


def test_watch_json_implies_json_lines(tmp_path: Path):
    proc = _cli("watch", str(tmp_path), "--json", "--timeout", "0.2", "--run", "true")
    assert proc.returncode == 0, proc.stderr


def test_adapter_timeout_is_clean_error(monkeypatch: pytest.MonkeyPatch):
    import subprocess as sp

    from carrel.core import adapters

    def boom(*_a, **kw):
        raise sp.TimeoutExpired(cmd="x", timeout=kw.get("timeout", 0))

    monkeypatch.setattr(adapters.subprocess, "run", boom)
    monkeypatch.setattr(adapters.shutil, "which", lambda *_: "/bin/true")
    with pytest.raises(adapters.ToolTimeoutError) as info:
        adapters.run("pandoc", "--version", timeout=7)
    assert info.value.exit_code == 1
    assert "pandoc" in str(info.value) and "7" in str(info.value)


def test_index_exits_3_when_only_missing_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from carrel.commands import index as index_mod
    from carrel.core.adapters import MissingDependencyError, _lookup

    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    def needs_tool(path, **_kw):
        raise MissingDependencyError(_lookup("pdftotext"))

    monkeypatch.setattr(index_mod, "extract_text", needs_tool)
    result = CliRunner().invoke(cli, ["--root", str(tmp_path), "index", "--json", str(tmp_path)])
    assert result.exit_code == 3, result.output
    assert "missing tool" in result.output or "pdftotext" in result.output


def test_redact_fail_empty_explains(tmp_path: Path):
    src = tmp_path / "plain.txt"
    src.write_text("nothing sensitive here\n")
    proc = _cli("redact", str(src), "--pattern", r"\d{3}-\d{2}-\d{4}", "--fail-empty",
                "-o", str(tmp_path / "out.txt"))
    assert proc.returncode == 5
    assert "no matches" in proc.stderr
