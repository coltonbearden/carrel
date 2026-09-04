"""carrel edit — small, safe edits to pdf / image / text / json files.

Subgroup with four subcommands. pypdf is the primary PDF engine; qpdf is used
only for --linearize / --decrypt (through carrel.core.adapters, degrading with
a MissingDependencyError → exit 3). Pillow handles images.

Overwrite policy (spec 04): never silently overwrite an existing file.
Writing onto an existing path requires --force; in-place text edits require
an explicit -i/--in-place.
"""

from __future__ import annotations

import functools
import json as jsonlib
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

# ---------------------------------------------------------------- shared bits


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


def _expect_type(src: Path, wanted: tuple[FileType, ...], what: str) -> FileType:
    ftype = detect_or_die(src)
    if ftype not in wanted:
        names = "/".join(t.value for t in wanted)
        raise CarrelInputError(f"edit {what} needs a {names} file, got {ftype.value}: {src}")
    return ftype


def _check_target(target: Path, force: bool) -> Path:
    if target.exists() and not force:
        raise CarrelError(f"refusing to overwrite existing file: {target} (pass --force)")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _parse_pages(spec: str, total: int) -> list[int]:
    """'1-3,7' → [1, 2, 3, 7] (1-based), validated against `total`."""
    nums: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        try:
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            else:
                lo = hi = int(part)
        except ValueError:
            raise click.UsageError(f"bad --pages spec {spec!r} (expected e.g. '1-3,7')") from None
        if lo < 1 or hi < lo:
            raise click.UsageError(f"bad --pages range {part!r}")
        if hi > total:
            raise CarrelInputError(f"--pages {part!r} out of range: document has {total} page(s)")
        nums.extend(range(lo, hi + 1))
    return nums


@click.group(name="edit")
def cmd() -> None:
    """Edit files in place-adjacent, non-destructive ways (pdf/image/text/json)."""


# ------------------------------------------------------------------- edit pdf


def _qpdf(*args: str, action: str) -> None:
    proc = adapters.run("qpdf", *args)
    if proc.returncode not in (0, 3):  # 3 = qpdf succeeded with warnings
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CarrelError(f"qpdf {action} failed (rc={proc.returncode}): {detail}")


