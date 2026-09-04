"""Shared text-extraction spine: pack, index, diff, audiobook and convert all reuse this."""

from __future__ import annotations

import csv
import json
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelInputError


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


def extract_text(path: Path | str, ocr: bool = False) -> str:
    """Best-effort plain text for any supported file type."""
    path = Path(path)
    ftype = detect_or_die(path)

    if ftype in (FileType.TXT, FileType.MD):
        return path.read_text(errors="replace")
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
