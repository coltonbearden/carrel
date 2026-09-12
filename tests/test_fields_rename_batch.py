"""Tests for specs 25 and 26: core.money / core.dates, `carrel fields`, `carrel rename`, core.fsops,
`carrel batch` and core.actions. Every desk-backed call passes --root at a tmp path."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs, not_as_root

from carrel.cli import cli
from carrel.commands.batch import collect_files, load_manifest_done, run_batch
from carrel.commands.fields import extract_fields
from carrel.commands.rename import UnresolvedPlaceholderError, build_name, slugify
from carrel.core import actions, dates, money
from carrel.core.db import DeskDB
from carrel.core.fsops import move_file, uncollide
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


# ------------------------------------------------------------------- money


@pytest.mark.parametrize(
    ("text", "value", "currency"),
    [
        ("$1,234.56", "1234.56", "USD"),
        ("1.234,56 €", "1234.56", "EUR"),
        ("(123.45)", "-123.45", None),
        ("123.45-", "-123.45", None),
        ("EUR 12", "12", "EUR"),
        ("1 234,56", "1234.56", None),
        ("USD 1,000", "1000", "USD"),
        ("12.5 CR", "-12.5", None),
        ("1'234.50", "1234.50", None),
        ("-5.00", "-5.00", None),
        ("£0.99", "0.99", "GBP"),
    ],
)
def test_parse_amount(text, value, currency):
    amount = money.parse_amount(text)
    assert amount is not None and amount.value == Decimal(value) and amount.currency == currency


def test_parse_amount_rejects_non_amounts():
    for text in ("abc", "1.2.3.4", "12,34,56", "", "$"):
        assert money.parse_amount(text) is None
    assert money.parse_number("1,234") == Decimal("1234")
    assert money.parse_number("1.234") == Decimal("1234")  # one separator, three digits: grouping
    assert money.parse_number("1.23") == Decimal("1.23")


def test_find_amounts_skips_years_ids_and_quantities():
    text = (
        "Total $1,234.56 and 84.56 on 09/10/2026 page 12 of 40, ref 2026-0042, 1.000,00 EUR, qty 10"
    )
    found = money.find_amounts(text)
    assert [(str(a.value), a.currency) for a in found] == [
        ("1234.56", "USD"),
        ("84.56", None),
        ("1000.00", "EUR"),
    ]
    assert found[0].raw == "$1,234.56" and found[0].as_dict()["value"] == "1234.56"


# ------------------------------------------------------------------- dates


def test_find_dates_formats_and_ambiguity():
    text = "Invoice Date: 09/10/2026 Due 10 Oct 2026 also 2026-10-01 and 31/12/26, September 10, 2026; v1.2.3"
    found = dates.find_dates(text)
    assert [(f.value.isoformat(), f.ambiguous) for f in found] == [
        ("2026-09-10", True),
        ("2026-10-10", False),
        ("2026-10-01", False),
        ("2026-12-31", False),
        ("2026-09-10", False),
    ]
    assert dates.find_dates("09/10/2026", "dmy")[0].value == date(2026, 10, 9)
    assert dates.parse_date("10.09.2026", "dmy") == date(2026, 9, 10)
    assert dates.parse_date("2026-02-30") is None and dates.parse_date("soon") is None
    with pytest.raises(ValueError, match="order"):
        dates.find_dates("x", "ymd")


# ------------------------------------------------------------------ fields


def test_extract_fields_invoice_fixtures(fixtures: Path):
    for name in ("invoice.txt", "invoice.pdf"):
        if name.endswith(".pdf"):
            from carrel.core import adapters

            if not adapters.have("pdftotext"):
                continue
        rec = extract_fields(fixtures / name)
        f = rec["fields"]
        assert rec["profile"] == "invoice"
        assert f["vendor"]["value"] == "ACME Corp" and f["vendor"]["confidence"] == "medium"
        assert f["invoice_no"] == {
            "value": "INV-2026-0042",
            "confidence": "high",
            "evidence": "INV-2026-0042",
        }
        assert f["po"]["value"] == "PO-4471"
        assert f["date"]["value"] == "2026-09-10" and f["date"]["confidence"] == "high"
        assert f["due"]["value"] == "2026-10-10"
        assert (f["subtotal"]["value"], f["tax"]["value"], f["total"]["value"]) == (
            "1150.00",
            "84.56",
            "1234.56",
        )
        assert f["currency"]["value"] == "USD"
        assert f["iban"]["value"] == "GB82WEST12345698765432"
        assert list(f) == [
            "vendor",
            "invoice_no",
            "po",
            "date",
            "due",
            "subtotal",
            "tax",
            "total",
            "currency",
            "iban",
        ]


def test_extract_fields_email_and_heuristics(fixtures: Path, tmp_path: Path):
    rec = extract_fields(fixtures / "sample.eml")
    f = rec["fields"]
    assert f["vendor"] == {
        "value": "Acme Billing",
        "confidence": "high",
        "evidence": "From: Acme Billing <billing@acme.example>",
    }
    assert (
        f["total"]["value"] == "1234.56" and f["total"]["confidence"] == "medium"
    )  # largest amount
    receipt = tmp_path / "receipt.txt"
    receipt.write_text(
        "Beanery Coffee\nThank you for your visit\n2 x latte 8.50\nTax 0.68\nTotal 9.18\nPaid by card ending 4242\nNet 30\n05/01/2026\n",
        encoding="utf-8",
    )
    rec = extract_fields(receipt, date_order="dmy")
    f = rec["fields"]
    assert rec["profile"] == "receipt"
    assert f["vendor"]["value"] == "Beanery Coffee"
    assert f["total"]["value"] == "9.18" and f["tax"]["value"] == "0.68"
    assert f["date"]["value"] == "2026-01-05" and f["date"]["confidence"] == "medium"
    assert f["due"] == {"value": "2026-02-04", "confidence": "medium", "evidence": "Net 30"}
    bare = tmp_path / "nothing.txt"
    bare.write_text("just words\n", encoding="utf-8")
    rec = extract_fields(bare)
    assert (
        rec["fields"]["date"]["confidence"] == "low"
        and rec["fields"]["vendor"]["value"] == "just words"
    )
    text_only = extract_fields("memo", text="Amount Due: $50.00\n")
    assert text_only["path"] is None and text_only["fields"]["total"]["value"] == "50.00"
    with pytest.raises(CarrelInputError):
        extract_fields(bare, profile="ledger")


def test_fields_cli_json_set_save_and_errors(fixtures: Path, tmp_path: Path):
    inv = tmp_path / "invoice.txt"
    inv.write_bytes((fixtures / "invoice.txt").read_bytes())
    records = run_json(
        "--root", str(tmp_path), "fields", str(inv), "--set", "vendor=Acme Corporation", "--save"
    )
    (rec,) = records
    assert rec["fields"]["vendor"] == {
        "value": "Acme Corporation",
        "confidence": "user",
        "evidence": "--set",
    }
    assert rec["saved"] == list(rec["fields"])
    meta = run_json("--root", str(tmp_path), "meta", "ls", str(inv))["meta"]
    by_key = {m["key"]: m for m in meta}
    assert by_key["total"] == {
        **by_key["total"],
        "value": "1234.56",
        "kind": "num",
        "source": "fields",
    }
    assert by_key["due"]["kind"] == "date" and by_key["invoice_no"]["kind"] == "str"
    assert run_json("--root", str(tmp_path), "meta", "find", "total>1000") == [
        {"path": "invoice.txt", "meta": {k: m["value"] for k, m in sorted(by_key.items())}}
    ]
    human = run("fields", str(inv)).output
    assert "invoice_no  INV-2026-0042" in human and "(invoice)" in human
    assert "--set" in run("fields", str(inv), "--set", "colour=red", expect=2).stderr
    run("fields", str(tmp_path / "ghost.txt"), expect=4)
    empty = tmp_path / "e.txt"
    empty.write_text("", encoding="utf-8")
    (rec,) = run_json("fields", str(empty))
    assert set(rec["fields"]) == {"date", "vendor"}  # mtime + file name fallbacks only
    records = run_json("fields", str(tmp_path), "--profile", "statement")  # directory walk
    assert {Path(r["path"]).name for r in records} == {"invoice.txt", "e.txt"}
    assert all(r["profile"] == "statement" for r in records)  # --profile forces the kind


def test_fields_missing_binary_exits_3(tmp_path: Path, monkeypatch):
    from pypdf import PdfWriter

    pdf = tmp_path / "only.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf.open("wb") as fh:
        writer.write(fh)
    monkeypatch.setenv("CARREL_BIN_PDFTOTEXT", str(tmp_path / "nowhere"))
    res = run("fields", str(pdf), expect=3)
    assert "pdftotext" in res.stderr


# ------------------------------------------------------------------ rename


def test_build_name_placeholders(fixtures: Path, tmp_path: Path):
    f = tmp_path / "Acme Invoice (final).PDF"
    f.write_bytes((fixtures / "invoice.pdf").read_bytes())
    fields = {
        "date": {"value": "2026-09-10"},
        "vendor": {"value": "ACME Corp"},
        "invoice_no": {"value": "INV-2026-0042"},
        "total": {"value": "1234.56"},
    }
    name, sources = build_name(f, "{date}_{vendor}_{ref}_{total}{ext}", fields=fields)
    assert name == "2026-09-10_ACME_Corp_INV-2026-0042_1234.56.PDF"
    assert sources == {
        "date": "fields",
        "vendor": "fields",
        "ref": "fields",
        "total": "fields",
        "ext": "file",
    }
    name, _ = build_name(f, "{yyyy}/{date:%m}_{vendor}{ext}", fields=fields, lower=True)
    assert name == "2026/09_acme_corp.pdf"
    with pytest.raises(CarrelInputError, match="unusable"):
        build_name(f, "../{stem}{ext}")
    name, sources = build_name(
        f,
        "{meta.client}_{fields.po}_{type}_{stem}_{sha8}{ext}",
        fields={"po": {"value": "PO-1"}},
        meta={"client": "Big Co"},
    )
    assert (
        name.startswith("Big_Co_PO-1_pdf_Acme_Invoice_final_") and sources["meta.client"] == "meta"
    )
    name, sources = build_name(f, "{date}_{ref}{ext}", refs=[{"kind": "ticket", "value": "QA-12"}])
    assert name.endswith("_QA-12.PDF") and sources == {
        "date": "mtime",
        "ref": "refs",
        "ext": "file",
    }
    with pytest.raises(UnresolvedPlaceholderError, match=r"\{ref\}"):
        build_name(f, "{ref}{ext}")
    assert build_name(f, "{ref}{ext}", fallback="none")[0] == "none.PDF"
    with pytest.raises(CarrelInputError, match="unknown placeholder"):
        build_name(f, "{colour}{ext}")
    long_name, _ = build_name(
        f, "{vendor}{ext}", fields={"vendor": {"value": "x" * 300}}, max_len=20
    )
    assert long_name == "x" * 20 + ".PDF"
    assert slugify("  Acme / Corp & Sons  ", lower=True) == "acme_corp_sons"


def test_rename_cli_plan_apply_and_desk_follow(fixtures: Path, tmp_path: Path):
    inv = tmp_path / "scan.txt"
    inv.write_bytes((fixtures / "invoice.txt").read_bytes())
    note = tmp_path / "note.md"
    note.write_text("# a note\n\nno references here\n", encoding="utf-8")
    run("--root", str(tmp_path), "tag", "add", str(inv), "keepme")
    plan = run_json("--root", str(tmp_path), "rename", str(tmp_path))
    by_src = {Path(e["src"]).name: e for e in plan}
    assert by_src["scan.txt"]["action"] == "rename"
    assert Path(by_src["scan.txt"]["dest"]).name == "2026-09-10_ACME_Corp_INV-2026-0042.txt"
    assert by_src["note.md"]["action"] == "skip" and "{ref}" in by_src["note.md"]["reason"]
    assert inv.exists()  # dry-run moved nothing
    human = run("--root", str(tmp_path), "rename", str(tmp_path)).output
    assert "dry-run: 1 rename(s) planned" in human
    note_day = datetime.fromtimestamp(note.stat().st_mtime).date().isoformat()
    plan = run_json(
        "--root", str(tmp_path), "rename", str(tmp_path), "--apply", "--fallback", "misc", "--lower"
    )
    names = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert names == {"2026-09-10_acme_corp_inv-2026-0042.txt", f"{note_day}_a_note_misc.md"}
    assert all(e["action"] == "renamed" for e in plan)
    assert run_json("--root", str(tmp_path), "tag", "find", "keepme") == [
        "2026-09-10_acme_corp_inv-2026-0042.txt"
    ]
    again = run_json(
        "--root",
        str(tmp_path),
        "rename",
        str(tmp_path / "2026-09-10_acme_corp_inv-2026-0042.txt"),
        "--lower",
    )
    assert again[0]["action"] == "skip" and "already named" in again[0]["reason"]


def test_rename_usage_errors(tmp_path: Path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    assert (
        "no placeholders"
        in run("rename", str(tmp_path / "f.txt"), "--template", "fixed.txt", expect=2).stderr
    )
    assert (
        "unknown placeholder"
        in run("rename", str(tmp_path / "f.txt"), "--template", "{nope}{ext}", expect=2).stderr
    )
    run("rename", str(tmp_path / "ghost.txt"), expect=4)


def test_rename_never_overwrites(tmp_path: Path, fixtures: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes((fixtures / "invoice.txt").read_bytes())
    b.write_bytes((fixtures / "invoice.txt").read_bytes())
    plan = run_json("rename", str(a), str(b), "--apply")
    dests = sorted(Path(e["dest"]).name for e in plan)
    assert dests == [
        "2026-09-10_ACME_Corp_INV-2026-0042-1.txt",
        "2026-09-10_ACME_Corp_INV-2026-0042.txt",
    ]


# ------------------------------------------------------------------- fsops


def test_uncollide_and_move_file_follow_desk(tmp_path: Path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    assert uncollide(tmp_path / "b.txt") == tmp_path / "b-1.txt"
    assert uncollide(tmp_path / "b.txt", {tmp_path / "b-1.txt"}) == tmp_path / "b-2.txt"
    with DeskDB(tmp_path) as db:
        db.add_tags(src, ["t"])
        db.set_meta(src, "k", "v")
        fid = db.upsert_file(src, ftype="txt")
        db.set_content(fid, src, "indexed words")
    dest = move_file(src, tmp_path / "sub" / "moved.txt", desk_root=tmp_path)
    assert dest.is_file() and not src.exists()
    with DeskDB(tmp_path) as db:
        assert db.tags_of(dest) == ["t"] and db.get_meta(dest, "k")["value"] == "v"
        assert [r["path"] for r in db.fts_search("indexed")] == ["sub/moved.txt"]
        assert db.get_file(src) is None
    with pytest.raises(FileExistsError):
        move_file(dest, tmp_path / "b.txt")
    with DeskDB(tmp_path) as db:
        assert db.rename_path(tmp_path / "ghost.txt", tmp_path / "x.txt") is False


def test_organize_apply_keeps_desk_rows(tmp_path: Path, fixtures: Path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes((fixtures / "b.pdf").read_bytes())
    run("--root", str(tmp_path), "tag", "add", str(pdf), "filed")
    run("--root", str(tmp_path), "organize", str(tmp_path), "--apply")
    assert (tmp_path / "pdf" / "doc.pdf").is_file()
    assert run_json("--root", str(tmp_path), "tag", "find", "filed") == ["pdf/doc.pdf"]


# ----------------------------------------------------------------- actions


def test_render_substitutes_every_placeholder():
    path = Path("/tmp/some dir/my file.pdf")
    rendered = actions.render("{path} {name} {stem} {ext} {dir}", path)
    if os.name == "nt":
        assert (
            rendered
            == '"\\tmp\\some dir\\my file.pdf" "my file.pdf" "my file" .pdf "\\tmp\\some dir"'
        )
    else:
        assert (
            rendered == "'/tmp/some dir/my file.pdf' 'my file.pdf' 'my file' .pdf '/tmp/some dir'"
        )
    from carrel.commands.watch import _render

    assert _render is actions.render  # the watch alias still points at the shared implementation


# ------------------------------------------------------------------- batch


@pytest.fixture
def tree(tmp_path: Path, fixtures: Path) -> Path:
    (tmp_path / "a.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("h\n", encoding="utf-8")
    return tmp_path


def test_collect_files_filters(tree: Path):
    names = [p.name for p in collect_files([tree])]
    assert names == ["a.md", "b.txt", "c.json"]
    assert [p.name for p in collect_files([tree], recursive=False)] == ["a.md", "b.txt"]
    assert [p.name for p in collect_files([tree], glob="*.md")] == ["a.md"]
    assert [p.name for p in collect_files([tree], types={"json"})] == ["c.json"]
    assert [p.name for p in collect_files([tree / "b.txt", tree / "sub"])] == ["b.txt", "c.json"]
    with pytest.raises(CarrelInputError):
        collect_files([tree / "nope"])


@pytest.mark.skipif(os.name == "nt", reason="the smoke actions use POSIX shell builtins")
def test_batch_cli_runs_actions_and_reports_failures(tree: Path):
    payload = run_json(
        "batch",
        str(tree),
        "--run",
        "echo {name}",
        "--run",
        "test {ext} != .json",
        "--jobs",
        "2",
        expect=1,
    )
    assert payload["summary"] == {
        **payload["summary"],
        "total": 3,
        "ran": 3,
        "ok": 2,
        "failed": 1,
        "skipped": 0,
    }
    by_name = {Path(r["path"]).name: r for r in payload["results"]}
    assert (
        by_name["a.md"]["ok"]
        and by_name["a.md"]["stdout"].strip() == "a.md"
        and by_name["a.md"]["rc"] == 0
    )
    assert not by_name["c.json"]["ok"] and by_name["c.json"]["rc"] == 1
    assert by_name["c.json"]["cmd"].startswith("test ")
    assert [Path(r["path"]).name for r in payload["results"]] == [
        "a.md",
        "b.txt",
        "c.json",
    ]  # input order
    human = run("batch", str(tree), "--run", "true {name}", "--run", "echo {stem}")
    assert "[ok]   " in human.output and "3 ok, 0 failed, 0 skipped of 3 file(s)" in human.output


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell builtins")
def test_batch_manifest_resume_and_dry_run(tree: Path, tmp_path: Path):
    manifest = tmp_path.parent / f"{tmp_path.name}-run.jsonl"  # outside the tree being batched
    run("batch", str(tree), "--run", "test {ext} != .json", "--manifest", str(manifest), expect=1)
    assert load_manifest_done(manifest, ["test {ext} != .json"]) == {
        str(tree / "a.md"),
        str(tree / "b.txt"),
    }
    assert load_manifest_done(manifest, ["other"]) == set()
    payload = run_json(
        "batch",
        str(tree),
        "--run",
        "test {ext} != .json",
        "--manifest",
        str(manifest),
        "--resume",
        expect=1,
    )
    assert payload["summary"]["skipped"] == 2 and payload["summary"]["ran"] == 1
    assert len(manifest.read_text(encoding="utf-8").splitlines()) == 4
    dry = run("batch", str(tree), "--glob", "*.md", "--run", "wc -c {path}", "--dry-run").output
    assert dry.startswith("wc -c ") and "dry-run: 1 file(s), 1 action(s) each" in dry
    lines = run(
        "--json", "batch", str(tree), "--run", "echo {name}", "--dry-run"
    ).output.splitlines()
    assert [json.loads(ln)["cmds"] for ln in lines] == [
        ["echo a.md"],
        ["echo b.txt"],
        ["echo c.json"],
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell builtins")
def test_batch_json_lines_fail_fast_and_timeout(tree: Path):
    out = run("batch", str(tree), "--run", "echo {name}", "--json-lines").output.splitlines()
    records = [json.loads(ln) for ln in out]
    assert [r["path"] for r in records[:-1]] and records[-1] == {"summary": records[-1]["summary"]}
    assert records[-1]["summary"]["ok"] == 3
    payload = run_json("batch", str(tree), "--run", "test -z {name}", "--fail-fast", expect=1)
    assert payload["summary"]["ran"] == 1 and payload["summary"]["failed"] == 1
    payload = run_json(
        "batch",
        str(tree / "a.md"),
        "--run",
        "sleep 5 && echo {name}",
        "--action-timeout",
        "0.3",
        expect=1,
    )
    assert payload["results"][0]["rc"] == 124 and "timed out" in payload["results"][0]["stderr"]
    results = run_batch([tree / "a.md", tree / "b.txt"], ["echo {name}"], jobs=2)
    assert [r["stdout"].strip() for r in results] == ["a.md", "b.txt"]


def test_batch_usage_errors_and_fail_empty(tree: Path, tmp_path: Path):
    assert "uses none of" in run("batch", str(tree), "--run", "echo static", expect=2).stderr
    assert (
        "--resume needs"
        in run("batch", str(tree), "--run", "echo {name}", "--resume", expect=2).stderr
    )
    assert (
        "unknown --type"
        in run("batch", str(tree), "--run", "echo {name}", "--type", "dna", expect=2).stderr
    )
    run("batch", str(tree), "--glob", "*.zzz", "--run", "echo {name}", "--fail-empty", expect=5)
    assert (
        run_json("batch", str(tree), "--glob", "*.zzz", "--run", "echo {name}")["summary"]["total"]
        == 0
    )
    run("batch", str(tmp_path / "ghost"), "--run", "echo {name}", expect=4)


@pytest.mark.parametrize("name", ["fields", "rename", "batch"])
def test_help_and_json_flag(name: str):
    result = run(name, "--help")
    assert "Usage:" in result.output and "--json" in result.output


@needs("pdftotext")
def test_fields_reads_pdf_pages(fixtures: Path):
    rec = extract_fields(fixtures / "invoice.pdf")
    assert rec["fields"]["total"]["value"] == "1234.56"


# ----------------------------------------------------------------- watch v2


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell builtins")
def test_watch_existing_stable_done_error_dirs_and_log(tmp_path: Path):
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "good.txt").write_text("hello\n", encoding="utf-8")
    (inbox / "bad.txt").write_text("nope\n", encoding="utf-8")
    log = tmp_path / "log.jsonl"
    run("--root", str(tmp_path), "tag", "add", str(inbox / "good.txt"), "keep")
    result = run(
        "--root",
        str(tmp_path),
        "watch",
        str(inbox),
        "--existing",
        "--timeout",
        "4",
        "--stable",
        "0.2",
        "--done-dir",
        str(tmp_path / "done"),
        "--error-dir",
        str(tmp_path / "err"),
        "--log",
        str(log),
        "--run",
        "test {name} != bad.txt",
    )
    assert "[existing]" in result.output
    assert sorted(p.name for p in inbox.iterdir()) == []
    assert (tmp_path / "done" / "good.txt").is_file() and (tmp_path / "err" / "bad.txt").is_file()
    records = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
    events = [(r["event"], Path(r["path"]).name) for r in records]
    assert ("existing", "good.txt") in events and ("filed", "bad.txt") in events
    filed = next(r for r in records if r["event"] == "filed" and r["path"].endswith("good.txt"))
    assert filed["ok"] is True and filed["dest"].endswith("done/good.txt")
    assert all("time" in r for r in records)
    # the desk row followed the moved file
    assert run_json("--root", str(tmp_path), "tag", "find", "keep") == ["done/good.txt"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell builtins")
def test_watch_recursive_and_poll(tmp_path: Path):
    inbox = tmp_path / "in"
    (inbox / "deep").mkdir(parents=True)
    (inbox / "deep" / "x.md").write_text("x\n", encoding="utf-8")
    flat = run("watch", str(inbox), "--existing", "--timeout", "2", "--run", "echo {name}").output
    assert "x.md" not in flat  # non-recursive: the nested file is not seen
    deep = run(
        "watch",
        str(inbox),
        "--existing",
        "--recursive",
        "--poll",
        "--poll-interval",
        "0.2",
        "--timeout",
        "3",
        "--run",
        "echo {name}",
    ).output
    assert (
        "[existing]" in deep
        and "x.md" in deep
        and "polling"
        in run("watch", str(inbox), "--poll", "--timeout", "0.5", "--run", "echo {name}").stderr
    )


def test_watch_print_service_and_usage(tmp_path: Path):
    unit = run(
        "watch", str(tmp_path), "--run", "echo {path}", "--recursive", "--print-service", "systemd"
    ).output
    assert unit.startswith("# Save as ~/.config/systemd/user/carrel-watch.service")
    assert (
        "[Service]" in unit
        and "ExecStart=" in unit
        and "--recursive" in unit
        and "--print-service" not in unit
    )
    task = run("watch", str(tmp_path), "--run", "echo {path}", "--print-service", "schtasks").output
    assert (
        task.startswith("REM ")
        and "schtasks /Create /SC ONLOGON" in task
        and "--print-service" not in task
    )


def test_watch_print_service_writes_absolute_paths(tmp_path: Path, monkeypatch):
    """A generated service starts in the manager's working directory, not the caller's.

    A systemd *user* unit has no WorkingDirectory, so it runs from $HOME. Every
    relative path baked into the unit would resolve against the wrong place:
    `--root` is click.Path(exists=True), so a relative one makes the unit die
    with exit 2 on every start, and a relative --done-dir would quietly file
    documents into a directory under $HOME.
    """
    watched = tmp_path / "inbox"
    done = tmp_path / "done"
    for d in (watched, done):
        d.mkdir()
    monkeypatch.chdir(tmp_path)

    unit = run(
        "--root",
        ".",
        "watch",
        "inbox",
        "--run",
        "echo {path}",
        "--done-dir",
        "done",
        "--print-service",
        "systemd",
    ).output

    exec_start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    # `_systemd_split`, not `shlex.split`: the line is built by `_systemd_word`,
    # which doubles `%` and `$` for systemd's specifier and variable expansion.
    # shlex does not undo that, so these assertions passed only because pytest's
    # tmp_path happens to hold neither character — a `--basetemp` under a path
    # containing `%` failed the test while the product was correct.
    argv = _systemd_split(exec_start.removeprefix("ExecStart="))
    after = {flag: argv[argv.index(flag) + 1] for flag in ("--root", "--done-dir", "watch")}

    assert after["--root"] == str(tmp_path.resolve()), argv
    assert after["watch"] == str(watched.resolve()), argv
    assert after["--done-dir"] == str(done.resolve()), argv
    assert all(Path(p).is_absolute() for p in after.values()), argv

    # without --root the unit should not name one at all
    plain = run("watch", "inbox", "--run", "echo {path}", "--print-service", "systemd").output
    assert "--root" not in plain
    assert (
        "--stable-timeout needs"
        in run(
            "watch", str(tmp_path), "--run", "echo {path}", "--stable-timeout", "1", expect=2
        ).stderr
    )
    assert "{stem}" in run("watch", "--help").output and "existing" in run("watch", "--help").output


def test_watcher_settle_waits_for_a_growing_file(tmp_path: Path, monkeypatch):
    """The settle window is driven by an injected clock, not by `time.sleep`.

    Asserting "not settled yet" after a real `sleep` shorter than `--stable`
    means asserting that the runner got back within the window. It does not
    always: this failed on `test-minimal (macos)` with the file already
    settled, because more than 0.2 s of wall clock had passed between the
    write and the check. Driving `watch`'s own clock makes the assertions say
    what they mean — and drops ~0.25 s of sleeping from the suite.
    """
    import time as real_time

    from carrel.commands import watch as watch_mod
    from carrel.commands.watch import _Watcher

    class _Clock:
        """`watch.time`, with monotonic() under the test's control.

        `sleep()` advances the fake clock instead of blocking. Without that,
        code that waits for a monotonic deadline — `_run_watch`'s `--timeout`
        loop at `watch.py:644` is the live example — would spin forever against
        a frozen clock, and the suite configures no pytest timeout, so the
        failure would be a silent 30-minute job kill rather than a test
        failure. `_run_watch` blocks on `watcher.stop.wait()` rather than
        `time.sleep()`, so this clock still must not be pointed at it.
        """

        def __init__(self) -> None:
            self.now = 1_000.0

        def monotonic(self) -> float:
            return self.now

        def advance(self, seconds: float) -> None:
            self.now += seconds

        def sleep(self, seconds: float) -> None:
            self.advance(seconds)

        def __getattr__(self, name: str):  # time(), strftime(), … stay real
            return getattr(real_time, name)

    clock = _Clock()
    monkeypatch.setattr(watch_mod, "time", clock)

    f = tmp_path / "grow.bin"
    f.write_bytes(b"a")
    w = _Watcher(
        on={"created"}, glob=None, debounce_ms=0, runs=("echo",), json_lines=False, stable=0.2
    )
    w.record("created", f)
    assert w.drain() == []  # first look: baseline recorded
    f.write_bytes(b"ab")  # changed → not settled, the clock restarts
    assert w.drain() == []
    clock.advance(0.1)
    assert w.drain() == []  # unchanged, but not yet for 0.2 s
    clock.advance(0.15)
    assert w.drain() == [("created", f)]
    w2 = _Watcher(
        on={"created"},
        glob=None,
        debounce_ms=0,
        runs=("echo",),
        json_lines=False,
        stable=60,
        stable_timeout=0.1,
    )
    w2.record("created", f)
    w2.drain()
    clock.advance(0.15)
    assert w2.drain() == [("created", f)]  # --stable-timeout gives up waiting


# ------------------------------------------- regressions from the PR C review


def test_negative_amounts_keep_their_sign(tmp_path: Path):
    """A credit note is not a charge: the label separator must not eat the minus."""
    credit = tmp_path / "credit.txt"
    credit.write_text(
        "Globex GmbH\nSubtotal  -$1,150.00\nTax  -$84.56\nTotal Due  -$1,234.56\n", encoding="utf-8"
    )
    f = extract_fields(credit)["fields"]
    assert (f["subtotal"]["value"], f["tax"]["value"], f["total"]["value"]) == (
        "-1150.00",
        "-84.56",
        "-1234.56",
    )
    assert money.parse_amount("-$1,234.56").value == Decimal("-1234.56")
    assert money.parse_amount("-€500,00").value == Decimal("-500.00")
    assert money.parse_amount("EUR -5").value == Decimal("-5")
    refund = money.find_amounts("Refund for order 5512:   -$1,234.56\nRestocking fee: $25.00")
    assert [str(a.value) for a in refund] == ["-1234.56", "25.00"]
    # a dash that really is a separator still works
    spaced = tmp_path / "spaced.txt"
    spaced.write_text("Total - $12.00\n", encoding="utf-8")
    assert extract_fields(spaced)["fields"]["total"]["value"] == "12.00"


def test_a_decoy_label_line_does_not_win(tmp_path: Path):
    src = tmp_path / "decoy.txt"
    src.write_text(
        "Acme\nTax ID: 12-3456789\nTotal units          3.00\n"
        "Tax  $84.56\nTotal          $1,234.56\n",
        encoding="utf-8",
    )
    f = extract_fields(src)["fields"]
    assert f["total"]["value"] == "1234.56" and "$1,234.56" in f["total"]["evidence"]
    assert f["tax"]["value"] == "84.56"  # the `Tax ID:` line yields no amount, so it is passed over


def test_net_terms_are_not_read_off_an_amount(tmp_path: Path):
    src = tmp_path / "net.txt"
    src.write_text(
        "Invoice Date: 2026-03-04\nNet  500.00\nVAT 19%  95.00\nTotal Due  595.00\n",
        encoding="utf-8",
    )
    f = extract_fields(src)["fields"]
    assert f["subtotal"]["value"] == "500.00"
    assert "due" not in f  # `Net  500.00` is a subtotal line, not Net-500 terms
    terms = tmp_path / "terms.txt"
    terms.write_text(
        "Invoice Date: 2026-03-04\nTerms: Net 30\nTotal Due  595.00\n", encoding="utf-8"
    )
    assert extract_fields(terms)["fields"]["due"]["value"] == "2026-04-03"


def test_currency_is_deterministic_on_a_tie(tmp_path: Path):
    src = tmp_path / "cur.txt"
    src.write_text("Amount charged: EUR 100.00\nConverted at rate: USD 118.00\n", encoding="utf-8")
    seen = {extract_fields(src)["fields"]["currency"]["value"] for _ in range(12)}
    assert seen == {"EUR"}  # most frequent, then alphabetical — never hash order


def test_a_dotted_date_is_not_an_amount(tmp_path: Path):
    src = tmp_path / "ymd.txt"
    src.write_text(
        "Kaufbeleg\n2026.03.04  Filiale 12\nEspresso 3,50\nZu zahlen 5,70\n", encoding="utf-8"
    )
    f = extract_fields(src)["fields"]
    assert f["total"]["value"] == "5.70" and f["date"]["value"] == "2026-03-04"
    assert [a.raw for a in money.find_amounts("Ref 2026.09.10 total $99.00")] == ["$99.00"]
    assert [a.raw for a in money.find_amounts("The total is 5.70.")] == [
        "5.70"
    ]  # sentence end is fine


def test_render_substitutes_in_one_pass(tmp_path: Path):
    """A file named `{name}.txt` must not have its own substituted path rewritten."""
    tricky = tmp_path / "{name}.txt"
    tricky.write_text("contents\n", encoding="utf-8")
    rendered = actions.render("cat {path}", tricky)
    assert rendered == f"cat {actions.quote(str(tricky))}"
    assert actions.render("{name} {stem} {ext}", tricky) == " ".join(
        actions.quote(x) for x in ("{name}.txt", "{name}", ".txt")
    )
    if os.name != "nt":  # `cat` is the POSIX half of the check
        payload = run_json("batch", str(tricky), "--run", "cat {path}")
        assert payload["summary"]["ok"] == 1
        assert payload["results"][0]["stdout"].strip() == "contents"


def test_manifest_and_log_directories_are_created(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    manifest = tmp_path / "logs" / "run.jsonl"
    payload = run_json("batch", str(tmp_path), "--run", "echo {name}", "--manifest", str(manifest))
    assert payload["summary"]["ok"] == 1
    assert json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])["ok"] is True
    log = tmp_path / "wlogs" / "watch.jsonl"
    run(
        "watch",
        str(tmp_path),
        "--existing",
        "--on",
        "created",
        "--once",
        "--timeout",
        "5",
        "--run",
        "echo {name}",
        "--log",
        str(log),
    )
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["rc"] == 0


def test_watch_output_heuristic_only_suppresses_added_segments(tmp_path: Path):
    from carrel.commands.watch import _Watcher

    w = _Watcher(on={"created"}, glob=None, debounce_ms=0, runs=("echo",), json_lines=False)
    source = tmp_path / "report.pdf"
    w.inflight.add(source)
    w.seed("created", tmp_path / "report.txt")  # an output of the action
    w.seed("created", tmp_path / "report.thumb.png")  # also an output
    w.seed("created", tmp_path / "report-2026.pdf")  # a NEW INPUT that merely shares a prefix
    assert set(w.pending) == {tmp_path / "report-2026.pdf"}


def test_watch_existing_skips_the_done_and_error_dirs(tmp_path: Path):
    from carrel.commands.watch import _existing_files

    (tmp_path / "done").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "done" / "old.txt").write_text("o", encoding="utf-8")
    (tmp_path / "sub" / "deep.txt").write_text("d", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "h.txt").write_text("h", encoding="utf-8")
    found = _existing_files(tmp_path, True, [tmp_path / "done"])
    assert [p.name for p in found] == ["a.txt", "deep.txt"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@not_as_root
def test_rename_records_a_failed_move_and_keeps_going(tmp_path: Path, fixtures: Path):
    ro = tmp_path / "ro"
    ro.mkdir()
    (ro / "invoice.txt").write_bytes((fixtures / "invoice.txt").read_bytes())
    ro.chmod(0o555)
    try:
        result = run("--json", "rename", str(ro / "invoice.txt"), "--apply", expect=1)
    finally:
        ro.chmod(0o755)
    # the JSON plan is still emitted; the failure line follows it on stderr
    plan, _ = json.JSONDecoder().raw_decode(result.output.lstrip())
    assert [e["action"] for e in plan] == ["error"]
    assert "Permission" in plan[0]["reason"]  # the record names the file that did not move
    assert "could not be renamed" in result.output


def _systemd_split(line: str) -> list[str]:
    """systemd's `ExecStart=` unquoting, as a model for tests.

    Follows systemd.syntax(7) (quoted items, C escapes) and systemd.service(5)
    (`%%` and `$$` for literal percent and dollar). The same inputs these tests
    use were round-tripped once through a real systemd 259 unit on 2026-09-11.
    """
    escapes = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "t": "\t", "r": "\r", "s": " ", ";": ";"}
    words: list[str] = []
    i, n = 0, len(line)
    while i < n:
        while i < n and line[i] in " \t":
            i += 1
        if i >= n:
            break
        quote = line[i] if line[i] in "\"'" else None
        if quote:
            i += 1
        cur: list[str] = []
        while i < n:
            c = line[i]
            if c == "\\" and i + 1 < n:
                cur.append(escapes[line[i + 1]])
                i += 2
                continue
            if quote and c == quote:
                i += 1
                break
            if not quote and c in " \t":
                break
            cur.append(c)
            i += 1
        words.append("".join(cur))
    return [w.replace("%%", "%").replace("$$", "$") for w in words]


def _ms_split(line: str) -> list[str]:
    """Windows command-line splitting (MSVCRT / CommandLineToArgvW rules), as a model."""
    args: list[str] = []
    cur: list[str] = []
    in_quotes = have = False
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            j = i
            while j < n and line[j] == "\\":
                j += 1
            count = j - i
            if j < n and line[j] == '"':
                cur.append("\\" * (count // 2))
                if count % 2:
                    cur.append('"')
                    j += 1
                i, have = j, True
                continue
            cur.append("\\" * count)
            i, have = j, True
            continue
        if c == '"':
            if in_quotes and i + 1 < n and line[i + 1] == '"':
                cur.append('"')
                i += 2
            else:
                in_quotes = not in_quotes
                i += 1
            have = True
            continue
        if c in " \t" and not in_quotes:
            if have:
                args.append("".join(cur))
                cur, have = [], False
            i += 1
            continue
        cur.append(c)
        i, have = i + 1, True
    if have:
        args.append("".join(cur))
    return args


def _runs(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, word in enumerate(argv) if word == "--run"]


#: actions that broke the unit shlex.join produced
SYSTEMD_ACTIONS = [
    'mv {path} "archive/$(date +%Y-%m)"',
    "sed 's/\\t/,/' {path}",
    "it's {name}",
    'say "hi" > {dir}/log',
    "copy {path} out\\",
    "$HOME ${USER} %h %% $$",
]

#: actions that broke the one-line schtasks /TR value
WINDOWS_ACTIONS = [
    'magick {path} "{dir}\\thumb.png"',
    'copy {path} "D:\\out dir\\\\"',
    "echo {path} done",
    'say "hi"',
]


def test_print_service_names_this_carrel_not_the_first_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A 0.4.1 venv must not print a unit pinned to an older global install."""
    import sys

    watched = tmp_path / "inbox"
    watched.mkdir()
    fake = tmp_path / "venv" / "bin" / "carrel"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [str(fake)])
    unit = run("watch", str(watched), "--run", "true", "--print-service", "systemd").output
    exec_start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert _systemd_split(exec_start.removeprefix("ExecStart="))[0] == str(fake.absolute())

    monkeypatch.setattr(sys, "argv", ["pytest"])  # not a carrel launcher
    unit = run("watch", str(watched), "--run", "true", "--print-service", "systemd").output
    exec_start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert _systemd_split(exec_start.removeprefix("ExecStart="))[:3] == [
        sys.executable,
        "-m",
        "carrel.cli",
    ]


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_print_service_keeps_the_launcher_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Homebrew's bin/carrel resolves into a Cellar directory that `brew cleanup` deletes."""
    import sys

    watched = tmp_path / "inbox"
    watched.mkdir()
    cellar = tmp_path / "Cellar" / "carrel" / "0.4.1" / "bin" / "carrel"
    cellar.parent.mkdir(parents=True)
    cellar.write_text("#!/bin/sh\n", encoding="utf-8")
    link = tmp_path / "bin" / "carrel"
    link.parent.mkdir()
    link.symlink_to(cellar)

    monkeypatch.setattr(sys, "argv", [str(link)])
    unit = run("watch", str(watched), "--run", "true", "--print-service", "systemd").output
    exec_start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    first = _systemd_split(exec_start.removeprefix("ExecStart="))[0]

    assert first == str(link.absolute())
    assert "Cellar" not in first