@cmd.command("pdf")
@click.argument("src", type=click.Path(exists=False, path_type=Path))
@click.option(
    "--merge",
    "merge_srcs",
    multiple=True,
    type=click.Path(path_type=Path),
    help="Append these PDFs after SRC (repeatable, in order).",
)
@click.option("--split", is_flag=True, help="Write one PDF per page into OUT (a directory).")
@click.option(
    "--pages", "pages_spec", metavar="SPEC", help="Keep only these pages, e.g. '1-3,7' (1-based)."
)
@click.option(
    "--rotate",
    "rotate_deg",
    type=int,
    metavar="DEG",
    help="Rotate output pages clockwise (multiple of 90).",
)
@click.option("--linearize", is_flag=True, help="Linearize output for fast web view (qpdf).")
@click.option("--decrypt", "password", metavar="PW", help="Decrypt SRC with password (qpdf).")
@click.option(
    "-o",
    "--out",
    type=click.Path(path_type=Path),
    help="Output file (or directory with --split). Default: SRC.edited.pdf / SRC-pages/.",
)
@click.option("--force", is_flag=True, help="Allow overwriting existing files.")
@click.pass_context
@_handled
def pdf(
    ctx: click.Context,
    src: Path,
    merge_srcs: tuple[Path, ...],
    split: bool,
    pages_spec: str | None,
    rotate_deg: int | None,
    linearize: bool,
    password: str | None,
    out: Path | None,
    force: bool,
) -> None:
    """Merge, split, extract pages, rotate, linearize or decrypt a PDF.

    Pipeline: decrypt → merge → --pages selection → rotate → write (--split
    writes one file per page) → linearize. --pages extracts: the output
    contains only the selected pages, so --rotate applies to that selection.
    """
    from pypdf import PdfReader, PdfWriter

    _expect_type(src, (FileType.PDF,), "pdf")
    operations: list[str] = []
    if not any([merge_srcs, split, pages_spec, rotate_deg is not None, linearize, password]):
        raise click.UsageError(
            "nothing to do: pass at least one of --merge/--split/--pages/--rotate/"
            "--linearize/--decrypt"
        )
    if rotate_deg is not None and rotate_deg % 90 != 0:
        raise click.UsageError("--rotate must be a multiple of 90")

    with tempfile.TemporaryDirectory(prefix="carrel-edit-") as tmpdir:
        src_eff = src
        if password:
            src_eff = Path(tmpdir) / "decrypted.pdf"
            _qpdf(f"--password={password}", "--decrypt", str(src), str(src_eff), action="--decrypt")
            operations.append("decrypt")

        reader = PdfReader(src_eff)
        if reader.is_encrypted:
            raise CarrelInputError(f"{src} is encrypted — pass --decrypt PASSWORD")
        all_pages = list(reader.pages)
        for extra in merge_srcs:
            _expect_type(extra, (FileType.PDF,), "pdf")
            extra_reader = PdfReader(extra)
            if extra_reader.is_encrypted:
                raise CarrelInputError(f"{extra} is encrypted — decrypt it first")
            all_pages.extend(extra_reader.pages)
        if merge_srcs:
            operations.append(f"merge(+{len(merge_srcs)})")
        pages_in = len(all_pages)

        if pages_spec:
            selection = _parse_pages(pages_spec, pages_in)
            all_pages = [all_pages[i - 1] for i in selection]
            operations.append(f"pages({pages_spec})")

        outputs: list[Path] = []
        if split:
            operations.append("split")
            out_dir = out or src.with_name(f"{src.stem}-pages")
            if out_dir.exists() and not out_dir.is_dir():
                raise CarrelError(f"--split output exists and is not a directory: {out_dir}")
            out_dir.mkdir(parents=True, exist_ok=True)
            for i, page in enumerate(all_pages, start=1):
                writer = PdfWriter()
                writer.add_page(page)
                if rotate_deg:
                    writer.pages[0].rotate(rotate_deg % 360)
                target = _check_target(out_dir / f"{src.stem}-p{i:03d}.pdf", force)
                with target.open("wb") as fh:
                    writer.write(fh)
                outputs.append(target)
        else:
            writer = PdfWriter()
            for page in all_pages:
                writer.add_page(page)
            if rotate_deg:
                for page in writer.pages:
                    page.rotate(rotate_deg % 360)
            target = _check_target(out or src.with_name(f"{src.stem}.edited.pdf"), force)
            with target.open("wb") as fh:
                writer.write(fh)
            outputs.append(target)
        if rotate_deg:
            operations.append(f"rotate({rotate_deg})")

        if linearize:
            operations.append("linearize")
            for produced in outputs:
                # temp lives next to the output so the final rename never crosses filesystems
                lin_tmp = produced.with_name(f".{produced.name}.lin.tmp")
                _qpdf("--linearize", str(produced), str(lin_tmp), action="--linearize")
                lin_tmp.replace(produced)

    record = {
        "action": "edit-pdf",
        "src": str(src),
        "operations": operations,
        "pages_in": pages_in,
        "pages_out": len(all_pages),
        "output": str(outputs[0]) if len(outputs) == 1 and not split else [str(p) for p in outputs],
    }
    emit(ctx, record, human=_human_record)


# ----------------------------------------------------------------- edit image


def _parse_resize(spec: str, size: tuple[int, int]) -> tuple[int, int]:
    spec = spec.strip().lower()
    if spec.endswith("%"):
        try:
            pct = float(spec[:-1])
        except ValueError:
            raise click.UsageError(f"bad --resize spec {spec!r} (expected WxH or N%)") from None
        if pct <= 0:
            raise click.UsageError("--resize percentage must be > 0")
        return (max(1, round(size[0] * pct / 100)), max(1, round(size[1] * pct / 100)))
    if "x" in spec:
        w_s, _, h_s = spec.partition("x")
        try:
            w, h = int(w_s), int(h_s)
        except ValueError:
            raise click.UsageError(f"bad --resize spec {spec!r} (expected WxH or N%)") from None
        if w < 1 or h < 1:
            raise click.UsageError("--resize dimensions must be >= 1")
        return (w, h)
    raise click.UsageError(f"bad --resize spec {spec!r} (expected WxH or N%)")


