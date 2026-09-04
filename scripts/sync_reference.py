#!/usr/bin/env python3
"""Regenerate docs/REFERENCE.md from the CLI's own ``--help`` text.

Walks ``carrel.cli.COMMANDS`` in sorted order, captures every command's (and every
subcommand's) ``--help`` in-process through ``click.Context`` at a fixed width, and
writes one Markdown page: header, the root options block, a ``##`` section per
command with ``###`` subsections per subcommand, then the exit-code table derived
from ``carrel.core.output.ExitCode``.

Output is deterministic: no timestamps, the version comes from ``_product.py``, and
the width is pinned (COLUMNS=100) so it never depends on the caller's terminal.

Usage:
    uv run python scripts/sync_reference.py            # rewrite docs/REFERENCE.md
    uv run python scripts/sync_reference.py --check    # exit 1 if the file would change

New commands need no change here: they appear as soon as they are registered in
``COMMANDS``. The lint CI job runs this and fails on ``git diff -- docs/REFERENCE.md``.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "REFERENCE.md"
HELP_WIDTH = 100

# One line per ExitCode member; a member missing here (and without an inline
# ``# comment`` in core/output.py) fails generation so the table can't go stale.
EXIT_CODE_MEANINGS: dict[str, str] = {
    "OK": "success",
    "ERROR": "general/unexpected error (message to stderr, no traceback unless `--debug`)",
    "USAGE": "bad usage/arguments",
    "MISSING_DEP": "missing optional dependency (message names the binary + install hint)",
    "BAD_INPUT": "input file not found / unreadable / unsupported type",
    "EMPTY": "operation produced no result (e.g. `search --fail-empty` with no hits)",
}


def _bootstrap_src() -> None:
    """Make ``carrel`` importable from a checkout without an installed wheel."""
    src = ROOT / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _help_text(command: click.Command, ctx: click.Context) -> str:
    return command.get_help(ctx).rstrip() + "\n"


def _fenced(text: str) -> str:
    return f"```text\n{text}```\n"


def _anchor(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _command_sections(
    command: click.Command, ctx: click.Context, title: str, level: int
) -> list[str]:
    """Render ``title`` (e.g. ``carrel edit``) and, for groups, every subcommand below it."""
    heading = "#" * min(level, 6)
    parts = [f"{heading} {title}\n\n{_fenced(_help_text(command, ctx))}"]
    if isinstance(command, click.Group):
        for name in sorted(command.list_commands(ctx)):
            sub = command.get_command(ctx, name)
            if sub is None:
                raise SystemExit(f"{title}: subcommand '{name}' is registered but unavailable")
            sub_ctx = click.Context(sub, info_name=name, parent=ctx)
            parts.extend(_command_sections(sub, sub_ctx, f"{title} {name}", level + 1))
    return parts


def _exit_code_rows() -> list[str]:
    """One table row per ExitCode member, described by an inline comment or the table above."""
    from carrel.core.output import ExitCode

    comments: dict[str, str] = {}
    for line in inspect.getsource(ExitCode).splitlines():
        match = re.match(r"\s*([A-Z_]+)\s*=\s*\d+\s*#\s*(.+)$", line)
        if match:
            comments[match.group(1)] = match.group(2).strip()
    rows = []
    for member in ExitCode:
        meaning = comments.get(member.name) or EXIT_CODE_MEANINGS.get(member.name)
        if meaning is None:
            raise SystemExit(
                f"ExitCode.{member.name} has no description: add an inline comment in "
                "core/output.py or an entry in EXIT_CODE_MEANINGS"
            )
        rows.append(f"| {int(member)} | `{member.name}` | {meaning} |")
    return rows


def render() -> str:
    """Build the complete REFERENCE.md text (pure function of the installed CLI)."""
    _bootstrap_src()
    os.environ["COLUMNS"] = str(HELP_WIDTH)  # anything that sizes itself from the terminal
    from carrel._product import PRODUCT
    from carrel.cli import COMMANDS, cli

    prog = str(PRODUCT["cli"])
    version = str(PRODUCT["version"])
    root_ctx = click.Context(cli, info_name=prog, terminal_width=HELP_WIDTH)

    out: list[str] = []
    out.append(
        f"# {PRODUCT['displayName']} command reference\n\n"
        f"Generated from `--help` of {prog} {version} by `scripts/sync_reference.py` — do not edit.\n"
        f"Regenerate with `uv run python scripts/sync_reference.py`; CI fails when this file drifts.\n\n"
        "Related docs: [Install](INSTALL.md) · [Quickstart](QUICKSTART.md) ·\n"
        "[Configuration](CONFIGURATION.md) · [Troubleshooting](TROUBLESHOOTING.md) ·\n"
        "[Cookbook & snippets](COOKBOOK.md)\n"
    )

    out.append(
        "## Global options\n\n"
        "These live on the root command, *before* the subcommand\n"
        f"(e.g. `{prog} --json inspect report.pdf`):\n\n"
        + _fenced(_help_text(cli, root_ctx))
        + "\n"
        "- `--json` — where a command produces data, exactly one JSON object or array\n"
        "  goes to stdout and nothing else (progress goes to stderr). Every command also\n"
        "  accepts `--json` after its name; both spellings work.\n"
        "- `--root PATH` — where db-backed commands keep `.carrel/carrel.db`.\n"
        "  See [Configuration](CONFIGURATION.md).\n"
        "- `--debug` — show tracebacks instead of one-line errors.\n"
    )

    names = sorted(COMMANDS)
    toc = " ·\n".join(f"[{n}](#{_anchor(f'{prog} {n}')})" for n in names)
    out.append(f"## Commands\n\n{len(names)} commands:\n\n{toc}\n")

    for name in names:
        command = cli.get_command(root_ctx, name)
        if command is None:
            raise SystemExit(
                f"command '{name}' is registered in COMMANDS but failed to import — "
                "install every extra (uv sync --all-extras) before regenerating"
            )
        ctx = click.Context(command, info_name=name, parent=root_ctx)
        out.extend(_command_sections(command, ctx, f"{prog} {name}", level=2))

    out.append(
        "## Exit codes\n\n"
        "| Code | Name | Meaning |\n|---|---|---|\n" + "\n".join(_exit_code_rows()) + "\n\n"
        f'Note: `{prog} diff` deliberately reuses `1` to mean "inputs differ" — its help\n'
        "text above spells out the full mapping.\n"
    )
    return "\n".join(out)


@click.command()
@click.option("--check", is_flag=True, help="Exit 1 if the file would change; write nothing.")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=DEFAULT_OUTPUT,
    show_default=True,
    help="Where to write (or what to compare against with --check).",
)
def main(check: bool, output: Path) -> None:
    """Regenerate docs/REFERENCE.md from the CLI's --help output."""
    text = render()
    rel = output.relative_to(ROOT) if output.is_relative_to(ROOT) else output
    current = output.read_text(encoding="utf-8") if output.is_file() else None
    if check:
        if current == text:
            click.echo(f"{rel}: up to date")
            return
        click.echo(f"{rel}: out of date — run `uv run python scripts/sync_reference.py`", err=True)
        raise SystemExit(1)
    if current == text:
        click.echo(f"{rel}: unchanged")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    click.echo(f"{rel}: written ({text.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
