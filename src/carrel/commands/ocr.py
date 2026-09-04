"""carrel ocr — OCR images and PDFs into text (txt/md) or searchable PDFs.

Images (jpg/png) run through tesseract; PDFs run through ocrmypdf with
--skip-text by default so born-digital pages pass through untouched (--redo
maps to ocrmypdf --force-ocr). The plain function `ocr_file()` is the reusable
entry point for the TUI/MCP; the click command `cmd` wraps it with the
overwrite policy and output plumbing.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail, progress

TARGETS = ("txt", "pdf", "md")

# ocrmypdf exit codes we care about (see ocrmypdf.exceptions.ExitCode)
_OCRMYPDF_OK = (0, 10)  # 10 = success, but PDF/A conversion had warnings
_OCRMYPDF_PRIOR_TEXT = 6  # input already carries a text layer

# stderr fingerprints of a missing tesseract language pack
#   tesseract: "Failed loading language 'xyz'"
#   ocrmypdf : "OCR engine does not have language data for the following
#               requested languages: xyz"
_LANG_ERR_MARKERS = (
    "failed loading language",
    "requested languages",
    "does not have language data",
)


class LanguagePackError(CarrelError):
    """OCR language data missing — an installable dependency → exit 3."""

    exit_code = ExitCode.MISSING_DEP


# ------------------------------------------------------------------ engines


def _engine_error(engine: str, proc: subprocess.CompletedProcess[str], lang: str) -> CarrelError:
    detail = (proc.stderr or proc.stdout or "").strip()
    msg = f"{engine} failed (rc={proc.returncode}): {detail}"
    if any(marker in detail.lower() for marker in _LANG_ERR_MARKERS):
        hints = "\n".join(
            f"  hint: sudo apt install tesseract-ocr-{code}" for code in lang.split("+")
        )
        return LanguagePackError(f"{msg}\n{hints}")
    return CarrelError(msg)


def _tesseract_text(src: Path, lang: str) -> str:
    proc = adapters.run("tesseract", str(src), "stdout", "-l", lang, timeout=300)
    if proc.returncode != 0:
        raise _engine_error("tesseract", proc, lang)
    return proc.stdout


def _tesseract_pdf(src: Path, dest: Path, lang: str) -> None:
    with tempfile.TemporaryDirectory(prefix="carrel-ocr-") as td:
        base = Path(td) / "ocr"  # tesseract appends .pdf itself
        proc = adapters.run("tesseract", str(src), str(base), "-l", lang, "pdf", timeout=300)
        if proc.returncode != 0:
            raise _engine_error("tesseract", proc, lang)
        shutil.move(f"{base}.pdf", dest)


def _ocrmypdf(src: Path, dest: Path, lang: str, redo: bool) -> None:
    mode = "--force-ocr" if redo else "--skip-text"
    proc = adapters.run(
        "ocrmypdf", mode, "-l", lang, "--output-type", "pdf", str(src), str(dest), timeout=600
    )
    if proc.returncode == _OCRMYPDF_PRIOR_TEXT:
        raise CarrelError(
            f"{src} already has a text layer — nothing to OCR (pass --redo to re-OCR it anyway)"
        )
    if proc.returncode not in _OCRMYPDF_OK:
        raise _engine_error("ocrmypdf", proc, lang)


def _pdf_chars(pdf: Path) -> int | None:
    """Extracted-character count of a PDF; None when pdftotext is unavailable."""
    if not adapters.have("pdftotext"):
        return None
    proc = adapters.run("pdftotext", "-layout", str(pdf), "-")
    return len(proc.stdout) if proc.returncode == 0 else None


# --------------------------------------------------------------- public API


def default_dest(src: Path, to: str) -> Path:
    """SRC with the target extension; SRC.ocr.pdf when that would equal SRC."""
    dest = src.with_suffix(f".{to}")
    return dest if dest != src else src.with_name(f"{src.stem}.ocr.{to}")


def ocr_file(
    src: Path | str,
    dest: Path | str | None = None,
    lang: str = "eng",
    to: str = "txt",
    redo: bool = False,
) -> dict[str, Any]:
    """OCR `src` (pdf/jpg/png) into `dest`; returns the result record.

    Record shape: {"src", "dest", "engine": "ocrmypdf"|"tesseract",
    "chars": <len of extracted text>} — `chars` is None only for PDF output
    when pdftotext is unavailable to count it.

    Writes `dest` unconditionally — overwrite protection (--force) is the
    CLI wrapper's job so TUI/MCP callers keep full control.
    """
    src = Path(src)
    if to not in TARGETS:
        raise CarrelInputError(
            f"unsupported OCR target {to!r} (expected one of: {', '.join(TARGETS)})"
        )
    ftype = detect_or_die(src)
    if ftype not in (FileType.PDF, FileType.JPG, FileType.PNG):
        raise CarrelInputError(f"ocr supports pdf/jpg/png input, got {ftype.value}: {src}")
    dest = Path(dest) if dest is not None else default_dest(src, to)
    dest.parent.mkdir(parents=True, exist_ok=True)

    chars: int | None
    if ftype is FileType.PDF:
        engine = "ocrmypdf"
        if to == "pdf":
            _ocrmypdf(src, dest, lang, redo)
            chars = _pdf_chars(dest)
        else:  # txt / md: OCR to a scratch pdf, then pull its text layer out
            with tempfile.TemporaryDirectory(prefix="carrel-ocr-") as td:
                ocred = Path(td) / "ocr.pdf"
                _ocrmypdf(src, ocred, lang, redo)
                proc = adapters.run("pdftotext", "-layout", str(ocred), "-")
                if proc.returncode != 0:
                    raise CarrelError(
                        f"pdftotext failed on the OCRed pdf (rc={proc.returncode}): "
                        f"{(proc.stderr or '').strip()}"
                    )
                dest.write_text(proc.stdout, encoding="utf-8")
                chars = len(proc.stdout)
    else:
        engine = "tesseract"
        if to == "pdf":
            _tesseract_pdf(src, dest, lang)
            chars = _pdf_chars(dest)
        else:  # txt / md carry the same recognized text
            text = _tesseract_text(src, lang)
            dest.write_text(text, encoding="utf-8")
            chars = len(text)

    return {"src": str(src), "dest": str(dest), "engine": engine, "chars": chars}


# ----------------------------------------------------------------- CLI shell


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


def _human(record: dict[str, Any]) -> None:
    chars = record["chars"]
    click.echo(f"ocr [{record['engine']}]: {record['src']}")
    click.echo(f"  characters: {'?' if chars is None else chars}")
    click.echo(f"  wrote: {record['dest']}")


@click.command(name="ocr")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--out",
    type=click.Path(path_type=Path),
    help="Output file. Default: SRC with the target extension (SRC.ocr.pdf for pdf → pdf).",
)
@click.option(
    "--lang",
    default="eng",
    show_default=True,
    metavar="LANG",
    help="OCR language(s), tesseract codes, e.g. eng or eng+deu.",
)
@click.option(
    "--to",
    type=click.Choice(TARGETS),
    default="txt",
    show_default=True,
    help="Output: extracted text (txt/md) or a searchable PDF.",
)
@click.option(
    "--redo",
    is_flag=True,
    help="Re-OCR PDF pages even if they already have text "
    "(ocrmypdf --force-ocr; default skips them).",
)
@click.option("--force", is_flag=True, help="Allow overwriting an existing output file.")
@click.pass_context
@_handled
def cmd(
    ctx: click.Context, src: Path, out: Path | None, lang: str, to: str, redo: bool, force: bool
) -> None:
    """OCR an image or PDF into text (txt/md) or a searchable PDF.

    Images (jpg/png) run through tesseract; PDFs through ocrmypdf, which
    passes born-digital pages through untouched unless --redo is given.
    """
    detect_or_die(src)  # report bad input before any overwrite complaint
    dest = out or default_dest(src, to)
    if dest.exists() and not force:
        raise CarrelError(f"refusing to overwrite existing file: {dest} (pass --force)")
    progress(f"ocr: {src} ({lang}) → {dest} …", ctx)
    record = ocr_file(src, dest, lang=lang, to=to, redo=redo)
    emit(ctx, record, human=_human)
