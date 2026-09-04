"""Tests for office & ebook formats (spec 18): docx, odt, epub, rtf, xlsx.

Fixtures come from tests/fixtures/generate.py (pandoc for the documents,
openpyxl for the workbook). Document tests skip without pandoc; xlsx tests
skip without openpyxl (`uv run --with openpyxl pytest tests/test_office.py`).
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.commands.convert import CONVERTERS, convert_file, normalize_target, supported_targets
from carrel.commands.inspect import inspect_file
from carrel.core import adapters, textextract
from carrel.core.filetypes import SUPPORTED_EXTENSIONS, FileType, detect, detect_or_die, sniff
from carrel.core.output import CarrelInputError
from carrel.core.textextract import cell_text, document_text, extract_text, select_sheet

MD_SENTINEL = "melodious cartography"
TXT_SENTINEL = "quixotic zephyr"
XLSX_SENTINEL = "Vellum Ledger"
DOCUMENTS = ["sample.docx", "sample.odt", "sample.epub", "sample.rtf"]
OFFICE_HINT = "carrel[office]"


def run(*args: str):
    return CliRunner().invoke(cli, list(args))


def all_output(res) -> str:
    try:
        return res.output + res.stderr
    except (ValueError, AttributeError):
        return res.output


def without_tool(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make `adapters.have/require(name)` behave as if the binary were absent."""
    real_have, real_require = adapters.have, adapters.require

    def fake_have(n: str) -> bool:
        return False if n == name else real_have(n)

    def fake_require(n: str) -> str:
        if n == name:
            raise adapters.MissingDependencyError(adapters.ADAPTERS[name])
        return real_require(n)

    monkeypatch.setattr(adapters, "have", fake_have)
    monkeypatch.setattr(adapters, "require", fake_require)


def without_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # makes `import openpyxl` raise ImportError


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ------------------------------------------------------------------ filetypes


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("sample.docx", FileType.DOCX),
        ("sample.odt", FileType.ODT),
        ("sample.epub", FileType.EPUB),
        ("sample.rtf", FileType.RTF),
        ("sample.xlsx", FileType.XLSX),
    ],
)
def test_detect_office_fixture(fixtures: Path, name: str, expected: FileType):
    path = fixtures / name
    assert path.is_file(), f"fixture missing: run tests/fixtures/generate.py ({name})"
    assert detect(path) is expected
    assert detect_or_die(path) is expected
    assert sniff(path) is expected  # bytes alone are conclusive for every office type


@pytest.mark.parametrize(
    ("name", "disguise", "expected"),
    [
        ("sample.docx", "x.bin", FileType.DOCX),
        ("sample.xlsx", "y.zip", FileType.XLSX),
        ("sample.epub", "z.docx", FileType.EPUB),
        ("sample.odt", "o.md", FileType.ODT),
        ("sample.rtf", "r.txt", FileType.RTF),
    ],
)
def test_bytes_beat_extension(fixtures: Path, tmp_path: Path, name, disguise, expected):
    p = tmp_path / disguise
    p.write_bytes((fixtures / name).read_bytes())
    assert detect(p) is expected


def test_plain_zip_stays_unknown(tmp_path: Path):
    p = tmp_path / "plain.zip"
    p.write_bytes(_zip_bytes({"a.txt": b"hello", "b/c.txt": b"world"}))
    assert sniff(p) is None
    assert detect(p) is FileType.UNKNOWN
    with pytest.raises(CarrelInputError, match="unsupported file type"):
        detect_or_die(p)


def test_unrecognised_zip_falls_back_to_extension(tmp_path: Path):
    p = tmp_path / "named.docx"
    p.write_bytes(_zip_bytes({"a.txt": b"hello"}))
    assert detect(p) is FileType.DOCX  # zip probe inconclusive → name decides


def test_truncated_zip_does_not_raise(fixtures: Path, tmp_path: Path):
    data = (fixtures / "sample.docx").read_bytes()[:300]
    assert data.startswith(b"PK\x03\x04")
    anon = tmp_path / "t.bin"
    anon.write_bytes(data)
    assert detect(anon) is FileType.UNKNOWN
    named = tmp_path / "t.docx"
    named.write_bytes(data)
    assert detect(named) is FileType.DOCX


