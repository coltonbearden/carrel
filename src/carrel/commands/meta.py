"""carrel meta — typed key/value fields on desk files (schema v2).

Fields live in `.carrel/carrel.db` next to tags and notes: `vendor=Acme`,
`total=1234.5`, `due=2026-10-01`, `paid=true`. The kind (str/num/date/bool) is
inferred from the value unless --kind forces it, and numbers and dates are
stored canonically so `find total>1000` compares numerically and
`find due<2026-11-01` compares chronologically. `source` records who wrote a
field (user by default; automation passes its own name with --source).

Read-only subcommands (get, ls, find, export) never create a `.carrel/`
directory; `set` registers the file in the desk db like `tag add` does.
`meta export` writes one row per file with a column per key — the desk as a
spreadsheet. Tags/notes/meta travel together through `catalog export/import`.
"""

from __future__ import annotations

import csv
import functools
import io
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from carrel._product import PRODUCT
from carrel.core.db import META_KINDS, DeskDB, normalize_meta_key
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail


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


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def meta_map(db: DeskDB, path: Path) -> dict[str, str]:
    """{key: value} for a file (empty when unknown)."""
    return {row["key"]: row["value"] for row in db.meta_of(path)}


def _echo_file_meta(data: dict[str, Any]) -> None:
    pairs = ", ".join(f"{k}={v}" for k, v in data["meta"].items()) or "(no fields)"
    click.echo(f"{data['path']}: {pairs}")


@click.group(name="meta")
def cmd() -> None:
    """Typed key/value fields on desk files (.carrel/carrel.db under --root)."""


# ------------------------------------------------------------------- set


def _usage_key(key: str) -> str:
    """A bad key on the command line is a usage error (exit 2) in every subcommand."""
    try:
        return normalize_meta_key(key)
    except CarrelInputError as e:
        raise click.UsageError(str(e)) from e