def test_launcher_path_finds_the_exe_a_windows_launcher_hides(tmp_path: Path):
    """uv and pip launchers strip `.exe` from sys.argv[0] on Windows."""
    from carrel.commands.watch import _launcher_path

    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "carrel.exe").write_bytes(b"MZ")
    stripped = str(scripts / "carrel")

    assert _launcher_path(stripped, windows=True) == (scripts / "carrel.exe").absolute()
    assert _launcher_path(stripped, windows=False) is None
    assert _launcher_path("", windows=True) is None
    (scripts / "python.exe").write_bytes(b"MZ")
    assert _launcher_path(str(scripts / "python"), windows=True) is None


def test_print_service_systemd_round_trips_every_action(tmp_path: Path):
    """systemd expands % and $ inside quotes and C-unescapes backslashes.

    shlex.join single-quoted, left % and $ alone and spliced '"'"' for
    apostrophes, so `date +%Y-%m` became the unit directory and machine ID.
    """
    watched = tmp_path / "in%box"
    watched.mkdir()
    args = ["watch", str(watched)]
    for action in SYSTEMD_ACTIONS:
        args += ["--run", action]
    unit = run(*args, "--print-service", "systemd").output

    exec_start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert _runs(_systemd_split(exec_start.removeprefix("ExecStart="))) == SYSTEMD_ACTIONS
    description = next(ln for ln in unit.splitlines() if ln.startswith("Description="))
    # Bare, not quoted: systemd 259 does not unquote Description= (quotes show
    # up verbatim in `systemctl show`) or WorkingDirectory= (a quoted path is
    # rejected as "not absolute"). Only `%` is doubled.
    assert description == f"Description=carrel watch {str(watched.resolve()).replace('%', '%%')}"


