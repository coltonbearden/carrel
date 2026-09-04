"""carrel note — sidecar notes in the desk db, plus PDF annotations via pypdf.

`add`/`ls` store free-form notes in .carrel/carrel.db (DeskDB), newest first,
ISO timestamps. `pdf` lists a PDF's annotations; `pdf-add` writes a FreeText
annotation with pypdf and verifies pypdf can read it back before reporting
success.
"""

from __future__ import annotations

import functools
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import click

from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, fail


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


def _require_pdf(path: Path) -> None:
    if detect_or_die(path) is not FileType.PDF:
        raise CarrelInputError(f"not a PDF: {path}")


@click.group(name="note")
def cmd() -> None:
    """Attach notes to files (desk db) and annotations to PDFs (pypdf)."""


# ------------------------------------------------------------ sidecar notes


@cmd.command("add")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("text")
@click.pass_context
@_handled
def add(ctx: click.Context, path: Path, text: str) -> None:
    """Attach TEXT as a sidecar note to PATH (stored in the desk db)."""
    path = path.resolve()
    if not path.is_file():
        raise CarrelInputError(f"no such file: {path}")
    with DeskDB(_root_of(ctx)) as db:
        note_id = db.add_note(path, text)
        newest = db.notes_of(path)[0]
        data = {"path": db.rel(path), "id": note_id,
                "created": _iso(newest["created"]), "body": text}
    emit(ctx, data, human=lambda d: click.echo(
        f"note {d['id']} on {d['path']} @ {d['created']}"))


@cmd.command("ls")
@click.argument("path", type=click.Path(path_type=Path))
@click.pass_context
@_handled
def ls(ctx: click.Context, path: Path) -> None:
    """List PATH's sidecar notes, newest first (ISO timestamps)."""
    root = _root_of(ctx)
    path = path.resolve()
    notes: list[dict[str, str]] = []
    if DeskDB.exists(root):
        with DeskDB(root) as db:
            notes = [{"created": _iso(r["created"]), "body": r["body"]}
                     for r in db.notes_of(path)]

    def human(items: list[dict[str, str]]) -> None:
        if not items:
            click.echo("no notes", err=True)
        for n in items:
            click.echo(f"[{n['created']}] {n['body']}")

    emit(ctx, notes, human=human)


# --------------------------------------------------------- pdf annotations


def _read_pdf(path: Path):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        return PdfReader(str(path))
    except PdfReadError as e:
        raise CarrelInputError(f"cannot read PDF {path}: {e}") from e


def _pdf_annotations(path: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for page_no, page in enumerate(_read_pdf(path).pages, 1):
        for ref in page.get("/Annots") or []:
            obj = ref.get_object()
            subtype = str(obj.get("/Subtype", "")).lstrip("/")
            if subtype == "Link":  # navigation plumbing, not a note
                continue
            contents = obj.get("/Contents")
            found.append({"page": page_no, "subtype": subtype,
                          "contents": str(contents) if contents is not None else ""})
    return found


@cmd.command("pdf")
@click.argument("path", type=click.Path(path_type=Path))
@click.pass_context
@_handled
def pdf(ctx: click.Context, path: Path) -> None:
    """List PATH's PDF annotations: page, subtype, contents."""
    path = path.resolve()
    _require_pdf(path)
    annots = _pdf_annotations(path)

    def human(items: list[dict[str, Any]]) -> None:
        if not items:
            click.echo("no annotations", err=True)
        for a in items:
            click.echo(f"p{a['page']}  {a['subtype']}: {a['contents']}")

    emit(ctx, annots, human=human)


@cmd.command("pdf-add")
@click.argument("path", type=click.Path(path_type=Path))
@click.argument("text")
@click.option("--page", default=1, show_default=True, type=int,
              help="1-based page to annotate.")
@click.option("--pos", default="72,72", show_default=True, metavar="X,Y",
              help="Lower-left corner of the note box in PDF points.")
@click.option("-o", "--out", type=click.Path(dir_okay=False, path_type=Path),
              help="Output PDF (default: PATH with an .annotated.pdf suffix; "
                   "pass PATH itself to annotate in place).")
@click.pass_context
@_handled
def pdf_add(ctx: click.Context, path: Path, text: str, page: int, pos: str,
            out: Path | None) -> None:
    """Add TEXT as a FreeText annotation to a PDF page.

    The result is verified by reading the output back with pypdf and checking
    the annotation is listed (same reader the `pdf` subcommand uses).
    """
    from pypdf import PdfWriter
    from pypdf.annotations import FreeText

    path = path.resolve()
    _require_pdf(path)
    try:
        x_s, y_s = pos.split(",", 1)
        x, y = float(x_s), float(y_s)
    except ValueError:
        raise click.UsageError(f"bad --pos {pos!r} (expected e.g. '72,720')") from None

    total = len(_read_pdf(path).pages)
    if not 1 <= page <= total:
        raise CarrelInputError(f"--page {page} out of range: document has {total} page(s)")

    out = (out or path.with_name(f"{path.stem}.annotated.pdf")).resolve()
    writer = PdfWriter(clone_from=str(path))
    annotation = FreeText(text=text, rect=(x, y, x + 240, y + 48),
                          font="Helvetica", font_size="12pt",
                          font_color="000000", border_color="000000",
                          background_color="ffffff")
    writer.add_annotation(page_number=page - 1, annotation=annotation)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        writer.write(fh)

    listed = [a for a in _pdf_annotations(out)
              if a["page"] == page and a["contents"] == text]
    if not listed:
        raise CarrelError(f"wrote {out} but could not read the annotation back")

    data = {"input": str(path), "output": str(out), "page": page,
            "subtype": listed[0]["subtype"], "contents": text}
    emit(ctx, data, human=lambda d: click.echo(
        f"annotated p{d['page']} of {d['input']} -> {d['output']}"))
