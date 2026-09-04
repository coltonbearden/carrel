"""Shared text-extraction spine: pack, index, diff, audiobook and convert all reuse this."""

from __future__ import annotations

import csv
import json
import re
import tempfile
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelInputError

# pandoc reader name per document type — chosen from the *detected* type, never the extension
PANDOC_READERS: dict[FileType, str] = {
    FileType.DOCX: "docx",
    FileType.ODT: "odt",
    FileType.EPUB: "epub",
    FileType.RTF: "rtf",
}

# openpyxl is a Python package, not a binary, so it is not in adapters.ADAPTERS
# (doctor would try to `which` it). It still raises the same MissingDependencyError
# so the CLI exits 3 with an install hint like every other optional dependency.
OPENPYXL = adapters.Adapter(
    name="openpyxl",
    binaries=("openpyxl",),
    version_args=(),
    install_hint="uv tool install 'carrel[office]'  (from a checkout: uv sync --extra office)",
    purpose="read .xlsx workbooks (xlsx → text/csv/json, inspect)",
)


class _HTMLTextParser(HTMLParser):
    _SKIP: ClassVar[set[str]] = {"script", "style", "head"}
    _BLOCK: ClassVar[set[str]] = {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "table",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLTextParser()
    parser.feed(html)
    lines = [ln.strip() for ln in "".join(parser.parts).splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def _flatten_json(value: object, prefix: str = "") -> list[str]:
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            lines.extend(_flatten_json(v, f"{prefix}{k}."))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            lines.extend(_flatten_json(v, f"{prefix}{i}."))
    else:
        lines.append(f"{prefix[:-1]}: {value}")
    return lines


def pdf_text(path: Path, ocr: bool = False) -> str:
    proc = adapters.run("pdftotext", "-layout", str(path), "-")
    text = proc.stdout if proc.returncode == 0 else ""
    if ocr and len(text.strip()) < 20 and adapters.have("ocrmypdf"):
        with tempfile.TemporaryDirectory() as td:
            ocred = Path(td) / "ocr.pdf"
            proc = adapters.run(
                "ocrmypdf", "--skip-text", "--quiet", str(path), str(ocred), timeout=600
            )
            if proc.returncode in (0, 10) and ocred.exists():  # 10 = ocrmypdf "done with warnings"
                proc2 = adapters.run("pdftotext", "-layout", str(ocred), "-")
                if proc2.returncode == 0:
                    text = proc2.stdout
    return text


def image_text(path: Path) -> str:
    proc = adapters.run("tesseract", str(path), "stdout", timeout=300)
    return proc.stdout if proc.returncode == 0 else ""


def document_text(path: Path, ftype: FileType | None = None) -> str:
    """docx/odt/epub/rtf → plain text via pandoc (`-t plain --wrap=none`).

    Raises MissingDependencyError (exit 3) without pandoc and CarrelInputError
    (exit 4) when pandoc cannot read the file. Empty output is not an error.
    """
    ftype = ftype or detect_or_die(path)
    reader = PANDOC_READERS.get(ftype)
    if reader is None:
        raise CarrelInputError(f"not a pandoc-readable document: {path} ({ftype.value})")
    proc = adapters.run("pandoc", "-f", reader, "-t", "plain", "--wrap=none", str(path))
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        raise CarrelInputError(
            f"pandoc could not read {path.name} as {reader}: {err[0] if err else '?'}"
        )
    return proc.stdout


def cell_text(value: Any) -> str:
    """Spreadsheet cell → text the way the CSV flattener would show it."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


_SHEET_INDEX = re.compile(r"[1-9]\d*\Z")


def xlsx_rows(path: Path) -> dict[str, list[list[Any]]]:
    """{sheet name: rows} for a workbook, in workbook order; trailing empty rows dropped.

    Cell values are native Python (str/int/float/bool/datetime/None); formulas
    are read as their cached results (data_only). Raises MissingDependencyError
    when openpyxl is not installed, CarrelInputError for an unreadable workbook.
    """
    try:
        import openpyxl
    except ImportError as e:
        raise adapters.MissingDependencyError(OPENPYXL) from e
    fh = path.open("rb")  # a handle, not a name: openpyxl would reject a mis-named .zip
    try:
        wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises a zoo of zip/xml errors on bad input; re-raised typed
        fh.close()
        raise CarrelInputError(f"cannot read workbook {path.name}: {e}") from e
    sheets: dict[str, list[list[Any]]] = {}
    try:
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            while rows and all(v is None for v in rows[-1]):
                rows.pop()
            sheets[str(ws.title)] = rows
    finally:
        wb.close()
        fh.close()
    return sheets


def select_sheet(sheets: dict[str, list[list[Any]]], which: str | None) -> str:
    """Resolve a `--sheet NAME|N` selector (N is 1-based) to a sheet name."""
    names = list(sheets)
    if not names:
        raise CarrelInputError("workbook has no sheets")
    if which is None:
        return names[0]
    if which in sheets:
        return which
    if _SHEET_INDEX.match(which) and int(which) <= len(names):
        return names[int(which) - 1]
    raise CarrelInputError(f"no sheet '{which}' (sheets: {', '.join(names)})")


def xlsx_text(path: Path) -> str:
    """Every sheet as a `# <name>` heading followed by CSV-flattened rows."""
    blocks = []
    for name, rows in xlsx_rows(path).items():
        lines = [f"# {name}"] + [", ".join(cell_text(v) for v in row) for row in rows]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def extract_text(path: Path | str, ocr: bool = False) -> str:
    """Best-effort plain text for any supported file type."""
    path = Path(path)
    ftype = detect_or_die(path)

    if ftype in (FileType.TXT, FileType.MD):
        return path.read_text(errors="replace")
    if ftype.is_document:
        return document_text(path, ftype)
    if ftype is FileType.XLSX:
        return xlsx_text(path)
    if ftype is FileType.HTML:
        return html_to_text(path.read_text(errors="replace"))
    if ftype is FileType.JSON:
        try:
            return "\n".join(_flatten_json(json.loads(path.read_text()))) + "\n"
        except json.JSONDecodeError as e:
            raise CarrelInputError(f"invalid JSON in {path}: {e}") from e
    if ftype is FileType.XML:
        return html_to_text(path.read_text(errors="replace"))
    if ftype is FileType.CSV:
        with path.open(newline="") as fh:
            return "\n".join(", ".join(row) for row in csv.reader(fh)) + "\n"
    if ftype is FileType.PDF:
        return pdf_text(path, ocr=ocr)
    if ftype.is_image:
        return image_text(path) if ocr else ""
    raise CarrelInputError(f"cannot extract text from {path}")


def markdown_to_html(md_text: str) -> str:
    """Pure-python md→html (pandoc-free fallback)."""
    from markdown_it import MarkdownIt

    return MarkdownIt("commonmark", {"html": True}).enable("table").render(md_text)