def test_print_service_schtasks_round_trips_every_action(tmp_path: Path):
    """Windows parses the pasted line twice, so the command is quoted twice.

    A bare quote-to-backslash-quote replace missed the backslashes in front of
    each quote, corrupting any action with an embedded quote or a trailing
    backslash.
    """
    watched = tmp_path / "inbox"
    watched.mkdir()
    args = ["watch", str(watched)]
    for action in WINDOWS_ACTIONS:
        args += ["--run", action]
    task = run(*args, "--print-service", "schtasks").output

    line = next(ln for ln in task.splitlines() if ln.startswith("schtasks /Create"))
    outer = _ms_split(line)
    assert outer[-1] == "/F"
    assert _runs(_ms_split(outer[outer.index("/TR") + 1])) == WINDOWS_ACTIONS


@pytest.mark.skipif(os.name != "nt", reason="needs Windows' own command-line parser")
def test_print_service_schtasks_survives_the_real_windows_parser(tmp_path: Path):
    """The same round trip through CreateProcess itself, not a model of it."""
    import subprocess
    import sys

    watched = tmp_path / "inbox"
    watched.mkdir()
    args = ["watch", str(watched)]
    for action in WINDOWS_ACTIONS:
        args += ["--run", action]
    task = run(*args, "--print-service", "schtasks").output
    line = next(ln for ln in task.splitlines() if ln.startswith("schtasks /Create"))

    probe = subprocess.list2cmdline(
        [sys.executable, "-c", "import json,sys;print(json.dumps(sys.argv[1:]))"]
    )
    outer = json.loads(
        subprocess.run(
            probe + line[len("schtasks") :], capture_output=True, text=True, check=True
        ).stdout
    )
    tr = outer[outer.index("/TR") + 1]
    inner = json.loads(
        subprocess.run(probe + " " + tr, capture_output=True, text=True, check=True).stdout
    )
    assert _runs(inner) == WINDOWS_ACTIONS


