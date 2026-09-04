"""carrel desk — launch the flagship Textual TUI.

The TUI itself lives in `carrel.desk.app`; this module is only the click
shell (and a guard for a missing textual, even though it is a core dep).
"""

from __future__ import annotations

from pathlib import Path

import click

from carrel.core.output import ExitCode, fail


@click.command(name="desk")
@click.argument(
    "root", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.pass_context
def cmd(ctx: click.Context, root: Path | None) -> None:
    """Open the interactive desk TUI on ROOT (default: --root, then cwd).

    Three panes: a directory tree of supported files, an inspector
    (metadata, text preview, tags/notes), and an actions list
    (convert / OCR / thumbnail / pack / index / tag / note). Action outputs
    land in ROOT/carrel-out/. Keys: q quit, / search, t tag, n note.
    """
    try:
        from carrel.desk.app import DeskApp
    except ModuleNotFoundError as e:  # guard: textual is a core dep, but be kind
        if e.name and e.name.split(".")[0] == "textual":
            fail(
                "textual is not installed — run: uv sync  (or: pip install textual)",
                ExitCode.MISSING_DEP,
            )
        raise
    base = root or Path((ctx.obj or {}).get("root", "."))
    DeskApp(base.resolve()).run()
