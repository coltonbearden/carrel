"""carrel inspect — metadata for one file: common fields plus per-type detail.

`inspect_file()` is the library entry point (reused by the desk TUI and the
MCP server); the click command `cmd` is a thin wrapper around it.

inspect never exits 3: the only optional binary it can use is exiftool
(`--deep`), and its absence is annotated in the output instead of failing.
"""

from __future__ import annotations

import contextlib
import csv
import functools
import hashlib
import json as jsonlib
import mimetypes
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

import click

from carrel.core import adapters, textextract
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

_SHA256_CAP = 512 * 1024 * 1024  # skip hashing files >= 512 MB

# XML namespaces inside office/ebook containers
_NS_DC = "{http://purl.org/dc/elements/1.1/}"
_NS_DCTERMS = "{http://purl.org/dc/terms/}"
_NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NS_OPF = "{http://www.idpf.org/2007/opf}"
_NS_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"


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


def _sha256(path: Path) -> str | None:
    if path.stat().st_size >= _SHA256_CAP:
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# per-type detail
# ---------------------------------------------------------------------------


def _pdf_detail(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001 — inspection degrades, never crashes
        return {"error": f"unreadable PDF: {e}"}
    detail: dict[str, Any] = {"encrypted": bool(reader.is_encrypted)}
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            detail.update(
                {
                    "pages": None,
                    "title": None,
                    "author": None,
                    "producer": None,
                    "form_fields": None,
                    "annotations": None,
                }
            )
            return detail
    try:
        detail["pages"] = len(reader.pages)
    except Exception:  # noqa: BLE001
        detail["pages"] = None
    meta = None
    with contextlib.suppress(Exception):  # metadata is optional and pypdf is picky
        meta = reader.metadata
    detail["title"] = meta.title if meta else None
    detail["author"] = meta.author if meta else None
    detail["producer"] = meta.producer if meta else None
    try:
        fields = reader.get_fields()
    except Exception:  # noqa: BLE001
        fields = None
    detail["form_fields"] = len(fields) if fields else 0
    annotations = 0
    try:
        for page in reader.pages:
            annotations += len(page.get("/Annots") or [])
    except Exception:  # noqa: BLE001, S110 — a malformed page must not sink the whole report
        pass
    detail["annotations"] = annotations
    return detail


def _image_detail(path: Path) -> dict[str, Any]:
    from PIL import Image
    from PIL.ExifTags import IFD, TAGS

    try:
        with Image.open(path) as im:
            detail: dict[str, Any] = {
                "width": im.width,
                "height": im.height,
                "mode": im.mode,
                "format": im.format,
            }
            sizes = im.info.get("sizes")
            if sizes:  # multi-size .ico
                detail["sizes"] = sorted([list(s) for s in sizes])
            summary: dict[str, str] = {}
            try:
                exif = im.getexif()
                items = list(exif.items())
                with contextlib.suppress(Exception):  # no Exif IFD is normal
                    items += list(exif.get_ifd(IFD.Exif).items())
                for tag, value in items:
                    summary[TAGS.get(tag, f"0x{tag:04x}")] = str(value)
            except Exception:  # noqa: BLE001, S110 — corrupt EXIF: report the image without it
                pass
            detail["exif"] = summary or None
            return detail
    except Exception as e:  # noqa: BLE001
        return {"error": f"unreadable image: {e}"}


def _json_depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_json_depth(v) for v in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(v) for v in value), default=0)
    return 0


def _json_detail(path: Path) -> dict[str, Any]:
    try:
        data = jsonlib.loads(path.read_text(errors="replace"))
    except jsonlib.JSONDecodeError as e:
        return {"error": f"invalid JSON: {e}"}
    if isinstance(data, dict):
        shape, keys = "object", len(data)
    elif isinstance(data, list):
        shape, keys = "array", len(data)
    else:
        shape, keys = "scalar", 0
    return {"shape": shape, "keys": keys, "depth": _json_depth(data)}


def _csv_detail(path: Path) -> dict[str, Any]:
    try:
        with path.open(newline="", errors="replace") as fh:
            sample = fh.read(64 * 1024)
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except csv.Error:
            delimiter = ","
        with path.open(newline="", errors="replace") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
    except OSError as e:
        return {"error": str(e)}
    return {"delimiter": delimiter, "columns": header, "column_count": len(header), "rows": rows}