def test_print_service_carries_the_global_json_flag(tmp_path: Path):
    """`carrel --json watch …` logs JSON lines; the service must too."""
    watched = tmp_path / "inbox"
    watched.mkdir()

    unit = run(
        "--json", "watch", str(watched), "--run", "true", "--print-service", "systemd"
    ).output
    exec_start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert "--json-lines" in _systemd_split(exec_start.removeprefix("ExecStart="))

    plain = run("watch", str(watched), "--run", "true", "--print-service", "systemd").output
    assert "--json-lines" not in plain


# ------------------------------------ regressions from the owed review of #36


@pytest.mark.skipif(
    os.name == "nt", reason="NTFS forbids a newline or a trailing backslash in a name"
)
def test_a_directory_name_cannot_inject_directives_into_the_unit(tmp_path: Path):
    """`Description=` was unquoted, so a newline in a path ended the line.

    Everything after it became further unit directives in the file the user is
    told to save and `systemctl --user enable`. The milder variant is a name
    ending in a backslash: systemd's line continuation then swallowed the
    `After=` line that followed, dropping the ordering dependency.
    """
    hostile = tmp_path / "x\n[Service]\nExecStart=/bin/sh -c touch /tmp/pwned"
    hostile.mkdir(parents=True)
    err = run("watch", str(hostile), "--run", "true", "--print-service", "systemd", expect=2).stderr
    assert "cannot represent" in err and "newline" in err, err

    # A trailing backslash is the quieter version: verified against systemd 259,
    # `Description=... back\` swallowed the `After=default.target` line that
    # followed, and After= fell back to its defaults.
    trailing = tmp_path / "back\\"
    trailing.mkdir()
    err = run(
        "watch", str(trailing), "--run", "true", "--print-service", "systemd", expect=2
    ).stderr
    assert "backslash" in err, err

    # Trailing whitespace is the third shape a bare line cannot carry: verified
    # on systemd 259, the config parser strips it, so `WorkingDirectory=/x/in `
    # silently becomes `/x/in` — a different directory that either fails the
    # unit 200/CHDIR under Restart=on-failure or quietly becomes the action cwd.
    spaced = tmp_path / "inbox "
    spaced.mkdir()
    err = run("watch", str(spaced), "--run", "true", "--print-service", "systemd", expect=2).stderr
    assert "whitespace" in err, err

    # and the schtasks arm refuses the same injection: its own first line says
    # "Paste into cmd.exe", and list2cmdline does not escape a newline
    err = run(
        "watch", str(hostile), "--run", "true", "--print-service", "schtasks", expect=2
    ).stderr
    assert "newline" in err and "pasted command line" in err, err


