"""Tests for `carrel refs` (spec 23): scanning, kinds, custom patterns, --tag, --link, exit codes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.commands.refs import link_refs, scan_refs, tag_for

INVOICE = """ACME Corp
Invoice # INV-2026-0042   Invoice Date: 2026-09-10
PO-4471   Order No. 88-771
Pay to IBAN DE89 3704 0044 0532 0130 00 routing 021000021 ref ABC-1234
Total $1,234.56  contact billing@acme.example
"""
REMIT = "# Remittance\n\nWe paid INV-2026-0042 and INV-2026-0043 today. Case ABC-1234.\n"


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
    (tmp_path / "inv.txt").write_text(INVOICE, encoding="utf-8")
    (tmp_path / "remit.md").write_text(REMIT, encoding="utf-8")
    (tmp_path / "empty.txt").write_text("nothing to see\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01INV-0000")  # unsupported: skipped on a walk
    hidden = tmp_path / ".secret"
    hidden.mkdir()
    (hidden / "h.txt").write_text("INV-9999\n", encoding="utf-8")
    return tmp_path


# ----------------------------------------------------------------- scanning


def test_scan_directory_json_shape(desk: Path):
    records = run_json("refs", str(desk))
    assert [Path(r["path"]).name for r in records] == ["empty.txt", "inv.txt", "remit.md"]
    by_name = {Path(r["path"]).name: r for r in records}
    assert by_name["empty.txt"]["refs"] == []
    inv = by_name["inv.txt"]["refs"]
    assert {(r["kind"], r["value"]) for r in inv} == {
        ("invoice", "INV-2026-0042"),
        ("po", "PO-4471"),
        ("order", "88-771"),
        ("ticket", "ABC-1234"),
        ("iban", "DE89370400440532013000"),
        ("routing", "021000021"),
    }
    row = next(r for r in inv if r["kind"] == "iban")
    assert row == {
        "kind": "iban",
        "value": "DE89370400440532013000",
        "count": 1,
        "valid": True,
        "pages": [1],
        "lines": [4],
    }
    assert "email" not in {r["kind"] for r in inv}  # pii only when named


def test_explicit_file_and_kind_filter(desk: Path):
    (rec,) = run_json("refs", str(desk / "inv.txt"), "--kind", "invoice,email")
    assert {(r["kind"], r["value"]) for r in rec["refs"]} == {
        ("invoice", "INV-2026-0042"),
        ("email", "billing@acme.example"),
    }


def test_custom_pattern(desk: Path):
    (rec,) = run_json(
        "refs", str(desk / "inv.txt"), "--kind", "ticket", "--pattern", r"acme=(?P<v1>ACME) Corp"
    )
    assert [(r["kind"], r["value"]) for r in rec["refs"]] == [
        ("ticket", "ABC-1234"),
        ("acme", "ACME"),
    ]


def test_bad_kind_and_bad_pattern_are_usage_errors(desk: Path):
    assert "unknown kind" in run("refs", str(desk), "--kind", "dna", expect=2).stderr
    assert "--pattern" in run("refs", str(desk), "--pattern", "nope", expect=2).stderr
    assert "--all" in run("refs", str(desk), "--all", expect=2).stderr


def test_missing_path_exits_4(tmp_path: Path):
    assert "no such path" in run("refs", str(tmp_path / "ghost"), expect=4).stderr


def test_fail_empty_exits_5(desk: Path):
    run("refs", str(desk / "empty.txt"), "--fail-empty", expect=5)
    run("refs", str(desk / "empty.txt"))  # without the flag: exit 0, no references


def test_human_output(desk: Path):
    out = run("refs", str(desk / "inv.txt")).output
    assert "invoice  INV-2026-0042  x1  line 2" in out
    assert "DE89370400440532013000" in out and "✓" in out
    assert "(no references)" in run("refs", str(desk / "empty.txt")).output


# --------------------------------------------------------------- link / tag


def test_link_groups_shared_values(desk: Path):
    groups = run_json("refs", str(desk), "--link")
    assert [(g["kind"], g["value"], len(g["files"])) for g in groups] == [
        ("invoice", "INV-2026-0042", 2),
        ("ticket", "ABC-1234", 2),
    ]
    assert [Path(p).name for p in groups[0]["files"]] == ["inv.txt", "remit.md"]
    assert groups[0]["count"] == 2
    everything = run_json("refs", str(desk), "--link", "--all")
    assert ("invoice", "INV-2026-0043") in {(g["kind"], g["value"]) for g in everything}
    human = run("refs", str(desk), "--link").output
    assert "invoice INV-2026-0042  (2 files, 2 occurrences)" in human


def test_tag_writes_ref_tags_into_desk(desk: Path):
    records = run_json("--root", str(desk), "refs", str(desk), "--tag")
    inv = next(r for r in records if Path(r["path"]).name == "inv.txt")
    assert "ref:invoice:inv-2026-0042" in inv["tags"]
    assert "ref:iban:de89370400440532013000" in inv["tags"]
    found = run_json("--root", str(desk), "tag", "find", "ref:invoice:inv-2026-0042")
    assert found == ["inv.txt", "remit.md"]
    empty = next(r for r in records if Path(r["path"]).name == "empty.txt")
    assert "tags" not in empty  # nothing to tag → no desk write for that file
    assert tag_for({"kind": "cc", "value": "4111 1111 1111 1111"}) == "ref:cc:4111111111111111"


def test_scan_without_tag_never_creates_desk(desk: Path):
    run_json("--root", str(desk), "refs", str(desk))
    assert not (desk / ".carrel").exists()


# ---------------------------------------------------------- library seams


def test_scan_refs_and_link_refs_library(desk: Path):
    records = scan_refs([desk / "inv.txt", desk / "remit.md"], kinds=["invoice"])
    assert [r["path"] for r in records] == [str(desk / "inv.txt"), str(desk / "remit.md")]
    groups = link_refs(records)
    assert [g["value"] for g in groups] == ["INV-2026-0042"]
    assert len(link_refs(records, all_=True)) == 2


def test_pdftotext_missing_exits_3(desk: Path, monkeypatch):
    from pypdf import PdfWriter

    pdf = desk / "only.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf.open("wb") as fh:
        writer.write(fh)
    monkeypatch.setenv("CARREL_BIN_PDFTOTEXT", str(desk / "nowhere"))
    result = run("refs", str(pdf), expect=3)
    assert "pdftotext" in result.stderr and "install" in result.stderr
    # a mixed scan keeps going and reports the failure per file
    records = run_json("refs", str(pdf), str(desk / "inv.txt"))
    assert records[0]["kind"] == "missing_dependency" and records[0]["refs"] == []
    assert records[1]["refs"]


@needs("pdftotext")
def test_pdf_pages_are_reported(tmp_path: Path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "two.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter, invariant=1)
    c.drawString(72, 700, "Cover page, nothing to see")
    c.showPage()
    c.drawString(72, 700, "Invoice # INV-77 and ticket QA-12")
    c.showPage()
    c.save()
    (rec,) = run_json("refs", str(pdf))
    by_kind = {r["kind"]: r for r in rec["refs"]}
    assert by_kind["invoice"]["value"] == "INV-77" and by_kind["invoice"]["pages"] == [2]
    assert by_kind["ticket"]["pages"] == [2]
    assert "p. 2" in run("refs", str(pdf)).output


def test_help_and_json_flag():
    out = run("refs", "--help").output
    assert "Usage:" in out and "--json" in out and "--link" in out and "--tag" in out
