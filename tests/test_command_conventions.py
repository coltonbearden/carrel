"""D-016 — the command modules share one `handled` and one `root_of`.

The error-to-exit-code decorator used to be copy-pasted into 25 modules under
``src/carrel/commands`` and the desk-root resolver into 12, byte for byte, with
four more root resolutions open-coded inline and `color.py` reaching across to
import `proof._handled`. A change to the exit-code convention in CLAUDE.md had
to be made in 25 places or it silently diverged. Both helpers now live beside
`emit`/`fail` in ``carrel.core.output``.

These tests are a drift gate *and* the behavioural cover for the two helpers.
The counts here are exact, not floors: a floor set below the real number leaves
room for exactly the partial revert the gate exists to catch. When a command
module is added, add it to the count or to `NO_HANDLED` with the reason.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from carrel.cli import cli
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, handled, root_of

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "src" / "carrel" / "commands"
#: files under commands/ that are not command modules — shared private helpers,
#: so the conventions below (a `@handled` callback, `root_of`) do not apply. Named
#: exactly, not matched by pattern: a `startswith("_")` rule would silently exempt
#: every future helper from this gate, which is the floor the docstring warns about.
NOT_COMMANDS = {"__init__.py", "_guard_flags.py"}
MODULES = sorted(p for p in COMMANDS_DIR.glob("*.py") if p.name not in NOT_COMMANDS)

#: the private names D-016 retired, mapped to their shared replacement
RETIRED = {"_handled": "carrel.core.output.handled", "_root_of": "carrel.core.output.root_of"}

#: the open-coded form of `root_of`'s body — the duplication that has no name
INLINE_ROOT = 'ctx.obj or {}).get("root"'

#: modules that deliberately do not decorate with @handled, and why
NO_HANDLED = {
    "convert.py": "per-file loop: records an error per source and keeps going",
    "thumb.py": "per-file loop: records an error per source and keeps going",
    "desk.py": "catches ImportError for the tui extra; raises nothing else",
    "doctor.py": "reports adapter state; never raises CarrelError out of the callback",
    "completion.py": "prints a shell script; no file input to fail on",
    "mcp.py": "a JSON-RPC server; errors become responses, not exits",
}


def module_ids() -> list[str]:
    return [p.name for p in MODULES]


def test_the_commands_package_is_not_empty() -> None:
    """Guard the guard: a bad glob would make every parametrized test here vacuous."""
    assert len(MODULES) == 33, (
        f"expected 33 command modules, found {len(MODULES)} in {COMMANDS_DIR}"
    )


@pytest.mark.parametrize("path", MODULES, ids=module_ids())
def test_no_command_module_redefines_a_shared_helper(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    clashes = sorted(defined & (RETIRED.keys() | {"handled", "root_of"}))
    assert not clashes, (
        f"{path.name} defines {', '.join(clashes)} locally; "
        "import it from carrel.core.output instead (D-016)"
    )


@pytest.mark.parametrize("path", MODULES, ids=module_ids())
def test_no_command_module_open_codes_the_root_lookup(path: Path) -> None:
    """The duplication that survived the first pass had no name to grep for."""
    assert INLINE_ROOT not in path.read_text(encoding="utf-8"), (
        f"{path.name} open-codes the desk-root lookup; call root_of(ctx) (D-016)"
    )


@pytest.mark.parametrize("path", MODULES, ids=module_ids())
def test_shared_helpers_come_from_core_output(path: Path) -> None:
    """A module that uses `handled` or `root_of` must import it from the shared home."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for helper, marker in (("handled", "@handled"), ("root_of", "root_of(")):
        if marker not in source:
            continue
        sources = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == helper for alias in node.names)
        }
        assert sources == {"carrel.core.output"}, (
            f"{path.name} imports `{helper}` from {sources or 'nowhere'}; "
            "it belongs to carrel.core.output (D-016)"
        )


def test_every_module_either_uses_handled_or_says_why() -> None:
    """Exact, not a floor: a floor below the real count permits a partial revert."""
    without = {p.name for p in MODULES if "@handled" not in p.read_text(encoding="utf-8")}
    assert without == set(NO_HANDLED), (
        "modules not using @handled changed — add the new one to NO_HANDLED with a "
        f"reason, or decorate it.\n  unexpected: {sorted(without - set(NO_HANDLED))}"
        f"\n  now decorated: {sorted(set(NO_HANDLED) - without)}"
    )
    assert len(MODULES) - len(without) == 27


# ------------------------------------------------------------------ behaviour


def test_root_of_resolves_the_context_root(tmp_path: Path) -> None:
    """Through a real click.Context, not a stand-in: --root if given, else the cwd."""
    ctx = click.Context(click.Command("x"), obj={"root": str(tmp_path)})
    assert root_of(ctx) == tmp_path.resolve()

    bare = click.Context(click.Command("x"), obj=None)
    assert root_of(bare) == Path.cwd().resolve()

    empty = click.Context(click.Command("x"), obj={})
    assert root_of(empty) == Path.cwd().resolve()