def test_the_unit_pins_a_working_directory(tmp_path: Path):
    """A systemd *user* unit starts in $HOME, so relative `--run` paths moved
    every processed file into the home directory instead of the inbox."""
    watched = tmp_path / "inbox"
    watched.mkdir()
    unit = run(
        "watch",
        str(watched),
        "--run",
        'mv {path} "archive/$(date +%Y-%m)"',
        "--print-service",
        "systemd",
    ).output
    workdir = next(ln for ln in unit.splitlines() if ln.startswith("WorkingDirectory="))
    # the cwd, not the watched directory: `_abs` already resolves option paths
    # against the cwd, so a unit pinned to the watch would resolve `--done-dir
    # archive` and `cp {path} backups/` against two different roots.
    assert workdir == f"WorkingDirectory={Path.cwd()}"


def test_launcher_path_survives_a_degenerate_argv0():
    """`with_name` raises ValueError when argv[0] has no final component, and
    `@handled` only converts CarrelError — so it escaped as a traceback.

    For pathlib that is exactly `/` and `.`: a trailing separator is stripped,
    so `bin/` has the name `bin` and never reached the raising branch. The
    `windows=True` half is the one that mattered — it is the only caller of
    `with_name` — and it is asserted first for that reason.
    """
    from carrel.commands.watch import _launcher_path

    for argv0 in ("/", "."):  # the two that raised
        assert _launcher_path(argv0, windows=True) is None
        assert _launcher_path(argv0, windows=False) is None
    for argv0 in ("..", "bin/", ""):  # never raised; still must not match
        assert _launcher_path(argv0, windows=True) is None


