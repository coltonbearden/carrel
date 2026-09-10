"""Tests for spec 28: eml/mbox as first-class types (detect, extract, inspect, convert, organize,
diff, index/search, guard) and the `carrel mail` group (attachments, split, threads, pst)."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import bash_path, needs

from carrel.cli import cli
from carrel.commands.mail import attachments_of, split_mbox, threads_of
from carrel.core import mail
from carrel.core.filetypes import FileType, detect, detect_or_die
from carrel.core.output import CarrelInputError
from carrel.core.textextract import extract_text


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0):
    return json.loads(run("--json", *args, expect=expect).output)


# ------------------------------------------------------------------ detection


def test_fixtures_detect_by_extension(fixtures: Path):
    assert detect(fixtures / "sample.eml") is FileType.EML
    assert detect(fixtures / "thread.mbox") is FileType.MBOX
    assert FileType.EML.is_mail and FileType.MBOX.is_mail and not FileType.TXT.is_mail
    assert not FileType.EML.is_text  # not a regex-redaction target


def test_sniff_only_for_unmapped_extensions(fixtures: Path, tmp_path: Path):
    """D-012: a mapped extension wins; an extension-less export is sniffed by shape."""
    as_txt = tmp_path / "message.txt"
    as_txt.write_bytes((fixtures / "sample.eml").read_bytes())
    assert detect(as_txt) is FileType.TXT
    bare = tmp_path / "export"
    bare.write_bytes((fixtures / "sample.eml").read_bytes())
    assert detect(bare) is FileType.EML
    bare_box = tmp_path / "INBOX"
    bare_box.write_bytes((fixtures / "thread.mbox").read_bytes())
    assert detect(bare_box) is FileType.MBOX
    prose = tmp_path / "notes"
    prose.write_text("From: my point of view\nthis is not mail\n", encoding="utf-8")
    assert detect(prose) is FileType.UNKNOWN  # one header-ish line is not a message


def test_looks_like_helpers():
    assert mail.looks_like_eml(b"From: a@b.co\nSubject: hi\n\nbody")
    assert mail.looks_like_eml(b"Received: from x\n\tby y\nDate: now\nSubject: s\n\n")
    assert not mail.looks_like_eml(b"From: only one field\n\nbody")
    assert not mail.looks_like_eml(b"plain text\nFrom: a@b.co\nSubject: s\n")
    assert mail.looks_like_mbox(
        b"From a@b.co Mon Jun 14 09:00:00 2021\nFrom: a@b.co\nSubject: s\n\n"
    )
    assert not mail.looks_like_mbox(b"From: a@b.co\nSubject: s\n\n")


# ------------------------------------------------------------ extract / parse


def test_extract_text_eml(fixtures: Path):
    text = extract_text(fixtures / "sample.eml")
    assert text.startswith("From: Acme Billing <billing@acme.example>\n")
    assert "Date: 2021-06-15T12:00:00+00:00" in text
    assert "Subject: Invoice INV-2026-0042 from Acme" in text
    assert "\n\nHello,\n" in text and "melodious ledger" in text
    assert "attachment: remittance.csv (text/csv, 37 bytes)" in text
    assert "<html>" not in text  # the plain part is preferred


def test_extract_text_mbox(fixtures: Path):
    text = extract_text(fixtures / "thread.mbox")
    assert text.count("# ") == 3 and "# Re: Quarterly close" in text
    assert "quixotic ledger" in text and "Sandwiches" in text


def test_html_only_message_flattens_html(tmp_path: Path):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "x@example.org"
    msg["Subject"] = "html only"
    msg.set_content("<p>Hello <b>there</b></p>", subtype="html")
    p = tmp_path / "h.eml"
    p.write_bytes(msg.as_bytes())
    assert "Hello there" in mail.body_text(mail.parse_eml(p))
    assert mail.body_html(mail.parse_eml(p)) is not None
    assert mail.summary(mail.parse_eml(p))["date"] is None  # no Date header → None, never a crash


def test_summary_and_threading(fixtures: Path):
    info = mail.summary(mail.parse_eml(fixtures / "sample.eml"))
    assert info["from"] == ["Acme Billing <billing@acme.example>"]
    assert info["message_id"] == "<inv-0042@acme.example>" and info["in_reply_to"] is None
    assert info["has_html"] is True and info["parts"] == 5
    msgs = [
        {**mail.summary(m), "where": f"thread.mbox#{i}"}
        for i, m in enumerate(mail.iter_mbox(fixtures / "thread.mbox"), 1)
    ]
    groups = mail.thread_groups(msgs)
    assert [(g["root_subject"], len(g["messages"])) for g in groups] == [
        ("Quarterly close", 2),
        ("Lunch", 1),
    ]
    assert [m["depth"] for m in groups[0]["messages"]] == [1, 2]


def test_names():
    assert mail.safe_filename("../../etc/passwd") == "passwd"
    assert mail.safe_filename("Q2 report (final).pdf") == "Q2_report_final_.pdf"
    assert mail.safe_filename("...") == "attachment"
    assert mail.slug("Re: Quarterly close / Q2!!") == "re-quarterly-close-q2"
    assert mail.slug("", 10) == "message"


# ---------------------------------------------------------- inspect / convert


def test_inspect_eml_and_mbox(fixtures: Path):
    eml = run_json("inspect", str(fixtures / "sample.eml"))
    assert eml["type"] == "eml" and eml["mime"] == "message/rfc822"
    assert eml["detail"]["subject"] == "Invoice INV-2026-0042 from Acme"
    assert eml["detail"]["attachments"] == [
        {"filename": "remittance.csv", "content_type": "text/csv", "size": 37}
    ]
    box = run_json("inspect", str(fixtures / "thread.mbox"))
    assert box["detail"]["messages"] == 3
    assert box["detail"]["first_date"] == "2021-06-14T09:00:00+00:00"
    assert box["detail"]["senders"][0]["messages"] == 1
    human = run("inspect", str(fixtures / "thread.mbox")).output
    assert "messages       3" in human


def test_convert_eml_to_md_txt_html(fixtures: Path, tmp_path: Path):
    src = fixtures / "sample.eml"
    md = run_json("convert", str(src), "--to", "md", "--out-dir", str(tmp_path))[0]
    assert md["ok"] and md["via"] == "email (stdlib)"
    text = Path(md["dest"]).read_text(encoding="utf-8")
    assert text.startswith("# Invoice INV-2026-0042 from Acme\n")
    assert "| From | Acme Billing <billing@acme.example> |" in text
    assert "- `remittance.csv` (text/csv, 37 bytes)" in text
    txt = run_json("convert", str(src), "--to", "txt", "--out-dir", str(tmp_path))[0]
    assert Path(txt["dest"]).read_text(encoding="utf-8") == extract_text(src)
    html = run_json("convert", str(src), "--to", "html", "--out-dir", str(tmp_path))[0]
    assert "<b>INV-2026-0042</b>" in Path(html["dest"]).read_text(encoding="utf-8")
    box = run_json(
        "convert", str(fixtures / "thread.mbox"), "--to", "md", "--out-dir", str(tmp_path)
    )[0]
    body = Path(box["dest"]).read_text(encoding="utf-8")
    assert body.startswith("# thread.mbox\n") and body.count("\n## ") == 3
    # unsupported pairs stay exit 4 and list the real targets
    res = run("convert", str(src), "--to", "csv", "--out-dir", str(tmp_path), expect=4)
    assert "html, md, pdf, txt" in res.stderr
    res = run(
        "convert",
        str(fixtures / "thread.mbox"),
        "--to",
        "pdf",
        "--out-dir",
        str(tmp_path),
        expect=4,
    )
    assert "md, txt" in res.stderr


@needs("weasyprint")
def test_convert_eml_to_pdf(fixtures: Path, tmp_path: Path):
    rec = run_json(
        "convert", str(fixtures / "sample.eml"), "--to", "pdf", "--out-dir", str(tmp_path)
    )[0]
    assert Path(rec["dest"]).read_bytes().startswith(b"%PDF")
    assert "weasyprint" in rec["via"]


def test_html_only_message_to_html_wraps_pre(tmp_path: Path):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "plain <only>"
    msg.set_content("just text")
    src = tmp_path / "p.eml"
    src.write_bytes(msg.as_bytes())
    rec = run_json("convert", str(src), "--to", "html", "--out-dir", str(tmp_path))[0]
    out = Path(rec["dest"]).read_text(encoding="utf-8")
    assert "<pre>" in out and "just text" in out and "plain &lt;only&gt;" in out


def test_organize_files_mail_into_mail_dir(fixtures: Path, tmp_path: Path):
    (tmp_path / "a.eml").write_bytes((fixtures / "sample.eml").read_bytes())
    (tmp_path / "b.mbox").write_bytes((fixtures / "thread.mbox").read_bytes())
    plan = run_json("organize", str(tmp_path))
    assert {Path(e["dest"]).parent.name for e in plan if e["action"] == "move"} == {"mail"}


def test_diff_treats_mail_as_text(fixtures: Path, tmp_path: Path):
    a = fixtures / "sample.eml"
    b = tmp_path / "b.eml"
    b.write_bytes(a.read_bytes().replace(b"melodious", b"raucous"))
    res = run("--json", "diff", str(a), str(b), expect=1)
    payload = json.loads(res.output)
    assert payload["identical"] is False and payload["mode"] == "text"
    assert "-Sentinel: melodious ledger." in payload["diff"]


def test_index_search_and_refs_reach_mail(fixtures: Path, tmp_path: Path):
    (tmp_path / "inv.eml").write_bytes((fixtures / "sample.eml").read_bytes())
    (tmp_path / "box.mbox").write_bytes((fixtures / "thread.mbox").read_bytes())
    summary = run_json("--root", str(tmp_path), "index")
    assert summary["indexed"] == 2 and summary["errors"] == []
    assert [h["path"] for h in run_json("--root", str(tmp_path), "search", "melodious")] == [
        "inv.eml"
    ]
    assert [
        h["path"] for h in run_json("--root", str(tmp_path), "search", "quixotic", "--type", "mbox")
    ] == ["box.mbox"]
    groups = run_json("refs", str(tmp_path), "--link")
    inv = next(g for g in groups if g["kind"] == "invoice")
    assert inv["value"] == "INV-2026-0042" and len(inv["files"]) == 2  # the eml and the mbox reply
    iban = next(
        r for r in run_json("refs", str(tmp_path / "inv.eml"))[0]["refs"] if r["kind"] == "iban"
    )
    assert iban["value"] == "GB82WEST12345698765432" and iban["valid"] is True


# ------------------------------------------------------------ mail attachments


def test_attachments_cli_and_library(fixtures: Path, tmp_path: Path):
    out = tmp_path / "att"
    records = run_json("mail", "attachments", str(fixtures / "sample.eml"), "--out-dir", str(out))
    (rec,) = records
    assert rec["message"] == str(fixtures / "sample.eml")
    (a,) = rec["attachments"]
    assert a["filename"] == "remittance.csv" and a["path"] == str(out / "remittance.csv")
    data = Path(a["path"]).read_bytes()
    assert data == b"invoice,amount\nINV-2026-0042,1234.56\n"
    assert a["sha256"] == hashlib.sha256(data).hexdigest() and a["size"] == 37
    # second run never overwrites: suffixed copy
    again = attachments_of([fixtures / "sample.eml"], out)
    assert again[0]["attachments"][0]["path"] == str(out / "remittance-1.csv")
    forced = attachments_of([fixtures / "sample.eml"], out, force=True)
    assert forced[0]["attachments"][0]["path"] == str(out / "remittance.csv")
    human = run("mail", "attachments", str(fixtures / "sample.eml"), "--out-dir", str(out)).output
    assert "remittance.csv ->" in human and "attachment(s) written" in human


def test_attachments_mbox_and_fail_empty(fixtures: Path, tmp_path: Path):
    records = run_json(
        "mail", "attachments", str(fixtures / "thread.mbox"), "--out-dir", str(tmp_path / "o")
    )
    assert [r["message"] for r in records] == [f"{fixtures / 'thread.mbox'}#{n}" for n in (1, 2, 3)]
    assert all(r["attachments"] == [] for r in records)
    run(
        "mail",
        "attachments",
        str(fixtures / "thread.mbox"),
        "--out-dir",
        str(tmp_path / "o"),
        "--fail-empty",
        expect=5,
    )
    res = run(
        "mail",
        "attachments",
        str(fixtures / "sample.txt"),
        "--out-dir",
        str(tmp_path / "o"),
        expect=4,
    )
    assert "not an email file" in res.stderr
    run(
        "mail",
        "attachments",
        str(tmp_path / "ghost.eml"),
        "--out-dir",
        str(tmp_path / "o"),
        expect=4,
    )


def test_attachment_names_are_sanitised(tmp_path: Path):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "tricky"
    msg.set_content("see attached")
    msg.add_attachment(
        b"x", maintype="application", subtype="octet-stream", filename="../../evil.bin"
    )
    src = tmp_path / "t.eml"
    src.write_bytes(msg.as_bytes())
    (rec,) = attachments_of([src], tmp_path / "out")
    assert rec["attachments"][0]["path"] == str(tmp_path / "out" / "evil.bin")


# ------------------------------------------------------------------ mail split


def test_split_mbox(fixtures: Path, tmp_path: Path):
    out = tmp_path / "split"
    rows = run_json("mail", "split", str(fixtures / "thread.mbox"), "--out-dir", str(out))
    assert [Path(r["path"]).name for r in rows] == [
        "1_2021-06-14_quarterly-close.eml",
        "2_2021-06-14_re-quarterly-close.eml",
        "3_2021-06-15_lunch.eml",
    ]
    assert rows[1]["message_id"] == "<close-2@example.org>" and rows[1]["n"] == 2
    for r in rows:
        assert detect_or_die(Path(r["path"])) is FileType.EML
    assert "quixotic ledger" in extract_text(Path(rows[0]["path"]))
    res = run("mail", "split", str(fixtures / "thread.mbox"), "--out-dir", str(out), expect=1)
    assert "--force" in res.stderr
    run("mail", "split", str(fixtures / "thread.mbox"), "--out-dir", str(out), "--force")
    custom = split_mbox(fixtures / "thread.mbox", tmp_path / "c", template="{id}.eml")
    assert Path(custom[0]["path"]).name == "close-1-example-org.eml"
    with pytest.raises(CarrelInputError, match=r"must end with \.eml"):
        split_mbox(fixtures / "thread.mbox", tmp_path / "d", template="{n}.txt")
    with pytest.raises(CarrelInputError, match="not an mbox"):
        split_mbox(fixtures / "sample.eml", tmp_path / "d")
    assert (
        "3 message(s) written"
        in run(
            "mail", "split", str(fixtures / "thread.mbox"), "--out-dir", str(tmp_path / "h")
        ).output
    )


# ---------------------------------------------------------------- mail threads


def test_threads_cli(fixtures: Path, tmp_path: Path):
    (tmp_path / "box.mbox").write_bytes((fixtures / "thread.mbox").read_bytes())
    (tmp_path / "inv.eml").write_bytes((fixtures / "sample.eml").read_bytes())
    (tmp_path / "noise.txt").write_text("not mail", encoding="utf-8")
    groups = run_json("mail", "threads", str(tmp_path))
    assert [(g["root_subject"], len(g["messages"])) for g in groups] == [
        ("Quarterly close", 2),
        ("Lunch", 1),
        ("Invoice INV-2026-0042 from Acme", 1),
    ]
    assert groups[0]["messages"][1]["where"].endswith("box.mbox#2")
    human = run("mail", "threads", str(tmp_path / "box.mbox")).output
    assert "Quarterly close  (2 message(s))" in human
    assert "    2021-06-14T10:30:00+00:00" in human  # depth-2 reply is indented twice
    run("mail", "threads", str(tmp_path / "noise.txt"), expect=4)  # explicit non-mail file
    run("mail", "threads", str(tmp_path / "ghost"), expect=4)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert threads_of([empty]) == []
    assert "no messages" in run("mail", "threads", str(empty)).stderr


def test_pst_missing_readpst_exits_3(tmp_path: Path, monkeypatch):
    src = tmp_path / "export.pst"
    src.write_bytes(b"!BDN" + b"\x00" * 64)
    monkeypatch.setenv("CARREL_BIN_READPST", str(tmp_path / "nowhere"))
    res = run("mail", "pst", str(src), "--out-dir", str(tmp_path / "out"), expect=3)
    assert "readpst" in res.stderr and "pst-utils" in res.stderr
    run("mail", "pst", str(tmp_path / "ghost.pst"), "--out-dir", str(tmp_path / "out"), expect=4)
    not_pst = tmp_path / "x.txt"
    not_pst.write_text("x", encoding="utf-8")
    res = run("mail", "pst", str(not_pst), "--out-dir", str(tmp_path / "out"), expect=4)
    assert "not an Outlook export" in res.stderr


@pytest.mark.skipif(bash_path() is None, reason="bash not installed")
def test_pst_plumbing_with_fake_readpst(tmp_path: Path, monkeypatch, fixtures: Path):
    """A stand-in readpst proves the argument plumbing and the file count."""
    fake = tmp_path / "readpst.sh"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -V) echo "readpst fake 0.6"; exit 0;; *) shift;; esac; done\n'
        'mkdir -p "$out/Inbox" && cp "$FIXTURE" "$out/Inbox/1.eml" && echo done\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    if os.name == "nt":
        pytest.skip("shebang exec is not available on Windows")
    monkeypatch.setenv("CARREL_BIN_READPST", str(fake))
    monkeypatch.setenv("FIXTURE", str(fixtures / "sample.eml"))
    src = tmp_path / "export.pst"
    src.write_bytes(b"!BDN")
    out = run_json("mail", "pst", str(src), "--out-dir", str(tmp_path / "out"))
    assert out == {
        "src": str(src),
        "out_dir": str(tmp_path / "out"),
        "format": "eml",
        "files": 1,
        "via": "readpst",
    }
    assert detect(tmp_path / "out" / "Inbox" / "1.eml") is FileType.EML
    human = run(
        "mail", "pst", str(src), "--out-dir", str(tmp_path / "out2"), "--format", "mbox"
    ).output
    assert "1 file(s) [readpst]" in human


@needs("readpst")
def test_readpst_present_reports_version():
    from carrel.core import adapters

    assert adapters.version_of("readpst")


# ------------------------------------------------------------------- plumbing


@pytest.mark.parametrize("sub", [[], ["attachments"], ["split"], ["threads"], ["pst"]])
def test_help_and_json_flag(sub: list[str]):
    result = run("mail", *sub, "--help")
    assert "Usage:" in result.output and "--json" in result.output


def test_doctor_lists_mail_and_readpst():
    report = run_json("doctor")
    assert any(c["command"] == "mail" for c in report["commands"])
    assert any(a["name"] == "readpst" for a in report["adapters"])
