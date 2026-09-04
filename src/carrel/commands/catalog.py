"""carrel catalog — export, import and check the desk catalog (tags + notes).

Tags and notes are the only desk data `carrel index` cannot regenerate.
`export` writes them as one deterministic JSON document (root-relative paths,
sorted), `import` merges such a document back (idempotent; `--replace` clears
first), and `status` reports schema version, row counts and index staleness.
`carrel index --status` is an alias of `catalog status`.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from carrel._product import PRODUCT
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

_EXAMPLES = 5  # paths listed per stale bucket in `status`


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


def _require_desk(root: Path) -> None:
    if not DeskDB.exists(root):
        raise CarrelInputError(
            f"no desk db under {root} (.carrel/carrel.db) — run `{PRODUCT['cli']} index` first"
        )


# ------------------------------------------------------------------- export


def build_export(root: Path) -> dict[str, Any]:
    """The catalog document for `root` (see `catalog export --help` for the shape)."""
    with DeskDB(root) as db:
        core = db.export_catalog()
    return {
        "schema": core["schema"],
        "product": PRODUCT["cli"],
        "version": PRODUCT["version"],
        "exported": datetime.now(UTC).isoformat(timespec="seconds"),
        "root": core["root"],
        "files": core["files"],
    }


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


@click.group(name="catalog")
def cmd() -> None:
    """Export, import and check the desk catalog (tags + notes in .carrel/carrel.db)."""


@cmd.command("export")
@click.option(
    "-o",
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the catalog to FILE instead of stdout (refuses to overwrite without --force).",
)
@click.option("--force", is_flag=True, help="Overwrite an existing --out file.")
@click.pass_context
@_handled
def export(ctx: click.Context, out: Path | None, force: bool) -> None:
    """Export every tagged or annotated file's tags and notes as JSON.

    Document: {"schema", "product", "version", "exported", "root", "files":
    [{"path": <root-relative>, "tags": [...sorted], "notes": [{"created",
    "body"}]}]}, sorted by path — byte-identical across runs apart from
    "exported". Without -o the document itself is printed (always JSON); with
    -o a short summary is printed instead. Exit 4 when no desk db exists.
    """
    root = _root_of(ctx)
    _require_desk(root)
    doc = build_export(root)
    if out is None:
        click.echo(_dump(doc), nl=False)
        return
    out = out.resolve()
    if out.exists() and not force:
        raise CarrelError(f"refusing to overwrite {out} (use --force)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_dump(doc), encoding="utf-8")
    summary = {
        "out": str(out),
        "files": len(doc["files"]),
        "tags": sum(len(f["tags"]) for f in doc["files"]),
        "notes": sum(len(f["notes"]) for f in doc["files"]),
    }
    emit(
        ctx,
        summary,
        human=lambda d: click.echo(
            f"wrote {d['out']}: {d['files']} file(s), {d['tags']} tag(s), {d['notes']} note(s)"
        ),
    )


# ------------------------------------------------------------------- import


def _load_catalog(file: Path) -> dict[str, Any]:
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as e:
        raise CarrelInputError(f"cannot read {file}: {e.strerror or e}") from e
    except UnicodeDecodeError as e:
        raise CarrelInputError(f"cannot read {file}: not UTF-8 text") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CarrelInputError(f"invalid JSON in {file}: {e.msg} (line {e.lineno})") from e
    if not isinstance(data, dict):
        raise CarrelInputError(f"invalid catalog {file}: top level must be a JSON object")
    return data


def _human_import(data: dict[str, Any]) -> None:
    if data["tags_removed"] or data["notes_removed"]:
        click.echo(f"removed {data['tags_removed']} tag(s) and {data['notes_removed']} note(s)")
    click.echo(
        f"imported {data['tags_added']} tag(s), {data['notes_added']} note(s) "
        f"across {data['files_touched']} file(s)"
    )
    if data["skipped_missing"]:
        click.echo(f"skipped {data['skipped_missing']} entry(ies) whose file is missing", err=True)


@cmd.command("import")
@click.argument("file", type=click.Path(path_type=Path))
@click.option(
    "--replace",
    is_flag=True,
    help="Delete ALL existing tags and notes first, then import (prints what was removed).",
)
@click.pass_context
@_handled
def import_(ctx: click.Context, file: Path, replace: bool) -> None:
    """Merge FILE (a `catalog export` document) into the desk under --root.

    Tags already present are kept (INSERT OR IGNORE); notes are deduplicated on
    (file, created, body), so importing the same document twice adds nothing.
    Entries whose path does not exist under the root are counted in
    skipped_missing and not created. Exit 4 for unreadable/invalid JSON or a
    "schema" newer than this build supports. JSON output: {tags_added,
    notes_added, files_touched, skipped_missing, tags_removed, notes_removed}.
    """
    root = _root_of(ctx)
    data = _load_catalog(file.resolve())
    with DeskDB(root) as db:
        result = db.import_catalog(data, replace=replace)
    emit(ctx, result, human=_human_import)


# ------------------------------------------------------------------- status


def build_status(root: Path) -> dict[str, Any]:
    """Schema version, row counts and staleness for the desk under `root`.

    Raises CarrelInputError (exit 4) when no desk db exists. `unindexed` counts
    supported files found by a walk (same rules as `carrel index`) that have no
    searchable text yet.
    """
    from carrel.commands.index import _walk

    root = root.resolve()
    _require_desk(root)
    with DeskDB(root) as db:
        version = db.schema_version()
        counts = db.counts()
        stale = db.stale()
        indexed = db.indexed_paths()
        unindexed = [
            db.rel(p)
            for p in _walk(root)
            if detect(p) is not FileType.UNKNOWN and db.rel(p) not in indexed
        ]
        db_path = db.path
    return {
        "schema_version": version,
        "db_path": str(db_path),
        "counts": counts,
        "stale": {
            "changed": len(stale["changed"]),
            "missing": len(stale["missing"]),
            "unindexed": len(unindexed),
        },
        "examples": {
            "changed": stale["changed"][:_EXAMPLES],
            "missing": stale["missing"][:_EXAMPLES],
            "unindexed": unindexed[:_EXAMPLES],
        },
    }


def _human_status(data: dict[str, Any]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(f"[bold]{data['db_path']}[/bold]  (schema {data['schema_version']})")
    table = Table(title="desk catalog")
    for col in ("files", "docs", "tags", "notes", "changed", "missing", "unindexed"):
        table.add_column(col, justify="right")
    c, s = data["counts"], data["stale"]
    table.add_row(
        *(str(c[k]) for k in ("files", "docs", "tags", "notes")),
        *(str(s[k]) for k in ("changed", "missing", "unindexed")),
    )
    console.print(table)
    for bucket in ("changed", "missing", "unindexed"):
        for path in data["examples"][bucket]:
            console.print(f"  {bucket:<9} {path}")
    cli = PRODUCT["cli"]
    hints = []
    if s["changed"] or s["unindexed"]:
        hints.append(f"`{cli} index` refreshes changed/unindexed files")
    if s["missing"]:
        hints.append(f"`{cli} index --prune` drops missing ones")
    if hints:
        console.print("hint: " + "; ".join(hints))


def emit_status(ctx: click.Context, root: Path) -> None:
    """Print the status report for `root` (shared with `carrel index --status`)."""
    emit(ctx, build_status(root), human=_human_status)


@cmd.command("status")
@click.pass_context
@_handled
def status(ctx: click.Context) -> None:
    """Report the desk db: schema version, row counts, and stale index entries.

    JSON: {schema_version, db_path, counts: {files, docs, tags, notes},
    stale: {changed, missing, unindexed}, examples: {changed, missing,
    unindexed} (up to 5 paths each)}. Always exit 0 (it is a report); exit 4
    when no .carrel/carrel.db exists under --root.
    """
    emit_status(ctx, _root_of(ctx))
