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
    assert mail.safe_filename("Q2 report (final).pdf") == "Q2_report_final.pdf"
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
    assert "readpst" in res.stderr and "install:" in res.stderr
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


# ---------------------------------------------- regressions from the PR B review

from email.message import EmailMessage  # noqa: E402


def _msg(**headers: str) -> EmailMessage:
    msg = EmailMessage()
    for key, value in headers.items():
        msg[key.replace("_", "-")] = value
    msg.set_content("body\n")
    return msg


def test_hostile_headers_never_abort_a_run(tmp_path: Path):
    """A nonsense Date or an address header with an embedded newline is data, not a crash."""
    overflow = tmp_path / "overflow.eml"
    overflow.write_bytes(
        b"From: a@example.org\nSubject: s\nDate: Mon, 14 Jun 99999999999 09:00:00 +0000\n\nbody\n"
    )
    msg = mail.parse_eml(overflow)
    assert mail.header_date(msg) is None and mail.header_datetime(msg) is None
    assert "Subject: s" in mail.message_text(msg)

    crlf = tmp_path / "crlf.eml"
    crlf.write_bytes(
        b"From: =?utf-8?q?Alice=0ASmith?= <alice@example.org>\nSubject: s\nDate: "
        b"Mon, 14 Jun 2021 09:00:00 +0000\n\nbody\n"
    )
    msg = mail.parse_eml(crlf)
    assert mail.addresses(msg, "From") == []  # degrades, never raises
    assert mail.summary(msg)["subject"] == "s"

    # a whole desk indexes cleanly with both of them in it
    (tmp_path / "good.txt").write_text("plain words\n", encoding="utf-8")
    summary = run_json("--root", str(tmp_path), "index")
    assert summary["errors"] == [] and summary["indexed"] == 3
    assert run_json("--root", str(tmp_path), "search", "plain") != []
    assert run("mail", "threads", str(tmp_path)).exit_code == 0


def test_long_reply_chain_does_not_recurse(tmp_path: Path):
    messages = [
        {
            "where": f"m{i}",
            "message_id": f"<m{i}@x>",
            "in_reply_to": f"<m{i - 1}@x>" if i else None,
            "references": [],
            "subject": "chain",
            "date": f"2021-06-14T{i % 24:02d}:00:00+00:00",
        }
        for i in range(3000)
    ]
    (group,) = mail.thread_groups(messages)
    assert len(group["messages"]) == 3000
    assert group["messages"][0]["depth"] == 1


def test_threads_order_by_instant_not_by_text(tmp_path: Path):
    """Two timezones: the earlier instant is the root even though its text sorts later."""
    root = tmp_path / "root.eml"
    root.write_bytes(
        b"From: a@example.org\nTo: b@example.org\nSubject: Budget\n"
        b"Message-ID: <root@x>\nDate: Tue, 15 Jun 2021 11:00:00 +0200\n\nfirst\n"
    )
    reply = tmp_path / "reply.eml"
    reply.write_bytes(
        b"From: b@example.org\nTo: a@example.org\nSubject: Re: Budget\n"
        b"Message-ID: <reply@x>\nIn-Reply-To: <root@x>\n"
        b"Date: Tue, 15 Jun 2021 09:30:00 +0000\n\nsecond\n"
    )
    (group,) = threads_of([tmp_path])
    assert group["root_subject"] == "Budget"
    assert [m["depth"] for m in group["messages"]] == [1, 2]


def test_unknown_charset_keeps_the_body(tmp_path: Path):
    src = tmp_path / "odd.eml"
    src.write_bytes(
        b"From: a@example.org\nSubject: s\nMIME-Version: 1.0\n"
        b'Content-Type: text/plain; charset="x-unknown-charset"\n\nthe sentinel body\n'
    )
    assert "the sentinel body" in mail.body_text(mail.parse_eml(src))
    assert "the sentinel body" in extract_text(src)


