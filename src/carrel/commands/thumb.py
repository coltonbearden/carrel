"""carrel thumb — thumbnails for PDFs, images, and HTML pages.

`thumb_file()` is the library entry point (reused by the desk TUI); the
click command `cmd` is a thin wrapper around it.

Routes by detected type:

- pdf   → pdftoppm renders the first page, long side scaled to --size.
- png/jpg → Pillow thumbnail (aspect preserved, never upscaled, no padding).
- ico   → Pillow opens the largest frame by default, then thumbnails it.
- html  → weasyprint renders to a temp PDF, then the pdf path applies
          (both binaries required; each missing one degrades with its
          own install hint, exit 3).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit

FORMATS = ("png", "jpg")
DEFAULT_SIZE = 256


def _pdf_thumb(src: Path, dest: Path, size: int) -> None:
    """First PDF page → dest, long side scaled to `size` (via pdftoppm)."""
    flag = "-jpeg" if dest.suffix == ".jpg" else "-png"
    prefix = dest.parent / dest.stem  # pdftoppm appends the extension itself
    proc = adapters.run(
        "pdftoppm",
        flag,
        "-f",
        "1",
        "-l",
        "1",
        "-singlefile",
        "-scale-to",
        str(size),
        str(src),
        str(prefix),
    )
    if proc.returncode != 0 or not dest.exists():
        err = (proc.stderr or "").strip().splitlines()
        raise CarrelError(f"pdftoppm failed ({proc.returncode}): {err[0] if err else '?'}")


def _image_thumb(src: Path, dest: Path, size: int) -> None:
    from PIL import Image

    with Image.open(src) as im:  # .ico: Pillow picks the largest frame by default
        im.load()
        thumb = im.copy()
    thumb.thumbnail((size, size))  # preserves aspect, never upscales
    if dest.suffix == ".jpg" and thumb.mode not in ("RGB", "L"):
        thumb = thumb.convert("RGB")
    thumb.save(dest)


def _html_thumb(src: Path, dest: Path, size: int) -> None:
    adapters.require("weasyprint")  # each missing link degrades with its own hint
    adapters.require("pdftoppm")
    with tempfile.TemporaryDirectory(prefix="carrel-thumb-") as td:
        pdf = Path(td) / f"{src.stem}.pdf"
        proc = adapters.run("weasyprint", str(src), str(pdf), timeout=300)
        if proc.returncode != 0 or not pdf.exists():
            err = (proc.stderr or "").strip().splitlines()
            raise CarrelError(f"weasyprint failed ({proc.returncode}): {err[-1] if err else '?'}")
        _pdf_thumb(pdf, dest, size)


def thumb_file(
    src: Path | str, out_dir: Path | str, size: int = DEFAULT_SIZE, fmt: str = "png"
) -> dict[str, Any]:
    """Thumbnail one file into out_dir; returns {"src", "thumb", "w", "h"}.

    Raises CarrelInputError (exit 4) for unsupported input, CarrelError
    (exit 1) on tool failure, MissingDependencyError (exit 3) when a
    needed binary is absent.
    """
    src, out_dir = Path(src), Path(out_dir)
    if fmt not in FORMATS:
        raise CarrelInputError(
            f"unsupported thumbnail format '{fmt}' (choose from: {', '.join(FORMATS)})"
        )
    if size < 1:
        raise CarrelInputError(f"--size must be positive (got {size})")
    ftype = detect_or_die(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{src.stem}.{fmt}"

    if ftype is FileType.PDF:
        _pdf_thumb(src, dest, size)
    elif ftype.is_image:
        _image_thumb(src, dest, size)
    elif ftype is FileType.HTML:
        _html_thumb(src, dest, size)
    else:
        raise CarrelInputError(
            f"cannot thumbnail {ftype.value} files: {src} (supported: pdf, png, jpg, ico, html)"
        )

    from PIL import Image

    with Image.open(dest) as im:
        w, h = im.size
    return {"src": str(src), "thumb": str(dest), "w": w, "h": h}


def _human(results: list[dict[str, Any]]) -> None:
    for r in results:
        if r.get("thumb"):
            click.echo(f"{r['src']} -> {r['thumb']}  ({r['w']}x{r['h']})")


@click.command(name="thumb")
@click.argument(
    "sources", nargs=-1, required=True, metavar="SRC...", type=click.Path(path_type=Path)
)
@click.option(
    "--size",
    type=click.IntRange(min=1),
    default=DEFAULT_SIZE,
    show_default=True,
    help="Maximum edge length in pixels.",
)
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("./thumbs"),
    show_default=True,
    help="Directory for the thumbnails.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(FORMATS),
    default="png",
    show_default=True,
    help="Thumbnail image format.",
)
@click.pass_context
def cmd(ctx: click.Context, sources: tuple[Path, ...], size: int, out_dir: Path, fmt: str) -> None:
    """Create thumbnails for SRC... (pdf, png, jpg, ico, html).

    Thumbnails land in --out-dir as <name>.<format>, aspect preserved,
    never larger than --size on either edge. With --json, prints one
    JSON array of {"src", "thumb", "w", "h"} records.
    """
    results: list[dict[str, Any]] = []
    first_err = 0
    for src in sources:
        try:
            results.append(thumb_file(src, out_dir, size=size, fmt=fmt))
        except CarrelError as e:
            if ctx.obj and ctx.obj.get("debug"):
                raise
            results.append({"src": str(src), "thumb": None, "error": str(e)})
            click.echo(f"error: {e}", err=True)
            first_err = first_err or int(e.exit_code)
    emit(ctx, results, human=_human)
    if first_err:
        sys.exit(first_err)
