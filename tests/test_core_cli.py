"""Unit tests for the carrel umbrella CLI (spec 00-core Acceptance)."""

from __future__ import annotations

import json
import os
import shutil
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
        capture_output=True,
        text=True,
        timeout=60,
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
    proc = _cli(
        "redact",
        str(src),
        "--pattern",
        r"\d{3}-\d{2}-\d{4}",
        "--fail-empty",
        "-o",
        str(tmp_path / "out.txt"),
    )
    assert proc.returncode == 5
    assert "no matches" in proc.stderr


# --- review follow-ups (PR #7) ------------------------------------------------


def _leaf_paths() -> list[list[str]]:
    """Every invocable command path, descending into click groups (tag ls, edit text…)."""
    import click

    from carrel.cli import LazyGroup

    paths: list[list[str]] = []
    ctx = click.Context(cli)
    for name in sorted(COMMANDS):
        cmd = LazyGroup.get_command(cli, ctx, name)
        assert cmd is not None, name
        stack: list[tuple[list[str], click.Command]] = [([name], cmd)]
        while stack:
            path, c = stack.pop()
            if isinstance(c, click.Group):
                stack.extend(([*path, sub], c.commands[sub]) for sub in sorted(c.commands))
            else:
                paths.append(path)
    return paths


@pytest.mark.parametrize("path", _leaf_paths(), ids=" ".join)
def test_json_flag_accepted_on_every_leaf_subcommand(path: list[str]):
    result = CliRunner().invoke(cli, [*path, "--json", "--help"])
    assert result.exit_code == 0, result.output


