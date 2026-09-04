"""carrel diff — compare two files: text, structured data, PDF text, or pixels.

`diff_files()` is the library entry point (reused by the desk TUI and the MCP
server); the click command `cmd` is a thin wrapper around it.

Process exit status (documented in --help): 0 identical · 1 different ·
2 usage · 3 missing dependency (pdf mode needs pdftotext) · 4 bad input.
"""

from __future__ import annotations

import csv
import difflib
import functools
import json as jsonlib
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, fail
from carrel.core.textextract import extract_text

MODES = ("auto", "text", "struct", "image", "pdf")
_STRUCT_TYPES = (FileType.JSON, FileType.CSV, FileType.XML)


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


# ---------------------------------------------------------------------------
# mode resolution
# ---------------------------------------------------------------------------


def _resolve_mode(ta: FileType, tb: FileType) -> str:
    if ta.is_image and tb.is_image:
        return "image"
    if ta is FileType.PDF and tb is FileType.PDF:
        return "pdf"
    if ta is tb and ta in _STRUCT_TYPES:
        return "struct"
    if _textlike(ta) and _textlike(tb):  # mismatched text-ish pairs fall back to text
        return "text"
    raise CarrelInputError(
        f"cannot auto-diff {ta.value} vs {tb.value}: need two images, two PDFs, "
        f"or two text-like files (text formats, documents, workbooks; force one with --mode)"
    )


def _textlike(t: FileType) -> bool:
    """Anything `--mode text` can read: text formats plus extractable documents."""
    return t.is_text or t.is_document or t is FileType.XLSX


# ---------------------------------------------------------------------------
# text + pdf
# ---------------------------------------------------------------------------


def _read_text(path: Path, ftype: FileType) -> str:
    if ftype is FileType.PDF or ftype.is_document or ftype is FileType.XLSX:
        return extract_text(path)
    if ftype.is_image:
        raise CarrelInputError(f"--mode text cannot read an image: {path}")
    return path.read_text(errors="replace")


def _unified(a_text: str, b_text: str, a: Path, b: Path) -> dict[str, Any]:
    lines = list(
        difflib.unified_diff(
            a_text.splitlines(), b_text.splitlines(), fromfile=str(a), tofile=str(b), lineterm=""
        )
    )
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    return {"identical": not lines, "diff": "\n".join(lines), "added": added, "removed": removed}


def _page_count(path: Path) -> int | None:
    from pypdf import PdfReader

    try:
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 — page count is a note, not a gate
        return None


def _diff_pdf(a: Path, b: Path) -> dict[str, Any]:
    result = _unified(extract_text(a), extract_text(b), a, b)
    pages = {"a": _page_count(a), "b": _page_count(b)}
    result["pages"] = pages
    if result["identical"] and pages["a"] != pages["b"]:
        result["identical"] = False
    return result


# ---------------------------------------------------------------------------
# struct (json / csv / xml)
# ---------------------------------------------------------------------------


def _flatten_json(value: Any, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict) and value:
        for k, v in value.items():
            _flatten_json(v, f"{prefix}{k}.", out)
    elif isinstance(value, list) and value:
        for i, v in enumerate(value):
            _flatten_json(v, f"{prefix}{i}.", out)
    else:  # scalar, or empty container (kept as a leaf so its loss is visible)
        if isinstance(value, dict):
            value = "{}"
        elif isinstance(value, list):
            value = "[]"
        out[prefix[:-1] if prefix else "$"] = value


def _json_leaves(path: Path) -> dict[str, Any]:
    try:
        data = jsonlib.loads(path.read_text(errors="replace"))
    except jsonlib.JSONDecodeError as e:
        raise CarrelInputError(f"invalid JSON in {path}: {e}") from e
    out: dict[str, Any] = {}
    _flatten_json(data, "", out)
    return out


def _flatten_xml(el: ET.Element, path: str, out: dict[str, Any]) -> None:
    for name, value in sorted(el.attrib.items()):
        out[f"{path}.@{name}"] = value
    children = list(el)
    if children:
        counts = Counter(c.tag for c in children)
        seen: dict[str, int] = {}
        for child in children:
            if counts[child.tag] == 1:
                cpath = f"{path}.{child.tag}"
            else:
                i = seen.get(child.tag, 0)
                seen[child.tag] = i + 1
                cpath = f"{path}.{child.tag}.{i}"
            _flatten_xml(child, cpath, out)
    else:
        out[path] = (el.text or "").strip()


