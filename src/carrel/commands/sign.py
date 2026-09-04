"""carrel sign — stamp PDFs, and create/verify sha256 manifests (optionally gpg-signed).

`stamp` draws a reportlab overlay (text and/or a signature image) and merges it
onto the chosen page with pypdf. `manifest` writes sha256sum-format lines for
files (directories recurse); `--gpg` adds a detached armored signature via the
gpg adapter. `verify` recomputes every hash — and checks the .asc signature
when one sits next to the manifest — exiting 1 on any mismatch.
"""

from __future__ import annotations

import functools
import getpass
import hashlib
import io
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail, progress

MARGIN = 36.0  # pt
FONT, FONT_SIZE = "Helvetica", 12.0
IMAGE_WIDTH = 144.0  # pt (2 inches) for --image overlays
GAP = 6.0

POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")

_MANIFEST_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](.+)$")


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


@click.group(name="sign")
def cmd() -> None:
    """Sign things: stamp PDFs, hash manifests, verify both."""


# ---------------------------------------------------------------------- stamp


def _parse_page(spec: str, total: int) -> int:
    """'first' | 'last' | 1-based number → 0-based index."""
    if spec == "last":
        return total - 1
    if spec == "first":
        return 0
    try:
        number = int(spec)
    except ValueError:
        raise click.UsageError(
            f"bad --page {spec!r} (expected 'first', 'last' or a number)"
        ) from None
    if not 1 <= number <= total:
        raise CarrelInputError(f"--page {number} out of range: document has {total} page(s)")
    return number - 1


