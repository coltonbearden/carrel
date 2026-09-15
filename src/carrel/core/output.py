"""Dual-audience output helpers and the exit-code convention (see CLAUDE.md)."""

from __future__ import annotations

import functools
import json
import sys
from collections.abc import Callable
from enum import IntEnum
from pathlib import Path
from typing import Any, NoReturn

import click


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    USAGE = 2
    MISSING_DEP = 3
    BAD_INPUT = 4
    EMPTY = 5


class CarrelError(Exception):
    """Base for expected, user-facing errors."""

    exit_code = ExitCode.ERROR


class CarrelInputError(CarrelError):
    """Unsupported/unreadable input → exit 4."""

    exit_code = ExitCode.BAD_INPUT


class CarrelUsageError(CarrelError):
    """The command was asked to do something it refuses to do → exit 2.

    `click.UsageError` is the wrong shape for this: click prefixes it with a
    `Usage:` / `Try --help` banner, which tells the user their arguments were
    malformed when in fact they were understood and refused. This goes through
    `fail()` like every other carrel error, so the message reads `error: …` and
    `core/` stays free of the CLI framework.
    """

    exit_code = ExitCode.USAGE


def emit(ctx: click.Context | None, data: Any, human: Callable[[Any], None] | None = None) -> None:
    """Print `data` as JSON when --json is active, else via `human` (or pretty rich fallback)."""
    as_json = bool(ctx and ctx.obj and ctx.obj.get("json"))
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif human is not None:
        human(data)
    else:
        from rich import print as rprint

        rprint(data)


def error_line(msg: str, code: ExitCode = ExitCode.ERROR) -> str:
    """One stderr line for an error — JSON under `--json`, `error: ...` otherwise.

    stdout is never touched: the data channel and the error channel stay apart.
    But a caller piping `--json` had to parse English out of stderr to learn
    anything beyond the exit code, and the exit code is what a *shell* sees, not
    what an MCP client or a `subprocess` reading stderr does.

    Every error carrel prints goes through here — `fail`, and the per-file loops
    in `convert` and `thumb` that report an error per source and keep going. The
    one exception is `click.UsageError` (a malformed command line), which click
    renders itself with the `Usage:` banner that is the answer to it.
    """
    ctx = click.get_current_context(silent=True)
    if ctx is not None and ctx.obj and ctx.obj.get("json"):
        return json.dumps({"error": msg, "exit_code": int(code)})
    return f"error: {msg}"


def fail(msg: str, code: ExitCode = ExitCode.ERROR) -> NoReturn:
    """Report an error on stderr and exit with its code."""
    click.echo(error_line(msg, code), err=True)
    sys.exit(int(code))


def progress(msg: str, ctx: click.Context | None = None) -> None:
    """Status line to stderr — keeps --json stdout clean."""
    if not (ctx and ctx.obj and ctx.obj.get("json")):
        click.echo(msg, err=True)


def debugging(ctx: click.Context | None) -> bool:
    """True when the user asked for tracebacks with the global --debug."""
    return bool(ctx is not None and ctx.obj and ctx.obj.get("debug"))


def handled[**P, R](fn: Callable[P, R]) -> Callable[P, R | None]:
    """Convert CarrelError — and a PDF pypdf refuses — into a clean message + exit code.

    Under --debug both propagate with their tracebacks instead.

    Most command callbacks wear this (D-016); the exit-code convention in
    CLAUDE.md is only honoured because the mapping lives here, once. The
    exceptions are the per-file loops in `convert` and `thumb`, which record an
    error per source and keep going — they share `debugging` but not this.

    Generic in the wrapped signature so mypy still checks calls through the
    decorator; the `| None` return is the `fail()` path, which never returns.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        ctx = click.get_current_context(silent=True)
        try:
            return fn(*args, **kwargs)
        except CarrelError as e:
            if debugging(ctx):
                raise
            fail(str(e), e.exit_code)
        except Exception as e:
            refused = pdf_refusal(e)
            if debugging(ctx) or refused is None:
                raise
            fail(*refused)

    return wrapper


def pdf_refusal(exc: Exception) -> tuple[str, ExitCode] | None:
    """The message and exit code for an error pypdf raised about its input, else None.

    Every refusal of a file derives from `pypdf.errors.PyPdfError` — including
    `LimitReachedError`, which pypdf 6 raises for decompression bombs and
    oversized structures and which is a sibling of `PdfReadError`, not a
    subclass, so catching `PdfReadError` alone let hostile files exit 1 as
    "unexpected error". Three cases are split out: an encrypted file gets the
    way to decrypt it, pypdf's `DependencyError` (AES needs `cryptography`, which
    carrel does not depend on) is exit 3 like any missing optional dependency,
    and the two `PyPdfError`s pypdf raises for API misuse rather than bad input
    stay unexpected, because they mean a carrel bug.

    Looked up in `sys.modules` rather than imported: if pypdf was never imported,
    the exception cannot be one of its errors, and importing it costs ~0.2 s.
    """
    errors = sys.modules.get("pypdf.errors")
    if errors is None:
        return None
    if isinstance(exc, errors.DependencyError):
        package = str(exc).split(">", 1)[0].split(" ", 1)[0] or "the package it names"
        hint = f"`uv tool install carrel --with {package}` or `pipx inject carrel {package}`"
        return f"{exc} — install {package} into carrel's environment ({hint})", ExitCode.MISSING_DEP
    if isinstance(exc, errors.FileNotDecryptedError):
        hint = "`carrel edit pdf FILE --decrypt PASSWORD -o OUT`"
        return f"encrypted PDF: {exc} — decrypt it first with {hint}", ExitCode.BAD_INPUT
    if isinstance(exc, (errors.PageSizeNotDefinedError, errors.XmpDocumentError)):
        return None
    if isinstance(exc, errors.PyPdfError):
        return f"unreadable PDF: {exc}", ExitCode.BAD_INPUT
    return None


def root_of(ctx: click.Context) -> Path:
    """The desk root for this invocation: --root if given, else the cwd."""
    return Path((ctx.obj or {}).get("root", ".")).resolve()
