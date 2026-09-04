"""carrel search — FTS5 full-text search over the desk index.

Ranking and snippets come from core.db.DeskDB.fts_search (bm25 + snippet()).
--type/--tag filters are applied here by post-filtering the ranked rows
(type from the files table, tags via DeskDB.tags_of), so core stays lean;
when filters are active we over-fetch so `--limit` still fills up.
"""

from __future__ import annotations

import functools
import sqlite3  # exception type only — all db access goes through DeskDB
from pathlib import Path
from typing import Any, Callable

import click

from carrel._product import PRODUCT

from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType
from carrel.core.output import CarrelError, ExitCode, emit, fail

_FILTER_FETCH_MIN = 500  # over-fetch floor when post-filtering


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


def _parse_types(csv: str | None) -> set[str] | None:
    if not csv:
        return None
    wanted = {t.strip().lower() for t in csv.split(",") if t.strip()}
    valid = {ft.value for ft in FileType if ft is not FileType.UNKNOWN}
    unknown = wanted - valid
    if unknown:
        raise click.UsageError(
            f"unknown --type value(s): {', '.join(sorted(unknown))} "
            f"(choose from {', '.join(sorted(valid))})"
        )
    return wanted


def _human_hits(hits: list[dict[str, Any]]) -> None:
    if not hits:
        click.echo("no results", err=True)
        return
    for rank, hit in enumerate(hits, 1):
        click.echo(f"{rank:2}. {hit['path']}  (score {hit['score']:.2f})")
        snippet = " ".join(hit["snippet"].split())
        if snippet:
            click.echo(f"    {snippet}")


@click.command(name="search")
@click.argument("query")
@click.option("--limit", default=20, show_default=True, type=int,
              help="Maximum number of hits.")
@click.option("--type", "types_csv", metavar="T1,T2",
              help="Only these file types, comma-separated (e.g. pdf,md).")
@click.option("--tag", "tags", multiple=True, metavar="TAG",
              help="Only files carrying TAG (repeatable — every TAG must match).")
@click.option("--fail-empty", is_flag=True, help="Exit 5 when there are no hits.")
@click.pass_context
@_handled
def cmd(ctx: click.Context, query: str, limit: int, types_csv: str | None,
        tags: tuple[str, ...], fail_empty: bool) -> None:
    """Full-text search the desk index for QUERY (FTS5 syntax, bm25-ranked).

    Matched terms are bracketed in the snippet. Filters combine with AND.
    JSON output is a list of {"path", "score", "snippet"} (lower bm25 score =
    better match). Run the `index` command first to build the index under --root.
    """
    if limit < 1:
        raise click.UsageError("--limit must be a positive integer")
    root = _root_of(ctx)
    if not DeskDB.exists(root):
        raise CarrelError(
            f"no index under {root} — run `{PRODUCT['cli']} index` there first")

    wanted_types = _parse_types(types_csv)
    wanted_tags = {t.strip().lower() for t in tags if t.strip()}
    filtered = bool(wanted_types or wanted_tags)
    fetch = max(limit * 25, _FILTER_FETCH_MIN) if filtered else limit

    hits: list[dict[str, Any]] = []
    with DeskDB(root) as db:
        try:
            rows = db.fts_search(query, limit=fetch)
        except sqlite3.OperationalError as e:
            raise click.UsageError(f"bad search query {query!r}: {e}") from e
        for row in rows:
            if wanted_types and row["type"] not in wanted_types:
                continue
            if wanted_tags and not wanted_tags <= set(db.tags_of(db.root / row["path"])):
                continue
            hits.append({"path": row["path"], "score": row["score"],
                         "snippet": row["snip"]})
            if len(hits) >= limit:
                break

    if not hits and fail_empty:
        fail("no results", ExitCode.EMPTY)
    emit(ctx, hits, human=_human_hits)
