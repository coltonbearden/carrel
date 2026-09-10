"""Tests for spec 27's intake half: the inbox pipeline (fields → refs → name → file → desk).

Every invocation targets tmp_path directories, so no .carrel is created in the repo.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.commands.intake import (
    ORIGINALS_DIR,
    destination_dir,
    fiscal_quarter,
    inbox_files,
    looks_scanned,
    process_file,
)
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
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
def inbox(tmp_path: Path, fixtures: Path) -> Path:
    """An inbox with an invoice, an email, and a note that carries no reference."""
    box = tmp_path / "in"
    box.mkdir()
    (box / "whatever.txt").write_bytes((fixtures / "invoice.txt").read_bytes())
    (box / "mail.eml").write_bytes((fixtures / "sample.eml").read_bytes())
    (box / "note.md").write_text("# a note\n\nnothing to reference here\n", encoding="utf-8")
    return box


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / "filed"


# ------------------------------------------------------------------ layout


def test_fiscal_quarter_and_destination(tmp_path: Path):
    assert fiscal_quarter(date(2026, 9, 10), 1) == (2026, 3)
    assert fiscal_quarter(date(2026, 1, 1), 1) == (2026, 1)
    assert fiscal_quarter(date(2026, 12, 31), 1) == (2026, 4)
    # a July fiscal year: August 2026 is FY2027 Q1, June 2026 is FY2026 Q4
    assert fiscal_quarter(date(2026, 8, 3), 7) == (2027, 1)
    assert fiscal_quarter(date(2026, 6, 30), 7) == (2026, 4)
    assert fiscal_quarter(date(2026, 10, 1), 10) == (2027, 1)
    with pytest.raises(CarrelInputError, match="fiscal-start"):
        fiscal_quarter(date(2026, 1, 1), 13)
    when = date(2026, 9, 10)
    assert destination_dir(tmp_path, when, "ym", 1) == tmp_path / "2026" / "09"
    assert destination_dir(tmp_path, when, "period", 7) == tmp_path / "FY2027" / "Q1"
    assert destination_dir(tmp_path, when, "flat", 1) == tmp_path


def test_inbox_files_skips_hidden_and_originals(tmp_path: Path):
    box = tmp_path / "in"
    (box / ORIGINALS_DIR).mkdir(parents=True)
    (box / "sub").mkdir()
    (box / "a.txt").write_text("a", encoding="utf-8")
    (box / ".hidden.txt").write_text("h", encoding="utf-8")
    (box / ORIGINALS_DIR / "old.pdf").write_text("o", encoding="utf-8")
    (box / "sub" / "deep.txt").write_text("d", encoding="utf-8")
    assert [p.name for p in inbox_files(box, None, False)] == ["a.txt"]
    assert [p.name for p in inbox_files(box, None, True)] == ["a.txt", "deep.txt"]
    assert [p.name for p in inbox_files(box, "*.md", True)] == []


# ------------------------------------------------------------------ dry run


def test_dry_run_plans_and_touches_nothing(inbox: Path, dest: Path):
    records = run_json("intake", str(inbox), "--to", str(dest))
    by_name = {Path(r["src"]).name: r for r in records}
    assert set(by_name) == {"whatever.txt", "mail.eml", "note.md"}
    inv = by_name["whatever.txt"]
    assert inv["action"] == "plan"
    assert Path(inv["dest"]) == dest / "2026" / "09" / "2026-09-10_ACME_Corp_INV-2026-0042.txt"
    assert inv["fields"]["total"] == "1234.56" and inv["fields"]["invoice_no"] == "INV-2026-0042"
    assert {"invoice", "po", "iban"} <= {r["kind"] for r in inv["refs"]}
    assert by_name["note.md"]["action"] == "skip" and "{ref}" in by_name["note.md"]["reason"]
    assert Path(by_name["mail.eml"]["dest"]).parent == dest / "2021" / "06"
    assert not dest.exists()  # dry-run creates nothing at all
    assert sorted(p.name for p in inbox.iterdir()) == ["mail.eml", "note.md", "whatever.txt"]
    human = run("intake", str(inbox), "--to", str(dest)).output
    assert "dry-run: 2 file(s) would be filed" in human and "plan " in human


def test_layout_and_fallback_options(inbox: Path, dest: Path):
    records = run_json(
        "intake",
        str(inbox),
        "--to",
        str(dest),
        "--by",
        "period",
        "--fiscal-start",
        "7",
        "--fallback",
        "misc",
    )
    dests = {
        Path(r["src"]).name: Path(r["dest"]).parent.relative_to(dest).as_posix() for r in records
    }
    assert dests == {"whatever.txt": "FY2027/Q1", "mail.eml": "FY2021/Q4", "note.md": "FY2027/Q1"}
    flat = run_json("intake", str(inbox), "--to", str(dest), "--by", "flat", "--fallback", "misc")
    assert all(Path(r["dest"]).parent == dest for r in flat)
    named = run_json(
        "intake", str(inbox), "--to", str(dest), "--template", "{yyyy}-{mm}_{stem}{ext}"
    )
    assert Path(next(r for r in named if r["src"].endswith("note.md"))["dest"]).name.endswith(
        "_note.md"
    )


# -------------------------------------------------------------------- apply


def test_apply_files_indexes_saves_fields_and_tags(inbox: Path, dest: Path):
    records = run_json("intake", str(inbox), "--to", str(dest), "--apply", "--tag", "inbox2026")
    filed = {Path(r["src"]).name: r for r in records if r["action"] == "filed"}
    assert set(filed) == {"whatever.txt", "mail.eml"}
    inv = filed["whatever.txt"]
    assert Path(inv["dest"]).is_file() and not (inbox / "whatever.txt").exists()
    assert inv["indexed"] == 1
    assert "total" in inv["saved"] and "vendor" in inv["saved"]
    assert "ref:invoice:inv-2026-0042" in inv["tags"] and "inbox2026" in inv["tags"]
    assert (inbox / "note.md").exists()  # skipped files stay put

    root = str(dest)
    rel = Path(inv["dest"]).relative_to(dest).as_posix()
    # the email carries the same invoice number, so both filed documents are linked by it
    tagged = run_json("--root", root, "tag", "find", "ref:invoice:inv-2026-0042")
    assert rel in tagged and len(tagged) == 2
    assert rel in [x["path"] for x in run_json("--root", root, "meta", "find", "total>1000")]
    fields = {m["key"]: m for m in run_json("--root", root, "meta", "ls", inv["dest"])["meta"]}
    assert fields["total"]["kind"] == "num" and fields["total"]["source"] == "intake"
    assert fields["due"]["kind"] == "date"
    hits = run_json(
        "--root", root, "search", '"INV-2026-0042"'
    )  # FTS5 phrase: the dashes are literal
    assert rel in [h["path"] for h in hits]
    human = run("intake", str(inbox), "--to", str(dest), "--apply").output
    assert "0 file(s) filed." in human  # only note.md is left, and it is skipped


def test_apply_never_overwrites_and_keeps_low_confidence_out_of_the_desk(
    inbox: Path, dest: Path, fixtures: Path
):
    (inbox / "copy.txt").write_bytes((fixtures / "invoice.txt").read_bytes())
    records = run_json("intake", str(inbox), "--to", str(dest), "--apply")
    names = sorted(Path(r["dest"]).name for r in records if r["action"] == "filed")
    assert names == [
        "2021-06-15_Acme_Billing_INV-2026-0042.eml",
        "2026-09-10_ACME_Corp_INV-2026-0042-1.txt",
        "2026-09-10_ACME_Corp_INV-2026-0042.txt",
    ]
    plain = inbox / "plain.txt"
    plain.write_text("Total 5.00 for INV-77\n", encoding="utf-8")
    (rec,) = [
        r
        for r in run_json("intake", str(inbox), "--to", str(dest), "--apply")
        if r["action"] == "filed"
    ]
    # vendor here is the medium first-line heuristic; the low mtime/name fallbacks never land
    saved = set(rec["saved"])
    assert "total" in saved and "invoice_no" in saved
    assert rec["fields"]["date"] and "date" not in saved  # low-confidence mtime date is not a fact


def test_no_index_no_refs_and_no_tags(inbox: Path, dest: Path):
    records = run_json(
        "intake", str(inbox), "--to", str(dest), "--apply", "--no-index", "--no-refs"
    )
    inv = next(r for r in records if r["src"].endswith("whatever.txt"))
    assert inv["refs"] == [] and "tags" not in inv and "indexed" not in inv
    assert inv["saved"]  # fields still recorded
    assert run_json("--root", str(dest), "tag", "ls") == {"tags": {}}
    run("--root", str(dest), "search", '"INV-2026-0042"', "--fail-empty", expect=5)  # never indexed


def test_usage_and_input_errors(inbox: Path, dest: Path, tmp_path: Path):
    assert "must be different" in run("intake", str(inbox), "--to", str(inbox), expect=2).stderr
    run("intake", str(tmp_path / "ghost"), "--to", str(dest), expect=4)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_json("intake", str(empty), "--to", str(dest)) == []
    run("intake", str(empty), "--to", str(dest), "--fail-empty", expect=5)
    out = run("intake", "--help").output
    assert "--apply" in out and "--by" in out and "--fiscal-start" in out and "_originals" in out


def test_unsupported_files_are_skipped(inbox: Path, dest: Path):
    (inbox / "blob.bin").write_bytes(b"\x00\x01\x02not a supported type")
    records = run_json("intake", str(inbox), "--to", str(dest))
    blob = next(r for r in records if r["src"].endswith("blob.bin"))
    assert blob["action"] == "skip" and blob["reason"] == "unsupported file type"


def test_explicit_root_overrides_the_destination_desk(inbox: Path, dest: Path, tmp_path: Path):
    desk = tmp_path / "desk"
    desk.mkdir()
    run("--root", str(desk), "intake", str(inbox), "--to", str(dest), "--apply")
    assert (desk / ".carrel" / "carrel.db").is_file()
    assert not (dest / ".carrel").exists()
    assert run_json("--root", str(desk), "meta", "ls")["keys"]["total"] == 2  # invoice + email


# ---------------------------------------------------------------------- ocr


def test_looks_scanned(fixtures: Path, tmp_path: Path):
    assert looks_scanned(fixtures / "scanned.pdf", FileType.PDF) is True
    assert looks_scanned(fixtures / "invoice.txt", FileType.TXT) is False
    if detect(fixtures / "text+image.pdf") is FileType.PDF:
        from carrel.core import adapters

        if adapters.have("pdftotext"):
            assert looks_scanned(fixtures / "text+image.pdf", FileType.PDF) is False


def test_no_ocr_flag_files_the_scan_as_is(inbox: Path, dest: Path, fixtures: Path):
    (inbox / "scan.pdf").write_bytes((fixtures / "scanned.pdf").read_bytes())
    rec = next(
        r
        for r in run_json("intake", str(inbox), "--to", str(dest), "--no-ocr", "--fallback", "misc")
        if r["src"].endswith("scan.pdf")
    )
    assert rec["ocr"] == "not needed" and rec["action"] == "plan"


def test_ocr_requested_without_the_binary_exits_3(
    inbox: Path, dest: Path, fixtures: Path, monkeypatch
):
    (inbox / "scan.pdf").write_bytes((fixtures / "scanned.pdf").read_bytes())
    monkeypatch.setenv("CARREL_BIN_OCRMYPDF", str(dest / "nowhere"))
    result = run("intake", str(inbox), "--to", str(dest), "--ocr", "--fallback", "misc", expect=3)
    assert "ocrmypdf" in result.stderr
    assert not (dest / "2026").exists()  # exits before anything moved


def test_missing_ocrmypdf_files_the_scan_and_says_so(
    inbox: Path, dest: Path, fixtures: Path, monkeypatch
):
    (inbox / "scan.pdf").write_bytes((fixtures / "scanned.pdf").read_bytes())
    monkeypatch.setenv("CARREL_BIN_OCRMYPDF", str(dest / "nowhere"))
    rec = next(
        r
        for r in run_json("intake", str(inbox), "--to", str(dest), "--apply", "--fallback", "misc")
        if r["src"].endswith("scan.pdf")
    )
    assert rec["ocr"] == "unavailable" and rec["action"] == "filed"
    assert Path(rec["dest"]).is_file() and not (dest / ORIGINALS_DIR).exists()


@needs("ocrmypdf")
@needs("pdftotext")
def test_ocr_files_the_searchable_copy_and_keeps_the_original(
    inbox: Path, dest: Path, fixtures: Path
):
    scan = inbox / "scan.pdf"
    scan.write_bytes((fixtures / "scanned.pdf").read_bytes())
    original_bytes = scan.read_bytes()
    rec = next(
        r
        for r in run_json("intake", str(inbox), "--to", str(dest), "--apply", "--fallback", "misc")
        if r["src"].endswith("scan.pdf")
    )
    assert rec["ocr"] == "ocred" and rec["action"] == "filed"
    filed = Path(rec["dest"])
    kept = Path(rec["original"])
    assert filed.is_file() and kept.is_file() and kept.parent.name == ORIGINALS_DIR
    assert kept.read_bytes() == original_bytes  # D-014: the original is untouched
    assert filed.read_bytes() != original_bytes  # the filed copy carries a text layer
    from carrel.core.textextract import extract_text

    assert len(extract_text(filed).strip()) > len(extract_text(kept).strip())


# ------------------------------------------------------------------- watch


@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="thread + observer timing")
def test_watch_mode_files_arrivals(tmp_path: Path, fixtures: Path):
    box = tmp_path / "in"
    box.mkdir()
    dest = tmp_path / "filed"
    import threading

    def drop() -> None:
        import time

        time.sleep(0.8)
        (box / "late.txt").write_bytes((fixtures / "invoice.txt").read_bytes())

    t = threading.Thread(target=drop, daemon=True)
    t.start()
    records = run_json(
        "intake",
        str(box),
        "--to",
        str(dest),
        "--watch",
        "--once",
        "--timeout",
        "12",
        "--stable",
        "0.2",
    )
    t.join(timeout=5)
    filed = [r for r in records if r["action"] == "filed"]
    assert filed and Path(filed[0]["dest"]).name == "2026-09-10_ACME_Corp_INV-2026-0042.txt"
    assert Path(filed[0]["dest"]).is_file()


# --------------------------------------------------------------- library API


def test_process_file_library_seam(tmp_path: Path, fixtures: Path):
    src = tmp_path / "inv.txt"
    src.write_bytes((fixtures / "invoice.txt").read_bytes())
    dest_root = tmp_path / "out"
    record = process_file(src, dest_root, apply=False)
    assert record["action"] == "plan" and record["dest"].endswith(
        "2026-09-10_ACME_Corp_INV-2026-0042.txt"
    )
    assert src.exists()
    record = process_file(src, dest_root, apply=True, desk_root=dest_root)
    assert record["action"] == "filed" and Path(record["dest"]).is_file()
    with DeskDB(dest_root) as db:
        assert db.get_meta(Path(record["dest"]), "total")["value"] == "1234.56"
