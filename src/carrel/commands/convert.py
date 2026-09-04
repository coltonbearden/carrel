"""carrel convert — convert files between the supported types.

`convert_file()` is the library entry point (reused by the desk TUI); the
click command `cmd` is a thin wrapper. Routing lives in the CONVERTERS
table keyed by (source FileType, target FileType), so --help and the
"unsupported pair" error always match what the code can actually do.

Documented conversion shapes (deliberately minimal, honest formats):

- pdf → html   wraps `pdftotext -layout` output in a <pre> block.
- pdf → md     pdftotext text with form feeds turned into `---` rules.
- json → csv   list-of-objects become rows; nested values are flattened
               to dotted column names (a top-level object is one row).
- csv → json   rows become a list of objects; cell values are inferred
               back to int/float/true/false where unambiguous.
- json → xml   objects map keys to elements (or <item key="..."> when the
               key is not a valid tag name), arrays to repeated <item>.
- xml → json   attributes become "@name" keys, text becomes "#text" (or
               a plain string for leaf elements); repeated tags → arrays.
- docx/odt/epub/rtf → md/html/txt   pandoc reads the *detected* type;
               → pdf goes pandoc-to-html then weasyprint; docx ↔ epub is
               pandoc on both sides.
- md/html/txt → docx/odt   pandoc writes; txt is wrapped as escaped HTML
               paragraphs first so nothing is mistaken for markup.
- xlsx → csv   one sheet (first, or --sheet NAME|N); --sheet all writes
               DEST-<sheet>.csv per sheet. Cells render like the CSV
               flattener (true/false, ISO dates, "" for empty).
- xlsx → json  {sheet: [row objects keyed by the header row]}; native
               numbers/bools kept, dates as ISO strings. Never the reverse.
"""

from __future__ import annotations

import csv
import html as htmllib
import json as jsonlib
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters, textextract
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit

ICO_SIZES = (16, 32, 48, 64, 128, 256)
PDF_RASTER_DPI = "150"

_TARGET_ALIASES = {
    "jpeg": "jpg",
    "htm": "html",
    "markdown": "md",
    "text": "txt",
    "xlsm": "xlsx",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# pandoc reader per *source* type (documents come from textextract; text types here)
_PANDOC_FROM: dict[FileType, str] = {
    **textextract.PANDOC_READERS,
    FileType.MD: "markdown",
    FileType.HTML: "html",
}
_XML_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9._-]*\Z")
_INT = re.compile(r"[+-]?\d+\Z")
_FLOAT = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?\Z")


def normalize_target(ext: str) -> FileType | None:
    """'.PDF' / 'jpeg' / 'md' → FileType, or None when not a supported type."""
    name = ext.lower().lstrip(".")
    name = _TARGET_ALIASES.get(name, name)
    try:
        ftype = FileType(name)
    except ValueError:
        return None
    return None if ftype is FileType.UNKNOWN else ftype


# --------------------------------------------------------------------------
# small shared helpers