@cmd.command("image")
@click.argument("src", type=click.Path(path_type=Path))
@click.option("--resize", "resize_spec", metavar="WxH|N%", help="Resize to WxH or by percent.")
@click.option(
    "--rotate",
    "rotate_deg",
    type=float,
    metavar="DEG",
    help="Rotate clockwise by DEG degrees (canvas expands).",
)
@click.option("--crop", "crop_spec", metavar="X,Y,W,H", help="Crop box: left,top,width,height.")
@click.option("--strip", is_flag=True, help="Drop EXIF/metadata from the output.")
@click.option("--quality", type=click.IntRange(1, 100), help="JPEG/WebP quality (1-100).")
@click.option(
    "-o", "--out", type=click.Path(path_type=Path), help="Output file. Default: SRC.edited.<ext>."
)
@click.option("--force", is_flag=True, help="Allow overwriting existing files.")
@click.pass_context
@_handled
def image(
    ctx: click.Context,
    src: Path,
    resize_spec: str | None,
    rotate_deg: float | None,
    crop_spec: str | None,
    strip: bool,
    quality: int | None,
    out: Path | None,
    force: bool,
) -> None:
    """Resize, rotate, crop, re-encode or strip metadata from an image.

    Operation order: crop → resize → rotate.
    """
    from PIL import Image

    _expect_type(src, (FileType.JPG, FileType.PNG, FileType.ICO), "image")
    if not any([resize_spec, rotate_deg is not None, crop_spec, strip, quality is not None]):
        raise click.UsageError(
            "nothing to do: pass at least one of --resize/--rotate/--crop/--strip/--quality"
        )

    target = _check_target(out or src.with_name(f"{src.stem}.edited{src.suffix}"), force)
    operations: list[str] = []
    with Image.open(src) as opened:
        img: Image.Image = opened
        img.load()
        exif_bytes = img.info.get("exif")
        size_in = img.size

        if crop_spec:
            try:
                x, y, w, h = (int(v) for v in crop_spec.split(","))
            except ValueError:
                raise click.UsageError(
                    f"bad --crop spec {crop_spec!r} (expected X,Y,W,H)"
                ) from None
            if w < 1 or h < 1:
                raise click.UsageError("--crop width/height must be >= 1")
            img = img.crop((x, y, x + w, y + h))
            operations.append(f"crop({crop_spec})")
        if resize_spec:
            new_size = _parse_resize(resize_spec, img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            operations.append(f"resize({resize_spec})")
        if rotate_deg is not None:
            img = img.rotate(-rotate_deg, expand=True)  # PIL rotates CCW; we expose CW
            operations.append(f"rotate({rotate_deg:g})")
        if strip:
            operations.append("strip")
        if quality is not None:
            operations.append(f"quality({quality})")

        save_kwargs: dict[str, Any] = {}
        suffix = target.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            if img.mode not in ("RGB", "L", "CMYK"):
                img = img.convert("RGB")
            if quality is not None:
                save_kwargs["quality"] = quality
            if exif_bytes and not strip:
                save_kwargs["exif"] = exif_bytes
        elif suffix == ".png" and exif_bytes and not strip:
            save_kwargs["exif"] = exif_bytes
        img.save(target, **save_kwargs)
        size_out = img.size

    record = {
        "action": "edit-image",
        "src": str(src),
        "operations": operations,
        "size_in": list(size_in),
        "size_out": list(size_out),
        "stripped": strip,
        "output": str(target),
    }
    emit(ctx, record, human=_human_record)


# ------------------------------------------------------------------ edit text

_TEXT_TYPES = (FileType.TXT, FileType.MD, FileType.HTML, FileType.CSV, FileType.XML, FileType.JSON)


@cmd.command("text")
@click.argument("src", type=click.Path(path_type=Path))
@click.option("--find", "pattern", required=True, metavar="PAT", help="Text (or regex) to find.")
@click.option(
    "--replace",
    "replacement",
    required=True,
    metavar="REP",
    help="Replacement text (may be empty).",
)
@click.option("--regex", is_flag=True, help="Treat PAT as a Python regular expression.")
@click.option("-i", "--in-place", is_flag=True, help="Rewrite SRC itself.")
@click.option("-o", "--out", type=click.Path(path_type=Path), help="Output file.")
@click.option("--force", is_flag=True, help="Allow overwriting an existing output file.")
@click.pass_context
@_handled
def text(
    ctx: click.Context,
    src: Path,
    pattern: str,
    replacement: str,
    regex: bool,
    in_place: bool,
    out: Path | None,
    force: bool,
) -> None:
    """Find & replace in a text file (txt/md/html/csv/xml/json-as-text).

    Requires -o OUT or an explicit -i/--in-place — never silently rewrites SRC.
    """
    _expect_type(src, _TEXT_TYPES, "text")
    if in_place and out:
        raise click.UsageError("pass either -o OUT or -i/--in-place, not both")
    if not in_place and not out:
        raise click.UsageError("refusing to guess the destination: pass -o OUT or -i/--in-place")

    try:
        content = src.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise CarrelInputError(f"{src} is not valid UTF-8 text: {e}") from e

    if regex:
        try:
            new_content, count = re.subn(pattern, replacement, content)
        except re.error as e:
            raise click.UsageError(f"bad regular expression {pattern!r}: {e}") from e
    else:
        count = content.count(pattern)
        new_content = content.replace(pattern, replacement)

    if in_place:
        target = src
    else:
        if out is None:  # pragma: no cover — click guarantees one of --in-place/--out
            raise click.UsageError("pass --out PATH or --in-place")
        target = _check_target(out, force)
    target.write_text(new_content, encoding="utf-8")

    record = {
        "action": "edit-text",
        "src": str(src),
        "operations": [f"replace({'regex' if regex else 'literal'})"],
        "find": pattern,
        "regex": regex,
        "replacements": count,
        "in_place": in_place,
        "output": str(target),
    }
    emit(ctx, record, human=_human_record)


# ------------------------------------------------------------------ edit json


def _json_value(raw: str) -> Any:
    """Parse VALUE as JSON, falling back to the raw string."""
    try:
        return jsonlib.loads(raw)
    except ValueError:
        return raw


def _walk(data: Any, keys: list[str], dotted: str, *, create: bool) -> Any:
    cur = data
    for k in keys:
        if isinstance(cur, list):
            try:
                idx = int(k)
            except ValueError:
                raise CarrelError(f"path {dotted!r}: {k!r} is not a list index") from None
            if not -len(cur) <= idx < len(cur):
                raise CarrelError(f"path {dotted!r}: index {idx} out of range")
            cur = cur[idx]
        elif isinstance(cur, dict):
            if k not in cur:
                if not create:
                    raise CarrelError(f"path {dotted!r}: no such key {k!r}")
                cur[k] = {}
            elif create and not isinstance(cur[k], (dict, list)):
                cur[k] = {}
            cur = cur[k]
        else:
            raise CarrelError(f"path {dotted!r}: cannot descend into {type(cur).__name__} at {k!r}")
    return cur


def _set_path(data: Any, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    parent = _walk(data, keys[:-1], dotted, create=True)
    last = keys[-1]
    if isinstance(parent, list):
        try:
            idx = int(last)
        except ValueError:
            raise CarrelError(f"path {dotted!r}: {last!r} is not a list index") from None
        if idx == len(parent):
            parent.append(value)
        elif -len(parent) <= idx < len(parent):
            parent[idx] = value
        else:
            raise CarrelError(f"path {dotted!r}: index {idx} out of range")
    elif isinstance(parent, dict):
        parent[last] = value
    else:
        raise CarrelError(f"path {dotted!r}: cannot set key on {type(parent).__name__}")


def _del_path(data: Any, dotted: str) -> None:
    keys = dotted.split(".")
    parent = _walk(data, keys[:-1], dotted, create=False)
    last = keys[-1]
    if isinstance(parent, list):
        try:
            idx = int(last)
        except ValueError:
            raise CarrelError(f"path {dotted!r}: {last!r} is not a list index") from None
        if not -len(parent) <= idx < len(parent):
            raise CarrelError(f"path {dotted!r}: index {idx} out of range")
        del parent[idx]
    elif isinstance(parent, dict):
        if last not in parent:
            raise CarrelError(f"path {dotted!r}: no such key {last!r}")
        del parent[last]
    else:
        raise CarrelError(
            f"path {dotted!r}: cannot delete from {type(parent).__name__}"  # noqa: S608 — message, not SQL
        )


@cmd.command("json")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--set",
    "sets",
    multiple=True,
    metavar="PATH=VALUE",
    help="Set dotted PATH to VALUE (parsed as JSON, string fallback). Repeatable.",
)
@click.option(
    "--del",
    "dels",
    multiple=True,
    metavar="PATH",
    help="Delete dotted PATH. Repeatable; applied after --set.",
)
@click.option(
    "-o", "--out", type=click.Path(path_type=Path), help="Output file. Default: SRC.edited.json."
)
@click.option("--force", is_flag=True, help="Allow overwriting existing files.")
@click.pass_context
@_handled
def json_cmd(
    ctx: click.Context,
    src: Path,
    sets: tuple[str, ...],
    dels: tuple[str, ...],
    out: Path | None,
    force: bool,
) -> None:
    """Set or delete values in a JSON file by dotted path (a.b.0.c)."""
    _expect_type(src, (FileType.JSON,), "json")
    if not sets and not dels:
        raise click.UsageError("nothing to do: pass --set PATH=VALUE and/or --del PATH")

    try:
        data = jsonlib.loads(src.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CarrelInputError(f"{src} is not valid JSON: {e}") from e
    if not isinstance(data, (dict, list)):
        raise CarrelInputError(f"{src}: top-level JSON must be an object or array to edit paths")

    applied_sets: list[dict[str, Any]] = []
    for assignment in sets:
        path_part, eq, raw_value = assignment.partition("=")
        if not eq or not path_part:
            raise click.UsageError(f"bad --set {assignment!r} (expected PATH=VALUE)")
        value = _json_value(raw_value)
        _set_path(data, path_part, value)
        applied_sets.append({"path": path_part, "value": value})
    for dotted in dels:
        _del_path(data, dotted)

    target = _check_target(out or src.with_name(f"{src.stem}.edited.json"), force)
    target.write_text(jsonlib.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    record = {
        "action": "edit-json",
        "src": str(src),
        "operations": ([f"set({s['path']})" for s in applied_sets] + [f"del({d})" for d in dels]),
        "set": applied_sets,
        "deleted": list(dels),
        "output": str(target),
    }
    emit(ctx, record, human=_human_record)


# ------------------------------------------------------------------ human view


def _human_record(record: dict[str, Any]) -> None:
    ops = ", ".join(record.get("operations", [])) or "-"
    click.echo(f"{record['action']}: {record['src']}")
    click.echo(f"  operations: {ops}")
    for key in ("pages_in", "pages_out", "size_in", "size_out", "replacements", "set", "deleted"):
        if key in record and record[key] not in ([], None):
            click.echo(f"  {key.replace('_', ' ')}: {record[key]}")
    out_val = record["output"]
    if isinstance(out_val, list):
        click.echo(f"  wrote {len(out_val)} file(s):")
        for p in out_val:
            click.echo(f"    {p}")
    else:
        click.echo(f"  wrote: {out_val}")
