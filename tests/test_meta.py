"""Tests for spec 24: schema v2 `meta` table, DeskDB meta API, `carrel meta`, `search --meta`,
and the catalog carrying fields. Every CLI call passes --root at a tmp desk."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from carrel.cli import cli
from carrel.core import db as dbmod
from carrel.core.db import (
    SCHEMA_VERSION,
    DeskDB,
    coerce_meta,
    normalize_meta_key,
    parse_meta_condition,
)
from carrel.core.output import CarrelInputError


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0):
    return json.loads(run("--json", *args, expect=expect).output)


@pytest.fixture
def desk(tmp_path: Path) -> Path:
    (tmp_path / "inv.txt").write_text("Invoice INV-1 from Acme\n", encoding="utf-8")
    (tmp_path / "receipt.md").write_text("# Receipt\n\nCoffee at Beanery\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def filled(desk: Path) -> Path:
    r = str(desk)
    run(
        "--root",
        r,
        "meta",
        "set",
        str(desk / "inv.txt"),
        "Vendor=Acme Corp",
        "total=1,234.50",
        "due=2026-10-01",
    )
    run(
        "--root",
        r,
        "meta",
        "set",
        str(desk / "receipt.md"),
        "vendor=Beanery",
        "total=4.75",
        "paid=true",
    )
    return desk


# ------------------------------------------------------------- helpers/kinds


def test_coerce_meta_inference():
    assert coerce_meta(" true ", None) == ("bool", "true")
    assert coerce_meta("1,234.50", None) == ("num", "1234.5")
    assert coerce_meta("-0", None) == ("num", "0")
    assert coerce_meta("100", None) == ("num", "100")
    assert coerce_meta("2026-10-01", None) == ("date", "2026-10-01")
    assert coerce_meta("2026-13-01", None) == ("str", "2026-13-01")  # not a real date
    assert coerce_meta("1e5", None) == ("str", "1e5")
    assert coerce_meta("Acme", None) == ("str", "Acme")


def test_coerce_meta_explicit_kinds_are_strict():
    assert coerce_meta("yes", "bool") == ("bool", "true")
    assert coerce_meta("0", "bool") == ("bool", "false")
    assert coerce_meta("99", "str") == ("str", "99")
    assert coerce_meta("2026-01-05", "date") == ("date", "2026-01-05")
    for value, kind in (("maybe", "bool"), ("abc", "num"), ("2026-1-5", "date"), ("1", "colour")):
        with pytest.raises(CarrelInputError):
            coerce_meta(value, kind)


def test_normalize_meta_key():
    assert normalize_meta_key(" Vendor.Name-2 ") == "vendor.name-2"
    for bad in ("", "has space", "-lead", "x" * 65, "é"):
        with pytest.raises(CarrelInputError, match="invalid meta key"):
            normalize_meta_key(bad)


def test_parse_meta_condition():
    assert parse_meta_condition("Total >= 10") == ("total", ">=", "10")
    assert parse_meta_condition("vendor~cme") == ("vendor", "~", "cme")
    assert parse_meta_condition("paid?") == ("paid", "?", "")
    for bad in ("nonsense", "total>", "paid?yes", "=1"):
        with pytest.raises(CarrelInputError, match=r"bad condition|invalid meta key"):
            parse_meta_condition(bad)


# ----------------------------------------------------------------- DeskDB


def test_v1_desk_migrates_to_v2_with_data_intact(desk: Path):
    (desk / ".carrel").mkdir()
    raw = sqlite3.connect(desk / ".carrel" / "carrel.db")
    raw.executescript(dbmod._SCHEMA)
    raw.execute(
        "INSERT INTO files (id, path, size, mtime, type, indexed_at) VALUES (1,'inv.txt',5,1.0,'txt',2.0)"
    )
    raw.execute("INSERT INTO tags (file_id, tag) VALUES (1,'legacy')")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()
    with DeskDB(desk) as db:
        assert db.schema_version() == SCHEMA_VERSION == 2
        assert db.tags_of(desk / "inv.txt") == ["legacy"]
        assert db.meta_of(desk / "inv.txt") == []
        db.set_meta(desk / "inv.txt", "vendor", "Acme")
    raw = sqlite3.connect(desk / ".carrel" / "carrel.db")
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 2
    assert raw.execute("SELECT key, value, kind, source FROM meta").fetchall() == [
        ("vendor", "Acme", "str", "user")
    ]
    raw.close()


def test_set_get_rm_and_keys(desk: Path):
    with DeskDB(desk) as db:
        inv = desk / "inv.txt"
        assert db.set_meta(inv, "Total", "1,000", source="fields") == {
            "key": "total",
            "value": "1000",
            "kind": "num",
            "source": "fields",
        }
        db.set_meta(inv, "total", "2000")  # overwrite keeps one row, newest wins
        assert db.get_meta(inv, "TOTAL")["value"] == "2000"
        assert db.get_meta(inv, "nope") is None
        assert db.get_meta(desk / "receipt.md", "total") is None  # unknown file
        db.set_meta(inv, "due", "2026-10-01")
        assert [r["key"] for r in db.meta_of(inv)] == ["due", "total"]
        assert db.meta_keys() == {"due": 1, "total": 1}
        assert db.counts()["meta"] == 2
        assert db.rm_meta(inv, ["due", "ghost"]) == 1
        assert db.rm_meta(desk / "receipt.md", ["total"]) == 0
        assert db.meta_keys() == {"total": 1}
        with pytest.raises(CarrelInputError):
            db.set_meta(inv, "bad key", "x")


def test_find_by_meta_operators(desk: Path):
    with DeskDB(desk) as db:
        inv, rec = desk / "inv.txt", desk / "receipt.md"
        db.set_meta(inv, "vendor", "Acme Corp")
        db.set_meta(inv, "total", "1234.5")
        db.set_meta(inv, "due", "2026-10-01")
        db.set_meta(rec, "vendor", "Beanery")
        db.set_meta(rec, "total", "4.75")
        db.set_meta(rec, "paid", "true")
        f = db.find_by_meta
        assert f(["total>1000"]) == ["inv.txt"]
        assert f(["total<=4.75"]) == ["receipt.md"]
        assert f(["total>=4.75"]) == ["inv.txt", "receipt.md"]
        assert f(["total=1,234.50"]) == ["inv.txt"]  # numeric equality, separators ignored
        assert f(["total!=4.75"]) == ["inv.txt"]
        assert f(["vendor=acme corp"]) == ["inv.txt"]  # case-insensitive text
        assert f(["vendor!=acme corp"]) == ["receipt.md"]
        assert f(["vendor~ean"]) == ["receipt.md"]
        assert f(["vendor~%"]) == []  # LIKE metacharacters are literal
        assert f(["paid?"]) == ["receipt.md"]
        assert f(["paid=true"]) == ["receipt.md"]
        assert f(["due<2026-11-01"]) == ["inv.txt"]
        assert f(["due>2026-11-01"]) == []
        assert f(["vendor~e", "total>100"]) == ["inv.txt"]  # AND
        with pytest.raises(CarrelInputError):
            f([])
        with pytest.raises(CarrelInputError):
            f(["nonsense"])


def test_meta_table(desk: Path):
    with DeskDB(desk) as db:
        db.set_meta(desk / "inv.txt", "vendor", "Acme")
        db.set_meta(desk / "receipt.md", "total", "4.75")
        assert db.meta_table() == (
            ["path", "total", "vendor"],
            [
                {"path": "inv.txt", "total": "", "vendor": "Acme"},
                {"path": "receipt.md", "total": "4.75", "vendor": ""},
            ],
        )
        assert db.meta_table(["vendor"]) == (
            ["path", "vendor"],
            [{"path": "inv.txt", "vendor": "Acme"}, {"path": "receipt.md", "vendor": ""}],
        )


def test_catalog_export_import_round_trip_with_meta(desk: Path):
    with DeskDB(desk) as db:
        db.set_meta(desk / "inv.txt", "vendor", "Acme", source="fields")
        db.set_meta(desk / "inv.txt", "total", "12")
        doc = db.export_catalog()
    assert doc["schema"] == 2
    assert doc["files"] == [
        {
            "path": "inv.txt",
            "tags": [],
            "notes": [],
            "meta": [
                {"key": "total", "value": "12", "kind": "num", "source": "user"},
                {"key": "vendor", "value": "Acme", "kind": "str", "source": "fields"},
            ],
        }
    ]
    with DeskDB(desk) as db:
        again = db.import_catalog(doc)
        assert again["meta_set"] == 0 and again["files_touched"] == 0  # idempotent
        doc["files"][0]["meta"][0]["value"] = "13"
        changed = db.import_catalog(doc)
        assert changed["meta_set"] == 1 and changed["files_touched"] == 1
        assert db.get_meta(desk / "inv.txt", "total")["value"] == "13"
        replaced = db.import_catalog({"schema": 1, "files": []}, replace=True)
        assert replaced["meta_removed"] == 2 and db.meta_keys() == {}


def test_import_validates_meta_shape(desk: Path):
    with DeskDB(desk) as db:
        for meta in (
            "x",
            [{"value": "1"}],
            [{"key": "k", "value": 1}],
            [{"key": "k", "value": "1", "kind": "money"}],
            [{"key": "bad key", "value": "1"}],
        ):
            with pytest.raises(CarrelInputError, match="invalid catalog"):
                db.import_catalog({"schema": 2, "files": [{"path": "inv.txt", "meta": meta}]})
        # schema-1 documents (no meta key) still import
        assert (
            db.import_catalog({"schema": 1, "files": [{"path": "inv.txt", "tags": ["a"]}]})[
                "tags_added"
            ]
            == 1
        )


# -------------------------------------------------------------------- CLI


def test_meta_set_json_and_human(desk: Path):
    r = str(desk)
    data = run_json(
        "--root", r, "meta", "set", str(desk / "inv.txt"), "Vendor=Acme Corp", "total=1,234.50"
    )
    assert data == {
        "path": "inv.txt",
        "set": ["vendor", "total"],
        "meta": {"total": "1234.5", "vendor": "Acme Corp"},
    }
    human = run("--root", r, "meta", "set", str(desk / "inv.txt"), "due=2026-10-01").output
    assert human.strip() == "inv.txt: due=2026-10-01, total=1234.5, vendor=Acme Corp"
    forced = run_json(
        "--root",
        r,
        "meta",
        "set",
        str(desk / "inv.txt"),
        "zip=01234",
        "--kind",
        "str",
        "--source",
        "clerk",
    )
    assert forced["meta"]["zip"] == "01234"
    assert run_json("--root", r, "meta", "get", str(desk / "inv.txt"), "zip")["source"] == "clerk"


def test_meta_set_errors(desk: Path):
    r = str(desk)
    assert (
        "KEY=VALUE"
        in run("--root", r, "meta", "set", str(desk / "inv.txt"), "novalue", expect=2).stderr
    )
    assert (
        "invalid meta key"
        in run("--root", r, "meta", "set", str(desk / "inv.txt"), "bad key=1", expect=2).stderr
    )
    assert (
        "no such file"
        in run("--root", r, "meta", "set", str(desk / "ghost.txt"), "a=1", expect=4).stderr
    )
    assert (
        "not a number"
        in run(
            "--root", r, "meta", "set", str(desk / "inv.txt"), "n=abc", "--kind", "num", expect=4
        ).stderr
    )


def test_meta_get(filled: Path):
    r = str(filled)
    assert (
        run("--root", r, "meta", "get", str(filled / "inv.txt"), "vendor").output == "Acme Corp\n"
    )
    data = run_json("--root", r, "meta", "get", str(filled / "inv.txt"), "due")
    assert data == {
        "path": "inv.txt",
        "key": "due",
        "value": "2026-10-01",
        "kind": "date",
        "source": "user",
    }
    missing = run("--root", r, "meta", "get", str(filled / "inv.txt"), "ghost")
    assert missing.output == ""
    assert run_json("--root", r, "meta", "get", str(filled / "inv.txt"), "ghost")["value"] is None
    run("--root", r, "meta", "get", str(filled / "inv.txt"), "ghost", "--fail-empty", expect=5)


def test_meta_ls(filled: Path):
    r = str(filled)
    keys = run_json("--root", r, "meta", "ls")
    assert keys == {"keys": {"due": 1, "paid": 1, "total": 2, "vendor": 2}}
    assert "total   2 file(s)" in run("--root", r, "meta", "ls").output
    data = run_json("--root", r, "meta", "ls", str(filled / "receipt.md"))
    assert data["path"] == "receipt.md"
    assert [(f["key"], f["value"], f["kind"], f["source"]) for f in data["meta"]] == [
        ("paid", "true", "bool", "user"),
        ("total", "4.75", "num", "user"),
        ("vendor", "Beanery", "str", "user"),
    ]
    assert all("T" in f["updated"] for f in data["meta"])  # ISO timestamps
    human = run("--root", r, "meta", "ls", str(filled / "receipt.md")).output
    assert "paid" in human and "(bool, user," in human
    assert "(no fields)" in run("--root", r, "meta", "ls", str(filled / "nope.txt")).output


def test_meta_rm(filled: Path):
    r = str(filled)
    data = run_json("--root", r, "meta", "rm", str(filled / "inv.txt"), "due", "ghost")
    assert data == {
        "path": "inv.txt",
        "removed": 1,
        "meta": {"total": "1234.5", "vendor": "Acme Corp"},
    }
    assert run_json("--root", r, "meta", "ls")["keys"] == {"paid": 1, "total": 2, "vendor": 2}


def test_meta_find(filled: Path):
    r = str(filled)
    rows = run_json("--root", r, "meta", "find", "total>100", "vendor~acme")
    assert rows == [
        {"path": "inv.txt", "meta": {"due": "2026-10-01", "total": "1234.5", "vendor": "Acme Corp"}}
    ]
    assert [x["path"] for x in run_json("--root", r, "meta", "find", "vendor?")] == [
        "inv.txt",
        "receipt.md",
    ]
    human = run("--root", r, "meta", "find", "paid=true").output
    assert human.strip() == "receipt.md  paid=true total=4.75 vendor=Beanery"
    assert "no files" in run("--root", r, "meta", "find", "total>999999").stderr
    assert "bad condition" in run("--root", r, "meta", "find", "nonsense", expect=2).stderr


def test_meta_readonly_ops_do_not_create_db(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    r = str(tmp_path)
    assert run_json("--root", r, "meta", "ls") == {"keys": {}}
    assert run_json("--root", r, "meta", "ls", str(tmp_path / "f.txt"))["meta"] == []
    assert run_json("--root", r, "meta", "get", str(tmp_path / "f.txt"), "k")["value"] is None
    assert run_json("--root", r, "meta", "rm", str(tmp_path / "f.txt"), "k")["removed"] == 0
    assert run_json("--root", r, "meta", "find", "k?") == []
    run("--root", r, "meta", "find", "bad", expect=2)  # syntax is still checked
    assert "no desk db" in run("--root", r, "meta", "export", expect=4).stderr
    assert not (tmp_path / ".carrel").exists()


def test_meta_export_stdout_csv_and_json(filled: Path):
    r = str(filled)
    out = run("--root", r, "meta", "export").output
    rows = list(csv.DictReader(io.StringIO(out)))
    assert list(rows[0]) == ["path", "due", "paid", "total", "vendor"]
    assert rows[0] == {
        "path": "inv.txt",
        "due": "2026-10-01",
        "paid": "",
        "total": "1234.5",
        "vendor": "Acme Corp",
    }
    assert rows[1]["vendor"] == "Beanery" and rows[1]["paid"] == "true"
    as_json = run_json("--root", r, "meta", "export", "--key", "vendor", "--key", "total")
    assert as_json == [
        {"path": "inv.txt", "vendor": "Acme Corp", "total": "1234.5"},
        {"path": "receipt.md", "vendor": "Beanery", "total": "4.75"},
    ]


def test_meta_export_to_file(filled: Path, tmp_path: Path):
    r = str(filled)
    out = tmp_path / "exports" / "desk.csv"
    summary = run_json("--root", r, "meta", "export", "-o", str(out))
    assert summary == {
        "out": str(out),
        "format": "csv",
        "files": 2,
        "keys": ["due", "paid", "total", "vendor"],
    }
    assert out.read_text(encoding="utf-8").startswith("path,due,paid,total,vendor\n")
    assert "--force" in run("--root", r, "meta", "export", "-o", str(out), expect=1).stderr
    human = run("--root", r, "meta", "export", "-o", str(out), "--force").output
    assert "wrote" in human and "2 file(s), 4 key(s) [csv]" in human
    js = tmp_path / "desk.json"
    run("--root", r, "meta", "export", "-o", str(js))
    assert json.loads(js.read_text(encoding="utf-8"))[1]["path"] == "receipt.md"


# ---------------------------------------------------------- search / catalog


def test_search_meta_filter(filled: Path):
    r = str(filled)
    run_json("--root", r, "index")
    assert len(run_json("--root", r, "search", "acme OR beanery")) == 2
    hits = run_json("--root", r, "search", "acme OR beanery", "--meta", "total>100")
    assert [h["path"] for h in hits] == ["inv.txt"]
    hits = run_json(
        "--root", r, "search", "acme OR beanery", "--meta", "paid?", "--meta", "vendor~bean"
    )
    assert [h["path"] for h in hits] == ["receipt.md"]
    assert run_json("--root", r, "search", "acme", "--meta", "paid=true") == []
    assert "bad condition" in run("--root", r, "search", "acme", "--meta", "???", expect=2).stderr


def test_catalog_carries_meta(filled: Path, tmp_path: Path):
    r = str(filled)
    doc = run_json("--root", r, "catalog", "export")
    assert doc["schema"] == 2
    assert doc["files"][0]["meta"][0] == {
        "key": "due",
        "value": "2026-10-01",
        "kind": "date",
        "source": "user",
    }
    out = tmp_path / "cat.json"
    summary = run_json("--root", r, "catalog", "export", "-o", str(out))
    assert summary["meta"] == 6 and summary["files"] == 2
    run("--root", r, "meta", "rm", str(filled / "inv.txt"), "due", "total", "vendor")
    result = run_json("--root", r, "catalog", "import", str(out))
    assert result["meta_set"] == 3 and result["files_touched"] == 1
    assert run_json("--root", r, "meta", "ls", str(filled / "inv.txt"))["meta"][0]["key"] == "due"
    human = run("--root", r, "catalog", "import", str(out), "--replace").output
    assert "6 field(s)" in human and "imported 0 tag(s), 0 note(s), 6 field(s)" in human
    status = run_json("--root", r, "catalog", "status")
    assert status["counts"]["meta"] == 6
    assert "meta" in run("--root", r, "catalog", "status").output


@pytest.mark.parametrize("sub", [[], ["set"], ["get"], ["ls"], ["rm"], ["find"], ["export"]])
def test_help_and_json_flag(sub: list[str]):
    result = run("meta", *sub, "--help")
    assert "Usage:" in result.output and "--json" in result.output