def test_zip_probe_only_reads_first_64_entries(tmp_path: Path):
    """A docx whose `word/` parts sit past the probe window still resolves (Content_Types first)."""
    entries = {"[Content_Types].xml": b"<Types/>"}
    entries.update({f"customXml/item{i}.xml": b"<x/>" for i in range(70)})
    entries["word/document.xml"] = b"<w:document/>"
    p = tmp_path / "deep.docx"
    p.write_bytes(_zip_bytes(entries))
    assert detect(p) is FileType.DOCX  # by extension fallback: probe stayed bounded and quiet


def test_rtf_magic_and_properties(tmp_path: Path):
    p = tmp_path / "note.bin"
    p.write_bytes(b"{\\rtf1\\ansi Hello}")
    assert detect(p) is FileType.RTF
    for t in (FileType.DOCX, FileType.ODT, FileType.EPUB, FileType.RTF):
        assert t.is_document and not t.is_text and not t.is_image
    assert not FileType.XLSX.is_document and not FileType.PDF.is_document
    for ext in (".docx", ".odt", ".epub", ".rtf", ".xlsx", ".xlsm"):
        assert ext in SUPPORTED_EXTENSIONS
    p2 = tmp_path / "macro.xlsm"
    p2.write_bytes(b"not a zip")
    assert detect(p2) is FileType.XLSX


# ---------------------------------------------------------------- textextract


@needs("pandoc")
@pytest.mark.parametrize("name", DOCUMENTS)
def test_extract_text_documents(fixtures: Path, name: str):
    text = extract_text(fixtures / name)
    assert MD_SENTINEL in text
    assert "Chapter One" in text
    assert "<" not in text.split(MD_SENTINEL)[0][:40]  # plain text, not markup


@needs("pandoc")
def test_document_text_uses_detected_type_not_extension(fixtures: Path, tmp_path: Path):
    disguised = tmp_path / "actually-epub.docx"
    disguised.write_bytes((fixtures / "sample.epub").read_bytes())
    assert MD_SENTINEL in document_text(disguised)


@needs("pandoc")
def test_document_text_bad_input_is_exit_4(tmp_path: Path):
    fake = tmp_path / "fake.docx"
    fake.write_bytes(_zip_bytes({"a.txt": b"not a word document"}))
    with pytest.raises(CarrelInputError, match="pandoc could not read"):
        document_text(fake)


def test_document_text_without_pandoc(fixtures: Path, monkeypatch: pytest.MonkeyPatch):
    without_tool(monkeypatch, "pandoc")
    with pytest.raises(adapters.MissingDependencyError, match="pandoc"):
        extract_text(fixtures / "sample.docx")


def test_document_text_rejects_non_document(fixtures: Path):
    with pytest.raises(CarrelInputError, match="not a pandoc-readable"):
        document_text(fixtures / "sample.txt")


def test_xlsx_text(fixtures: Path):
    pytest.importorskip("openpyxl")
    text = extract_text(fixtures / "sample.xlsx")
    lines = text.splitlines()
    assert lines[0] == "# Books"
    assert lines[1] == "title, shelf, year"
    assert "Vellum Ledger, C1, 2020" in lines
    assert "# Loans" in lines
    assert text.count("\n\n") == 1  # two sheets separated by one blank line
    assert (
        len([ln for ln in lines if ln and not ln.startswith("#")]) == 8
    )  # 2 sheets x (header + 3)


def test_xlsx_text_without_openpyxl(fixtures: Path, monkeypatch: pytest.MonkeyPatch):
    without_openpyxl(monkeypatch)
    with pytest.raises(adapters.MissingDependencyError) as ei:
        extract_text(fixtures / "sample.xlsx")
    assert OFFICE_HINT in str(ei.value)
    assert ei.value.exit_code == 3


def test_xlsx_rows_bad_workbook(tmp_path: Path):
    pytest.importorskip("openpyxl")
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(_zip_bytes({"[Content_Types].xml": b"<Types/>", "xl/nothing": b""}))
    assert detect(bad) is FileType.XLSX
    with pytest.raises(CarrelInputError, match="cannot read workbook"):
        textextract.xlsx_rows(bad)


