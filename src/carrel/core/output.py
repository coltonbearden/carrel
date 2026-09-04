"""Dual-audience output helpers and the exit-code convention (see CLAUDE.md)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from enum import IntEnum
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


def fail(msg: str, code: ExitCode = ExitCode.ERROR) -> NoReturn:
    click.echo(f"error: {msg}", err=True)
    sys.exit(int(code))


def progress(msg: str, ctx: click.Context | None = None) -> None:
    """Status line to stderr — keeps --json stdout clean."""
    if not (ctx and ctx.obj and ctx.obj.get("json")):
        click.echo(msg, err=True)
