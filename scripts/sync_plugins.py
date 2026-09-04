#!/usr/bin/env python3
"""Regenerate the usage blocks inside ``plugins/*/commands/*.md`` from the CLI's ``--help``.

Every slash-command markdown file names the carrel command it wraps in its frontmatter
(``carrel-command: convert``) and carries one pair of markers::

    <!-- usage:start -->
    ```text
    Usage: carrel convert [OPTIONS] SRC...
    ...
    ```
    <!-- usage:end -->

This script replaces everything between the markers with the current ``--help`` output of
that command, captured in-process through ``click`` at a pinned width (COLUMNS=100) so the
result is deterministic and comes from the carrel in the current environment, never from
PATH. For click groups (edit, tag, note, sign, form, color, catalog) it emits the group's
own help followed by one fenced block per subcommand, recursively. Text outside the
markers is preserved byte for byte.

Usage:
    uv run python scripts/sync_plugins.py            # rewrite files whose block drifted
    uv run python scripts/sync_plugins.py --check    # exit 1 listing files that would change

A file without both markers, without a ``carrel-command`` frontmatter key, or naming a
command that is not registered in ``carrel.cli.COMMANDS`` is an error (exit 1) in both
modes. New commands need no change here: add ``carrel-command: <name>`` and the markers
to a new ``commands/<name>.md`` and run the script. The lint CI job runs ``--check``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLUGINS_DIR = ROOT / "plugins"
HELP_WIDTH = 100
START = "<!-- usage:start -->"
END = "<!-- usage:end -->"
FRONTMATTER_KEY = "carrel-command"

_MARKED = re.compile(re.escape(START) + r"\n.*?" + re.escape(END), re.DOTALL)


def _bootstrap_src() -> None:
    """Make ``carrel`` importable from a checkout without an installed wheel."""
    src = ROOT / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def frontmatter_command(text: str, path: Path) -> str:
    """Return the ``carrel-command:`` value from a command file's YAML frontmatter."""
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise SystemExit(f"{path}: missing YAML frontmatter")
    block = text[4:].split("\n---", 1)[0]
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == FRONTMATTER_KEY:
            name = value.strip().strip("\"'")
            if name:
                return name
    raise SystemExit(f"{path}: frontmatter needs `{FRONTMATTER_KEY}: <name>`")


def _fenced(text: str) -> str:
    return f"```text\n{text.rstrip()}\n```\n"


def _help_blocks(command: click.Command, ctx: click.Context, title: str) -> list[str]:
    """Fenced ``--help`` of ``title`` and, for groups, of every subcommand below it."""
    blocks = [_fenced(command.get_help(ctx))]
    if isinstance(command, click.Group):
        for name in sorted(command.list_commands(ctx)):
            sub = command.get_command(ctx, name)
            if sub is None:
                raise SystemExit(f"{title}: subcommand '{name}' is registered but unavailable")
            sub_ctx = click.Context(sub, info_name=name, parent=ctx)
            blocks.extend(_help_blocks(sub, sub_ctx, f"{title} {name}"))
    return blocks


class UsageRenderer:
    """Renders the between-markers text for a command name; caches per command."""

    def __init__(self) -> None:
        _bootstrap_src()
        os.environ["COLUMNS"] = str(HELP_WIDTH)
        from carrel._product import PRODUCT
        from carrel.cli import COMMANDS, cli

        self.commands = COMMANDS
        self._cli = cli
        self._prog = str(PRODUCT["cli"])
        self._root_ctx = click.Context(cli, info_name=self._prog, terminal_width=HELP_WIDTH)
        self._cache: dict[str, str] = {}

    def render(self, name: str) -> str:
        if name not in self._cache:
            if name not in self.commands:
                raise SystemExit(
                    f"'{name}' is not a carrel command (known: {', '.join(sorted(self.commands))})"
                )
            command = self._cli.get_command(self._root_ctx, name)
            if command is None:
                raise SystemExit(
                    f"command '{name}' failed to import — run `uv sync --all-extras` first"
                )
            ctx = click.Context(command, info_name=name, parent=self._root_ctx)
            blocks = _help_blocks(command, ctx, f"{self._prog} {name}")
            self._cache[name] = "\n".join(blocks)
        return self._cache[name]


def sync_text(text: str, path: Path, renderer: UsageRenderer) -> tuple[str, str]:
    """Return ``(command_name, new_text)`` for one command file (does not write)."""
    name = frontmatter_command(text, path)
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise SystemExit(f"{path}: needs exactly one `{START}` … `{END}` pair, in that order")
    usage = renderer.render(name)
    new_text = _MARKED.sub(lambda _m: f"{START}\n{usage}{END}", text, count=1)
    return name, new_text


def command_files(plugins_dir: Path) -> list[Path]:
    return sorted(plugins_dir.glob("*/commands/*.md"))


@click.command()
@click.option("--check", is_flag=True, help="Exit 1 if any file would change; write nothing.")
@click.option(
    "--plugins-dir",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=DEFAULT_PLUGINS_DIR,
    show_default=True,
    help="Directory holding <plugin>/commands/*.md (tests point this at a copy).",
)
def main(check: bool, plugins_dir: Path) -> None:
    """Regenerate the usage blocks in plugins/*/commands/*.md from `carrel … --help`."""
    renderer = UsageRenderer()
    files = command_files(plugins_dir)
    if not files:
        raise SystemExit(f"{plugins_dir}: no */commands/*.md files found")

    def rel(path: Path) -> Path:
        return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path

    changed: list[Path] = []
    for path in files:
        current = path.read_text(encoding="utf-8")
        _name, new_text = sync_text(current, path, renderer)
        if new_text == current:
            continue
        changed.append(path)
        if not check:
            path.write_text(new_text, encoding="utf-8")

    if check:
        if changed:
            for path in changed:
                click.echo(f"{rel(path)}: out of date", err=True)
            click.echo(
                f"{len(changed)} of {len(files)} command files drifted — "
                "run `uv run python scripts/sync_plugins.py`",
                err=True,
            )
            raise SystemExit(1)
        click.echo(f"{len(files)} command files: up to date")
        return
    for path in changed:
        click.echo(f"{rel(path)}: written")
    click.echo(f"{len(files)} command files: {len(changed)} updated")


if __name__ == "__main__":
    main()