def test_index_rerun_with_fresh_files_stays_exit_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A missing tool for one file must not turn a no-op re-run into exit 3."""
    from carrel.commands import index as index_mod
    from carrel.core.adapters import MissingDependencyError, _lookup
    from carrel.core.textextract import extract_text as real_extract

    (tmp_path / "a.md").write_text("# a\n")
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    def extract(path, **kw):
        if path.suffix == ".pdf":
            raise MissingDependencyError(_lookup("pdftotext"))
        return real_extract(path, **kw)

    monkeypatch.setattr(index_mod, "extract_text", extract)
    first = CliRunner().invoke(cli, ["--root", str(tmp_path), "index", "--json", str(tmp_path)])
    assert first.exit_code == 0, first.output
    second = CliRunner().invoke(cli, ["--root", str(tmp_path), "index", "--json", str(tmp_path)])
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["skipped"] == 1
    # hook mode never fails, even for the file that needs the missing tool
    hook = CliRunner().invoke(
        cli, ["--root", str(tmp_path), "index", "--json", "--update", str(tmp_path / "scan.pdf")]
    )
    assert hook.exit_code == 0, hook.output


def test_index_records_tool_timeout_per_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from carrel.commands import index as index_mod
    from carrel.core.adapters import ToolTimeoutError
    from carrel.core.textextract import extract_text as real_extract

    for name in ("a.md", "c.md"):
        (tmp_path / name).write_text(f"# {name}\n")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    def extract(path, **kw):
        if path.suffix == ".pdf":
            raise ToolTimeoutError("pdftotext", 120)
        return real_extract(path, **kw)

    monkeypatch.setattr(index_mod, "extract_text", extract)
    result = CliRunner().invoke(cli, ["--root", str(tmp_path), "index", "--json", str(tmp_path)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["indexed"] == 2
    assert [e["kind"] for e in data["errors"]] == ["error"]
    assert "pdftotext" in data["errors"][0]["error"]


def test_adapter_output_that_is_not_utf8_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from carrel.core import adapters

    fake = tmp_path / "pandoc"
    fake.write_bytes(b"#!/bin/sh\nprintf 'pandoc 3.1 \\351\\n'\n")
    fake.chmod(0o755)
    monkeypatch.setattr(
        adapters.shutil, "which", lambda name, *a, **k: str(fake) if name == "pandoc" else None
    )
    assert adapters.version_of("pandoc").startswith("pandoc 3.1")
    proc = adapters.run("pandoc", "--version")
    assert "\ufffd" in proc.stdout


# --- spec 19: optional extras (D-007) -------------------------------------------


def test_textual_is_an_extra_not_a_core_dependency():
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    core = " ".join(pyproject["project"]["dependencies"])
    assert "textual" not in core
    extras = pyproject["project"]["optional-dependencies"]
    assert set(extras) == {"tui", "office", "tokens", "all"}
    assert any(d.startswith("textual") for d in extras["tui"])
    assert any(d.startswith("openpyxl") for d in extras["office"])
    assert any(d.startswith("tiktoken") for d in extras["tokens"])
    # `all` is the union of the named extras
    union = {d for name in ("tui", "office", "tokens") for d in extras[name]}
    assert set(extras["all"]) == union
    # sdist leaves the (generated) office fixtures out, like the binary ones
    excluded = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]
    for pattern in ("*.docx", "*.odt", "*.epub", "*.xlsx", "*.pdf"):
        assert f"tests/fixtures/{pattern}" in excluded


def test_desk_without_textual_exits_3_with_extra_hint(monkeypatch: pytest.MonkeyPatch):
    """Simulate a plain install (no `tui` extra): hide textual from the import system."""
    for mod in [m for m in sys.modules if m == "carrel.desk.app" or m.startswith("textual")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setitem(sys.modules, "textual", None)  # `import textual` -> ModuleNotFoundError
    result = CliRunner().invoke(cli, ["desk"])
    assert result.exit_code == 3, result.output
    assert "carrel[tui]" in result.output
    assert "uv sync --extra tui" in result.output
    assert "core dep" not in result.output


def test_desk_help_needs_no_textual(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "textual", None)
    result = CliRunner().invoke(cli, ["desk", "--help"])
    assert result.exit_code == 0, result.output


def test_doctor_desk_row_reads_tui_hint(monkeypatch: pytest.MonkeyPatch):
    from carrel.commands import doctor

    assert "carrel[tui]" in doctor.CAPABILITIES["desk"]["note"]
    # with textual absent the row is unavailable and names the extra
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: None)
    rows = {r["command"]: r for r in doctor.build_report()["commands"]}
    assert rows["desk"]["status"] == "unavailable"
    assert rows["desk"]["missing"] == ["textual (carrel[tui])"]
    # and the human table shows it
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "unavailable" in result.output


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_fresh_install_without_extras(tmp_path: Path):
    """`uv pip install .` (no extras): CLI + pack work, desk exits 3 with the tui hint."""
    venv = tmp_path / "venv"
    env = {**os.environ, "UV_NO_PROGRESS": "1"}
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, "--seed", str(venv)],
        check=True,
        capture_output=True,
        env=env,
        timeout=300,
    )
    python = venv / "bin" / "python"
    install = subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    assert install.returncode == 0, install.stderr
    carrel_bin = venv / "bin" / "carrel"
    assert carrel_bin.exists()

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(carrel_bin), *args], capture_output=True, text=True, env=env, timeout=120
        )

    assert run("--help").returncode == 0
    pack = run("pack", str(REPO_ROOT / "tests" / "fixtures"), "--tree-only")
    assert pack.returncode == 0, pack.stderr
    probe = subprocess.run(
        [str(python), "-c", "import textual"], capture_output=True, text=True, timeout=60
    )
    assert probe.returncode != 0, "textual must not be installed without the tui extra"
    desk = run("desk")
    assert desk.returncode == 3, desk.stderr
    assert "carrel[tui]" in desk.stderr
    assert "Traceback" not in desk.stderr


def test_watch_timeout_orphan_check(tmp_path: Path):
    import subprocess as sp
    import time

    marker = tmp_path / "late.out"
    watched = tmp_path / "watched"
    watched.mkdir()
    watcher = sp.Popen(
        [
            sys.executable,
            "-m",
            "carrel.cli",
            "watch",
            str(watched),
            "--once",
            "--on",
            "created",
            "--action-timeout",
            "1",
            "--timeout",
            "10",
            "--json-lines",
            "--run",
            f"sh -c 'sleep 4; touch {marker}'",
        ],
        stdout=sp.PIPE,
        stderr=sp.PIPE,
        text=True,
    )
    time.sleep(1.0)
    (watched / "a.txt").write_text("hi\n")
    out, err = watcher.communicate(timeout=30)
    assert watcher.returncode == 0, err
    assert '"rc": 124' in out, out
    time.sleep(4.5)  # longer than the orphan would have needed
    assert not marker.exists(), "timed-out action kept running after the watcher killed sh"
