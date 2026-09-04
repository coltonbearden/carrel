"""Unit tests for carrel.core.textextract (spec 00-core Acceptance)."""

from __future__ import annotations

import pytest
from conftest import needs

from carrel.core.output import CarrelInputError
from carrel.core.textextract import extract_text, html_to_text, markdown_to_html


def test_txt(fixtures):
    text = extract_text(fixtures / "sample.txt")
    assert "quixotic zephyr" in text
    assert "jane.doe@example.com" in text
    assert "123-45-6789" in text


def test_md(fixtures):
    text = extract_text(fixtures / "sample.md")
    assert "melodious cartography" in text
    assert "# Chapter One" in text  # md is returned raw


def test_html(fixtures):
    text = extract_text(fixtures / "sample.html")
    assert "Carrel Sample Page" in text
    assert "Zephyr Atlas" in text  # table cell survives
    assert "<h1>" not in text  # tags stripped
    assert "font-family" not in text  # <style> content dropped


def test_json(fixtures):
    text = extract_text(fixtures / "sample.json")
    assert "library.name: reading desk test library" in text
    assert "records.0.name: Ada" in text  # list items flattened with index
    assert "counts.books: 1204" in text


def test_json_invalid(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(CarrelInputError, match="invalid JSON"):
        extract_text(bad)


def test_xml(fixtures):
    text = extract_text(fixtures / "sample.xml")
    assert "Zephyr Atlas" in text
    assert "<shelf" not in text


def test_csv(fixtures):
    text = extract_text(fixtures / "sample.csv")
    lines = text.strip().splitlines()
    assert lines[0] == "id, title, shelf, year, checked_out"
    assert len(lines) == 21  # header + 20 rows


@needs("pdftotext")
def test_pdf(fixtures):
    text = extract_text(fixtures / "text+image.pdf")
    assert "palimpsest harbor" in text
    assert "Page Two" in text


def test_image_without_ocr_is_empty(fixtures):
    assert extract_text(fixtures / "sample.png") == ""
    assert extract_text(fixtures / "sample.jpg", ocr=False) == ""


@needs("tesseract")
def test_image_ocr(fixtures):
    text = " ".join(extract_text(fixtures / "scanned.png", ocr=True).split())
    assert "CARREL OCR" in text
    assert "FIXTURE 42" in text


@needs("pdftotext")
def test_scanned_pdf_without_ocr_is_empty(fixtures):
    assert extract_text(fixtures / "scanned.pdf").strip() == ""


@needs("pdftotext")
@needs("ocrmypdf")
def test_scanned_pdf_with_ocr(fixtures):
    text = " ".join(extract_text(fixtures / "scanned.pdf", ocr=True).split())
    assert "CARREL OCR" in text
    assert "FIXTURE 42" in text


def test_unsupported_raises(tmp_path):
    p = tmp_path / "blob.zzz"
    p.write_bytes(b"junk")
    with pytest.raises(CarrelInputError):
        extract_text(p)


def test_missing_raises(tmp_path):
    with pytest.raises(CarrelInputError):
        extract_text(tmp_path / "ghost.txt")


def test_html_to_text_collapses_blank_runs():
    out = html_to_text("<p>a</p><p></p><div></div><p>b</p>")
    assert out == "a\n\nb\n"


def test_markdown_to_html(fixtures):
    html = markdown_to_html((fixtures / "sample.md").read_text())
    assert "<h1>Chapter One: The Reading Room</h1>" in html
    assert "<code" in html
    assert '<a href="https://example.com/reading-desk"' in html