def test_launcher_path_normalises_dot_dot(tmp_path: Path, monkeypatch):
    """systemd refuses an ExecStart whose executable path is not normalised.

    `absolute()` prepends the cwd without resolving `..`; `resolve()` would
    follow the Homebrew/Nix symlink into a store the next upgrade deletes.
    """
    from carrel.commands.watch import _launcher_path

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "carrel"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    found = _launcher_path("bin/../bin/carrel", windows=False)
    assert found is not None
    assert ".." not in found.parts, found
    assert found == launcher


def test_the_guard_walk_skips_git_internals_and_the_archive(tmp_path: Path):
    """`.git/objects` can never be tracked, and the archive grows without bound.

    Hidden *files* stay in the set: `--existing` skips them, but a live event
    reaches `_Watcher.seed`, which applies only `--glob`.
    """
    from carrel.commands.watch import _walk_files

    root = tmp_path / "inbox"
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "objects" / "abc").write_text("x", encoding="utf-8")
    (root / "sub").mkdir()
    done = root / "done"
    done.mkdir()
    (done / "filed.pdf").write_text("x", encoding="utf-8")
    (root / ".gitkeep").write_text("", encoding="utf-8")
    (root / "sub" / "a.pdf").write_text("x", encoding="utf-8")

    found = _walk_files(root, recursive=True, skip=[done], glob_=None)
    names = {p.name for p in found}
    assert names == {".gitkeep", "a.pdf"}, found
    assert not any(".git" in p.parts for p in found)
    assert not any(p.is_relative_to(done) for p in found)

    assert {p.name for p in _walk_files(root, recursive=True, skip=[done], glob_="*.pdf")} == {
        "a.pdf"
    }
    assert {p.name for p in _walk_files(root, recursive=False, skip=[done])} == {".gitkeep"}