def _html_doc(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n"
        f'<meta charset="utf-8">\n<title>{htmllib.escape(title)}</title>\n'
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _run_pandoc(src: Path, dest: Path, from_fmt: str, to_fmt: str, *extra: str) -> None:
    proc = adapters.run("pandoc", "-f", from_fmt, "-t", to_fmt, *extra, str(src), "-o", str(dest))
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        raise CarrelError(f"pandoc failed ({proc.returncode}): {err[0] if err else '?'}")


def _weasyprint(html_path: Path, dest: Path) -> None:
    proc = adapters.run("weasyprint", str(html_path), str(dest), timeout=300)
    if proc.returncode != 0 or not dest.exists():
        err = (proc.stderr or "").strip().splitlines()
        raise CarrelError(f"weasyprint failed ({proc.returncode}): {err[0] if err else '?'}")


def _check_overwrite(dest: Path, force: bool) -> None:
    if dest.exists() and not force:
        raise CarrelError(f"refusing to overwrite {dest} (use --force)")


# --------------------------------------------------------------------------
# converters — each fn(src, dest, opts) writes dest and returns at least
# {"via": ...}; extra keys are merged into the result record.


def _copy(src: Path, dest: Path, opts: dict) -> dict:
    shutil.copyfile(src, dest)
    return {"via": "copy"}


def _md_to_html(src: Path, dest: Path, opts: dict) -> dict:
    if adapters.have("pandoc"):
        _run_pandoc(src, dest, "markdown", "html", "-s", "--metadata", f"title={src.stem}")
        return {"via": "pandoc"}
    body = textextract.markdown_to_html(src.read_text(errors="replace"))
    dest.write_text(_html_doc(src.stem, body))
    return {"via": "markdown-it"}


def _md_to_txt(src: Path, dest: Path, opts: dict) -> dict:
    if adapters.have("pandoc"):
        _run_pandoc(src, dest, "markdown", "plain")
        return {"via": "pandoc"}
    html = textextract.markdown_to_html(src.read_text(errors="replace"))
    dest.write_text(textextract.html_to_text(html))
    return {"via": "markdown-it"}


def _html_to_md(src: Path, dest: Path, opts: dict) -> dict:
    adapters.require("pandoc")  # no honest fallback for html → md
    _run_pandoc(src, dest, "html", "gfm")
    return {"via": "pandoc"}


def _html_to_txt(src: Path, dest: Path, opts: dict) -> dict:
    if adapters.have("pandoc"):
        _run_pandoc(src, dest, "html", "plain")
        return {"via": "pandoc"}
    dest.write_text(textextract.html_to_text(src.read_text(errors="replace")))
    return {"via": "textextract"}


def _txt_to_html(src: Path, dest: Path, opts: dict) -> dict:
    body = f"<pre>{htmllib.escape(src.read_text(errors='replace'))}</pre>"
    dest.write_text(_html_doc(src.stem, body))
    return {"via": "builtin"}


def _to_pdf(src: Path, dest: Path, opts: dict) -> dict:
    """md/html/txt → pdf: get to HTML first, then render with weasyprint."""
    adapters.require("weasyprint")
    src_type = detect_or_die(src)
    if src_type is FileType.HTML:
        _weasyprint(src, dest)
        return {"via": "weasyprint"}
    with tempfile.TemporaryDirectory(prefix="carrel-convert-") as td:
        page = Path(td) / f"{src.stem}.html"
        if src_type is FileType.MD:
            via = _md_to_html(src, page, opts)["via"]
        else:  # txt
            _txt_to_html(src, page, opts)
            via = "builtin"
        _weasyprint(page, dest)
    return {"via": f"{via}+weasyprint"}


def _pdf_to_txt(src: Path, dest: Path, opts: dict) -> dict:
    dest.write_text(textextract.pdf_text(src))
    return {"via": "pdftotext"}


def _pdf_to_md(src: Path, dest: Path, opts: dict) -> dict:
    proc = adapters.run("pdftotext", str(src), "-")
    if proc.returncode != 0:
        raise CarrelError(f"pdftotext failed ({proc.returncode}) on {src}")
    pages = [p.strip("\n") for p in proc.stdout.split("\f")]
    dest.write_text("\n\n---\n\n".join(p for p in pages if p.strip()) + "\n")
    return {"via": "pdftotext"}


def _pdf_to_html(src: Path, dest: Path, opts: dict) -> dict:
    proc = adapters.run("pdftotext", "-layout", str(src), "-")
    if proc.returncode != 0:
        raise CarrelError(f"pdftotext failed ({proc.returncode}) on {src}")
    body = f"<pre>\n{htmllib.escape(proc.stdout)}</pre>"
    dest.write_text(_html_doc(src.stem, body))
    return {"via": "pdftotext"}


def _page_no(path: Path) -> int:
    m = re.search(r"-(\d+)\Z", path.stem)
    return int(m.group(1)) if m else 0


def _pdf_to_image(src: Path, dest: Path, opts: dict) -> dict:
    fmt_flag = "-jpeg" if normalize_target(dest.suffix) is FileType.JPG else "-png"
    if opts.get("pages") != "all":
        prefix = dest.parent / dest.stem
        proc = adapters.run(
            "pdftoppm",
            fmt_flag,
            "-r",
            PDF_RASTER_DPI,
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
            str(src),
            str(prefix),
        )
        if proc.returncode != 0 or not dest.exists():
            raise CarrelError(f"pdftoppm failed ({proc.returncode}) on {src}")
        return {"via": "pdftoppm"}
    with tempfile.TemporaryDirectory(prefix="carrel-convert-") as td:
        proc = adapters.run(
            "pdftoppm", fmt_flag, "-r", PDF_RASTER_DPI, str(src), str(Path(td) / "page")
        )
        produced = sorted(Path(td).glob("page-*"), key=_page_no)
        if proc.returncode != 0 or not produced:
            raise CarrelError(f"pdftoppm failed ({proc.returncode}) on {src}")
        targets = [
            dest.with_name(f"{dest.stem}-{i}{dest.suffix}") for i in range(1, len(produced) + 1)
        ]
        for target in targets:
            _check_overwrite(target, opts.get("force", False))
        for page, target in zip(produced, targets, strict=False):
            shutil.move(str(page), target)
    return {"via": "pdftoppm", "dest": str(targets[0]), "dests": [str(t) for t in targets]}


def _image_convert(src: Path, dest: Path, opts: dict) -> dict:
    from PIL import Image

    target = normalize_target(dest.suffix)
    with Image.open(src) as im:
        im.load()
        if target is FileType.ICO:
            ico = im.convert("RGBA")
            if max(ico.size) < ICO_SIZES[-1]:  # upscale small sources: full size set
                scale = ICO_SIZES[-1] / max(ico.size)
                ico = ico.resize(
                    (round(ico.width * scale), round(ico.height * scale)), Image.Resampling.LANCZOS
                )
            side = max(ico.size)  # square-pad so every frame is a proper icon
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(ico, ((side - ico.width) // 2, (side - ico.height) // 2))
            canvas.save(dest, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
        elif target is FileType.JPG:
            out = im if im.mode in ("RGB", "L") else im.convert("RGB")
            out.save(dest, format="JPEG", quality=90)
        elif target is FileType.PNG:
            im.save(dest, format="PNG")
        else:  # pdf
            im.convert("RGB").save(dest, format="PDF")
    return {"via": "pillow"}


# ---- structured data -------------------------------------------------------


def _load_json(src: Path) -> Any:
    try:
        return jsonlib.loads(src.read_text(errors="replace"))
    except jsonlib.JSONDecodeError as e:
        raise CarrelInputError(f"invalid JSON in {src}: {e}") from e


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Nested dicts/lists → one level with dotted keys."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1] if prefix else "value"] = value
    return out


def _json_records(data: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """(ordered fieldnames, flattened rows) for tabular renderings."""
    records = data if isinstance(data, list) else [data]
    flat = [_flatten(r) if isinstance(r, (dict, list)) else {"value": r} for r in records]
    fields: list[str] = []
    for row in flat:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields, flat


def _cell(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return ""
    return str(v)


def _json_to_csv(src: Path, dest: Path, opts: dict) -> dict:
    fields, rows = _json_records(_load_json(src))
    with dest.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _cell(v) for k, v in row.items()})
    return {"via": "builtin"}


def _infer(s: str) -> Any:
    if s == "true":
        return True
    if s == "false":
        return False
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


def _csv_to_json(src: Path, dest: Path, opts: dict) -> dict:
    with src.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise CarrelInputError(f"empty CSV (no header row): {src}")
        rows = [{k: _infer(v) for k, v in row.items() if k is not None} for row in reader]
    dest.write_text(jsonlib.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    return {"via": "builtin"}


def _read_csv(src: Path) -> tuple[list[str], list[list[str]]]:
    with src.open(newline="") as fh:
        raw = [row for row in csv.reader(fh) if row]
    if not raw:
        raise CarrelInputError(f"empty CSV: {src}")
    header, body = raw[0], raw[1:]
    width = len(header)
    return header, [(r + [""] * width)[:width] for r in body]


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    def esc(c: str) -> str:
        return c.replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(esc(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(esc(c) for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _html_table(title: str, header: list[str], rows: list[list[str]]) -> str:
    e = htmllib.escape
    head = "".join(f"<th>{e(c)}</th>" for c in header)
    body = "\n".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in rows)
    table = f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody>\n</table>"
    return _html_doc(title, table)


def _csv_to_md(src: Path, dest: Path, opts: dict) -> dict:
    header, rows = _read_csv(src)
    dest.write_text(_md_table(header, rows))
    return {"via": "builtin"}


def _csv_to_html(src: Path, dest: Path, opts: dict) -> dict:
    header, rows = _read_csv(src)
    dest.write_text(_html_table(src.stem, header, rows))
    return {"via": "builtin"}


def _json_to_html(src: Path, dest: Path, opts: dict) -> dict:
    fields, flat = _json_records(_load_json(src))
    rows = [[_cell(row.get(f, "")) for f in fields] for row in flat]
    dest.write_text(_html_table(src.stem, fields, rows))
    return {"via": "builtin"}


def _json_to_element(value: Any, tag: str, key: str | None = None) -> ET.Element:
    el = ET.Element(tag)
    if key is not None:
        el.set("key", key)
    if isinstance(value, dict):
        for k, v in value.items():
            if _XML_NAME.match(k):
                el.append(_json_to_element(v, k))
            else:
                el.append(_json_to_element(v, "item", key=k))
    elif isinstance(value, list):
        for v in value:
            el.append(_json_to_element(v, "item"))
    elif value is not None:
        el.text = _cell(value)
    return el


def _json_to_xml(src: Path, dest: Path, opts: dict) -> dict:
    root = _json_to_element(_load_json(src), "root")
    ET.indent(root)
    dest.write_text(ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n")
    return {"via": "builtin"}


def _element_to_json(el: ET.Element) -> Any:
    children = list(el)
    if not children and not el.attrib:
        return (el.text or "").strip()
    out: dict[str, Any] = {f"@{k}": v for k, v in el.attrib.items()}
    text = (el.text or "").strip()
    if text:
        out["#text"] = text
    groups: dict[str, list[Any]] = {}
    for child in children:
        groups.setdefault(child.tag, []).append(_element_to_json(child))
    for tag, vals in groups.items():
        out[tag] = vals[0] if len(vals) == 1 else vals
    return out


def _xml_to_json(src: Path, dest: Path, opts: dict) -> dict:
    try:
        root = ET.parse(src).getroot()
    except ET.ParseError as e:
        raise CarrelInputError(f"invalid XML in {src}: {e}") from e
    data = {root.tag: _element_to_json(root)}
    dest.write_text(jsonlib.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {"via": "builtin"}


# ---- office & ebook documents (pandoc) -------------------------------------


def _pandoc_reader(src: Path) -> str:
    """pandoc `-f` name for the detected source type (bytes, never the extension)."""
    src_type = detect_or_die(src)
    reader = _PANDOC_FROM.get(src_type)
    if reader is None:
        raise CarrelInputError(f"pandoc cannot read {src_type.value}: {src}")
    return reader


def _txt_paragraph_html(text: str) -> str:
    """Plain text → escaped <p> blocks (blank-line paragraphs, <br> line breaks)."""
    paras = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "\n".join(
        "<p>" + "<br>\n".join(htmllib.escape(ln) for ln in p.splitlines()) + "</p>" for p in paras
    )


def _pandoc_doc(to_fmt: str, *extra: str) -> Callable[[Path, Path, dict], dict]:
    """Converter factory: any pandoc-readable source → `to_fmt` (docx/odt/epub/md/html/txt)."""

    def convert(src: Path, dest: Path, opts: dict) -> dict:
        adapters.require("pandoc")
        src_type = detect_or_die(src)
        if src_type is FileType.TXT:  # pandoc has no plain-text reader; wrap first
            with tempfile.TemporaryDirectory(prefix="carrel-convert-") as td:
                page = Path(td) / f"{src.stem}.html"
                body = _txt_paragraph_html(src.read_text(errors="replace"))
                page.write_text(_html_doc(src.stem, body))
                _run_pandoc(page, dest, "html", to_fmt, *extra)
            return {"via": "pandoc"}
        args = list(extra)
        if to_fmt == "html":  # standalone page; pandoc wants a title
            args += ["-s", "--metadata", f"title={src.stem}"]
        _run_pandoc(src, dest, _pandoc_reader(src), to_fmt, *args)
        return {"via": "pandoc"}

    return convert


_doc_to_md = _pandoc_doc("gfm")
_doc_to_html = _pandoc_doc("html")
_doc_to_txt = _pandoc_doc("plain", "--wrap=none")
_to_docx = _pandoc_doc("docx")
_to_odt = _pandoc_doc("odt")
_to_epub = _pandoc_doc("epub")


def _doc_to_pdf(src: Path, dest: Path, opts: dict) -> dict:
    """docx/odt/epub/rtf → pdf: pandoc to HTML, then the weasyprint chain."""
    adapters.require("pandoc")
    adapters.require("weasyprint")
    with tempfile.TemporaryDirectory(prefix="carrel-convert-") as td:
        page = Path(td) / f"{src.stem}.html"
        _doc_to_html(src, page, opts)
        _weasyprint(page, dest)
    return {"via": "pandoc+weasyprint"}


# ---- spreadsheets (openpyxl) -----------------------------------------------


def _write_csv_rows(dest: Path, rows: list[list[Any]]) -> None:
    with dest.open("w", newline="") as fh:
        writer = csv.writer(fh)
        for row in rows:
            writer.writerow([textextract.cell_text(v) for v in row])


def _xlsx_to_csv(src: Path, dest: Path, opts: dict) -> dict:
    sheets = textextract.xlsx_rows(src)
    which = opts.get("sheet")
    if which != "all":
        _write_csv_rows(dest, sheets[textextract.select_sheet(sheets, which)])
        return {"via": "openpyxl"}
    if not sheets:
        raise CarrelInputError(f"workbook has no sheets: {src}")
    targets = [
        dest.with_name(f"{dest.stem}-{_SAFE_NAME.sub('_', name)}{dest.suffix}") for name in sheets
    ]
    for target in targets:
        _check_overwrite(target, opts.get("force", False))
    for rows, target in zip(sheets.values(), targets, strict=True):
        _write_csv_rows(target, rows)
    return {"via": "openpyxl", "dest": str(targets[0]), "dests": [str(t) for t in targets]}


def _sheet_records(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Header row → keys (blank headers become col<N>); remaining rows → objects."""
    if not rows:
        return []
    header = [textextract.cell_text(h) or f"col{i + 1}" for i, h in enumerate(rows[0])]
    records = []
    for row in rows[1:]:
        if all(v is None for v in row):
            continue
        rec: dict[str, Any] = {}
        for key, value in zip(header, row, strict=False):
            rec[key] = value.isoformat() if hasattr(value, "isoformat") else value
        records.append(rec)
    return records


def _xlsx_to_json(src: Path, dest: Path, opts: dict) -> dict:
    sheets = textextract.xlsx_rows(src)
    which = opts.get("sheet")
    if which not in (None, "all"):
        name = textextract.select_sheet(sheets, which)
        sheets = {name: sheets[name]}
    data = {name: _sheet_records(rows) for name, rows in sheets.items()}
    dest.write_text(jsonlib.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {"via": "openpyxl"}


# --------------------------------------------------------------------------
# routing table

_F = FileType
CONVERTERS: dict[tuple[FileType, FileType], Callable[[Path, Path, dict], dict]] = {
    (_F.MD, _F.HTML): _md_to_html,
    (_F.MD, _F.TXT): _md_to_txt,
    (_F.MD, _F.PDF): _to_pdf,
    (_F.HTML, _F.MD): _html_to_md,
    (_F.HTML, _F.TXT): _html_to_txt,
    (_F.HTML, _F.PDF): _to_pdf,
    (_F.TXT, _F.MD): _copy,
    (_F.TXT, _F.HTML): _txt_to_html,
    (_F.TXT, _F.PDF): _to_pdf,
    (_F.PDF, _F.TXT): _pdf_to_txt,
    (_F.PDF, _F.MD): _pdf_to_md,
    (_F.PDF, _F.HTML): _pdf_to_html,
    (_F.PDF, _F.PNG): _pdf_to_image,
    (_F.PDF, _F.JPG): _pdf_to_image,
    (_F.PNG, _F.JPG): _image_convert,
    (_F.PNG, _F.ICO): _image_convert,
    (_F.PNG, _F.PDF): _image_convert,
    (_F.JPG, _F.PNG): _image_convert,
    (_F.JPG, _F.ICO): _image_convert,
    (_F.JPG, _F.PDF): _image_convert,
    (_F.ICO, _F.PNG): _image_convert,
    (_F.ICO, _F.JPG): _image_convert,
    (_F.ICO, _F.PDF): _image_convert,
    (_F.JSON, _F.CSV): _json_to_csv,
    (_F.JSON, _F.XML): _json_to_xml,
    (_F.JSON, _F.HTML): _json_to_html,
    (_F.CSV, _F.JSON): _csv_to_json,
    (_F.CSV, _F.MD): _csv_to_md,
    (_F.CSV, _F.HTML): _csv_to_html,
    (_F.XML, _F.JSON): _xml_to_json,
    # office & ebook documents (pandoc)
    **{(s, _F.MD): _doc_to_md for s in (_F.DOCX, _F.ODT, _F.EPUB, _F.RTF)},
    **{(s, _F.HTML): _doc_to_html for s in (_F.DOCX, _F.ODT, _F.EPUB, _F.RTF)},
    **{(s, _F.TXT): _doc_to_txt for s in (_F.DOCX, _F.ODT, _F.EPUB, _F.RTF)},
    **{(s, _F.PDF): _doc_to_pdf for s in (_F.DOCX, _F.ODT, _F.EPUB, _F.RTF)},
    (_F.DOCX, _F.EPUB): _to_epub,
    (_F.EPUB, _F.DOCX): _to_docx,
    **{(s, _F.DOCX): _to_docx for s in (_F.MD, _F.HTML, _F.TXT)},
    **{(s, _F.ODT): _to_odt for s in (_F.MD, _F.HTML, _F.TXT)},
    # spreadsheets (openpyxl; read-only in this release)
    (_F.XLSX, _F.CSV): _xlsx_to_csv,
    (_F.XLSX, _F.JSON): _xlsx_to_json,
}


def supported_targets(src_type: FileType) -> list[str]:
    return sorted(d.value for (s, d) in CONVERTERS if s is src_type)


def convert_file(
    src: Path | str,
    dest: Path | str,
    force: bool = False,
    *,
    pages: str = "first",
    sheet: str | None = None,
) -> dict[str, Any]:
    """Convert one file; returns {"src", "dest", "via", "ok", ...}.

    Raises CarrelInputError (exit 4) for unsupported input or pair,
    CarrelError (exit 1) when dest exists and force is False, and
    MissingDependencyError (exit 3) when a needed binary is absent.
    `pages` ("first"|"all") only affects pdf → png/jpg; with "all" the
    outputs are DEST-1.ext..DEST-N.ext, listed under "dests".
    `sheet` (None|NAME|N|"all") only affects xlsx → csv/json; "all" with
    csv writes DEST-<sheet>.csv per sheet, listed under "dests".
    """
    src, dest = Path(src), Path(dest)
    src_type = detect_or_die(src)
    dest_type = normalize_target(dest.suffix)
    if dest_type is None:
        raise CarrelInputError(
            f"unsupported target type: '{dest.suffix or dest.name}' "
            f"(supported targets for {src_type.value}: "
            f"{', '.join(supported_targets(src_type)) or 'none'})"
        )
    fn = CONVERTERS.get((src_type, dest_type))
    if fn is None:
        raise CarrelInputError(
            f"cannot convert {src_type.value} → {dest_type.value} "
            f"(supported targets for {src_type.value}: "
            f"{', '.join(supported_targets(src_type)) or 'none'})"
        )
    multi = (fn is _pdf_to_image and pages == "all") or (fn is _xlsx_to_csv and sheet == "all")
    if not multi:
        _check_overwrite(dest, force)
    dest.parent.mkdir(parents=True, exist_ok=True)
    info = fn(src, dest, {"pages": pages, "force": force, "sheet": sheet})
    via = info.pop("via")
    return {"src": str(src), "dest": info.pop("dest", str(dest)), "via": via, "ok": True, **info}


# --------------------------------------------------------------------------
# CLI


def _matrix_epilog() -> str:
    by_src: dict[str, list[str]] = {}
    for s, d in CONVERTERS:
        by_src.setdefault(s.value, []).append(d.value)
    lines = [f"  {s:<5} → {', '.join(sorted(ts))}" for s, ts in sorted(by_src.items())]
    return "\b\nSupported conversions (SRC type → --to targets):\n" + "\n".join(lines)


def _human(results: list[dict[str, Any]]) -> None:
    for r in results:
        if r.get("ok"):
            dests = r.get("dests") or [r["dest"]]
            click.echo(f"{r['src']} -> {', '.join(dests)}  [{r['via']}]")


@click.command(name="convert", epilog=_matrix_epilog())
@click.argument(
    "sources", nargs=-1, required=True, metavar="SRC...", type=click.Path(path_type=Path)
)
@click.option(
    "--to",
    "to",
    required=True,
    metavar="EXT",
    help="Target type: pdf, md, txt, html, json, xml, csv, png, jpg, ico, docx, odt, epub.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Explicit output path (single SRC only).",
)
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Write outputs into this directory (required for multiple SRC).",
)
@click.option("--force", is_flag=True, help="Overwrite existing outputs.")
@click.option(
    "--pages",
    type=click.Choice(["first", "all"]),
    default="first",
    show_default=True,
    help="pdf → png/jpg only: rasterize the first page, or every page as DEST-1..N.",
)
@click.option(
    "--sheet",
    metavar="NAME|N|all",
    help="xlsx → csv/json only: pick a sheet by name or 1-based number (default: first; "
    "json defaults to every sheet). 'all' with csv writes DEST-<sheet>.csv per sheet.",
)
@click.pass_context
def cmd(
    ctx: click.Context,
    sources: tuple[Path, ...],
    to: str,
    output: Path | None,
    out_dir: Path | None,
    force: bool,
    pages: str,
    sheet: str | None,
) -> None:
    """Convert SRC... to another supported type.

    By default the output lands next to each SRC with the new extension.
    Existing outputs are never overwritten without --force. With --json,
    prints one JSON array of {"src", "dest", "via", "ok"} records.

    Office and ebook sources (docx, odt, epub, rtf) are read by pandoc and
    can go to md/html/txt/pdf (pdf also needs weasyprint); md/html/txt can
    be written as docx or odt, and docx <-> epub round-trips. xlsx reads
    need the `office` extra (openpyxl) and go to csv or json only.
    """
    dest_type = normalize_target(to)
    if dest_type is None:
        known = sorted(t.value for t in FileType if t is not FileType.UNKNOWN)
        raise click.UsageError(f"unknown target type '{to}' (choose from: {', '.join(known)})")
    if output and out_dir:
        raise click.UsageError("-o/--output and --out-dir are mutually exclusive")
    if len(sources) > 1 and not out_dir:
        raise click.UsageError("multiple SRC files require --out-dir")
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    first_err = 0
    for src in sources:
        dest = output or ((out_dir or src.parent) / src.name).with_suffix(f".{dest_type.value}")
        try:
            results.append(convert_file(src, dest, force=force, pages=pages, sheet=sheet))
        except CarrelError as e:
            if ctx.obj and ctx.obj.get("debug"):
                raise
            results.append(
                {"src": str(src), "dest": str(dest), "via": None, "ok": False, "error": str(e)}
            )
            click.echo(f"error: {e}", err=True)
            first_err = first_err or int(e.exit_code)
    emit(ctx, results, human=_human)
    if first_err:
        sys.exit(first_err)
