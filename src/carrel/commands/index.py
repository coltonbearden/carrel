"""carrel index — build or refresh the desk full-text index (.carrel/carrel.db).

Walks the given paths (default: the desk root), extracts text from every
supported file via core.textextract, and upserts files + FTS rows through
core.db.DeskDB. Unchanged files (same size+mtime) are skipped.

Source and config files (`.py`, `.rs`, `.toml`, `.yaml`, ...) are indexed as
FileType.CODE, so `search` and `pack --query` reach source trees; `--no-source`
opts out. The walk honours `.gitignore` (`--no-gitignore` opts out), without
which a source tree would drag in node_modules/, build/ and dist/.

`--update FILE... [--if-indexed]` is the hook-facing mode: reindex just the
named files, no walking; with --if-indexed it exits 0 silently when no desk
db exists yet (so a PostToolUse hook is a no-op outside an indexed desk).

`index_paths(...)` is the public implementation shared by the click command
and the MCP `carrel_index` tool (spec 15). `--status` is an alias of
`carrel catalog status` (spec 17).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import click

from carrel.core.adapters import MissingDependencyError
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
from carrel.core.fsops import within
from carrel.core.ignore import IgnoreFile, ancestor_ignores, ignored, load_ignore
from carrel.core.output import (
    CarrelError,
    CarrelInputError,
    ExitCode,
    emit,
    fail,
    handled,
    progress,
    root_of,
)
from carrel.core.textextract import extract_text


def _walk(
    top: Path,
    ignores: tuple[IgnoreFile, ...] = (),
    *,
    use_gitignore: bool = True,
    confine_to: Path | None = None,
) -> Iterator[Path]:
    """Yield files under `top`: hidden entries (.carrel, .git, dotfiles),
    symlinked directories and `.gitignore`d paths are skipped; order is
    deterministic. `ignores` is the inherited rule stack (empty = no filtering).

    `confine_to` additionally drops any entry that *resolves* outside it. Skipping
    symlinked directories is not enough on its own: a symlinked **file** is still
    read, so a link inside the tree is a way out of it. Callers with a boundary to
    keep — `carrel mcp`, confined to its launch root (D-021) — pass it; the CLI
    passes None and keeps following links, because a desk that symlinks documents
    in from elsewhere is a legitimate layout."""
    if top.is_file():
        if within(top, confine_to):
            yield top
        return
    if use_gitignore:
        ig = load_ignore(top)
        if ig:
            ignores = (*ignores, ig)
    try:
        children = sorted(top.iterdir(), key=lambda p: p.name)
    except OSError:
        return
    for child in children:
        if child.name.startswith("."):
            continue
        # only a symlink can leave a tree we descended from a resolved top, and
        # `is_symlink` is answered by the scandir cache — `within` is a realpath
        # walk, so it is not worth paying on every ordinary entry
        if child.is_symlink() and not within(child, confine_to):
            continue
        if child.is_dir():
            if not child.is_symlink() and not ignored(child, True, ignores):
                yield from _walk(child, ignores, use_gitignore=use_gitignore, confine_to=confine_to)
        elif child.is_file() and not ignored(child, False, ignores):
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
    source: bool = True,
    gitignore: bool = True,
    confine_to: Path | None = None,
) -> dict[str, Any]:
    """Index `paths` (default: `root`) into the desk db under `root`.

    Shared by `carrel index` and the MCP `carrel_index` tool. Walk mode
    descends directories (hidden entries skipped) and raises CarrelInputError
    for a path that does not exist; `update` treats each path as one file and
    silently skips missing/unsupported ones (hook semantics). `source`
    includes plain-text source/config files (FileType.CODE); `gitignore`
    honours `.gitignore` while walking. Returns
    `{"indexed", "skipped", "pruned", "errors": [{path, error, kind}]}`.
    Progress lines go to stderr when a click context with human output is active.
    """
    root = Path(root).resolve()
    ctx = click.get_current_context(silent=True)
    targets = [Path(p).resolve() for p in paths] if paths else [root]
    counts = {"indexed": 0, "skipped": 0, "pruned": 0}
    errors: list[dict[str, str]] = []

    def _candidate(f: Path) -> bool:
        ftype = detect(f)
        if ftype is FileType.UNKNOWN:
            return False
        return source or not ftype.is_code

    with DeskDB(root) as db:
        if update:
            for f in targets:
                if not within(f, confine_to):
                    counts["skipped"] += 1
                    continue
                if not f.is_file() or not _candidate(f):
                    counts["skipped"] += 1  # hook mode: never fail on odd files
                    continue
                _index_file(db, f, ocr=ocr, counts=counts, errors=errors, ctx=ctx)
        else:
            for top in targets:
                if not top.exists():
                    raise CarrelInputError(f"no such path: {top}")
                if not within(top, confine_to):
                    continue  # `_walk`'s symlink fast path assumes an inside top
                seed = ancestor_ignores(top, root) if gitignore else ()
                for f in _walk(top, seed, use_gitignore=gitignore, confine_to=confine_to):
                    if not _candidate(f):
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
    "--no-source",
    is_flag=True,
    help="Skip plain-text source and config files (.py, .rs, .toml, .yaml, ...); "
    "index only the document types.",
)
@click.option(
    "--no-gitignore",
    is_flag=True,
    help="Do not honor .gitignore files while walking.",
)
@click.option(
    "--status",
    is_flag=True,
    help="Report index health instead of indexing (alias of `carrel catalog status`); "
    "other options are ignored. Exit 4 when no desk db exists under --root.",
)
@click.pass_context
@handled
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    ocr: bool,
    prune: bool,
    update_mode: bool,
    if_indexed: bool,
    no_source: bool,
    no_gitignore: bool,
    status: bool,
) -> None:
    """Index PATH... (default: the desk root) into .carrel/carrel.db.

    Walks directories for the supported file types plus plain-text source
    and config files (.py, .rs, .toml, .yaml, ... — indexed as type `code`,
    use --no-source to skip them), honoring .gitignore and skipping hidden
    entries (.carrel, .git, dotfiles). Files unchanged since the last run
    (same size + mtime) are skipped. Text comes from core.textextract; images
    are registered but only get searchable text with --ocr. Progress goes to
    stderr; the JSON summary is {"indexed", "skipped", "pruned", "errors"}.
    `--status` prints the `carrel catalog status` report instead.
    """
    root = root_of(ctx)
    if status:
        from carrel.commands.catalog import emit_status

        emit_status(ctx, root)
        return
    if if_indexed and not DeskDB.exists(root):
        return
    if update_mode and not paths:
        raise click.UsageError("--update requires at least one FILE argument")

    data = index_paths(
        root,
        list(paths),
        update=update_mode,
        prune=prune,
        ocr=ocr,
        source=not no_source,
        gitignore=not no_gitignore,
    )
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
