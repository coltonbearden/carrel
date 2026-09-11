"""carrel tag — tag files in the desk db (add / rm / ls / find).

Tags are normalized to lowercase by DeskDB. `add` auto-registers the file in
the files table; read-only subcommands never create a .carrel directory as a
side effect (they return empty results when no desk db exists yet).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from carrel.core.db import DeskDB
from carrel.core.output import CarrelInputError, emit, handled, root_of


def _echo_file_tags(data: dict[str, Any]) -> None:
    click.echo(f"{data['path']}: {', '.join(data['tags']) or '(no tags)'}")


@click.group(name="tag")
def cmd() -> None:
    """Tag files in the desk db (.carrel/carrel.db under --root)."""


@cmd.command("add")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("tags", nargs=-1, required=True)
@click.pass_context
@handled
def add(ctx: click.Context, path: Path, tags: tuple[str, ...]) -> None:
    """Add TAG... to PATH (registers the file in the desk db if needed)."""
    path = path.resolve()
    if not path.is_file():
        raise CarrelInputError(f"no such file: {path}")
    with DeskDB(root_of(ctx)) as db:
        db.add_tags(path, list(tags))
        data = {"path": db.rel(path), "tags": db.tags_of(path)}
    emit(ctx, data, human=_echo_file_tags)


@cmd.command("rm")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("tags", nargs=-1, required=True)
@click.pass_context
@handled
def rm(ctx: click.Context, path: Path, tags: tuple[str, ...]) -> None:
    """Remove TAG... from PATH (unknown tags/files are a quiet no-op)."""
    root = root_of(ctx)
    path = path.resolve()
    if not DeskDB.exists(root):
        emit(ctx, {"path": str(path), "tags": []}, human=_echo_file_tags)
        return
    with DeskDB(root) as db:
        db.rm_tags(path, list(tags))
        data = {"path": db.rel(path), "tags": db.tags_of(path)}
    emit(ctx, data, human=_echo_file_tags)


def _echo_tag_counts(data: dict[str, Any]) -> None:
    if not data["tags"]:
        click.echo("no tags", err=True)
        return
    width = max(len(t) for t in data["tags"])
    for tag, count in data["tags"].items():
        click.echo(f"{tag:<{width}}  {count} file(s)")


@cmd.command("ls")
@click.argument("path", required=False, type=click.Path(path_type=Path))
@click.pass_context
@handled
def ls(ctx: click.Context, path: Path | None) -> None:
    """List tags of PATH, or (without PATH) every tag with its file count."""
    root = root_of(ctx)
    if path is not None:
        path = path.resolve()
        if not DeskDB.exists(root):
            emit(ctx, {"path": str(path), "tags": []}, human=_echo_file_tags)
            return
        with DeskDB(root) as db:
            data = {"path": db.rel(path), "tags": db.tags_of(path)}
        emit(ctx, data, human=_echo_file_tags)
        return
    if not DeskDB.exists(root):
        emit(ctx, {"tags": {}}, human=_echo_tag_counts)
        return
    with DeskDB(root) as db:
        rows = db.conn.execute(
            "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY tag"
        ).fetchall()
    emit(ctx, {"tags": {r["tag"]: r["n"] for r in rows}}, human=_echo_tag_counts)


@cmd.command("find")
@click.argument("tags", nargs=-1, required=True)
@click.pass_context
@handled
def find(ctx: click.Context, tags: tuple[str, ...]) -> None:
    """List files carrying ALL of TAG... (paths relative to the desk root)."""
    root = root_of(ctx)
    paths: list[str] = []
    if DeskDB.exists(root):
        with DeskDB(root) as db:
            paths = db.find_by_tags(list(tags))

    def human(items: list[str]) -> None:
        if not items:
            click.echo("no files", err=True)
        for p in items:
            click.echo(p)

    emit(ctx, paths, human=human)