def test_nested_and_forwarded_attachments_are_found(tmp_path: Path):
    inner = EmailMessage()
    inner["From"] = "a@example.org"
    inner["Subject"] = "inner"
    inner.set_content("inner body\n")
    inner.add_attachment(
        b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="inner.pdf"
    )
    outer = EmailMessage()
    outer["From"] = "b@example.org"
    outer["Subject"] = "Fwd: inner"
    outer.set_content("see attached\n")
    outer.add_attachment(inner, filename="inner.eml")
    src = tmp_path / "fwd.eml"
    src.write_bytes(outer.as_bytes())

    found = mail.attachments(mail.parse_eml(src))
    assert [a["filename"] for a in found] == ["inner.pdf"]
    assert found[0]["content_type"] == "application/pdf" and found[0]["size"] == 13
    records = run_json("mail", "attachments", str(src), "--out-dir", str(tmp_path / "out"))
    assert [a["filename"] for a in records[0]["attachments"]] == ["inner.pdf"]
    assert (tmp_path / "out" / "inner.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_attachments_never_clobber_within_one_run(tmp_path: Path):
    box = tmp_path / "two.mbox"
    parts = []
    for n, payload in enumerate((b"first", b"second-longer"), 1):
        msg = EmailMessage()
        msg["From"] = f"a{n}@example.org"
        msg["Subject"] = f"m{n}"
        msg["Date"] = "Mon, 14 Jun 2021 09:00:00 +0000"
        msg.set_content("body\n")
        msg.add_attachment(payload, maintype="image", subtype="png", filename="image001.png")
        parts.append(b"From a@example.org Mon Jun 14 09:00:00 2021\n" + msg.as_bytes() + b"\n")
    box.write_bytes(b"".join(parts))
    out = tmp_path / "att"
    for force in (False, True):
        target = out if not force else tmp_path / "att-forced"
        args = ["mail", "attachments", str(box), "--out-dir", str(target)]
        records = run_json(*(args + (["--force"] if force else [])))
        paths = [a["path"] for r in records for a in r["attachments"]]
        assert len(set(paths)) == 2, f"force={force}: {paths}"
        assert all(Path(x).is_file() for x in paths)
        assert {Path(x).read_bytes() for x in paths} == {b"first", b"second-longer"}


def test_long_attachment_name_is_capped(tmp_path: Path):
    msg = EmailMessage()
    msg["From"] = "a@example.org"
    msg["Subject"] = "big name"
    msg.set_content("body\n")
    msg.add_attachment(
        b"x", maintype="application", subtype="octet-stream", filename="n" * 300 + ".pdf"
    )
    src = tmp_path / "long.eml"
    src.write_bytes(msg.as_bytes())
    (rec,) = run_json("mail", "attachments", str(src), "--out-dir", str(tmp_path / "out"))
    written = Path(rec["attachments"][0]["path"])
    assert written.is_file() and len(written.name) <= 105 and written.suffix == ".pdf"
    assert mail.safe_filename("CON") == "CON_"
    assert mail.safe_filename("nul.txt") == "nul_.txt"
    assert mail.safe_filename("COM1.pdf") == "COM1_.pdf"


def test_split_plans_names_before_writing_and_keeps_stored_bytes(tmp_path: Path, fixtures: Path):
    out = tmp_path / "split"
    rows = run_json(
        "mail",
        "split",
        str(fixtures / "thread.mbox"),
        "--out-dir",
        str(out),
        "--template",
        "{date}.eml",
    )
    names = sorted(Path(r["path"]).name for r in rows)
    assert names == ["2021-06-14-1.eml", "2021-06-14.eml", "2021-06-15.eml"]
    assert len({r["path"] for r in rows}) == 3
    # the stored bytes survive: headers are not refolded or re-encoded
    raw = list(mail.iter_mbox_raw(fixtures / "thread.mbox"))
    written = [Path(r["path"]).read_bytes() for r in sorted(rows, key=lambda r: r["n"])]
    assert written == raw

    box = tmp_path / "utf8.mbox"
    msg = EmailMessage()
    msg["From"] = "a@example.org"
    msg["Subject"] = "Zürich"
    msg["Date"] = "Mon, 14 Jun 2021 09:00:00 +0000"
    msg["DKIM-Signature"] = "v=1; a=rsa-sha256; b=AAAABBBBCCCCDDDD"
    msg.set_content("body\n")
    stored = b"From a@example.org Mon Jun 14 09:00:00 2021\n" + msg.as_bytes() + b"\n"
    box.write_bytes(stored)
    (row,) = split_mbox(box, tmp_path / "one")
    assert b"b=AAAABBBBCCCCDDDD" in Path(row["path"]).read_bytes()


def test_split_refuses_a_pre_existing_name_before_writing_anything(tmp_path: Path, fixtures: Path):
    out = tmp_path / "split"
    out.mkdir()
    (out / "1_2021-06-14_quarterly-close.eml").write_text("older\n", encoding="utf-8")
    result = run("mail", "split", str(fixtures / "thread.mbox"), "--out-dir", str(out), expect=1)
    assert "--force" in result.stderr
    assert sorted(p.name for p in out.iterdir()) == ["1_2021-06-14_quarterly-close.eml"]
    assert (out / "1_2021-06-14_quarterly-close.eml").read_text(encoding="utf-8") == "older\n"
    with pytest.raises(CarrelInputError, match="not a path"):
        split_mbox(fixtures / "thread.mbox", out, template="{date}/{n}.eml")


def test_mbox_without_a_separator_is_an_error(tmp_path: Path, fixtures: Path):
    fake = tmp_path / "notreally.mbox"
    fake.write_text("From: a@example.org\nSubject: s\n\nbody\n", encoding="utf-8")
    with pytest.raises(CarrelInputError, match="no mbox `From ` separator"):
        list(mail.iter_mbox(fake))
    assert run("inspect", str(fake)).exit_code == 0  # inspect degrades to an error field


def test_mailbox_named_eml_is_detected_by_its_bytes(tmp_path: Path, fixtures: Path):
    disguised = tmp_path / "inbox.eml"
    disguised.write_bytes((fixtures / "thread.mbox").read_bytes())
    assert detect(disguised) is FileType.MBOX
    text = extract_text(disguised)
    assert text.count("# ") == 3  # all three messages, not just the first


def test_mboxrd_from_quoting_is_undone(tmp_path: Path):
    body = "line one\n>From the desk of nobody\nline three\n"
    msg = EmailMessage()
    msg["From"] = "a@example.org"
    msg["Subject"] = "quoting"
    msg["Date"] = "Mon, 14 Jun 2021 09:00:00 +0000"
    msg.set_content(body)
    box = tmp_path / "q.mbox"
    box.write_bytes(b"From a@example.org Mon Jun 14 09:00:00 2021\n" + msg.as_bytes() + b"\n")
    text = extract_text(box)
    assert "\nFrom the desk of nobody" in text and ">From the desk" not in text


def test_long_header_block_still_detects_without_an_extension(tmp_path: Path):
    padding = b"".join(
        f"Received: from relay{i}.example.org by mx.example.org\n".encode() for i in range(80)
    )
    bare = tmp_path / "1704103200.M1P2.host:2,S"  # Maildir: the "suffix" is delivery flags
    bare.write_bytes(
        b"From: a@example.org\n"
        + padding
        + b"Subject: s\nDate: Mon, 14 Jun 2021 09:00:00 +0000\n\nbody\n"
    )
    assert len(padding) > 2048
    assert detect(bare) is FileType.EML


@pytest.mark.parametrize("name", ["0001-fix-widget.patch", "series.diff", "notes.bak", "mail.log"])
def test_named_text_files_are_never_reclassified_as_mail(tmp_path: Path, name: str):
    """D-012: the shape sniff is for extension-less files only."""
    p = tmp_path / name
    p.write_text(
        "From 9d4e1e23bd5b727046a9e3b4b7db57bd8d6ee684 Mon Sep 17 00:00:00 2001\n"
        "From: A Dev <dev@example.org>\nDate: Mon, 14 Jun 2021 09:00:00 +0000\n"
        "Subject: [PATCH] fix the widget\n\n---\n diff --git a/x b/x\n",
        encoding="utf-8",
    )
    assert detect(p) is not FileType.MBOX
    assert detect(p) is not FileType.EML


def test_eml_to_html_declares_utf8_and_pdf_never_fetches(tmp_path: Path):
    src = tmp_path / "styled.eml"
    msg = EmailMessage()
    msg["From"] = "a@example.org"
    msg["Subject"] = "Café crème"
    msg["Date"] = "Mon, 14 Jun 2021 09:00:00 +0000"
    msg.set_content("Café crème — März\n")
    msg.add_alternative(
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
        "</head><body><p>Café crème — März</p>"
        '<img src="http://tracker.example.org/pixel.gif">'
        '<link rel="attachment" href="file:///etc/hostname"></body></html>',
        subtype="html",
    )
    src.write_bytes(msg.as_bytes())

    (rec,) = run_json("convert", str(src), "--to", "html", "--out-dir", str(tmp_path))
    html = Path(rec["dest"]).read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert "windows-1252" not in html  # the stale declaration is gone
    assert "Café crème" in html

    from carrel.commands.convert import _eml_text_document

    rendered = _eml_text_document(src)
    assert "tracker.example.org" not in rendered  # nothing the sender referenced survives
    assert "file:///etc/hostname" not in rendered
    assert "<img" not in rendered and "<link" not in rendered
    assert "Café crème" in rendered


@needs("weasyprint")
def test_eml_to_pdf_output_has_no_external_references(tmp_path: Path):
    src = tmp_path / "tracked.eml"
    msg = EmailMessage()
    msg["From"] = "a@example.org"
    msg["Subject"] = "tracked"
    msg.set_content("plain body\n")
    msg.add_alternative(
        '<html><body><img src="http://127.0.0.1:9/pixel.gif">hi</body></html>', subtype="html"
    )
    src.write_bytes(msg.as_bytes())
    (rec,) = run_json("convert", str(src), "--to", "pdf", "--out-dir", str(tmp_path))
    from pypdf import PdfReader

    reader = PdfReader(rec["dest"])
    assert not reader.attachments  # no local file was pulled in
    assert "plain body" in "".join(page.extract_text() for page in reader.pages)


@pytest.mark.skipif(bash_path() is None, reason="bash not installed")
def test_pst_uses_the_documented_readpst_flags(tmp_path: Path, monkeypatch, fixtures: Path):
    fake = tmp_path / "readpst.sh"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$ARGV_LOG"\n'
        'out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -V) echo fake; exit 0;; *) shift;; esac; done\n'
        'mkdir -p "$out/Inbox" && cp "$FIXTURE" "$out/Inbox/1.eml"\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    if os.name == "nt":
        pytest.skip("shebang exec is not available on Windows")
    log = tmp_path / "argv.log"
    monkeypatch.setenv("CARREL_BIN_READPST", str(fake))
    monkeypatch.setenv("FIXTURE", str(fixtures / "sample.eml"))
    monkeypatch.setenv("ARGV_LOG", str(log))
    src = tmp_path / "export.pst"
    src.write_bytes(b"!BDN")
    run_json("mail", "pst", str(src), "--out-dir", str(tmp_path / "eml"))
    run_json("mail", "pst", str(src), "--out-dir", str(tmp_path / "mbox"), "--format", "mbox")
    lines = log.read_text(encoding="utf-8").splitlines()
    assert " -e " in f" {lines[0]} "  # one .eml per message
    assert " -r " in f" {lines[1]} "  # one mbox file per folder, never -M (MH format)
    assert "-M" not in lines[1]


def test_pst_missing_binary_creates_no_output_directory(tmp_path: Path, monkeypatch):
    src = tmp_path / "export.pst"
    src.write_bytes(b"!BDN")
    out = tmp_path / "should-not-exist"
    monkeypatch.setenv("CARREL_BIN_READPST", str(tmp_path / "nowhere"))
    run("mail", "pst", str(src), "--out-dir", str(out), expect=3)
    assert not out.exists()


def test_mail_threads_honours_ancestor_gitignore(tmp_path: Path, fixtures: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    sub = repo / "sub"
    (sub / "build").mkdir(parents=True)
    (sub / "build" / "ignored.eml").write_bytes((fixtures / "sample.eml").read_bytes())
    (sub / "kept.eml").write_bytes((fixtures / "sample.eml").read_bytes())
    groups = run_json("--root", str(repo), "mail", "threads", str(sub))
    wheres = [m["where"] for g in groups for m in g["messages"]]
    assert all("build" not in w for w in wheres) and any("kept.eml" in w for w in wheres)
