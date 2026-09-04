"""carrel organize — sort a directory's files into subdirectories.

Operates on the files directly inside DIRECTORY (non-recursive; hidden files
and subdirectories are left alone). Default is a dry-run that prints the
plan; nothing moves without --apply. Destinations never overwrite: name
collisions get a ``-1``, ``-2``, … suffix before the extension.

--by type mapping (also in --help):
    pdf            -> pdf/
    jpg, png, ico  -> images/
    json, xml, csv -> data/
    md, txt, html  -> docs/
    anything else  -> skipped
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

TYPE_DIRS: dict[FileType, str] = {
    FileType.PDF: "pdf",
    FileType.JPG: "images",
    FileType.PNG: "images",
    FileType.ICO: "images",
    FileType.JSON: "data",
    FileType.XML: "data",
    FileType.CSV: "data",
    FileType.MD: "docs",
    FileType.TXT: "docs",
    FileType.HTML: "docs",
}
TYPE_CATEGORIES = ("pdf", "images", "data", "docs")


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


def _exif_year_month(path: Path) -> tuple[int, int] | None:
    """(year, month) from EXIF DateTimeOriginal, or None when absent/unreadable."""
    try:
        from PIL import ExifTags, Image

        with Image.open(path) as img:
            exif = img.getexif().get_ifd(ExifTags.IFD.Exif)
            raw = exif.get(ExifTags.Base.DateTimeOriginal)
        if not raw:
            return None
        date = str(raw).split(" ")[0]
        year, month, _day = (int(part) for part in date.split(":"))
        return year, month
    except Exception:  # noqa: BLE001 — malformed EXIF must not break the plan
        return None


def _mtime_year_month(path: Path) -> tuple[int, int]:
    dt = datetime.fromtimestamp(path.stat().st_mtime)
    return dt.year, dt.month


def _bucket(src: Path, by: str, into: dict[str, str]) -> tuple[str | None, str | None]:
    """(relative destination dir, skip reason). Dir is None when skipped."""
    ftype = detect(src)
    if by == "type":
        category = TYPE_DIRS.get(ftype)
        if category is None:
            return None, "unsupported type"
        return into.get(category, category), None
    if by == "exif-date":
        if not ftype.is_image:
            return None, "not an image (exif-date organizes images only)"
        year, month = _exif_year_month(src) or _mtime_year_month(src)
    else:  # date
        year, month = _mtime_year_month(src)
    return f"{year:04d}/{month:02d}", None


def _uncollide(dest: Path, taken: set[Path]) -> Path:
    """First non-existing, not-yet-planned variant: name.ext, name-1.ext, …"""
    candidate, n = dest, 0
    while candidate.exists() or candidate in taken:
        n += 1
        candidate = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
    return candidate


def _build_plan(directory: Path, by: str, into: dict[str, str]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    taken: set[Path] = set()
    files = sorted(
        (p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.name,
    )
    for src in files:
        subdir, reason = _bucket(src, by, into)
        if subdir is None:
            plan.append({"src": str(src), "dest": None, "action": "skip", "reason": reason})
            continue
        dest = _uncollide(directory / subdir / src.name, taken)
        taken.add(dest)
        plan.append({"src": str(src), "dest": str(dest), "action": "move"})
    return plan


def _human_plan(applied: bool) -> Callable[[list[dict[str, Any]]], None]:
    def _print(plan: list[dict[str, Any]]) -> None:
        moves = 0
        for entry in plan:
            if entry["action"] == "skip":
                click.echo(f"skip  {entry['src']}  ({entry['reason']})")
            else:
                moves += 1
                verb = "moved" if applied else "move "
                click.echo(f"{verb} {entry['src']} -> {entry['dest']}")
        if applied:
            click.echo(f"{moves} file(s) moved.")
        else:
            click.echo(f"dry-run: {moves} move(s) planned — re-run with --apply to execute.")

    return _print


@click.command(name="organize")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option(
    "--by",
    "by",
    type=click.Choice(["type", "date", "exif-date"]),
    default="type",
    show_default=True,
    help="Grouping: 'type' -> pdf/, images/ (jpg, png, ico), "
    "data/ (json, xml, csv), docs/ (md, txt, html); "
    "'date' -> YYYY/MM from mtime; 'exif-date' -> YYYY/MM from "
    "EXIF DateTimeOriginal, mtime fallback (images only; other "
    "files are skipped).",
)
@click.option(
    "--into",
    "into_",
    multiple=True,
    metavar="CATEGORY=DIR",
    help="Override a type category's destination subdir, e.g. "
    "--into images=pics (only with --by type; repeatable).",
)
@click.option(
    "--apply/--dry-run",
    "apply_",
    default=False,
    help="Execute the moves. Default is a dry-run that only prints the plan.",
)
@click.pass_context
@_handled
def cmd(ctx: click.Context, directory: Path, by: str, into_: tuple[str, ...], apply_: bool) -> None:
    """Plan (default) or perform (--apply) sorting DIRECTORY's files.

    Only files directly inside DIRECTORY are considered; subdirectories and
    hidden files stay put. Existing files are never overwritten — colliding
    names get a -1, -2, … suffix. JSON output is a list of
    {src, dest, action} ('move' planned, 'moved' executed, 'skip').
    """
    directory = directory.resolve()
    if not directory.is_dir():
        raise CarrelInputError(f"no such directory: {directory}")

    into: dict[str, str] = {}
    for spec in into_:
        category, sep, dest = spec.partition("=")
        if not sep or not dest or category not in TYPE_CATEGORIES:
            raise click.UsageError(
                f"--into expects CATEGORY=DIR with CATEGORY one of "
                f"{', '.join(TYPE_CATEGORIES)} (got: {spec!r})"
            )
        into[category] = dest
    if into and by != "type":
        raise click.UsageError("--into only applies to --by type")

    plan = _build_plan(directory, by, into)

    if apply_:
        for entry in plan:
            if entry["action"] != "move":
                continue
            dest_path = Path(entry["dest"])
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(entry["src"], dest_path)
            entry["action"] = "moved"

    emit(ctx, plan, human=_human_plan(applied=apply_))