def test_cell_text_and_select_sheet():
    from datetime import date, datetime

    assert cell_text(None) == ""
    assert cell_text(True) == "true" and cell_text(False) == "false"
    assert cell_text(3) == "3" and cell_text(2.5) == "2.5"
    assert cell_text(date(2021, 6, 15)) == "2021-06-15"
    assert cell_text(datetime(2021, 6, 15, 12, 0)) == "2021-06-15T12:00:00"
    sheets = {"Books": [], "2": [], "Loans": []}
    assert select_sheet(sheets, None) == "Books"
    assert select_sheet(sheets, "Loans") == "Loans"
    assert select_sheet(sheets, "2") == "2"  # a literal name wins over the index reading
    assert select_sheet(sheets, "3") == "Loans"
    with pytest.raises(CarrelInputError, match="no sheet 'Nope'"):
        select_sheet(sheets, "Nope")
    with pytest.raises(CarrelInputError, match="no sheet '9'"):
        select_sheet(sheets, "9")
    with pytest.raises(CarrelInputError, match="no sheets"):
        select_sheet({}, None)


# -------------------------------------------------------------------- convert


def test_targets_and_matrix():
    for name in ("docx", "odt", "epub", "xlsx", "xlsm", "rtf"):
        assert normalize_target(name) is not None
    assert normalize_target("xlsm") is FileType.XLSX
    assert supported_targets(FileType.DOCX) == ["epub", "html", "md", "pdf", "txt"]
    assert supported_targets(FileType.EPUB) == ["docx", "html", "md", "pdf", "txt"]
    assert supported_targets(FileType.RTF) == ["html", "md", "pdf", "txt"]
    assert supported_targets(FileType.XLSX) == ["csv", "json"]
    for src in (FileType.MD, FileType.HTML, FileType.TXT):
        assert {"docx", "odt"} <= set(supported_targets(src))
    assert not any(d is FileType.XLSX for (_, d) in CONVERTERS)  # never write xlsx
    res = run("convert", "--help")
    assert res.exit_code == 0
    for t in ("docx", "odt", "epub", "rtf", "xlsx", "--sheet"):
        assert t in res.output


