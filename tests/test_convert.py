"""Tests for `carrel convert` (spec 01)."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs
from PIL import Image

from carrel.cli import cli
from carrel.commands.convert import (
    CONVERTERS,
    ICO_SIZES,
    convert_file,
    normalize_target,
    supported_targets,
)
from carrel.core.filetypes import FileType
from carrel.core.output import CarrelError, CarrelInputError


def run(*args: str) -> CliRunner.Result:
    return CliRunner().invoke(cli, list(args))


def all_output(res) -> str:
    try:
        return res.output + res.stderr
    except (ValueError, AttributeError):
        return res.output


# ------------------------------------------------------------------ helpers


def test_normalize_target_aliases():
    assert normalize_target(".PDF") is FileType.PDF
    assert normalize_target("jpeg") is FileType.JPG
    assert normalize_target("htm") is FileType.HTML
    assert normalize_target("markdown") is FileType.MD
    assert normalize_target("bogus") is None
    assert normalize_target("unknown") is None


def test_help_lists_supported_pairs():
    res = run("convert", "--help")
    assert res.exit_code == 0
    assert "Supported conversions" in res.output
    # every source type in the table appears in the epilog matrix
    for src_type in {s for (s, _) in CONVERTERS}:
        assert src_type.value in res.output
    for flag in ("--to", "--force", "--out-dir", "--pages", "-o"):
        assert flag in res.output


# ------------------------------------------------------- text conversions


@needs("pandoc")
def test_md_to_html_pandoc(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.md")
    res = run("convert", str(src), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    out = src.with_suffix(".html")
    html = out.read_text()
    assert "<h1" in html and "melodious cartography" in html


def test_md_to_txt(tmp_copy):
    src = tmp_copy("sample.md")
    res = run("convert", str(src), "--to", "txt")
    assert res.exit_code == 0, all_output(res)
    text = src.with_suffix(".txt").read_text()
    assert "melodious cartography" in text
    assert "<h1" not in text and "# Chapter" not in text


def test_html_to_txt_strips_tags(tmp_copy):
    src = tmp_copy("sample.html")
    res = run("convert", str(src), "--to", "txt")
    assert res.exit_code == 0, all_output(res)
    text = src.with_suffix(".txt").read_text()
    assert "The Palimpsest" in text
    assert "<table>" not in text and "font-family" not in text


@needs("pandoc")
def test_html_to_md(tmp_copy):
    src = tmp_copy("sample.html")
    res = run("convert", str(src), "--to", "md")
    assert res.exit_code == 0, all_output(res)
    md = src.with_suffix(".md").read_text()
    assert "Carrel Sample Page" in md
    assert "<body>" not in md


def test_txt_to_md_is_copy_but_new_file(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run("--json", "convert", str(src), "--to", "md")
    assert res.exit_code == 0, all_output(res)
    out = src.with_suffix(".md")
    assert out.exists() and out.read_text() == src.read_text()
    assert json.loads(res.stdout)[0]["via"] == "copy"


def test_txt_to_html_pre_wrapped(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run("convert", str(src), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    html = src.with_suffix(".html").read_text()
    assert "<pre>" in html and "quixotic zephyr" in html


# ------------------------------------------------------------ pdf pipeline


@needs("weasyprint")
def test_md_to_html_to_pdf_chain(tmp_copy, tmp_path: Path):
    """Acceptance: md→html→pdf chain on fixtures."""
    md = tmp_copy("sample.md")
    res = run("convert", str(md), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    html = md.with_suffix(".html")
    res = run("convert", str(html), "--to", "pdf")
    assert res.exit_code == 0, all_output(res)
    pdf = md.with_suffix(".pdf")
    assert pdf.read_bytes().startswith(b"%PDF")


@needs("weasyprint")
def test_md_to_pdf_direct(tmp_copy):
    src = tmp_copy("sample.md")
    res = run("--json", "convert", str(src), "--to", "pdf")
    assert res.exit_code == 0, all_output(res)
    assert src.with_suffix(".pdf").read_bytes().startswith(b"%PDF")
    assert "weasyprint" in json.loads(res.stdout)[0]["via"]


@needs("weasyprint")
def test_txt_to_pdf(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run("convert", str(src), "--to", "pdf")
    assert res.exit_code == 0, all_output(res)
    assert src.with_suffix(".pdf").read_bytes().startswith(b"%PDF")


@needs("pdftotext")
def test_pdf_to_txt_nonempty(tmp_copy):
    """Acceptance: pdf→txt non-empty on the text fixture."""
    src = tmp_copy("text+image.pdf")
    res = run("convert", str(src), "--to", "txt")
    assert res.exit_code == 0, all_output(res)
    text = src.with_suffix(".txt").read_text()
    assert "palimpsest harbor" in text


@needs("pdftotext")
def test_pdf_to_md_pages_become_rules(tmp_copy):
    src = tmp_copy("text+image.pdf")  # two pages
    res = run("convert", str(src), "--to", "md")
    assert res.exit_code == 0, all_output(res)
    md = src.with_suffix(".md").read_text()
    assert "palimpsest harbor" in md
    assert "\n---\n" in md  # page break rendered as a rule
    assert "\f" not in md


@needs("pdftotext")
def test_pdf_to_html_is_pre_block(tmp_copy):
    src = tmp_copy("b.pdf")
    res = run("convert", str(src), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    html = src.with_suffix(".html").read_text()
    assert "<pre>" in html and "second fiddle harbor" in html


@needs("pdftoppm")
def test_pdf_to_png_first_page(tmp_copy):
    src = tmp_copy("b.pdf")
    res = run("--json", "convert", str(src), "--to", "png")
    assert res.exit_code == 0, all_output(res)
    out = src.with_suffix(".png")
    assert out.read_bytes().startswith(b"\x89PNG")
    assert json.loads(res.stdout)[0]["via"] == "pdftoppm"


@needs("pdftoppm")
def test_pdf_to_jpg_all_pages(tmp_copy):
    src = tmp_copy("text+image.pdf")  # two pages
    res = run("--json", "convert", str(src), "--to", "jpg", "--pages", "all")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)[0]
    assert len(rec["dests"]) == 2
    for d in rec["dests"]:
        assert Path(d).read_bytes().startswith(b"\xff\xd8\xff")
    assert rec["dest"] == rec["dests"][0]


# ---------------------------------------------------------------- images


def test_png_to_ico_to_png_roundtrip(tmp_copy):
    """Acceptance: png→ico→png roundtrip."""
    src = tmp_copy("sample.png")
    res = run("convert", str(src), "--to", "ico")
    assert res.exit_code == 0, all_output(res)
    ico = src.with_suffix(".ico")
    with Image.open(ico) as im:
        assert im.format == "ICO"
        sizes = im.info["sizes"]
        assert {(s, s) for s in ICO_SIZES} <= set(sizes)
    res = run("convert", str(ico), "--to", "png", "--force")
    assert res.exit_code == 0, all_output(res)
    with Image.open(src.with_suffix(".png")) as back:
        assert back.format == "PNG"
        assert max(back.size) == max(ICO_SIZES)  # largest frame wins


def test_small_image_to_ico_upscales(tmp_path: Path):
    src = tmp_path / "tiny.png"
    Image.new("RGB", (20, 20), "red").save(src)
    result = convert_file(src, tmp_path / "tiny.ico")
    with Image.open(result["dest"]) as im:
        assert {(s, s) for s in ICO_SIZES} <= set(im.info["sizes"])


def test_jpg_to_png_and_back(tmp_copy):
    src = tmp_copy("sample.jpg")
    assert run("convert", str(src), "--to", "png").exit_code == 0
    png = src.with_suffix(".png")
    with Image.open(png) as im:
        assert im.format == "PNG" and im.size == (400, 300)
    res = run("convert", str(png), "--to", "jpg")  # dest sample.jpg exists
    assert res.exit_code == 1  # refused: the original jpg is already there
    res = run("convert", str(png), "--to", "jpg", "--force")
    assert res.exit_code == 0, all_output(res)


def test_image_to_pdf(tmp_copy):
    src = tmp_copy("sample.png")
    res = run("convert", str(src), "--to", "pdf")
    assert res.exit_code == 0, all_output(res)
    assert src.with_suffix(".pdf").read_bytes().startswith(b"%PDF")


# ---------------------------------------------------------- data formats


def test_json_csv_json_roundtrip_preserves_flat_data(tmp_copy, tmp_path: Path):
    """Acceptance: json→csv→json preserves flat list-of-objects data."""
    src = tmp_copy("records.json")
    original = json.loads(src.read_text())
    assert run("convert", str(src), "--to", "csv").exit_code == 0
    csv_path = src.with_suffix(".csv")
    assert csv_path.exists()
    back = tmp_path / "back.json"
    assert run("convert", str(csv_path), "--to", "json", "-o", str(back)).exit_code == 0
    assert json.loads(back.read_text()) == original


def test_nested_json_to_csv_dotted_keys(tmp_copy):
    src = tmp_copy("sample.json")
    res = run("convert", str(src), "--to", "csv")
    assert res.exit_code == 0, all_output(res)
    header = src.with_suffix(".csv").read_text().splitlines()[0]
    assert "library.location.city" in header
    assert "records.0.name" in header


def test_csv_to_md_table(tmp_copy):
    src = tmp_copy("sample.csv")
    res = run("convert", str(src), "--to", "md")
    assert res.exit_code == 0, all_output(res)
    lines = src.with_suffix(".md").read_text().splitlines()
    assert lines[0].startswith("| id | title |")
    assert set(lines[1].replace("|", "").split()) == {"---"}
    assert any("Palimpsest Vol 1" in ln for ln in lines)


def test_csv_to_html_table(tmp_copy):
    src = tmp_copy("sample.csv")
    res = run("convert", str(src), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    html = src.with_suffix(".html").read_text()
    assert "<table>" in html and "<th>title</th>" in html
    assert "<td>Zephyr Vol 1</td>" in html


def test_json_to_html_table(tmp_copy):
    src = tmp_copy("records.json")
    res = run("convert", str(src), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    html = src.with_suffix(".html").read_text()
    assert "<th>name</th>" in html and "<td>Ada</td>" in html
    assert "<td>true</td>" in html


def test_json_to_xml(tmp_copy):
    src = tmp_copy("records.json")
    res = run("convert", str(src), "--to", "xml")
    assert res.exit_code == 0, all_output(res)
    root = ET.parse(src.with_suffix(".xml")).getroot()
    assert root.tag == "root"
    items = root.findall("item")
    assert len(items) == 8
    assert items[0].find("name").text == "Ada"
    assert items[0].find("active").text == "true"


def test_xml_to_json(tmp_copy):
    src = tmp_copy("sample.xml")
    res = run("convert", str(src), "--to", "json")
    assert res.exit_code == 0, all_output(res)
    data = json.loads(src.with_suffix(".json").read_text())
    shelves = data["library"]["shelf"]
    assert [s["@id"] for s in shelves] == ["A", "B", "C"]
    assert shelves[0]["book"][0]["title"] == "The Palimpsest"
    assert shelves[2]["book"]["title"] == "Cartography of Sound"  # single child


# ------------------------------------------------- overwrite / bad input


def test_overwrite_refused_without_force(tmp_copy):
    """Acceptance: refuse overwrite without --force (exit 1)."""
    src = tmp_copy("sample.txt")
    assert run("convert", str(src), "--to", "md").exit_code == 0
    res = run("convert", str(src), "--to", "md")
    assert res.exit_code == 1
    assert "--force" in all_output(res)
    res = run("convert", str(src), "--to", "md", "--force")
    assert res.exit_code == 0, all_output(res)


def test_unsupported_pair_exits_4_and_lists_targets(tmp_copy):
    """Acceptance: bad pair → exit 4 with the valid target list."""
    src = tmp_copy("sample.png")
    res = run("convert", str(src), "--to", "csv")
    assert res.exit_code == 4
    out = all_output(res)
    for target in supported_targets(FileType.PNG):
        assert target in out
    assert "ico" in out and "pdf" in out


def test_same_type_pair_is_unsupported(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run("convert", str(src), "--to", "txt")
    assert res.exit_code == 4


def test_missing_source_exits_4(tmp_path: Path):
    res = run("convert", str(tmp_path / "nope.md"), "--to", "html")
    assert res.exit_code == 4
    assert "no such file" in all_output(res)


def test_unknown_target_type_is_usage_error(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run("convert", str(src), "--to", "docx")
    assert res.exit_code == 2
    assert "docx" in all_output(res)


# ------------------------------------------------------- multi-src / -o


def test_multiple_src_requires_out_dir(tmp_copy):
    a, b = tmp_copy("sample.txt"), tmp_copy("sample.md")
    res = run("convert", str(a), str(b), "--to", "html")
    assert res.exit_code == 2
    assert "--out-dir" in all_output(res)


def test_output_and_out_dir_mutually_exclusive(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    res = run(
        "convert",
        str(src),
        "--to",
        "html",
        "-o",
        str(tmp_path / "x.html"),
        "--out-dir",
        str(tmp_path),
    )
    assert res.exit_code == 2


def test_multiple_src_with_out_dir(tmp_copy, tmp_path: Path):
    a, b = tmp_copy("sample.txt"), tmp_copy("sample.csv", "books.csv")
    out = tmp_path / "outputs"
    res = run("--json", "convert", str(a), str(b), "--to", "html", "--out-dir", str(out))
    assert res.exit_code == 0, all_output(res)
    assert (out / "sample.html").exists()  # from sample.txt
    assert (out / "books.html").exists()  # from books.csv
    results = json.loads(res.stdout)
    assert len(results) == 2 and all(r["ok"] for r in results)


def test_batch_continues_after_one_failure(tmp_copy, tmp_path: Path):
    good, bad = tmp_copy("sample.csv"), tmp_copy("sample.png")
    out = tmp_path / "outputs"
    res = run("--json", "convert", str(bad), str(good), "--to", "json", "--out-dir", str(out))
    assert res.exit_code == 4  # first failure's code
    results = json.loads(res.stdout)
    assert [r["ok"] for r in results] == [False, True]
    assert (out / "sample.json").exists()


def test_explicit_output_path(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    dest = tmp_path / "renamed.html"
    res = run("--json", "convert", str(src), "--to", "html", "-o", str(dest))
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)[0]
    assert rec == {"src": str(src), "dest": str(dest), "via": "builtin", "ok": True}
    assert dest.exists()


# ------------------------------------------------------------ library API


def test_convert_file_library_api(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    dest = tmp_path / "out.md"
    result = convert_file(src, dest)
    assert result == {"src": str(src), "dest": str(dest), "via": "copy", "ok": True}
    with pytest.raises(CarrelError):
        convert_file(src, dest)  # exists, force=False
    assert convert_file(src, dest, force=True)["ok"] is True
    with pytest.raises(CarrelInputError):
        convert_file(src, tmp_path / "out.ico")  # txt → ico unsupported


# ------------------------------------------------------------- subprocess


@needs("pdftotext")
def test_subprocess_real_cli(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    dest = tmp_path / "out.txt"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "carrel.cli",
            "--json",
            "convert",
            str(src),
            "--to",
            "txt",
            "-o",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    rec = json.loads(proc.stdout)[0]
    assert rec["ok"] is True and rec["via"] == "pdftotext"
    assert "palimpsest harbor" in dest.read_text()
