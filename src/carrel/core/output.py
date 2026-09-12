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
    """Convert CarrelError into a clean message + exit code (unless --debug).

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

    return wrapper


def root_of(ctx: click.Context) -> Path:
    """The desk root for this invocation: --root if given, else the cwd."""
    return Path((ctx.obj or {}).get("root", ".")).resolve()
