"""carrel extract-images — pull embedded/referenced images out of a file.

Routes by detected type:

- pdf  → `pdfimages -png`; frames smaller than --min-size on either
         edge are discarded.
- ico  → `icotool -x` (icoutils); when icotool is absent, degrades to a
         Pillow frame dump (every stored size as PNG).
- html → copies local `<img src>` targets that resolve to existing
         files relative to the document. Remote references (http/https,
         protocol-relative, data: URIs) are deliberately never fetched —
         this command does no network I/O.
"""

from __future__ import annotations

import functools
import shutil
import urllib.parse
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

DEFAULT_MIN_SIZE = 32


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


# --------------------------------------------------------------------------
# pdf


def _extract_pdf(src: Path, out_dir: Path, min_size: int) -> list[Path]:
    from PIL import Image

    prefix = out_dir / src.stem
    proc = adapters.run("pdfimages", "-png", str(src), str(prefix))
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        raise CarrelError(f"pdfimages failed ({proc.returncode}): {err[0] if err else '?'}")
    kept: list[Path] = []
    for path in sorted(out_dir.glob(f"{src.stem}-*.png")):
        try:
            with Image.open(path) as im:
                w, h = im.size
        except OSError:
            path.unlink(missing_ok=True)
            continue
        if min(w, h) < min_size:
            path.unlink()  # filter tiny decorations/artifacts
        else:
            kept.append(path)
    return kept


# --------------------------------------------------------------------------
# ico


def _extract_ico(src: Path, out_dir: Path) -> list[Path]:
    if adapters.have("icotool"):
        before = set(out_dir.iterdir())
        proc = adapters.run("icotool", "-x", "-o", str(out_dir), str(src))
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            raise CarrelError(f"icotool failed ({proc.returncode}): {err[0] if err else '?'}")
        return sorted(set(out_dir.iterdir()) - before)
    # degrade: Pillow frame dump (one PNG per stored size)
    from PIL import Image

    with Image.open(src) as probe:
        sizes = sorted(probe.info.get("sizes") or {probe.size})
    extracted: list[Path] = []
    for w, h in sizes:
        with Image.open(src) as im:
            im.size = (w, h)  # type: ignore[misc]  # IcoImageFile: selecting a frame
            im.load()
            dest = out_dir / f"{src.stem}_{w}x{h}.png"
            im.save(dest)
        extracted.append(dest)
    return extracted


# --------------------------------------------------------------------------
# html


class _ImgCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            for key, value in attrs:
                if key == "src" and value:
                    self.srcs.append(value)


def _extract_html(src: Path, out_dir: Path) -> list[Path]:
    parser = _ImgCollector()
    parser.feed(src.read_text(errors="replace"))
    extracted: list[Path] = []
    seen: set[Path] = set()
    for ref in parser.srcs:
        parts = urllib.parse.urlsplit(ref)
        if parts.scheme or parts.netloc:  # http(s)/data:/protocol-relative: never fetched
            continue
        rel = urllib.parse.unquote(parts.path)
        if not rel:
            continue
        candidate = Path(rel) if Path(rel).is_absolute() else src.parent / rel
        if not candidate.is_file():
            continue
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        dest = out_dir / candidate.name
        shutil.copy2(candidate, dest)
        extracted.append(dest)
    return extracted


# --------------------------------------------------------------------------
# library entry point + CLI


def extract_images_file(
    src: Path | str, out_dir: Path | str | None = None, min_size: int = DEFAULT_MIN_SIZE
) -> dict[str, Any]:
    """Extract images from src; returns {"src", "out_dir", "count", "extracted"}."""
    src = Path(src)
    ftype = detect_or_die(src)
    out_dir = Path(out_dir) if out_dir else src.parent / f"{src.stem}-images"
    out_dir.mkdir(parents=True, exist_ok=True)

    if ftype is FileType.PDF:
        extracted = _extract_pdf(src, out_dir, min_size)
    elif ftype is FileType.ICO:
        extracted = _extract_ico(src, out_dir)
    elif ftype is FileType.HTML:
        extracted = _extract_html(src, out_dir)
    else:
        raise CarrelInputError(
            f"cannot extract images from {ftype.value} files: {src} (supported: pdf, ico, html)"
        )
    return {
        "src": str(src),
        "out_dir": str(out_dir),
        "count": len(extracted),
        "extracted": [str(p) for p in extracted],
    }


def _human(result: dict[str, Any]) -> None:
    for path in result["extracted"]:
        click.echo(path)
    click.echo(f"{result['count']} image(s) -> {result['out_dir']}")


@click.command(name="extract-images")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory [default: <SRC>-images next to the source].",
)
@click.option(
    "--min-size",
    type=click.IntRange(min=1),
    default=DEFAULT_MIN_SIZE,
    show_default=True,
    help="pdf mode: discard images smaller than this on either edge.",
)
@click.pass_context
@_handled
def cmd(ctx: click.Context, src: Path, out_dir: Path | None, min_size: int) -> None:
    """Extract images embedded in / referenced by SRC (pdf, ico, html).

    pdf uses pdfimages, ico uses icotool (or a Pillow fallback), html
    copies local <img src> files that exist next to the document —
    remote URLs are never fetched. With --json, prints one JSON object
    {"src", "out_dir", "count", "extracted"}.
    """
    emit(ctx, extract_images_file(src, out_dir, min_size=min_size), human=_human)