def _xml_detail(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return {"error": f"invalid XML: {e}"}

    def depth(el: ET.Element) -> int:
        return 1 + max((depth(c) for c in el), default=0)

    return {"root": root.tag, "elements": sum(1 for _ in root.iter()), "depth": depth(root)}


class _HTMLOutline(HTMLParser):
    _H: ClassVar[dict[str, int]] = {f"h{i}": i for i in range(1, 7)}

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.headings: list[dict[str, Any]] = []
        self.links = 0
        self.images = 0
        self._level: int | None = None
        self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a":
            self.links += 1
        elif tag == "img":
            self.images += 1
        elif tag in self._H:
            self._level, self._buf = self._H[tag], []
        elif tag == "title":
            self._in_title, self._buf = True, []

    def handle_data(self, data: str) -> None:
        if self._level is not None or self._in_title:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._H and self._level is not None:
            self.headings.append({"level": self._level, "text": "".join(self._buf).strip()})
            self._level = None
        elif tag == "title" and self._in_title:
            self.title = "".join(self._buf).strip()
            self._in_title = False


def _html_detail(path: Path) -> dict[str, Any]:
    parser = _HTMLOutline()
    parser.feed(path.read_text(errors="replace"))
    return {
        "title": parser.title,
        "headings": parser.headings,
        "links": parser.links,
        "images": parser.images,
    }


def _md_detail(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    headings: list[dict[str, Any]] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        title = stripped[level:].strip()
        if 1 <= level <= 6 and title:
            headings.append({"level": level, "text": title})
    return {"headings": headings, "words": len(text.split())}


def _txt_detail(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    return {"lines": len(text.splitlines()), "words": len(text.split()), "chars": len(text)}


def _zip_xml(path: Path, member: str) -> ET.Element | None:
    """Parsed XML member of a zip container, or None when absent/unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            return ET.fromstring(zf.read(member))
    except Exception:  # noqa: BLE001 — inspection degrades, never crashes
        return None


def _document_words(path: Path, ftype: FileType) -> int | None:
    """Word count via pandoc; None (never exit 3) when pandoc is missing or fails."""
    if not adapters.have("pandoc"):
        return None
    try:
        return len(textextract.document_text(path, ftype).split())
    except CarrelError:
        return None


def _docx_detail(path: Path) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "paragraphs": None,
        "words": _document_words(path, FileType.DOCX),
        "title": None,
        "author": None,
        "created": None,
    }
    body = _zip_xml(path, "word/document.xml")
    if body is not None:
        detail["paragraphs"] = sum(1 for _ in body.iter(f"{_NS_W}p"))
    core = _zip_xml(path, "docProps/core.xml")
    if core is not None:
        detail["title"] = core.findtext(f"{_NS_DC}title") or None
        detail["author"] = core.findtext(f"{_NS_DC}creator") or None
        detail["created"] = core.findtext(f"{_NS_DCTERMS}created") or None
    return detail


def _epub_detail(path: Path) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "title": None,
        "creator": None,
        "language": None,
        "spine_items": None,
        "words": _document_words(path, FileType.EPUB),
    }
    container = _zip_xml(path, "META-INF/container.xml")
    rootfile = container.find(f".//{_NS_CONTAINER}rootfile") if container is not None else None
    opf_path = rootfile.get("full-path") if rootfile is not None else None
    opf = _zip_xml(path, opf_path) if opf_path else None
    if opf is None:
        detail["error"] = "no readable OPF package document"
        return detail
    detail["title"] = opf.findtext(f".//{_NS_DC}title") or None
    detail["creator"] = opf.findtext(f".//{_NS_DC}creator") or None
    detail["language"] = opf.findtext(f".//{_NS_DC}language") or None
    detail["spine_items"] = len(opf.findall(f".//{_NS_OPF}spine/{_NS_OPF}itemref"))
    return detail


def _document_detail(path: Path, ftype: FileType) -> dict[str, Any]:
    """odt / rtf: word count only (size is a top-level field)."""
    return {"words": _document_words(path, ftype)}


def _xlsx_detail(path: Path) -> dict[str, Any]:
    try:
        sheets = textextract.xlsx_rows(path)
    except adapters.MissingDependencyError as e:
        return {"sheets": None, "error": f"openpyxl not installed — {e.adapter.install_hint}"}
    except CarrelInputError as e:
        return {"sheets": None, "error": str(e)}
    return {
        "sheets": [
            {"name": name, "rows": len(rows), "cols": max((len(r) for r in rows), default=0)}
            for name, rows in sheets.items()
        ]
    }


def _type_detail(path: Path, ftype: FileType) -> dict[str, Any]:
    if ftype is FileType.PDF:
        return _pdf_detail(path)
    if ftype.is_image:
        return _image_detail(path)
    if ftype is FileType.DOCX:
        return _docx_detail(path)
    if ftype is FileType.EPUB:
        return _epub_detail(path)
    if ftype in (FileType.ODT, FileType.RTF):
        return _document_detail(path, ftype)
    if ftype is FileType.XLSX:
        return _xlsx_detail(path)
    if ftype is FileType.JSON:
        return _json_detail(path)
    if ftype is FileType.CSV:
        return _csv_detail(path)
    if ftype is FileType.XML:
        return _xml_detail(path)
    if ftype is FileType.HTML:
        return _html_detail(path)
    if ftype is FileType.MD:
        return _md_detail(path)
    return _txt_detail(path)  # TXT


def _exiftool_tags(path: Path) -> Any:
    """Full exiftool tag table, or an annotation string — never an error."""
    if not adapters.have("exiftool"):
        return "not installed"
    try:
        proc = adapters.run("exiftool", "-json", str(path))
        if proc.returncode != 0:
            msg = (proc.stderr or "exiftool failed").strip().splitlines()
            return f"error: {msg[0] if msg else 'exiftool failed'}"
        tags = jsonlib.loads(proc.stdout)[0]
        tags.pop("SourceFile", None)
        return tags
    except Exception as e:  # noqa: BLE001 — --deep degrades, never exits 3
        return f"error: {e}"


# ---------------------------------------------------------------------------
# library entry point
# ---------------------------------------------------------------------------


def inspect_file(path: Path | str, deep: bool = False) -> dict[str, Any]:
    """Metadata for one file: name/size/mtime/type/sha256/mime + per-type detail.

    With deep=True, adds an "exiftool" key: the full tag table when exiftool
    is installed, else the string "not installed". Never raises
    MissingDependencyError; raises CarrelInputError for missing/unsupported
    files (exit 4 at the CLI).
    """
    path = Path(path)
    ftype = detect_or_die(path)
    st = path.stat()
    info: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "type": ftype.value,
        "mime": mimetypes.guess_type(path.name)[0],
        "sha256": _sha256(path),
        "detail": _type_detail(path, ftype),
    }
    if deep:
        info["exiftool"] = _exiftool_tags(path)
    return info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render(info: dict[str, Any]) -> None:
    for key in ("name", "path", "type", "mime", "size", "mtime", "sha256"):
        click.echo(f"{key:10} {info.get(key)}")
    click.echo("detail:")
    for k, v in (info.get("detail") or {}).items():
        if isinstance(v, (dict, list)):
            v = jsonlib.dumps(v, ensure_ascii=False)
        click.echo(f"  {k:14} {v}")
    if "exiftool" in info:
        table = info["exiftool"]
        if isinstance(table, dict):
            click.echo(f"exiftool ({len(table)} tags):")
            for k, v in table.items():
                click.echo(f"  {k:30} {v}")
        else:
            click.echo(f"exiftool: {table}")


@click.command(name="inspect")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option(
    "--deep",
    is_flag=True,
    help="Add exiftool's full tag table when exiftool is installed; "
    "without it the output notes 'not installed' (never an error).",
)
@click.pass_context
@_handled
def cmd(ctx: click.Context, path: Path, as_json: bool, deep: bool) -> None:
    """Show metadata for one file.

    Always: name, size, mtime, detected type, sha256 (files under 512 MB) and
    a mime guess. Plus per-type detail: pdf (pages, title/author/producer,
    encryption, form fields, annotations), images (dimensions, mode, EXIF
    summary), json (shape, key count, depth), csv (dialect, columns, rows),
    xml (root tag, element count, depth), html (title, headings outline,
    link/img counts), md (headings outline, word count), txt
    (lines/words/chars), docx (paragraphs, words, title/author/created),
    epub (title, creator, language, spine items, words), odt/rtf (words),
    xlsx (sheets with row/column counts; needs the `office` extra).
    Word counts for office/ebook files use pandoc and are null without it.
    """
    ctx.ensure_object(dict)
    if as_json:
        ctx.obj["json"] = True
    emit(ctx, inspect_file(path, deep=deep), human=_render)