def _xml_leaves(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise CarrelInputError(f"invalid XML in {path}: {e}") from e
    out: dict[str, Any] = {}
    _flatten_xml(root, root.tag, out)
    return out


def _leaf_diff(la: dict[str, Any], lb: dict[str, Any]) -> dict[str, Any]:
    added = sorted(k for k in lb if k not in la)
    removed = sorted(k for k in la if k not in lb)
    changed = [
        {"path": k, "a": la[k], "b": lb[k]} for k in sorted(la.keys() & lb.keys()) if la[k] != lb[k]
    ]
    return {
        "identical": not (added or removed or changed),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", errors="replace") as fh:
        sample = fh.read(64 * 1024)
        fh.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except csv.Error:
            delimiter = ","
        return list(csv.reader(fh, delimiter=delimiter))


def _diff_csv(a: Path, b: Path) -> dict[str, Any]:
    """Row/cell diff by position. Row indices are 1-based data rows (header
    excluded); cells are compared per shared column name."""
    rows_a, rows_b = _read_csv(a), _read_csv(b)
    header_a = rows_a[0] if rows_a else []
    header_b = rows_b[0] if rows_b else []
    data_a, data_b = rows_a[1:], rows_b[1:]

    columns_added = [c for c in header_b if c not in header_a]
    columns_removed = [c for c in header_a if c not in header_b]
    shared = [c for c in header_a if c in header_b]
    idx_a = {c: header_a.index(c) for c in shared}
    idx_b = {c: header_b.index(c) for c in shared}

    changed: list[dict[str, Any]] = []
    for r in range(min(len(data_a), len(data_b))):
        for c in shared:
            va = data_a[r][idx_a[c]] if idx_a[c] < len(data_a[r]) else ""
            vb = data_b[r][idx_b[c]] if idx_b[c] < len(data_b[r]) else ""
            if va != vb:
                changed.append({"row": r + 1, "column": c, "a": va, "b": vb})
    rows_added = list(range(len(data_a) + 1, len(data_b) + 1))  # only in b
    rows_removed = list(range(len(data_b) + 1, len(data_a) + 1))  # only in a
    return {
        "identical": not (
            changed or rows_added or rows_removed or columns_added or columns_removed
        ),
        "columns_added": columns_added,
        "columns_removed": columns_removed,
        "rows_a": len(data_a),
        "rows_b": len(data_b),
        "rows_added": rows_added,
        "rows_removed": rows_removed,
        "changed": changed,
    }


def _diff_struct(a: Path, b: Path, ftype: FileType) -> dict[str, Any]:
    if ftype is FileType.CSV:
        return _diff_csv(a, b)
    if ftype is FileType.JSON:
        return _leaf_diff(_json_leaves(a), _json_leaves(b))
    return _leaf_diff(_xml_leaves(a), _xml_leaves(b))


# ---------------------------------------------------------------------------
# image (Pillow only)
# ---------------------------------------------------------------------------


def _diff_image(a: Path, b: Path, out: Path | None) -> dict[str, Any]:
    from PIL import Image, ImageChops, ImageOps, ImageStat

    with Image.open(a) as raw_a:
        img_a = raw_a.convert("RGBA")
    with Image.open(b) as raw_b:
        img_b = raw_b.convert("RGBA")
    size_a, size_b = img_a.size, img_b.size
    mismatch = size_a != size_b
    canvas = (max(size_a[0], size_b[0]), max(size_a[1], size_b[1]))
    if mismatch:  # pad both onto a common transparent canvas, anchored top-left

        def _pad(img: Image.Image) -> Image.Image:
            padded = Image.new("RGBA", canvas, (0, 0, 0, 0))
            padded.paste(img, (0, 0))
            return padded

        img_a, img_b = _pad(img_a), _pad(img_b)

    diff = ImageChops.difference(img_a, img_b)
    bands = diff.split()
    magnitude = bands[0]  # per-pixel max delta across channels
    for band in bands[1:]:
        magnitude = ImageChops.lighter(magnitude, band)
    total = canvas[0] * canvas[1]
    pixels_changed = total - magnitude.histogram()[0]
    means = ImageStat.Stat(diff).mean  # per-channel mean abs delta (r,g,b,a)

    result: dict[str, Any] = {
        "identical": not mismatch and pixels_changed == 0,
        "size_a": list(size_a),
        "size_b": list(size_b),
        "size_mismatch": mismatch,
        "canvas": list(canvas),
        "pixels_changed": pixels_changed,
        "pixel_diff_percent": round(pixels_changed / total * 100, 4),
        "mean_channel_delta": {c: round(m, 4) for c, m in zip("rgba", means, strict=False)},
    }
    if out is not None:
        heat = ImageOps.colorize(magnitude, black="#000000", white="#ffff00", mid="#ff0000")
        heat.save(out, "PNG")
        result["heatmap"] = str(out)
    return result


# ---------------------------------------------------------------------------
# library entry point
# ---------------------------------------------------------------------------


def diff_files(
    a: Path | str, b: Path | str, mode: str = "auto", out: Path | str | None = None
) -> dict[str, Any]:
    """Compare two files; returns a dict that always includes "identical".

    mode "auto" resolves by type pair: images → image, PDFs → pdf, matching
    json/csv/xml → struct, text-ish pairs (also mismatched) → text; anything
    else raises CarrelInputError. `out` (image mode only) writes a per-pixel
    delta heatmap PNG.
    """
    a, b = Path(a), Path(b)
    if mode not in MODES:
        raise CarrelInputError(f"unknown diff mode: {mode} (choose {'/'.join(MODES)})")
    ta, tb = detect_or_die(a), detect_or_die(b)
    resolved = _resolve_mode(ta, tb) if mode == "auto" else mode
    if out is not None and resolved != "image":
        raise CarrelInputError("--out (heatmap) is only available in image mode")

    if resolved == "image":
        if not (ta.is_image and tb.is_image):
            raise CarrelInputError(f"--mode image needs two images, got {ta.value} vs {tb.value}")
        result = _diff_image(a, b, Path(out) if out is not None else None)
    elif resolved == "pdf":
        if not (ta is FileType.PDF and tb is FileType.PDF):
            raise CarrelInputError(f"--mode pdf needs two PDFs, got {ta.value} vs {tb.value}")
        result = _diff_pdf(a, b)
    elif resolved == "struct":
        if ta is not tb or ta not in _STRUCT_TYPES:
            raise CarrelInputError(
                "--mode struct needs two files of the same structured type "
                f"(json/csv/xml), got {ta.value} vs {tb.value}"
            )
        result = _diff_struct(a, b, ta)
    else:  # text
        result = _unified(_read_text(a, ta), _read_text(b, tb), a, b)

    return {"a": str(a), "b": str(b), "mode": resolved, **result}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DIFF_COLORS = (("+++", "green"), ("---", "red"), ("+", "green"), ("-", "red"), ("@@", "cyan"))


def _echo_diff(text: str) -> None:
    for line in text.splitlines():
        for prefix, color in _DIFF_COLORS:
            if line.startswith(prefix):
                click.secho(line, fg=color, bold=prefix in ("+++", "---", "@@"))
                break
        else:
            click.echo(line)


def _render(data: dict[str, Any]) -> None:
    mode = data["mode"]
    if data["identical"]:
        click.echo(f"identical ({mode})")
        return
    if mode in ("text", "pdf"):
        if "pages" in data:
            click.echo(f"pages: {data['pages']['a']} vs {data['pages']['b']}")
        _echo_diff(data["diff"])
    elif mode == "struct":
        if "columns_added" in data:  # csv
            for key in ("columns_added", "columns_removed", "rows_added", "rows_removed"):
                if data[key]:
                    click.echo(f"{key.replace('_', ' ')}: {', '.join(str(x) for x in data[key])}")
            for ch in data["changed"]:
                click.echo(f"row {ch['row']}, {ch['column']}: {ch['a']!r} -> {ch['b']!r}")
        else:  # json / xml
            for p in data["removed"]:
                click.secho(f"- {p}", fg="red")
            for p in data["added"]:
                click.secho(f"+ {p}", fg="green")
            for ch in data["changed"]:
                click.secho(f"~ {ch['path']}: {ch['a']!r} -> {ch['b']!r}", fg="yellow")
    else:  # image
        click.echo(
            f"size: {data['size_a']} vs {data['size_b']}"
            + (" (MISMATCH — padded to common canvas)" if data["size_mismatch"] else "")
        )
        click.echo(f"pixels changed: {data['pixels_changed']} ({data['pixel_diff_percent']}%)")
        deltas = data["mean_channel_delta"]
        click.echo("mean channel delta: " + " ".join(f"{c}={v}" for c, v in deltas.items()))
        if data.get("heatmap"):
            click.echo(f"heatmap written: {data['heatmap']}")


@click.command(name="diff")
@click.argument("a", type=click.Path(path_type=Path))
@click.argument("b", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option(
    "--mode",
    type=click.Choice(MODES),
    default="auto",
    show_default=True,
    help="Comparison strategy; auto picks by type pair.",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Image mode: write a per-pixel delta heatmap PNG here.",
)
@click.pass_context
@_handled
def cmd(ctx: click.Context, a: Path, b: Path, as_json: bool, mode: str, out: Path | None) -> None:
    """Compare two files A and B.

    Modes: text (unified diff), struct (json: dotted-path added/removed/changed;
    csv: per-row/column cell changes; xml: element-path changes), pdf (extracted
    text diff + page counts), image (Pillow pixel diff: dimensions, changed-pixel
    percentage, mean channel delta; sizes are padded to a common canvas and the
    mismatch reported). auto picks by type pair and falls back to a text diff
    when both files are text-like.

    \b
    Exit status:
      0  files are identical
      1  files differ
      2  bad usage
      3  missing optional dependency (pdf mode needs pdftotext)
      4  missing/unsupported input, or no mode fits the type pair
    """
    ctx.ensure_object(dict)
    if as_json:
        ctx.obj["json"] = True
    result = diff_files(a, b, mode=mode, out=out)
    emit(ctx, result, human=_render)
    if not result["identical"]:
        # sys.exit (not ctx.exit): the status must survive cli.main()'s
        # standalone_mode=False invocation, where click's Exit is swallowed.
        sys.exit(1)
