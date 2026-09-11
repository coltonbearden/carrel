"""D-016 — the command modules share one `handled` and one `root_of`.

Before v0.4.1 the error-to-exit-code decorator was copy-pasted into 25 modules
under ``src/carrel/commands`` and the desk-root resolver into 12, byte for byte.
A change to the exit-code convention in CLAUDE.md had to be made 25 times or it
silently diverged, and `color.py` reached across to import `proof._handled`.
Both now live beside `emit`/`fail` in ``carrel.core.output``.

These tests are a drift gate, not a behaviour test: the rest of the suite proves
the decorator still maps CarrelError onto its exit code. They fail the moment a
new command module grows a private copy.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from carrel.core.output import handled, root_of

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "src" / "carrel" / "commands"
MODULES = sorted(p for p in COMMANDS_DIR.glob("*.py") if p.name != "__init__.py")

#: the private names v0.4.1 consolidated, mapped to their shared replacement
RETIRED = {"_handled": "carrel.core.output.handled", "_root_of": "carrel.core.output.root_of"}


def module_ids() -> list[str]:
    return [p.name for p in MODULES]


def test_the_commands_package_is_not_empty() -> None:
    """Guard the guard: a bad glob would make every other test here vacuous."""
    assert len(MODULES) >= 30, f"only found {len(MODULES)} command modules in {COMMANDS_DIR}"


@pytest.mark.parametrize("path", MODULES, ids=module_ids())
def test_no_command_module_redefines_a_shared_helper(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    clashes = sorted(defined & RETIRED.keys())
    assert not clashes, (
        f"{path.name} defines {', '.join(clashes)} locally; "
        f"import {' / '.join(RETIRED[name] for name in clashes)} instead (D-016)"
    )


@pytest.mark.parametrize("path", MODULES, ids=module_ids())
def test_handled_comes_from_core_output(path: Path) -> None:
    """A module that decorates with @handled must import it from the shared home."""
    source = path.read_text(encoding="utf-8")
    if "@handled" not in source:
        return
    tree = ast.parse(source, filename=str(path))
    sources = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and any(alias.name == "handled" for alias in node.names)
    }
    assert sources == {"carrel.core.output"}, (
        f"{path.name} imports `handled` from {sources or 'nowhere'}; "
        "it belongs to carrel.core.output (D-016)"
    )


def test_every_command_module_that_needs_handled_uses_the_shared_one() -> None:
    """At least the bulk of the CLI is decorated — catches a partial revert."""
    users = [p.name for p in MODULES if "@handled" in p.read_text(encoding="utf-8")]
    assert len(users) >= 25, f"only {len(users)} modules use @handled: {users}"


def test_root_of_resolves_the_context_root(tmp_path: Path) -> None:
    """The moved resolver still reads --root off ctx.obj and falls back to the cwd."""
    assert root_of(SimpleNamespace(obj={"root": str(tmp_path)})) == tmp_path.resolve()
    assert root_of(SimpleNamespace(obj=None)) == Path.cwd().resolve()
    assert root_of(SimpleNamespace(obj={})) == Path.cwd().resolve()


def test_handled_is_transparent_when_nothing_raises() -> None:
    """The decorator preserves the wrapped callable's name, doc and return value."""

    @handled
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    assert add(2, 3) == 5
    assert add.__name__ == "add"
    assert add.__doc__ == "Add two numbers."
