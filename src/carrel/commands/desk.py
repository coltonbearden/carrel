"""carrel desk — launch the flagship Textual TUI.

The TUI itself lives in `carrel.desk.app`; this module is only the click
shell plus the guard for a missing textual — an optional extra since v0.2.0
(D-007): `carrel[tui]`.
"""

from __future__ import annotations

from pathlib import Path

import click

from carrel._product import PRODUCT
from carrel.core.output import ExitCode, fail

# Shared with `carrel doctor`, whose capability row for desk reads the same hint.
TUI_INSTALL_HINT = (
    f"uv tool install '{PRODUCT['cli']}[tui]'  (from a checkout: uv sync --extra tui)"
)


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
    except ModuleNotFoundError as e:  # textual is the optional `tui` extra (D-007)
        if e.name and e.name.split(".")[0] == "textual":
            fail(
                f"textual is not installed (optional extra 'tui') — run: {TUI_INSTALL_HINT}",
                ExitCode.MISSING_DEP,
            )
        raise
    base = root or Path((ctx.obj or {}).get("root", "."))
    DeskApp(base.resolve()).run()
