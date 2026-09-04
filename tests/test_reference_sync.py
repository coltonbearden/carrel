"""docs/REFERENCE.md is generated from --help by scripts/sync_reference.py and must not drift."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import click
import pytest

from carrel.cli import COMMANDS, cli

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "sync_reference.py"
REFERENCE = REPO_ROOT / "docs" / "REFERENCE.md"
GROUPS = ("edit", "tag", "note", "sign", "form", "color")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_reference", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "COLUMNS": "37"},  # width must come from the script, not the caller
    )


def _headings(text: str) -> dict[str, int]:
    """Markdown heading title -> level, e.g. {"carrel edit pdf": 3}."""
    return {m.group(2): len(m.group(1)) for m in re.finditer(r"(?m)^(#{1,6}) (.+)$", text)}


def test_check_passes_on_committed_reference():
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_after_edit(tmp_path: Path):
    copy = tmp_path / "REFERENCE.md"
    copy.write_text(REFERENCE.read_text() + "\nhand edit\n")
    result = _run("--check", "--output", str(copy))
    assert result.returncode == 1
    assert "out of date" in result.stderr
    assert copy.read_text().endswith("hand edit\n"), "--check must not write"


def test_check_fails_when_file_missing(tmp_path: Path):
    result = _run("--check", "--output", str(tmp_path / "nope.md"))
    assert result.returncode == 1


def test_write_creates_identical_file(tmp_path: Path):
    target = tmp_path / "REFERENCE.md"
    result = _run("--output", str(target))
    assert result.returncode == 0, result.stderr
    assert target.read_text() == REFERENCE.read_text()


def test_render_is_deterministic():
    module = _load_script()
    assert module.render() == module.render()
    assert module.render() == REFERENCE.read_text()


def test_every_command_has_a_section():
    headings = _headings(REFERENCE.read_text())
    missing = [name for name in COMMANDS if headings.get(f"carrel {name}") != 2]
    assert not missing, f"no `## carrel <cmd>` heading for: {missing}"


@pytest.mark.parametrize("group", GROUPS)
def test_every_subcommand_has_a_subsection(group: str):
    ctx = click.Context(cli, info_name="carrel")
    command = cli.get_command(ctx, group)
    assert isinstance(command, click.Group), f"{group} is expected to be a click group"
    subs = command.list_commands(ctx)
    assert subs, f"{group} has no subcommands"
    headings = _headings(REFERENCE.read_text())
    for sub in subs:
        assert headings.get(f"carrel {group} {sub}") == 3, f"missing ### carrel {group} {sub}"


def test_header_and_exit_codes():
    text = REFERENCE.read_text()
    assert "do not edit" in text.splitlines()[2]
    assert "## Exit codes" in text  # TROUBLESHOOTING links to #exit-codes
    for code in range(6):
        assert re.search(rf"(?m)^\| {code} \| `[A-Z_]+` \|", text), f"exit code {code} row"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text), "generated text must carry no dates"
    assert "Usage: carrel edit pdf" in text, "subcommand usage must show the full command path"
