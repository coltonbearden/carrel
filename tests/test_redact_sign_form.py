"""Tests for `carrel redact`, `carrel sign` and `carrel form` (spec 10).

Fixture-backed where the planted strings live (sample.txt, text+image.pdf,
form.pdf); everything else is synthesized in tmp_path. Binary-dependent tests
skip via conftest.needs(). gpg tests build an ephemeral key inside a tmp
GNUPGHOME and skip if key generation fails — the user's keyring is never used.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs
from PIL import Image
from pypdf import PdfReader

from carrel.cli import cli
from carrel.core import adapters

PLANTED_EMAILS = ("jane.doe@example.com", "j.public+desk@test.example.org")
PLANTED_SSN = "123-45-6789"
PDF_SENTINEL = "palimpsest harbor"

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0) -> dict:
    result = run("--json", *args, expect=expect)
    return json.loads(result.output)


def pdf_text(pdf: Path) -> str:
    proc = adapters.run("pdftotext", "-layout", str(pdf), "-")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def render_page(pdf: Path, page: int, out_dir: Path, tag: str) -> Image.Image:
    prefix = out_dir / f"render-{tag}"
    proc = adapters.run(
        "pdftoppm", "-r", "72", "-png", "-f", str(page), "-l", str(page), str(pdf), str(prefix)
    )
    assert proc.returncode == 0, proc.stderr
    (png,) = sorted(out_dir.glob(f"render-{tag}-*.png"))
    return Image.open(png).convert("RGB")


# ======================================================================= redact


def test_redact_txt_builtin_email_ssn(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    out = tmp_path / "clean.txt"
    record = run_json("redact", str(src), "--builtin", "email,ssn", "-o", str(out))
    text = out.read_text()
    for email in PLANTED_EMAILS:
        assert email not in text
    assert PLANTED_SSN not in text
    assert record["matches"]["email"] == 2
    assert record["matches"]["ssn"] == 1
    assert record["total"] == 3
    assert "quixotic zephyr" in text  # non-matching content survives


def test_redact_txt_builtin_phone(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    out = tmp_path / "clean.txt"
    record = run_json("redact", str(src), "--builtin", "phone", "-o", str(out))
    assert record["matches"]["phone"] == 1
    assert "(555) 867-5309" not in out.read_text()


def test_redact_json_stays_parseable(tmp_path: Path):
    src = tmp_path / "people.json"
    src.write_text(
        json.dumps(
            {
                "people": [
                    {"name": "Jane", "email": "jane.doe@example.com", "ssn": "123-45-6789"},
                    {"name": "Joe", "email": "j.public@test.example.org", "note": "no secrets"},
                ],
            },
            indent=2,
        )
    )
    out = tmp_path / "people.redacted.json"
    record = run_json("redact", str(src), "--builtin", "email,ssn", "-o", str(out))
    data = json.loads(out.read_text())  # acceptance: output re-parses
    assert record["matches"] == {"email": 2, "ssn": 1}
    assert data["people"][0]["email"] == "█"
    assert data["people"][0]["ssn"] == "█"
    assert data["people"][1]["note"] == "no secrets"


def test_redact_xml_stays_parseable(tmp_path: Path):
    src = tmp_path / "contacts.xml"
    src.write_text('<?xml version="1.0"?>\n<c><e>jane.doe@example.com</e></c>\n')
    out = tmp_path / "out.xml"
    record = run_json("redact", str(src), "--builtin", "email", "-o", str(out))
    root = ET.fromstring(out.read_text())
    assert record["matches"]["email"] == 1
    assert root.find("e").text == "█"


def test_redact_custom_pattern_and_replacement(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    out = tmp_path / "out.txt"
    record = run_json(
        "redact", str(src), "--pattern", "zephyr", "--replacement", "[REDACTED]", "-o", str(out)
    )
    text = out.read_text()
    assert record["matches"]["zephyr"] == 2
    assert "zephyr" not in text
    assert text.count("[REDACTED]") == 2


def test_redact_cc_luhn_checked(tmp_path: Path):
    src = tmp_path / "cards.txt"
    src.write_text(
        "good: 4111 1111 1111 1111\nbad luhn: 4111 1111 1111 1112\norder number 1234567 stays\n"
    )
    out = tmp_path / "out.txt"
    record = run_json("redact", str(src), "--builtin", "cc", "-o", str(out))
    text = out.read_text()
    assert record["matches"]["cc"] == 1
    assert "4111 1111 1111 1111" not in text
    assert "4111 1111 1111 1112" in text  # fails Luhn → kept
    assert "1234567" in text  # too short → not even a candidate


def test_redact_ipv4_builtin(tmp_path: Path):
    src = tmp_path / "log.txt"
    src.write_text("client 192.168.1.100 connected; version 1.2 unaffected\n")
    out = tmp_path / "out.txt"
    record = run_json("redact", str(src), "--builtin", "ipv4", "-o", str(out))
    assert record["matches"]["ipv4"] == 1
    text = out.read_text()
    assert "192.168.1.100" not in text
    assert "version 1.2" in text


def test_redact_zero_matches_writes_output_exit_0(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    out = tmp_path / "out.txt"
    record = run_json("redact", str(src), "--pattern", "nonexistentxyzzy", "-o", str(out))
    assert record["total"] == 0
    assert out.read_text() == src.read_text()


def test_redact_zero_matches_fail_empty_exits_5(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    run(
        "redact",
        str(src),
        "--pattern",
        "nonexistentxyzzy",
        "-o",
        str(tmp_path / "o.txt"),
        "--fail-empty",
        expect=5,
    )


def test_redact_no_patterns_is_usage_error(tmp_copy):
    run("redact", str(tmp_copy("sample.txt")), expect=2)


def test_redact_unknown_builtin_is_usage_error(tmp_copy):
    run("redact", str(tmp_copy("sample.txt")), "--builtin", "dna", expect=2)


def test_redact_missing_file_exits_4(tmp_path: Path):
    run("redact", str(tmp_path / "ghost.txt"), "--builtin", "email", expect=4)


def test_redact_unsupported_type_exits_4(tmp_copy):
    run("redact", str(tmp_copy("sample.png")), "--builtin", "email", expect=4)


def test_redact_overwrite_needs_force(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    out = tmp_path / "out.txt"
    out.write_text("keep me")
    run("redact", str(src), "--builtin", "email", "-o", str(out), expect=1)
    assert out.read_text() == "keep me"
    run_json("redact", str(src), "--builtin", "email", "-o", str(out), "--force")


@needs("pdftoppm")
@needs("tesseract")
@needs("pdftotext")
def test_redact_pdf_removes_sentinel(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    assert "palimpsest" in pdf_text(src)
    out = tmp_path / "redacted.pdf"
    record = run_json("redact", str(src), "--pattern", "palimpsest", "-o", str(out))
    assert record["matches"]["palimpsest"] >= 1
    assert record["pages"].get("1", 0) >= 1  # sentinel lives on page 1
    assert record["verified"] is True
    assert "palimpsest" not in pdf_text(out).lower()
    assert len(PdfReader(out).pages) == 2  # page count preserved


@needs("pdftoppm")
@needs("tesseract")
@needs("pdftotext")
def test_redact_pdf_multiword_pattern(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "redacted.pdf"
    record = run_json("redact", str(src), "--pattern", PDF_SENTINEL, "-o", str(out))
    assert record["matches"][PDF_SENTINEL] >= 1
    remaining = pdf_text(out).lower()
    assert "palimpsest" not in remaining and "harbor" not in remaining


@needs("pdftoppm")
@needs("tesseract")
def test_redact_pdf_page_size_preserved(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "redacted.pdf"
    run_json("redact", str(src), "--pattern", "palimpsest", "-o", str(out))
    box_in = PdfReader(src).pages[0].mediabox
    box_out = PdfReader(out).pages[0].mediabox
    assert float(box_out.width) == pytest.approx(float(box_in.width), abs=1.0)
    assert float(box_out.height) == pytest.approx(float(box_in.height), abs=1.0)


# ==================================================================== sign stamp


@needs("pdftotext")
def test_stamp_default_text_mentions_signer(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "signed.pdf"
    record = run_json("sign", "stamp", str(src), "-o", str(out))
    assert record["text"].startswith("Signed by ")
    assert re.search(r"\d{4}-\d{2}-\d{2}", record["text"])  # ISO date
    assert record["page"] == 2  # default --page last
    assert "Signed by" in pdf_text(out)


@needs("pdftotext")
@needs("pdftoppm")
def test_stamp_custom_text_page_pos_pixels_change(tmp_copy, tmp_path: Path):
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "signed.pdf"
    record = run_json(
        "sign",
        "stamp",
        str(src),
        "--text",
        "CARREL STAMP XYZ",
        "--page",
        "1",
        "--pos",
        "top-left",
        "-o",
        str(out),
    )
    assert record["page"] == 1 and record["pos"] == "top-left"
    assert "CARREL STAMP XYZ" in pdf_text(out)
    before = render_page(src, 1, tmp_path, "before")
    after = render_page(out, 1, tmp_path, "after")
    assert before.size == after.size
    assert before.tobytes() != after.tobytes()  # the stamp is visibly rendered


@needs("pdftoppm")
def test_stamp_image_overlay_changes_pixels(tmp_copy, tmp_path: Path):
    sig = tmp_path / "sig.png"
    Image.new("RGB", (120, 40), (10, 10, 160)).save(sig)
    src = tmp_copy("text+image.pdf")
    out = tmp_path / "signed.pdf"
    record = run_json("sign", "stamp", str(src), "--image", str(sig), "--page", "2", "-o", str(out))
    assert record["image"] == str(sig)
    before = render_page(src, 2, tmp_path, "ib")
    after = render_page(out, 2, tmp_path, "ia")
    assert before.tobytes() != after.tobytes()


def test_stamp_page_out_of_range_exits_4(tmp_copy, tmp_path: Path):
    run(
        "sign",
        "stamp",
        str(tmp_copy("text+image.pdf")),
        "--page",
        "99",
        "-o",
        str(tmp_path / "x.pdf"),
        expect=4,
    )


def test_stamp_bad_page_spec_is_usage_error(tmp_copy, tmp_path: Path):
    run(
        "sign",
        "stamp",
        str(tmp_copy("text+image.pdf")),
        "--page",
        "verso",
        "-o",
        str(tmp_path / "x.pdf"),
        expect=2,
    )


def test_stamp_non_pdf_exits_4(tmp_copy, tmp_path: Path):
    run("sign", "stamp", str(tmp_copy("sample.png")), "-o", str(tmp_path / "x.pdf"), expect=4)


# ================================================================ sign manifest


def make_tree(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("alpha\n")
    (docs / "b.txt").write_text("bravo\n")
    return docs


def test_manifest_verify_roundtrip(tmp_path: Path):
    docs = make_tree(tmp_path)
    manifest = tmp_path / "MANIFEST.sha256"
    record = run_json(
        "sign", "manifest", str(docs / "a.txt"), str(docs / "b.txt"), "-o", str(manifest)
    )
    assert record["files"] == 2 and record["signature"] is None
    lines = manifest.read_text().splitlines()
    assert len(lines) == 2
    assert all(re.match(r"^[0-9a-f]{64}  \S", line) for line in lines)  # sha256sum format
    verdict = run_json("sign", "verify", str(manifest))
    assert verdict["ok"] is True and verdict["checked"] == 2
    assert verdict["signature"] == {"present": False, "valid": None}


def test_manifest_directory_recurses(tmp_path: Path):
    docs = make_tree(tmp_path)
    manifest = tmp_path / "m.sha256"
    record = run_json("sign", "manifest", str(docs), "-o", str(manifest))
    assert record["files"] == 2
    run("sign", "verify", str(manifest))


def test_verify_tampered_file_exits_1(tmp_path: Path):
    docs = make_tree(tmp_path)
    manifest = tmp_path / "m.sha256"
    run_json("sign", "manifest", str(docs), "-o", str(manifest))
    (docs / "a.txt").write_text("tampered!\n")
    verdict = run_json("sign", "verify", str(manifest), expect=1)
    assert verdict["ok"] is False
    assert verdict["mismatched"] == ["docs/a.txt"]


def test_verify_missing_file_exits_1(tmp_path: Path):
    docs = make_tree(tmp_path)
    manifest = tmp_path / "m.sha256"
    run_json("sign", "manifest", str(docs), "-o", str(manifest))
    (docs / "b.txt").unlink()
    verdict = run_json("sign", "verify", str(manifest), expect=1)
    assert verdict["missing"] == ["docs/b.txt"]


def test_verify_garbage_manifest_exits_4(tmp_path: Path):
    bad = tmp_path / "m.sha256"
    bad.write_text("this is not a manifest\n")
    run("sign", "verify", str(bad), expect=4)


def test_manifest_no_files_exits_4(tmp_path: Path):
    run("sign", "manifest", str(tmp_path / "ghost.txt"), "-o", str(tmp_path / "m.sha256"), expect=4)


# ------------------------------------------------------------------ gpg tests


@pytest.fixture
def gpg_home(tmp_path: Path, monkeypatch) -> Path:
    """Ephemeral GNUPGHOME with one no-passphrase signing key; skips on failure."""
    if not adapters.have("gpg"):
        pytest.skip("requires 'gpg'")
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("GNUPGHOME", str(home))
    batch = tmp_path / "keyspec"
    batch.write_text(
        "%no-protection\n"
        "Key-Type: eddsa\n"
        "Key-Curve: ed25519\n"
        "Key-Usage: sign\n"
        "Name-Real: Carrel Test\n"
        "Name-Email: carrel-test@example.invalid\n"
        "Expire-Date: 0\n"
        "%commit\n"
    )
    proc = subprocess.run(  # noqa: PLW1510 — tests inspect returncode
        [adapters.require("gpg"), "--batch", "--gen-key", str(batch)],
        capture_output=True,
        text=True,
        env={"GNUPGHOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    if proc.returncode != 0:
        pytest.skip(f"ephemeral gpg key generation failed: {proc.stderr.strip()[:200]}")
    return home


def test_manifest_gpg_sign_and_verify(tmp_path: Path, gpg_home: Path):
    docs = make_tree(tmp_path)
    manifest = tmp_path / "m.sha256"
    record = run_json("sign", "manifest", str(docs), "-o", str(manifest), "--gpg")
    asc = Path(record["signature"])
    assert asc == manifest.with_name("m.sha256.asc") and asc.is_file()
    assert "BEGIN PGP SIGNATURE" in asc.read_text()
    verdict = run_json("sign", "verify", str(manifest))
    assert verdict["ok"] is True
    assert verdict["signature"] == {"present": True, "valid": True}


def test_verify_tampered_manifest_bad_signature_exits_1(tmp_path: Path, gpg_home: Path):
    docs = make_tree(tmp_path)
    manifest = tmp_path / "m.sha256"
    run_json("sign", "manifest", str(docs), "-o", str(manifest), "--gpg")
    # re-hash a legitimately changed file: hashes match, but the signature must fail
    (docs / "a.txt").write_text("changed\n")
    run_json("sign", "manifest", str(docs), "-o", str(manifest), "--force")
    verdict = run_json("sign", "verify", str(manifest), expect=1)
    assert verdict["mismatched"] == [] and verdict["missing"] == []
    assert verdict["signature"] == {"present": True, "valid": False}


# ========================================================================= form

FORM_SPEC = {
    "title": "Library Card Application",
    "fields": [
        {"name": "full_name", "label": "Full name", "type": "text", "required": True},
        {"name": "email", "label": "Email", "type": "email", "required": True},
        {"name": "birthdate", "label": "Date of birth", "type": "date"},
        {"name": "books", "label": "Books at once", "type": "number"},
        {
            "name": "branch",
            "label": "Home branch",
            "type": "select",
            "options": ["Central", "East", "West"],
        },
        {
            "name": "format",
            "label": "Preferred format",
            "type": "radio",
            "options": ["print", "ebook", "audio"],
        },
        {"name": "notes", "label": "Anything else?", "type": "textarea"},
        {
            "name": "agree",
            "label": "I accept the late-fee policy",
            "type": "checkbox",
            "required": True,
        },
    ],
}


def write_spec(tmp_path: Path, spec: dict | None = None) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec or FORM_SPEC, indent=2))
    return path


def test_form_build_produces_valid_html(tmp_path: Path):
    spec = write_spec(tmp_path)
    out = tmp_path / "form.html"
    record = run_json("form", "build", str(spec), "-o", str(out))
    assert record["fields"] == 8 and record["pdf"] is None
    text = out.read_text()
    assert text.startswith("<!DOCTYPE html>")
    # acceptance: parseable — the document is well-formed XML minus the doctype
    root = ET.fromstring(text.split("\n", 1)[1])
    body = root.find("body")
    assert body is not None
    names = {el.get("name") for el in body.iter() if el.get("name")}
    assert names == {f["name"] for f in FORM_SPEC["fields"]}
    for field in FORM_SPEC["fields"]:
        assert field["label"] in text
    assert "action=" not in text  # POST-less
    assert "font-family: system-ui" in text  # embedded CSS, system stack
    assert "@media print" in text  # print-friendly


def test_form_build_radio_and_select_options(tmp_path: Path):
    spec = write_spec(tmp_path)
    out = tmp_path / "form.html"
    run("form", "build", str(spec), "-o", str(out))
    root = ET.fromstring(out.read_text().split("\n", 1)[1])
    radios = [el for el in root.iter("input") if el.get("type") == "radio"]
    assert {r.get("value") for r in radios} == {"print", "ebook", "audio"}
    options = [el.text for el in root.iter("option") if el.text]
    assert options == ["Central", "East", "West"]


def test_form_build_escapes_html(tmp_path: Path):
    spec = write_spec(
        tmp_path,
        {
            "title": "T <script>alert(1)</script>",
            "fields": [{"name": "a", "label": 'x "<b>&', "type": "text"}],
        },
    )
    out = tmp_path / "form.html"
    run("form", "build", str(spec), "-o", str(out))
    text = out.read_text()
    assert "<script>" not in text
    ET.fromstring(text.split("\n", 1)[1])  # still well-formed


@needs("weasyprint")
def test_form_build_pdf(tmp_path: Path):
    spec = write_spec(tmp_path)
    out = tmp_path / "form.html"
    record = run_json("form", "build", str(spec), "-o", str(out), "--pdf")
    pdf = Path(record["pdf"])
    assert pdf == tmp_path / "form.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    assert len(PdfReader(pdf).pages) >= 1


def test_form_build_bad_specs_exit_4(tmp_path: Path):
    for bad in (
        {"title": "no fields key"},
        {"fields": [{"label": "nameless"}]},
        {"fields": [{"name": "x", "type": "hologram"}]},
        {"fields": [{"name": "x", "type": "select"}]},  # options missing
    ):
        run(
            "form",
            "build",
            str(write_spec(tmp_path, bad)),
            "-o",
            str(tmp_path / "o.html"),
            expect=4,
        )


def test_form_fields_lists_acroform(fixtures: Path):
    rows = run_json("form", "fields", str(fixtures / "form.pdf"))
    by_name = {row["name"]: row for row in rows}
    assert set(by_name) == {"name", "agree"}
    assert by_name["name"]["type"] == "text"
    assert by_name["agree"]["type"] == "button"
    assert "/Yes" in by_name["agree"]["states"]


def test_form_fields_no_acroform_is_empty(tmp_copy):
    rows = run_json("form", "fields", str(tmp_copy("text+image.pdf")))
    assert rows == []


def test_form_fill_roundtrip(tmp_copy, tmp_path: Path):
    src = tmp_copy("form.pdf")
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"name": "Ada Lovelace", "agree": True, "bogus": 1}))
    out = tmp_path / "filled.pdf"
    record = run_json("form", "fill", str(src), str(data), "-o", str(out))
    assert record["filled"] == ["agree", "name"]
    assert record["unmatched"] == ["bogus"]
    fields = PdfReader(out).get_fields()
    assert fields["name"].value == "Ada Lovelace"
    assert fields["agree"].value == "/Yes"


def test_form_fill_checkbox_false_stays_off(tmp_copy, tmp_path: Path):
    src = tmp_copy("form.pdf")
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"agree": False}))
    out = tmp_path / "filled.pdf"
    run_json("form", "fill", str(src), str(data), "-o", str(out))
    assert PdfReader(out).get_fields()["agree"].value == "/Off"


def test_form_fill_no_acroform_exits_4(tmp_copy, tmp_path: Path):
    data = tmp_path / "data.json"
    data.write_text("{}")
    run(
        "form",
        "fill",
        str(tmp_copy("text+image.pdf")),
        str(data),
        "-o",
        str(tmp_path / "o.pdf"),
        expect=4,
    )


def test_form_fill_non_object_data_exits_4(tmp_copy, tmp_path: Path):
    data = tmp_path / "data.json"
    data.write_text("[1, 2, 3]")
    run(
        "form",
        "fill",
        str(tmp_copy("form.pdf")),
        str(data),
        "-o",
        str(tmp_path / "o.pdf"),
        expect=4,
    )


# ===================================================================== plumbing


def test_help_for_all_commands_and_subcommands():
    run("redact", "--help")
    for group, subs in (
        ("sign", ("stamp", "manifest", "verify")),
        ("form", ("build", "fields", "fill")),
    ):
        result = run(group, "--help")
        for sub in subs:
            assert sub in result.output
            run(group, sub, "--help")


def test_json_output_is_single_document(tmp_copy, tmp_path: Path):
    result = run(
        "--json",
        "redact",
        str(tmp_copy("sample.txt")),
        "--builtin",
        "email",
        "-o",
        str(tmp_path / "o.txt"),
    )
    record = json.loads(result.output)  # raises if anything but one JSON doc
    assert record["matches"]["email"] == 2