def _overlay_pdf(page_w: float, page_h: float, text: str, image: Path | None, pos: str) -> bytes:
    """One-page PDF with the stamp block anchored at a page corner."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    img_w = img_h = 0.0
    if image is not None:
        from PIL import Image

        with Image.open(image) as img:
            native_w, native_h = img.size
        img_w = IMAGE_WIDTH
        img_h = IMAGE_WIDTH * native_h / native_w

    text_w = stringWidth(text, FONT, FONT_SIZE)
    block_h = FONT_SIZE + ((GAP + img_h) if image else 0.0)
    y_base = MARGIN if pos.startswith("bottom") else page_h - MARGIN - block_h

    def x_for(width: float) -> float:
        return MARGIN if pos.endswith("left") else page_w - MARGIN - width

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setFont(FONT, FONT_SIZE)
    c.drawString(x_for(text_w), y_base, text)
    if image is not None:
        c.drawImage(
            ImageReader(str(image)),
            x_for(img_w),
            y_base + FONT_SIZE + GAP,
            width=img_w,
            height=img_h,
            mask="auto",
        )
    c.showPage()
    c.save()
    return buf.getvalue()


@cmd.command("stamp")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--text",
    "stamp_text",
    metavar="TEXT",
    help='Stamp text. Default: "Signed by <user> on <ISO date>".',
)
@click.option(
    "--image",
    type=click.Path(path_type=Path),
    help="Signature image (png/jpg) drawn above the text.",
)
@click.option(
    "--page",
    "page_spec",
    default="last",
    show_default=True,
    metavar="PAGE",
    help="Page to stamp: 'first', 'last' or a 1-based number.",
)
@click.option(
    "--pos",
    type=click.Choice(POSITIONS),
    default="bottom-right",
    show_default=True,
    help="Page corner for the stamp.",
)
@click.option(
    "-o", "--out", type=click.Path(path_type=Path), help="Output file. Default: SRC.signed.pdf."
)
@click.option("--force", is_flag=True, help="Allow overwriting an existing output file.")
@click.pass_context
@_handled
def stamp(
    ctx: click.Context,
    src: Path,
    stamp_text: str | None,
    image: Path | None,
    page_spec: str,
    pos: str,
    out: Path | None,
    force: bool,
) -> None:
    """Stamp a visible signature block onto a PDF page."""
    from pypdf import PdfReader, PdfWriter

    if detect_or_die(src) is not FileType.PDF:
        raise CarrelInputError(f"sign stamp needs a pdf, got: {src}")
    if image is not None and detect_or_die(image) not in (FileType.PNG, FileType.JPG):
        raise CarrelInputError(f"--image must be a png/jpg, got: {image}")
    text = stamp_text or f"Signed by {getpass.getuser()} on {date.today().isoformat()}"

    dest = out or src.with_name(f"{src.stem}.signed.pdf")
    if dest.exists() and not force:
        raise CarrelError(f"refusing to overwrite existing file: {dest} (pass --force)")

    writer = PdfWriter(clone_from=str(src))
    index = _parse_page(page_spec, len(writer.pages))
    target_page = writer.pages[index]
    box = target_page.mediabox
    overlay_bytes = _overlay_pdf(float(box.width), float(box.height), text, image, pos)
    overlay = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
    target_page.merge_page(overlay)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        writer.write(fh)

    record = {
        "action": "sign-stamp",
        "src": str(src),
        "dest": str(dest),
        "page": index + 1,
        "pos": pos,
        "text": text,
        "image": str(image) if image else None,
    }
    emit(
        ctx,
        record,
        human=lambda r: click.echo(
            f"stamped page {r['page']} ({r['pos']}): {r['text']!r}\n  wrote: {r['dest']}"
        ),
    )


# ------------------------------------------------------------------- manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_entry_path(target: Path, manifest_dir: Path) -> str:
    """Path as written in the manifest: relative to the manifest when possible."""
    try:
        return str(target.resolve().relative_to(manifest_dir.resolve()))
    except ValueError:
        return str(target.resolve())


def _collect_files(paths: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            raise CarrelInputError(f"no such file: {path}")
    if not files:
        raise CarrelInputError("no files to hash")
    return files


def _gpg_sign(manifest: Path, key: str | None) -> Path:
    asc = manifest.with_name(manifest.name + ".asc")
    args = ["--batch", "--yes", "--armor"]
    if key:
        args += ["--local-user", key]
    args += ["--output", str(asc), "--detach-sign", str(manifest)]
    proc = adapters.run("gpg", *args)
    if proc.returncode != 0:
        raise CarrelError(
            f"gpg signing failed (rc={proc.returncode}): {(proc.stderr or '').strip()}"
        )
    return asc


@cmd.command("manifest")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--out",
    type=click.Path(path_type=Path),
    default=Path("MANIFEST.sha256"),
    show_default=True,
    help="Manifest file to write (sha256sum format).",
)
@click.option(
    "--gpg", "with_gpg", is_flag=True, help="Also write a detached armored signature (OUT.asc)."
)
@click.option("--key", metavar="ID", help="gpg key id/email to sign with (implies --gpg).")
@click.option("--force", is_flag=True, help="Allow overwriting an existing manifest.")
@click.pass_context
@_handled
def manifest(
    ctx: click.Context,
    paths: tuple[Path, ...],
    out: Path,
    with_gpg: bool,
    key: str | None,
    force: bool,
) -> None:
    """Write a sha256 manifest for PATHS (directories recurse)."""
    if out.exists() and not force:
        raise CarrelError(f"refusing to overwrite existing file: {out} (pass --force)")
    out_abs = out.resolve()
    files = [
        f
        for f in _collect_files(paths)
        if f.resolve() not in (out_abs, out_abs.with_suffix(out_abs.suffix + ".asc"))
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{_sha256(f)}  {_manifest_entry_path(f, out.parent)}" for f in files]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    asc: Path | None = None
    if with_gpg or key:
        progress(f"gpg-signing {out} …", ctx)
        asc = _gpg_sign(out, key)

    record = {
        "action": "sign-manifest",
        "manifest": str(out),
        "files": len(files),
        "signature": str(asc) if asc else None,
    }
    emit(
        ctx,
        record,
        human=lambda r: click.echo(
            f"manifest: {r['files']} file(s) → {r['manifest']}"
            + (f"\n  signature: {r['signature']}" if r["signature"] else "")
        ),
    )


# --------------------------------------------------------------------- verify


@cmd.command("verify")
@click.argument("manifest_path", metavar="MANIFEST", type=click.Path(path_type=Path))
@click.pass_context
@_handled
def verify(ctx: click.Context, manifest_path: Path) -> None:
    """Recompute a sha256 manifest (and its gpg signature, if present)."""
    if not manifest_path.is_file():
        raise CarrelInputError(f"no such file: {manifest_path}")
    entries: list[tuple[str, str]] = []
    for lineno, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        m = _MANIFEST_LINE.match(line)
        if not m:
            raise CarrelInputError(f"{manifest_path}:{lineno}: not a sha256sum line")
        entries.append((m.group(1).lower(), m.group(2)))
    if not entries:
        raise CarrelInputError(f"{manifest_path}: empty manifest")

    base = manifest_path.parent
    mismatched: list[str] = []
    missing: list[str] = []
    for expected, rel in entries:
        target = Path(rel) if Path(rel).is_absolute() else base / rel
        if not target.is_file():
            missing.append(rel)
        elif _sha256(target) != expected:
            mismatched.append(rel)

    asc = manifest_path.with_name(manifest_path.name + ".asc")
    sig_present, sig_valid = asc.exists(), None
    if sig_present:
        proc = adapters.run("gpg", "--batch", "--verify", str(asc), str(manifest_path))
        sig_valid = proc.returncode == 0

    ok = not mismatched and not missing and sig_valid is not False
    record = {
        "action": "sign-verify",
        "manifest": str(manifest_path),
        "checked": len(entries),
        "ok": ok,
        "mismatched": mismatched,
        "missing": missing,
        "signature": {"present": sig_present, "valid": sig_valid},
    }

    def human(r: dict[str, Any]) -> None:
        click.echo(f"verify: {r['manifest']} — {r['checked']} file(s)")
        for path in r["mismatched"]:
            click.echo(f"  MISMATCH: {path}")
        for path in r["missing"]:
            click.echo(f"  MISSING:  {path}")
        if r["signature"]["present"]:
            click.echo(f"  signature: {'valid' if r['signature']['valid'] else 'INVALID'}")
        click.echo("  OK" if r["ok"] else "  FAILED")

    emit(ctx, record, human=human)
    if not ok:
        raise SystemExit(int(ExitCode.ERROR))
