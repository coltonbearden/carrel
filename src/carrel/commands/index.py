"""carrel index — build or refresh the desk full-text index (.carrel/carrel.db).

Walks the given paths (default: the desk root), extracts text from every
supported file via core.textextract, and upserts files + FTS rows through
core.db.DeskDB. Unchanged files (same size+mtime) are skipped.

`--update FILE... [--if-indexed]` is the hook-facing mode: reindex just the
named files, no walking; with --if-indexed it exits 0 silently when no desk
db exists yet (so a PostToolUse hook is a no-op outside an indexed desk).

`index_paths(...)` is the public implementation shared by the click command
and the MCP `carrel_index` tool (spec 15). `--status` is an alias of
`carrel catalog status` (spec 17).
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import click

from carrel.core.adapters import MissingDependencyError
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail, progress
from carrel.core.textextract import extract_text


def _handled(fn: Callable) -> Callable:
    """Convert CarrelError into a clean message + exit code (unless --debug)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = click.get_current_context(silent=True)
        try:
            return fn(*args, **kwargs)
        except CarrelError as e:
            if ctx is not None and ctx.obj and ctx.obj.get("debug"):
                raise
            fail(str(e), e.exit_code)

    return wrapper


def _root_of(ctx: click.Context) -> Path:
    return Path((ctx.obj or {}).get("root", ".")).resolve()


def _walk(top: Path) -> Iterator[Path]:
    """Yield files under `top`: hidden entries (.carrel, .git, dotfiles) and
    symlinked directories are skipped; order is deterministic."""
    if top.is_file():
        yield top
        return
    try:
        children = sorted(top.iterdir(), key=lambda p: p.name)
    except OSError:
        return
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if not child.is_symlink():
                yield from _walk(child)
        elif child.is_file():
            yield child


def _index_file(
    db: DeskDB,
    path: Path,
    *,
    ocr: bool,
    counts: dict[str, int],
    errors: list[dict[str, str]],
    ctx: click.Context | None,
) -> None:
    if db.is_fresh(path):
        counts["skipped"] += 1
        return
    rel = db.rel(path)
    progress(f"indexing {rel}", ctx)
    try:
        text = extract_text(path, ocr=ocr)
    except MissingDependencyError as e:
        errors.append({"path": rel, "error": str(e), "kind": "missing_dependency"})
        return
    except CarrelInputError as e:
        errors.append({"path": rel, "error": str(e), "kind": "bad_input"})
        return
    except CarrelError as e:  # e.g. ToolTimeoutError: one slow file must not abort the walk
        errors.append({"path": rel, "error": str(e), "kind": "error"})
        return
    fid = db.upsert_file(path, ftype=detect(path).value)
    db.set_content(fid, path, text)
    counts["indexed"] += 1


def index_paths(
    root: Path,
    paths: list[Path] | None = None,
    *,
    update: bool = False,
    prune: bool = False,
    ocr: bool = False,
) -> dict[str, Any]:
    """Index `paths` (default: `root`) into the desk db under `root`.

    Shared by `carrel index` and the MCP `carrel_index` tool. Walk mode
    descends directories (hidden entries skipped) and raises CarrelInputError
    for a path that does not exist; `update` treats each path as one file and
    silently skips missing/unsupported ones (hook semantics). Returns
    `{"indexed", "skipped", "pruned", "errors": [{path, error, kind}]}`.
    Progress lines go to stderr when a click context with human output is active.
    """
    root = Path(root).resolve()
    ctx = click.get_current_context(silent=True)
    targets = [Path(p).resolve() for p in paths] if paths else [root]
    counts = {"indexed": 0, "skipped": 0, "pruned": 0}
    errors: list[dict[str, str]] = []

    with DeskDB(root) as db:
        if update:
            for f in targets:
                if not f.is_file() or detect(f) is FileType.UNKNOWN:
                    counts["skipped"] += 1  # hook mode: never fail on odd files
                    continue
                _index_file(db, f, ocr=ocr, counts=counts, errors=errors, ctx=ctx)
        else:
            for top in targets:
                if not top.exists():
                    raise CarrelInputError(f"no such path: {top}")
                for f in _walk(top):
                    if detect(f) is FileType.UNKNOWN:
                        continue  # not a supported type — not a candidate
                    _index_file(db, f, ocr=ocr, counts=counts, errors=errors, ctx=ctx)
        if prune:
            counts["pruned"] = db.prune()
    return {**counts, "errors": errors}


def _human_summary(data: dict[str, Any]) -> None:
    from rich.console import Console
    from rich.table import Table

    for err in data["errors"]:
        click.echo(f"error: {err['path']}: {err['error']}", err=True)
    table = Table(title="index summary")
    for col in ("indexed", "skipped", "pruned", "errors"):
        table.add_column(col, justify="right")
    table.add_row(
        str(data["indexed"]), str(data["skipped"]), str(data["pruned"]), str(len(data["errors"]))
    )
    Console().print(table)


@click.command(name="index")
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option(
    "--ocr", is_flag=True, help="OCR images and scanned PDFs (needs tesseract / ocrmypdf)."
)
@click.option(
    "--prune", is_flag=True, help="Remove index rows whose files no longer exist on disk."
)
@click.option(
    "--update",
    "update_mode",
    is_flag=True,
    help="Treat PATH... as individual files to (re)index — no directory "
    "walking; unsupported or missing files are silently skipped.",
)
@click.option(
    "--if-indexed",
    is_flag=True,
    help="Exit 0 silently when no desk db exists yet under --root "
    "(for hooks: only refresh an index someone already created).",
)
@click.option(
    "--status",
    is_flag=True,
    help="Report index health instead of indexing (alias of `carrel catalog status`); "
    "other options are ignored. Exit 4 when no desk db exists under --root.",
)
@click.pass_context
@_handled
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    ocr: bool,
    prune: bool,
    update_mode: bool,
    if_indexed: bool,
    status: bool,
) -> None:
    """Index PATH... (default: the desk root) into .carrel/carrel.db.

    Walks directories for the supported file types, skipping hidden entries
    (.carrel, .git, dotfiles). Files unchanged since the last run (same
    size + mtime) are skipped. Text comes from core.textextract; images are
    registered but only get searchable text with --ocr. Progress goes to
    stderr; the JSON summary is {"indexed", "skipped", "pruned", "errors"}.
    `--status` prints the `carrel catalog status` report instead.
    """
    root = _root_of(ctx)
    if status:
        from carrel.commands.catalog import emit_status

        emit_status(ctx, root)
        return
    if if_indexed and not DeskDB.exists(root):
        return
    if update_mode and not paths:
        raise click.UsageError("--update requires at least one FILE argument")

    data = index_paths(root, list(paths), update=update_mode, prune=prune, ocr=ocr)
    counts, errors = data, data["errors"]
    emit(ctx, data, human=_human_summary)
    missing = [e for e in errors if e.get("kind") == "missing_dependency"]
    nothing_else_happened = counts["indexed"] == 0 and counts["skipped"] == 0
    if missing and nothing_else_happened and len(missing) == len(errors) and not update_mode:
        # every file touched this run needed a binary we don't have: exit 3, not success.
        # (Fresh files skipped as unchanged count as success; --update hook mode never fails.)
        fail(
            f"nothing indexed — {len(missing)} file(s) need a missing tool:\n{missing[0]['error']}",
            ExitCode.MISSING_DEP,
        )