def _parse_pairs(pairs: tuple[str, ...]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for spec in pairs:
        key, sep, value = spec.partition("=")
        if not sep or not key.strip():
            raise click.UsageError(f"expected KEY=VALUE (got: {spec!r})")
        out.append((_usage_key(key), value))
    return out


@cmd.command("set")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("pairs", nargs=-1, required=True, metavar="KEY=VALUE...")
@click.option(
    "--kind",
    type=click.Choice(META_KINDS),
    default=None,
    help="Force the kind of every field in this call (default: inferred — "
    "true/false → bool, 1234.5 → num, an ISO YYYY-MM-DD date → date, else str; "
    "digits with a leading zero such as 02134 stay str).",
)
@click.option(
    "--source",
    default="user",
    show_default=True,
    help="Who is writing the field (automation should pass its own name).",
)
@click.pass_context
@_handled
def set_(
    ctx: click.Context, path: Path, pairs: tuple[str, ...], kind: str | None, source: str
) -> None:
    """Set KEY=VALUE... on PATH (registers the file in the desk db if needed)."""
    path = path.resolve()
    if not path.is_file():
        raise CarrelInputError(f"no such file: {path}")
    parsed = _parse_pairs(pairs)
    with DeskDB(_root_of(ctx)) as db:
        stored = [db.set_meta(path, k, v, kind=kind, source=source) for k, v in parsed]
        data = {"path": db.rel(path), "set": [s["key"] for s in stored], "meta": meta_map(db, path)}
    emit(ctx, data, human=_echo_file_meta)


# ------------------------------------------------------------------- get / ls / rm


@cmd.command("get")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("key")
@click.option("--fail-empty", is_flag=True, help="Exit 5 when PATH has no such field.")
@click.pass_context
@_handled
def get(ctx: click.Context, path: Path, key: str, fail_empty: bool) -> None:
    """Print one field of PATH (its value alone in human mode; null when absent)."""
    root = _root_of(ctx)
    path = path.resolve()
    key = _usage_key(key)
    row = None
    if DeskDB.exists(root):
        with DeskDB(root) as db:
            row = db.get_meta(path, key)
            rel = db.rel(path)
    else:
        rel = str(path)
    data: dict[str, Any] = {"path": rel, "key": key, "value": None, "kind": None, "source": None}
    if row:
        data.update({"value": row["value"], "kind": row["kind"], "source": row["source"]})

    def human(d: dict[str, Any]) -> None:
        if d["value"] is not None:
            click.echo(d["value"])

    emit(ctx, data, human=human)
    if fail_empty and row is None:
        fail(f"{rel} has no field {key!r}", ExitCode.EMPTY)


def _echo_keys(data: dict[str, Any]) -> None:
    if not data["keys"]:
        click.echo("no fields", err=True)
        return
    width = max(len(k) for k in data["keys"])
    for key, count in data["keys"].items():
        click.echo(f"{key:<{width}}  {count} file(s)")


def _echo_fields(data: dict[str, Any]) -> None:
    if not data["meta"]:
        click.echo(f"{data['path']}: (no fields)")
        return
    width = max(len(f["key"]) for f in data["meta"])
    click.echo(data["path"])
    for f in data["meta"]:
        click.echo(
            f"  {f['key']:<{width}}  {f['value']}  ({f['kind']}, {f['source']}, {f['updated']})"
        )


@cmd.command("ls")
@click.argument("path", required=False, type=click.Path(path_type=Path))
@click.pass_context
@_handled
def ls(ctx: click.Context, path: Path | None) -> None:
    """List PATH's fields with kind/source, or (without PATH) every key with its file count."""
    root = _root_of(ctx)
    if path is None:
        keys: dict[str, int] = {}
        if DeskDB.exists(root):
            with DeskDB(root) as db:
                keys = db.meta_keys()
        emit(ctx, {"keys": keys}, human=_echo_keys)
        return
    path = path.resolve()
    if not DeskDB.exists(root):
        emit(ctx, {"path": str(path), "meta": []}, human=_echo_fields)
        return
    with DeskDB(root) as db:
        rows = [{**r, "updated": _iso(r["updated"])} for r in db.meta_of(path)]
        data = {"path": db.rel(path), "meta": rows}
    emit(ctx, data, human=_echo_fields)


@cmd.command("rm")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("keys", nargs=-1, required=True)
@click.pass_context
@_handled
def rm(ctx: click.Context, path: Path, keys: tuple[str, ...]) -> None:
    """Remove KEY... from PATH (unknown keys/files are a quiet no-op)."""
    root = _root_of(ctx)
    path = path.resolve()
    if not DeskDB.exists(root):
        emit(ctx, {"path": str(path), "removed": 0, "meta": {}}, human=_echo_file_meta)
        return
    wanted = [_usage_key(k) for k in keys]
    with DeskDB(root) as db:
        removed = db.rm_meta(path, wanted)
        data = {"path": db.rel(path), "removed": removed, "meta": meta_map(db, path)}
    emit(ctx, data, human=_echo_file_meta)


# ------------------------------------------------------------------- find


def _human_find(rows: list[dict[str, Any]]) -> None:
    if not rows:
        click.echo("no files", err=True)
        return
    for row in rows:
        pairs = " ".join(f"{k}={v}" for k, v in row["meta"].items())
        click.echo(f"{row['path']}  {pairs}")


@cmd.command("find")
@click.argument("conditions", nargs=-1, required=True, metavar="CONDITION...")
@click.pass_context
@_handled
def find(ctx: click.Context, conditions: tuple[str, ...]) -> None:
    """List files whose fields satisfy every CONDITION (paths relative to the desk root).

    A condition is KEY OP VALUE with OP one of = != > >= < <= ~ (contains), or
    KEY? (has the field): `vendor=acme`, `total>1000`, `due<2026-11` (ISO
    dates compare chronologically, so a year-month prefix works), `invoice_no~2026`,
    `paid?`. Numbers compare numerically, text case-insensitively.
    JSON: [{path, meta: {key: value}}].
    """
    root = _root_of(ctx)
    rows: list[dict[str, Any]] = []
    if DeskDB.exists(root):
        with DeskDB(root) as db:
            try:
                paths = db.find_by_meta(list(conditions))
            except CarrelInputError as e:
                raise click.UsageError(str(e)) from e
            by_path = db.meta_for_paths(paths)
            rows = [{"path": p, "meta": by_path[p]} for p in paths]
    else:
        try:  # validate the syntax even without a desk, so typos fail loudly
            from carrel.core.db import parse_meta_condition

            for c in conditions:
                parse_meta_condition(c)
        except CarrelInputError as e:
            raise click.UsageError(str(e)) from e
    emit(ctx, rows, human=_human_find)


# ------------------------------------------------------------------- export


def _render_csv(columns: list[str], rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


@cmd.command("export")
@click.option(
    "--key",
    "keys",
    multiple=True,
    metavar="KEY",
    help="Only these columns, in this order (repeatable).",
)
@click.option(
    "-o",
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write to FILE (.json → JSON rows, anything else → CSV) instead of stdout.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing --out file.")
@click.pass_context
@_handled
def export(ctx: click.Context, keys: tuple[str, ...], out: Path | None, force: bool) -> None:
    """Export every file's fields as a table: one row per file, one column per key.

    Without -o the table goes to stdout as CSV (or as JSON rows with --json);
    with -o a summary is printed instead. Rows are sorted by path, columns by
    key (or as given with --key); a missing field is empty. Exit 4 when no desk
    db exists under --root.
    """
    root = _root_of(ctx)
    if not DeskDB.exists(root):
        raise CarrelInputError(
            f"no desk db under {root} (.carrel/carrel.db) — run `{PRODUCT['cli']} meta set` first"
        )
    wanted = [_usage_key(k) for k in keys]
    with DeskDB(root) as db:
        columns, rows = db.meta_table(wanted or None)
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if out is None:
        if as_json:
            click.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            click.echo(_render_csv(columns, rows), nl=False)
        return
    out = out.resolve()
    if out.exists() and not force:
        raise CarrelError(f"refusing to overwrite {out} (use --force)")
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = "json" if out.suffix.lower() == ".json" else "csv"
    text = (
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
        if fmt == "json"
        else _render_csv(columns, rows)
    )
    out.write_text(text, encoding="utf-8", newline="\n")
    summary = {"out": str(out), "format": fmt, "files": len(rows), "keys": columns[1:]}
    emit(
        ctx,
        summary,
        human=lambda d: click.echo(
            f"wrote {d['out']}: {d['files']} file(s), {len(d['keys'])} key(s) [{d['format']}]"
        ),
    )