def test_handled_is_transparent_when_nothing_raises() -> None:
    """The decorator preserves the wrapped callable's name, doc and return value."""

    @handled
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    assert add(2, 3) == 5
    assert add.__name__ == "add"
    assert add.__doc__ == "Add two numbers."


def _one_shot(exc: Exception) -> click.Group:
    """A throwaway CLI shaped like carrel's root group, whose only command raises `exc`.

    Built fresh per test rather than bolted onto `carrel.cli.cli`: that group is
    a module-level singleton, and `add_command` on it would leak into every
    other test in the session.
    """

    @click.group()
    @click.option("--debug", is_flag=True)
    @click.pass_context
    def group(ctx: click.Context, debug: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["debug"] = debug

    @group.command(name="boom")
    @click.pass_context
    @handled
    def boom(ctx: click.Context) -> None:
        raise exc

    return group


def test_handled_maps_carrel_error_onto_its_exit_code() -> None:
    """A clean message, the error's own exit code, and no traceback."""
    result = CliRunner().invoke(_one_shot(CarrelInputError("bad input here")), ["boom"])

    assert result.exit_code == int(ExitCode.BAD_INPUT)
    assert "error: bad input here" in result.output
    assert "Traceback" not in result.output


def test_handled_reraises_under_debug() -> None:
    """--debug is the documented escape hatch; nothing else in the suite covers it.

    Inverting this condition would make all 27 decorated callbacks dump
    tracebacks at end users while every other test still passed.
    """
    sentinel = CarrelError("boom with a traceback")
    result = CliRunner().invoke(_one_shot(sentinel), ["--debug", "boom"])

    assert result.exception is sentinel, f"expected it to propagate, got {result.exception!r}"


def test_the_real_cli_maps_a_bad_input_to_exit_4() -> None:
    """The shared decorator is wired into the actual command tree, not just a stub."""
    result = CliRunner().invoke(cli, ["inspect", "/no/such/file/anywhere.pdf"])

    assert result.exit_code == int(ExitCode.BAD_INPUT)
    assert "Traceback" not in result.output


# ------------------------------------------- the error channel under --json


@click.command("boom")
@click.pass_context
@handled
def _boom(ctx: click.Context) -> None:
    raise CarrelInputError("no such file: /nope")


def _run_boom(*args: str):
    @click.group()
    @click.option("--json", "json_", is_flag=True)
    @click.pass_context
    def root(ctx: click.Context, json_: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json"] = json_

    root.add_command(_boom)
    return CliRunner().invoke(root, [*args, "boom"])


def test_an_error_under_json_is_itself_json():
    """A caller piping `--json` had to parse English out of stderr."""
    result = _run_boom("--json")

    assert result.exit_code == int(ExitCode.BAD_INPUT)
    assert result.stdout == "", "stdout is the data channel and stays clean"
    payload = json.loads(result.stderr)
    assert payload == {"error": "no such file: /nope", "exit_code": int(ExitCode.BAD_INPUT)}


def test_an_error_without_json_is_still_the_plain_line():
    result = _run_boom()

    assert result.exit_code == int(ExitCode.BAD_INPUT)
    assert result.stderr.strip() == "error: no such file: /nope"


# ------------------------------------------- a PDF pypdf refuses to read

#: 156 bytes: a cross-reference table claiming 200,000 objects and a trailer
#: with no /Root. pypdf 6 walks for the root, logs one warning per missing
#: object, and gives up with `LimitReachedError` — a sibling of `PdfReadError`.
NO_ROOT_PDF = (
    b"%PDF-1.7\n1 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"xref\n0 2\n0000000000 65535 f \n0000000009 00000 n \n"
    b"trailer\n<< /Size 200000 >>\nstartxref\n66\n%%EOF\n"
)


def test_handled_maps_a_pypdf_limit_onto_exit_4() -> None:
    from pypdf.errors import LimitReachedError, PdfReadError

    assert not issubclass(LimitReachedError, PdfReadError), "the premise of this test changed"
    result = CliRunner().invoke(_one_shot(LimitReachedError("too many objects")), ["boom"])

    assert result.exit_code == int(ExitCode.BAD_INPUT), result.output
    assert result.stderr.strip() == "error: unreadable PDF: too many objects"


def test_handled_lets_a_pypdf_refusal_through_under_debug() -> None:
    from pypdf.errors import LimitReachedError

    sentinel = LimitReachedError("too many objects")
    result = CliRunner().invoke(_one_shot(sentinel), ["--debug", "boom"])

    assert result.exception is sentinel, "--debug must show pypdf's traceback, not a clean line"


def test_an_encrypted_pdf_says_how_to_decrypt_it() -> None:
    from pypdf.errors import WrongPasswordError

    result = CliRunner().invoke(
        _one_shot(WrongPasswordError("File has not been decrypted")), ["boom"]
    )

    assert result.exit_code == int(ExitCode.BAD_INPUT)
    assert "--decrypt PASSWORD" in result.stderr, result.stderr


def test_pypdf_missing_a_package_is_exit_3_with_an_install_hint() -> None:
    """AES needs `cryptography`, which carrel does not depend on (CLAUDE.md: exit 3)."""
    from pypdf.errors import DependencyError

    exc = DependencyError("cryptography>=3.1 is required for AES algorithm")
    result = CliRunner().invoke(_one_shot(exc), ["boom"])

    assert result.exit_code == int(ExitCode.MISSING_DEP), result.output
    assert "uv tool install carrel --with cryptography" in result.stderr, result.stderr


def test_pypdf_api_misuse_is_still_a_bug_not_bad_input() -> None:
    from pypdf.errors import PageSizeNotDefinedError

    sentinel = PageSizeNotDefinedError()
    result = CliRunner().invoke(_one_shot(sentinel), ["boom"])

    assert result.exception is sentinel


def test_classifying_an_error_does_not_import_pypdf() -> None:
    """`handled` sees every exception; pypdf costs ~0.2 s to import for none of them."""
    import subprocess
    import sys

    probe = (
        "import sys; from carrel.core.output import pdf_refusal; "
        "assert pdf_refusal(RuntimeError('x')) is None; print('pypdf' in sys.modules)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert proc.stdout.strip() == "False", proc.stdout + proc.stderr


def test_the_mcp_server_reports_a_pypdf_refusal_as_the_cli_does() -> None:
    from pypdf.errors import LimitReachedError

    from carrel.commands.mcp import _tool_error

    body = json.loads(_tool_error(LimitReachedError("too many objects"))["content"][0]["text"])
    assert body == {
        "error": "unreadable PDF: too many objects",
        "exit_code": int(ExitCode.BAD_INPUT),
    }


def test_handled_still_lets_a_real_bug_through() -> None:
    """Only pypdf's refusals are input errors; anything else stays unexpected."""
    sentinel = RuntimeError("a carrel bug")
    result = CliRunner().invoke(_one_shot(sentinel), ["boom"])

    assert result.exception is sentinel


def test_a_hostile_pdf_is_one_clean_json_error_not_a_stderr_flood(tmp_path: Path) -> None:
    """Through the real entry point, which is where the logging and exit live."""
    import subprocess
    import sys

    pdf = tmp_path / "noroot.pdf"
    pdf.write_bytes(NO_ROOT_PDF)
    proc = subprocess.run(
        [sys.executable, "-m", "carrel.cli", "--json", "note", "pdf", str(pdf)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert proc.returncode == int(ExitCode.BAD_INPUT), proc.stderr[-500:]
    lines = proc.stderr.splitlines()
    assert len(lines) == 1, f"{len(lines)} stderr lines; pypdf's warnings are leaking"
    payload = json.loads(lines[0])
    assert payload["exit_code"] == int(ExitCode.BAD_INPUT)
    assert payload["error"].startswith("unreadable PDF: ")


@pytest.fixture
def pypdf_logger_level():
    """`main` silences pypdf's logger for the process; put it back for later tests."""
    import logging

    logger = logging.getLogger("pypdf")
    before = logger.level
    yield logger
    logger.setLevel(before)


def _run_main(monkeypatch, exc: Exception, *argv: str) -> int:
    import sys

    import carrel.cli as cli_module

    def explode(**_kwargs):
        raise exc

    monkeypatch.setattr(cli_module, "cli", explode)
    monkeypatch.setattr(sys, "argv", ["carrel", *argv])
    with pytest.raises(SystemExit) as exit_info:
        cli_module.main()
    return int(exit_info.value.code)


def test_an_unexpected_error_under_json_is_json_too(monkeypatch, capsys, pypdf_logger_level):
    """`main`'s last-resort handler runs after click's context is gone."""
    import logging

    assert _run_main(monkeypatch, RuntimeError("a carrel bug"), "--json", "inspect", "x") == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["exit_code"] == 1
    assert payload["error"].startswith("unexpected error: a carrel bug")
    # and pypdf's error-level logs (one per unsupported font encoding) are off too
    assert pypdf_logger_level.getEffectiveLevel() > logging.ERROR


def test_a_carrel_error_reaching_main_under_json_is_json(monkeypatch, capsys, pypdf_logger_level):
    """Commands without `handled` (convert, thumb, doctor, desk…) end up here."""
    code = _run_main(monkeypatch, CarrelInputError("no such file: /nope"), "--json", "thumb", "x")

    assert code == int(ExitCode.BAD_INPUT)
    assert json.loads(capsys.readouterr().err) == {
        "error": "no such file: /nope",
        "exit_code": int(ExitCode.BAD_INPUT),
    }


def test_a_carrel_error_reaching_main_without_json_is_the_plain_line(
    monkeypatch, capsys, pypdf_logger_level
):
    code = _run_main(monkeypatch, CarrelInputError("no such file: /nope"), "thumb", "x")

    assert code == int(ExitCode.BAD_INPUT)
    assert capsys.readouterr().err.strip() == "error: no such file: /nope"