@needs("pandoc")
def test_md_docx_md_roundtrip(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.md")
    res = run("convert", str(src), "--to", "docx")
    assert res.exit_code == 0, all_output(res)
    docx = src.with_suffix(".docx")
    assert detect(docx) is FileType.DOCX
    back = tmp_path / "back.md"
    info = convert_file(docx, back)
    assert info["via"] == "pandoc"
    assert MD_SENTINEL in back.read_text()
    assert "# Chapter One" in back.read_text()  # heading survives the round-trip


@needs("pandoc")
def test_md_odt_txt(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.md")
    odt = tmp_path / "out.odt"
    convert_file(src, odt)
    assert detect(odt) is FileType.ODT
    res = run("convert", str(odt), "--to", "txt", "--json")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.output)[0]
    assert rec["ok"] and rec["via"] == "pandoc"
    assert MD_SENTINEL in Path(rec["dest"]).read_text()


@needs("pandoc")
def test_txt_to_docx_is_verbatim(tmp_path: Path):
    src = tmp_path / "notes.txt"
    src.write_text("# not a heading\n\n*not emphasis* and a <tag>\nsecond line\n")
    docx = tmp_path / "notes.docx"
    convert_file(src, docx)
    text = document_text(docx)
    assert "# not a heading" in text and "*not emphasis*" in text and "<tag>" in text


@needs("pandoc")
def test_txt_to_odt(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    res = run("convert", str(src), "--to", "odt")
    assert res.exit_code == 0, all_output(res)
    assert TXT_SENTINEL in document_text(src.with_suffix(".odt"))


@needs("pandoc")
@pytest.mark.parametrize("name", DOCUMENTS)
def test_documents_to_html(tmp_copy, name: str):
    src = tmp_copy(name)
    res = run("convert", str(src), "--to", "html")
    assert res.exit_code == 0, all_output(res)
    html = src.with_suffix(".html").read_text()
    assert MD_SENTINEL in html and "<h1" in html and "<title>" in html


@needs("pandoc")
def test_rtf_to_md_and_epub_to_txt(tmp_copy):
    rtf = tmp_copy("sample.rtf")
    res = run("convert", str(rtf), "--to", "md")
    assert res.exit_code == 0, all_output(res)
    assert MD_SENTINEL in rtf.with_suffix(".md").read_text()
    epub = tmp_copy("sample.epub")
    res = run("convert", str(epub), "--to", "txt")
    assert res.exit_code == 0, all_output(res)
    assert MD_SENTINEL in epub.with_suffix(".txt").read_text()


@needs("pandoc")
def test_docx_epub_docx(tmp_copy, tmp_path: Path):
    docx = tmp_copy("sample.docx")
    epub = tmp_path / "rt.epub"
    assert convert_file(docx, epub)["via"] == "pandoc"
    assert detect(epub) is FileType.EPUB
    back = tmp_path / "rt.docx"
    convert_file(epub, back)
    assert detect(back) is FileType.DOCX
    assert MD_SENTINEL in document_text(back)


@needs("pandoc")
def test_docx_to_pdf(tmp_copy):
    src = tmp_copy("sample.docx")
    res = run("convert", str(src), "--to", "pdf", "--json")
    if adapters.have("weasyprint"):
        assert res.exit_code == 0, all_output(res)
        rec = json.loads(res.output)[0]
        assert rec["via"] == "pandoc+weasyprint"
        assert Path(rec["dest"]).read_bytes().startswith(b"%PDF")
    else:
        assert res.exit_code == 3
        assert "weasyprint" in all_output(res) and "install" in all_output(res)


@needs("pandoc")
def test_docx_to_pdf_without_weasyprint(tmp_copy, monkeypatch: pytest.MonkeyPatch):
    without_tool(monkeypatch, "weasyprint")
    src = tmp_copy("sample.docx")
    res = run("convert", str(src), "--to", "pdf")
    assert res.exit_code == 3
    assert "weasyprint" in all_output(res) and "apt install" in all_output(res)


def test_convert_docx_without_pandoc(tmp_copy, monkeypatch: pytest.MonkeyPatch):
    without_tool(monkeypatch, "pandoc")
    src = tmp_copy("sample.docx")
    res = run("convert", str(src), "--to", "md")
    assert res.exit_code == 3
    out = all_output(res)
    assert "pandoc" in out and "sudo apt install pandoc" in out
    assert not src.with_suffix(".md").exists()


def test_md_to_docx_without_pandoc(tmp_copy, monkeypatch: pytest.MonkeyPatch):
    without_tool(monkeypatch, "pandoc")
    src = tmp_copy("sample.md")
    res = run("convert", str(src), "--to", "docx")
    assert res.exit_code == 3 and "pandoc" in all_output(res)


def test_unsupported_office_pair(tmp_copy):
    res = run("convert", str(tmp_copy("sample.xlsx")), "--to", "docx")
    assert res.exit_code == 4
    assert "cannot convert xlsx → docx" in all_output(res)
    assert "csv, json" in all_output(res)
    res = run("convert", str(tmp_copy("sample.csv")), "--to", "xlsx")
    assert res.exit_code == 4
    assert "cannot convert csv → xlsx" in all_output(res)


def test_xlsx_to_csv_default_first_sheet(tmp_copy):
    pytest.importorskip("openpyxl")
    src = tmp_copy("sample.xlsx")
    res = run("convert", str(src), "--to", "csv", "--json")
    assert res.exit_code == 0, all_output(res)
    assert json.loads(res.output)[0]["via"] == "openpyxl"
    lines = src.with_suffix(".csv").read_text().splitlines()
    assert lines[0] == "title,shelf,year"
    assert len(lines) == 4  # header + 3 data rows
    assert "Vellum Ledger,C1,2020" in lines


def test_xlsx_to_csv_sheet_selection(tmp_copy, tmp_path: Path):
    pytest.importorskip("openpyxl")
    src = tmp_copy("sample.xlsx")
    by_index = tmp_path / "by-index.csv"
    res = run("convert", str(src), "--to", "csv", "--sheet", "2", "-o", str(by_index))
    assert res.exit_code == 0, all_output(res)
    lines = by_index.read_text().splitlines()
    assert lines[0] == "member,title,days_out" and len(lines) == 4
    by_name = tmp_path / "by-name.csv"
    convert_file(src, by_name, sheet="Loans")
    assert by_name.read_text() == by_index.read_text()
    res = run("convert", str(src), "--to", "csv", "--sheet", "9", "-o", str(tmp_path / "x.csv"))
    assert res.exit_code == 4
    assert "no sheet '9'" in all_output(res) and "Books, Loans" in all_output(res)


def test_xlsx_to_csv_all_sheets(tmp_copy, tmp_path: Path):
    pytest.importorskip("openpyxl")
    src = tmp_copy("sample.xlsx")
    out = tmp_path / "sheets"
    res = run("convert", str(src), "--to", "csv", "--sheet", "all", "--out-dir", str(out), "--json")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.output)[0]
    names = sorted(Path(p).name for p in rec["dests"])
    assert names == ["sample-Books.csv", "sample-Loans.csv"]
    assert rec["dest"] == rec["dests"][0]
    assert (out / "sample-Loans.csv").read_text().splitlines()[0] == "member,title,days_out"
    assert not (out / "sample.csv").exists()
    # overwrite protection applies per sheet file
    res = run("convert", str(src), "--to", "csv", "--sheet", "all", "--out-dir", str(out))
    assert res.exit_code == 1 and "refusing to overwrite" in all_output(res)
    res = run(
        "convert", str(src), "--to", "csv", "--sheet", "all", "--out-dir", str(out), "--force"
    )
    assert res.exit_code == 0, all_output(res)


def test_xlsx_to_json(tmp_copy, tmp_path: Path):
    pytest.importorskip("openpyxl")
    src = tmp_copy("sample.xlsx")
    res = run("convert", str(src), "--to", "json")
    assert res.exit_code == 0, all_output(res)
    data = json.loads(src.with_suffix(".json").read_text())
    assert set(data) == {"Books", "Loans"}
    assert len(data["Books"]) == 3 and len(data["Loans"]) == 3
    assert data["Books"][0] == {"title": "Palimpsest Harbor", "shelf": "A2", "year": 1998}
    assert isinstance(data["Loans"][2]["days_out"], int)
    one = tmp_path / "one.json"
    convert_file(src, one, sheet="Loans")
    assert list(json.loads(one.read_text())) == ["Loans"]


def test_xlsx_json_blank_header_and_dates(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    from datetime import datetime

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["when", None, "ok"])
    ws.append([datetime(2021, 6, 15, 12, 0), 1.5, True])
    ws.append([None, None, None])  # blank rows are dropped
    src = tmp_path / "d.xlsx"
    wb.save(src)
    assert detect(src) is FileType.XLSX
    out = tmp_path / "d.json"
    convert_file(src, out)
    data = json.loads(out.read_text())
    assert data == {"Data": [{"when": "2021-06-15T12:00:00", "col2": 1.5, "ok": True}]}
    csv_out = tmp_path / "d.csv"
    convert_file(src, csv_out)
    assert csv_out.read_text().splitlines() == ["when,,ok", "2021-06-15T12:00:00,1.5,true"]


def test_convert_xlsx_without_openpyxl(tmp_copy, monkeypatch: pytest.MonkeyPatch):
    without_openpyxl(monkeypatch)
    src = tmp_copy("sample.xlsx")
    res = run("convert", str(src), "--to", "csv")
    assert res.exit_code == 3
    out = all_output(res)
    assert "openpyxl" in out and OFFICE_HINT in out
    assert not src.with_suffix(".csv").exists()


# ------------------------------------------------------- index / search / pack


@needs("pandoc")
def test_index_search_pack_documents(fixtures: Path, tmp_path: Path):
    desk = tmp_path / "desk"
    desk.mkdir()
    for name in ("sample.docx", "sample.epub"):
        (desk / name).write_bytes((fixtures / name).read_bytes())

    res = run("--root", str(desk), "index", "--json")
    assert res.exit_code == 0, all_output(res)
    summary = json.loads(res.output)
    assert summary["indexed"] == 2 and summary["errors"] == []

    res = run("--root", str(desk), "search", "melodious", "--json")
    assert res.exit_code == 0, all_output(res)
    hits = json.loads(res.output)
    assert sorted(Path(h["path"]).name for h in hits) == ["sample.docx", "sample.epub"]

    res = run("--root", str(desk), "search", "melodious", "--type", "epub", "--json")
    assert [Path(h["path"]).name for h in json.loads(res.output)] == ["sample.epub"]

    res = run("pack", str(desk), "--json")
    assert res.exit_code == 0, all_output(res)
    assert res.output.count(MD_SENTINEL) >= 2  # both documents inlined as text
    packed = json.loads(res.output)
    files = json.dumps(packed)
    assert "sample.docx" in files and "sample.epub" in files


def test_index_xlsx(fixtures: Path, tmp_path: Path):
    pytest.importorskip("openpyxl")
    desk = tmp_path / "desk"
    desk.mkdir()
    (desk / "sample.xlsx").write_bytes((fixtures / "sample.xlsx").read_bytes())
    res = run("--root", str(desk), "index", "--json")
    assert res.exit_code == 0, all_output(res)
    res = run("--root", str(desk), "search", "vellum", "--json")
    assert [Path(h["path"]).name for h in json.loads(res.output)] == ["sample.xlsx"]


def test_index_documents_without_pandoc_records_error(
    fixtures: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    without_tool(monkeypatch, "pandoc")
    desk = tmp_path / "desk"
    desk.mkdir()
    (desk / "sample.docx").write_bytes((fixtures / "sample.docx").read_bytes())
    (desk / "sample.txt").write_bytes((fixtures / "sample.txt").read_bytes())
    res = run("--root", str(desk), "index", "--json")
    # the walk continues past the docx; the missing tool is recorded, not raised
    assert res.exit_code == 0, all_output(res)
    summary = json.loads(res.output)
    assert summary["indexed"] == 1
    assert summary["errors"][0]["path"] == "sample.docx"
    assert summary["errors"][0]["kind"] == "missing_dependency"
    assert "pandoc" in summary["errors"][0]["error"]
    # when *nothing* could be indexed and every failure was a missing tool, index exits 3
    (desk / "sample.txt").unlink()
    res = run("--root", str(desk), "index", "--json", "--prune")
    assert res.exit_code == 3 and "pandoc" in all_output(res)


# -------------------------------------------------------------------- inspect


def test_inspect_docx(fixtures: Path):
    res = run("inspect", str(fixtures / "sample.docx"), "--json")
    assert res.exit_code == 0, all_output(res)
    info = json.loads(res.output)
    assert info["type"] == "docx"
    detail = info["detail"]
    assert set(detail) == {"paragraphs", "words", "title", "author", "created"}
    assert detail["paragraphs"] > 5
    assert detail["title"] == "Carrel Sample Document"
    assert detail["author"] == "Fixture Generator"
    assert detail["created"].startswith("2021-06-15")
    if adapters.have("pandoc"):
        assert detail["words"] > 50
    else:
        assert detail["words"] is None


def test_inspect_epub(fixtures: Path):
    detail = inspect_file(fixtures / "sample.epub")["detail"]
    assert detail["title"] == "Carrel Sample Document"
    assert detail["creator"] == "Fixture Generator"
    assert detail["language"] == "en"
    assert detail["spine_items"] == 3  # title page + two chapters
    assert "error" not in detail


@pytest.mark.parametrize("name", ["sample.odt", "sample.rtf"])
def test_inspect_odt_rtf(fixtures: Path, name: str):
    info = inspect_file(fixtures / name)
    assert info["size"] > 0
    assert set(info["detail"]) == {"words"}
    if adapters.have("pandoc"):
        assert info["detail"]["words"] > 50


def test_inspect_documents_without_pandoc_never_exit_3(
    fixtures: Path, monkeypatch: pytest.MonkeyPatch
):
    without_tool(monkeypatch, "pandoc")
    res = run("inspect", str(fixtures / "sample.docx"), "--json")
    assert res.exit_code == 0, all_output(res)
    detail = json.loads(res.output)["detail"]
    assert detail["words"] is None and detail["title"] == "Carrel Sample Document"


def test_inspect_xlsx(fixtures: Path):
    pytest.importorskip("openpyxl")
    res = run("inspect", str(fixtures / "sample.xlsx"), "--json")
    assert res.exit_code == 0, all_output(res)
    info = json.loads(res.output)
    assert info["type"] == "xlsx"
    assert info["detail"] == {
        "sheets": [
            {"name": "Books", "rows": 4, "cols": 3},
            {"name": "Loans", "rows": 4, "cols": 3},
        ]
    }
    human = run("inspect", str(fixtures / "sample.xlsx"))
    assert human.exit_code == 0 and "Books" in human.output


def test_inspect_xlsx_without_openpyxl(fixtures: Path, monkeypatch: pytest.MonkeyPatch):
    without_openpyxl(monkeypatch)
    res = run("inspect", str(fixtures / "sample.xlsx"), "--json")
    assert res.exit_code == 0, all_output(res)  # inspect degrades instead of exiting 3
    detail = json.loads(res.output)["detail"]
    assert detail["sheets"] is None and OFFICE_HINT in detail["error"]


def test_inspect_broken_epub_degrades(tmp_path: Path):
    p = tmp_path / "broken.epub"
    p.write_bytes(_zip_bytes({"mimetype": b"application/epub+zip", "junk.txt": b"x"}))
    assert detect(p) is FileType.EPUB
    detail = inspect_file(p)["detail"]
    assert detail["error"] == "no readable OPF package document"
    assert detail["spine_items"] is None
