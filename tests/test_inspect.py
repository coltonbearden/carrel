"""Tests for `carrel inspect` (spec 03)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.commands.inspect import inspect_file
from carrel.core.output import CarrelInputError


def run(*args: str):
    return CliRunner().invoke(cli, list(args))


def inspect_json(path: Path, *extra: str) -> dict:
    res = run("inspect", str(path), "--json", *extra)
    assert res.exit_code == 0, res.output
    return json.loads(res.output)


ALL_FIXTURES = [
    "sample.txt",
    "sample.md",
    "sample.html",
    "sample.json",
    "records.json",
    "sample.xml",
    "sample.csv",
    "sample.png",
    "sample.jpg",
    "sample-copy.jpg",
    "sample-resized.jpg",
    "sample.ico",
    "scanned.png",
    "text+image.pdf",
    "form.pdf",
    "scanned.pdf",
    "b.pdf",
]

COMMON_KEYS = {"path", "name", "size", "mtime", "type", "mime", "sha256", "detail"}


# ------------------------------------------------------------- common surface


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_every_fixture_returns_sane_json(fixtures: Path, name: str):
    obj = inspect_json(fixtures / name)
    assert set(obj) >= COMMON_KEYS
    assert obj["name"] == name
    assert obj["size"] > 0
    assert isinstance(obj["sha256"], str) and len(obj["sha256"]) == 64
    assert isinstance(obj["detail"], dict) and obj["detail"]
    assert "error" not in obj["detail"], obj["detail"]


def test_sha256_matches_hashlib(fixtures: Path):
    obj = inspect_json(fixtures / "sample.txt")
    expected = hashlib.sha256((fixtures / "sample.txt").read_bytes()).hexdigest()
    assert obj["sha256"] == expected


def test_type_detected(fixtures: Path):
    assert inspect_json(fixtures / "text+image.pdf")["type"] == "pdf"
    assert inspect_json(fixtures / "sample.jpg")["type"] == "jpg"
    assert inspect_json(fixtures / "sample.md")["type"] == "md"


# ------------------------------------------------------------------- per type


def test_pdf_detail(fixtures: Path):
    d = inspect_json(fixtures / "text+image.pdf")["detail"]
    assert d["pages"] == 2
    assert d["encrypted"] is False
    assert d["form_fields"] == 0
    assert {"title", "author", "producer", "annotations"} <= set(d)


def test_pdf_form_fields(fixtures: Path):
    d = inspect_json(fixtures / "form.pdf")["detail"]
    assert d["form_fields"] == 2  # name + agree
    assert d["annotations"] >= 2  # widget annotations
    assert d["pages"] == 1


def test_jpg_detail_with_exif(fixtures: Path):
    d = inspect_json(fixtures / "sample.jpg")["detail"]
    assert (d["width"], d["height"]) == (400, 300)
    assert d["mode"] == "RGB"
    assert d["format"] == "JPEG"
    assert d["exif"]["DateTimeOriginal"] == "2021:06:15 12:00:00"
    assert d["exif"]["Make"] == "deskfixture"


def test_png_detail(fixtures: Path):
    d = inspect_json(fixtures / "sample.png")["detail"]
    assert (d["width"], d["height"]) == (400, 300)
    assert d["exif"] is None


def test_ico_detail(fixtures: Path):
    d = inspect_json(fixtures / "sample.ico")["detail"]
    assert d["width"] > 0 and d["height"] > 0
    assert d["format"] == "ICO"


def test_json_detail_object(fixtures: Path):
    d = inspect_json(fixtures / "sample.json")["detail"]
    assert d == {"shape": "object", "keys": 3, "depth": 3}


def test_json_detail_array(fixtures: Path):
    d = inspect_json(fixtures / "records.json")["detail"]
    assert d == {"shape": "array", "keys": 8, "depth": 2}


def test_csv_detail(fixtures: Path):
    d = inspect_json(fixtures / "sample.csv")["detail"]
    assert d["delimiter"] == ","
    assert d["columns"] == ["id", "title", "shelf", "year", "checked_out"]
    assert d["column_count"] == 5
    assert d["rows"] == 20


def test_xml_detail(fixtures: Path):
    d = inspect_json(fixtures / "sample.xml")["detail"]
    assert d["root"] == "library"
    assert d["elements"] == 19  # library + 3 shelves + 5 books * (book,title,status)
    assert d["depth"] == 4


def test_html_detail(fixtures: Path):
    d = inspect_json(fixtures / "sample.html")["detail"]
    assert d["title"] == "Carrel Sample Page"
    assert d["headings"][0] == {"level": 1, "text": "Carrel Sample Page"}
    assert [h["level"] for h in d["headings"]] == [1, 2, 2, 2]
    assert d["images"] == 1
    assert d["links"] == 0


def test_md_detail(fixtures: Path):
    d = inspect_json(fixtures / "sample.md")["detail"]
    levels = [h["level"] for h in d["headings"]]
    assert levels == [1, 2, 3, 1, 2]
    assert d["headings"][0]["text"] == "Chapter One: The Reading Room"
    assert d["words"] > 50


def test_txt_detail(fixtures: Path):
    text = (fixtures / "sample.txt").read_text()
    d = inspect_json(fixtures / "sample.txt")["detail"]
    assert d["lines"] == len(text.splitlines())
    assert d["words"] == len(text.split())
    assert d["chars"] == len(text)


# ----------------------------------------------------------------------- deep


@needs("exiftool")
def test_deep_with_exiftool(fixtures: Path):
    obj = inspect_json(fixtures / "sample.jpg", "--deep")
    table = obj["exiftool"]
    assert isinstance(table, dict) and len(table) > 5
    assert str(table.get("DateTimeOriginal", "")).startswith("2021:06:15")
    assert "SourceFile" not in table


def test_deep_without_exiftool_never_exits_3(fixtures: Path, monkeypatch):
    from carrel.commands import inspect as mod

    monkeypatch.setattr(mod.adapters, "have", lambda name: False)
    res = run("inspect", str(fixtures / "sample.jpg"), "--json", "--deep")
    assert res.exit_code == 0, res.output
    obj = json.loads(res.output)
    assert obj["exiftool"] == "not installed"
    # builtin EXIF summary still present
    assert obj["detail"]["exif"]["Make"] == "deskfixture"


def test_no_deep_flag_no_exiftool_key(fixtures: Path):
    assert "exiftool" not in inspect_json(fixtures / "sample.jpg")


# ------------------------------------------------------------ errors & UX


def test_missing_file_exit_4(tmp_path: Path):
    res = run("inspect", str(tmp_path / "nope.txt"))
    assert res.exit_code == 4


def test_unsupported_type_exit_4(tmp_path: Path):
    weird = tmp_path / "blob.zzz"
    weird.write_bytes(b"\x00\x01\x02nonsense")
    res = run("inspect", str(weird))
    assert res.exit_code == 4


def test_help_and_human_output(fixtures: Path):
    res = run("inspect", "--help")
    assert res.exit_code == 0
    assert "--deep" in res.output and "--json" in res.output
    human = run("inspect", str(fixtures / "sample.txt"))
    assert human.exit_code == 0
    assert "sha256" in human.output and "detail:" in human.output


# ------------------------------------------------------------------- library


def test_inspect_file_library_api(fixtures: Path):
    info = inspect_file(fixtures / "sample.csv")
    assert set(info) >= COMMON_KEYS
    assert "exiftool" not in info
    with pytest.raises(CarrelInputError):
        inspect_file(fixtures / "does-not-exist.csv")