def test_schtasks_warns_when_the_tr_value_is_over_budget(tmp_path: Path):
    """schtasks rejects or truncates a /TR past ~261 characters."""
    watched = tmp_path / ("inbox_" + "x" * 120)
    watched.mkdir()
    long_line = run(
        "watch",
        str(watched),
        "--run",
        "magick {path} {dir}/thumb.png",
        "--done-dir",
        str(tmp_path / ("done_" + "y" * 120)),
        "--print-service",
        "schtasks",
    ).output
    assert "WARNING: the /TR value is" in long_line, long_line

    short = tmp_path / "in"
    short.mkdir()
    ok = run("watch", str(short), "--run", "true", "--print-service", "schtasks").output
    assert "WARNING" not in ok, ok


def test_the_schtasks_warning_names_every_part_of_the_line(tmp_path: Path):
    """`C:\\R&D\\inbox` splits the pasted line just as a `--run` action would."""
    watched = tmp_path / "inbox"
    watched.mkdir()
    out = run("watch", str(watched), "--run", "true", "--print-service", "schtasks").output
    assert "--done-dir" in out and "--log" in out and "--run action" in out
    assert "ANY part of the line" in out


def test_generated_service_text_comes_from_product_json(tmp_path: Path, monkeypatch):
    """CLAUDE.md: the product name lives only in product.json, and anything
    generated must read it. `_launcher_path` compared `argv[0]` against a
    literal "carrel", and the unit file name, Description and schtasks /TN were
    hardcoded too — so after `scripts/finalize.sh` renamed the product, every
    generated unit named a module that no longer exists and died at boot.

    Asserted by renaming the product and reading the output, not by grepping
    the source: prose in docstrings legitimately says "carrel".
    """
    from carrel.commands import watch as watch_mod

    watched = tmp_path / "inbox"
    watched.mkdir()
    monkeypatch.setitem(watch_mod.PRODUCT, "cli", "shelf")
    monkeypatch.setitem(watch_mod.PRODUCT, "package", "shelf")

    unit = run("watch", str(watched), "--run", "true", "--print-service", "systemd").output
    assert "shelf-watch.service" in unit and "--now shelf-watch" in unit, unit
    assert "Description=shelf watch " in unit, unit
    # Asserted on shape, not by scanning for the string "carrel": every line
    # carrying a path also carries tmp_path, and `--basetemp` under a directory
    # named carrel would fail this while the product is correct — the same
    # false alarm this PR removes from the ExecStart test above.
    assert f"WorkingDirectory={Path.cwd()}" in unit, unit
    assert "carrel-watch.service" not in unit and "carrel watch " not in unit, unit

    task = run("watch", str(watched), "--run", "true", "--print-service", "schtasks").output
    assert '/TN "shelf watch"' in task, task
    assert '/TN "carrel watch"' not in task, task

    # and the module fallback, used when argv[0] is not a product launcher
    monkeypatch.setattr(sys, "argv", ["pytest"])
    unit = run("watch", str(watched), "--run", "true", "--print-service", "systemd").output
    assert '"-m" "shelf.cli"' in unit, unit


@pytest.mark.skipif(
    shutil.which("systemd-analyze") is None, reason="systemd-analyze is not installed"
)
def test_the_generated_unit_is_accepted_by_real_systemd(tmp_path: Path):
    """Round-trip through the consumer, not through our model of it.

    `_systemd_split` is a reimplementation of systemd.syntax(7). It has no
    notion of value whitespace stripping, specifier expansion or line
    continuation, so a unit systemd rejects still passes every string
    assertion — which is exactly how the first draft of this fix shipped a
    quoted `WorkingDirectory=` that systemd refuses as "path is not absolute".
    """
    import subprocess as sp

    watched = tmp_path / "in%box with spaces"
    watched.mkdir()
    unit_text = run(
        "watch",
        str(watched),
        "--run",
        'mv {path} "archive/$(date +%Y-%m)"',
        "--print-service",
        "systemd",
    ).output

    unit = tmp_path / "carrel-probe.service"
    unit.write_text(unit_text, encoding="utf-8", newline="\n")
    proc = sp.run(
        ["systemd-analyze", "--user", "verify", str(unit)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    output = proc.stdout + proc.stderr
    # `--user` needs a reachable user manager. Under `env -i PATH=/usr/bin`
    # (the minimal-environment gate) there is no XDG_RUNTIME_DIR, so
    # systemd-analyze cannot start one — an unavailable capability, which
    # CLAUDE.md says must skip with a reason rather than fail.
    if "Failed to initialize manager" in output or "RuntimeDirectory" in output:
        pytest.skip("no user systemd manager reachable in this environment")

    complaints = [
        ln
        for ln in output.splitlines()
        # the ExecStart binary need not exist on a CI box; everything else must be clean
        if ln.strip() and "Executable" not in ln and "not found" not in ln.lower()
    ]
    assert not complaints, "systemd rejects the generated unit:\n" + "\n".join(complaints)
