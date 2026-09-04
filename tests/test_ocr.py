"""Tests for `carrel ocr` (spec 02).

Real OCR runs against the generated fixtures — scanned.png / scanned.pdf carry
the phrase "CARREL OCR FIXTURE 42" in large clear type. Binary-dependent tests
skip via @needs() when tesseract / ocrmypdf / pdftotext are absent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.commands.ocr import default_dest, ocr_file
from carrel.core import adapters

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str) -> dict:
    result = run("--json", *args)
    return json.loads(result.output)


# ------------------------------------------------------------- image inputs


@needs("tesseract")
def test_image_to_txt_reads_fixture_text(fixtures, tmp_path: Path):
    out = tmp_path / "scan.txt"
    record = run_json("ocr", str(fixtures / "scanned.png"), "-o", str(out))
    assert record["engine"] == "tesseract"
    assert record["dest"] == str(out)
    text = out.read_text()
    assert "CARREL" in text and "FIXTURE" in text
    assert record["chars"] == len(text) > 0


@needs("tesseract")
def test_image_to_md_same_text(fixtures, tmp_path: Path):
    out = tmp_path / "scan.md"
    record = run_json("ocr", str(fixtures / "scanned.png"), "--to", "md", "-o", str(out))
    assert record["engine"] == "tesseract"
    assert "CARREL" in out.read_text()


@needs("tesseract")
def test_image_to_pdf_writes_pdf(fixtures, tmp_path: Path):
    out = tmp_path / "scan.pdf"
    record = run_json("ocr", str(fixtures / "scanned.png"), "--to", "pdf", "-o", str(out))
    assert record["engine"] == "tesseract"
    assert out.read_bytes()[:4] == b"%PDF"
    if adapters.have("pdftotext"):
        assert record["chars"] > 0


@needs("tesseract")
def test_default_dest_next_to_src(tmp_copy):
    src = tmp_copy("scanned.png")
    record = run_json("ocr", str(src))
    assert record["dest"] == str(src.with_suffix(".txt"))
    assert "CARREL" in src.with_suffix(".txt").read_text()


# --------------------------------------------------------------- pdf inputs


@needs("ocrmypdf")
@needs("pdftotext")
def test_scanned_pdf_to_searchable_pdf(fixtures, tmp_path: Path):
    out = tmp_path / "searchable.pdf"
    record = run_json("ocr", str(fixtures / "scanned.pdf"), "--to", "pdf", "-o", str(out))
    assert record["engine"] == "ocrmypdf"
    assert out.read_bytes()[:4] == b"%PDF"
    extracted = subprocess.run(
        [adapters.require("pdftotext"), "-layout", str(out), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "CARREL" in extracted
    assert record["chars"] == len(extracted) > 0


@needs("ocrmypdf")
@needs("pdftotext")
def test_scanned_pdf_to_txt(fixtures, tmp_path: Path):
    out = tmp_path / "scan.txt"
    record = run_json("ocr", str(fixtures / "scanned.pdf"), "-o", str(out))
    assert record["engine"] == "ocrmypdf"
    text = out.read_text()
    assert "CARREL" in text
    assert record["chars"] == len(text)


@needs("ocrmypdf")
@needs("pdftotext")
def test_born_digital_pdf_passes_through(fixtures, tmp_path: Path):
    # --skip-text default: pages that already have text are left alone,
    # and their existing text layer comes out of --to txt.
    out = tmp_path / "born.txt"
    record = run_json("ocr", str(fixtures / "text+image.pdf"), "-o", str(out))
    assert record["engine"] == "ocrmypdf"
    assert record["chars"] > 0


def test_prior_text_rc6_suggests_redo(fixtures, tmp_path: Path, monkeypatch):
    # ocrmypdf exit 6 = "already has text"; must become a friendly --redo hint.
    real_run = adapters.run

    def fake_run(name, *args, **kwargs):
        if name == "ocrmypdf":
            return subprocess.CompletedProcess(
                [name, *args], 6, stdout="", stderr="PriorOcrFoundError: page already has text!"
            )
        return real_run(name, *args, **kwargs)

    monkeypatch.setattr(adapters, "run", fake_run)
    monkeypatch.setattr("carrel.commands.ocr.adapters.run", fake_run)
    result = CliRunner().invoke(
        cli, ["ocr", str(fixtures / "text+image.pdf"), "-o", str(tmp_path / "o.txt")]
    )
    assert result.exit_code == 1
    assert "--redo" in result.stderr and "text layer" in result.stderr


# --------------------------------------------------------------- degradation


def test_missing_tesseract_exits_3_with_hint(fixtures, tmp_path: Path, monkeypatch):
    real = adapters.ADAPTERS["tesseract"]
    broken = adapters.Adapter(
        "tesseract",
        ("definitely-not-a-real-binary-xyz",),
        real.version_args,
        real.install_hint,
        real.purpose,
    )
    monkeypatch.setitem(adapters.ADAPTERS, "tesseract", broken)
    result = CliRunner().invoke(
        cli, ["ocr", str(fixtures / "scanned.png"), "-o", str(tmp_path / "o.txt")]
    )
    assert result.exit_code == 3
    assert "tesseract" in result.stderr and "install" in result.stderr


def test_missing_ocrmypdf_exits_3_with_hint(fixtures, tmp_path: Path, monkeypatch):
    real = adapters.ADAPTERS["ocrmypdf"]
    broken = adapters.Adapter(
        "ocrmypdf",
        ("definitely-not-a-real-binary-xyz",),
        real.version_args,
        real.install_hint,
        real.purpose,
    )
    monkeypatch.setitem(adapters.ADAPTERS, "ocrmypdf", broken)
    result = CliRunner().invoke(
        cli, ["ocr", str(fixtures / "scanned.pdf"), "-o", str(tmp_path / "o.txt")]
    )
    assert result.exit_code == 3
    assert "ocrmypdf" in result.stderr and "install" in result.stderr


@needs("tesseract")
def test_missing_language_pack_hint_image(fixtures, tmp_path: Path):
    # 'xyz' is not a real language pack: tesseract fails loading it, and the
    # error must carry the apt install hint. Exit 3 = missing dependency.
    result = CliRunner().invoke(
        cli, ["ocr", str(fixtures / "scanned.png"), "--lang", "xyz", "-o", str(tmp_path / "o.txt")]
    )
    assert result.exit_code == 3
    assert "sudo apt install tesseract-ocr-xyz" in result.stderr


@needs("ocrmypdf")
def test_missing_language_pack_hint_pdf(fixtures, tmp_path: Path):
    result = CliRunner().invoke(
        cli, ["ocr", str(fixtures / "scanned.pdf"), "--lang", "xyz", "-o", str(tmp_path / "o.txt")]
    )
    assert result.exit_code == 3
    assert "sudo apt install tesseract-ocr-xyz" in result.stderr


# --------------------------------------------------------- input validation


def test_unsupported_type_exits_4(fixtures, tmp_path: Path):
    run("ocr", str(fixtures / "sample.txt"), "-o", str(tmp_path / "o.txt"), expect=4)


def test_missing_file_exits_4(tmp_path: Path):
    run("ocr", str(tmp_path / "ghost.png"), expect=4)


def test_bad_to_choice_is_usage_error(fixtures):
    run("ocr", str(fixtures / "scanned.png"), "--to", "docx", expect=2)


@needs("tesseract")
def test_overwrite_needs_force(fixtures, tmp_path: Path):
    out = tmp_path / "o.txt"
    out.write_text("precious")
    run("ocr", str(fixtures / "scanned.png"), "-o", str(out), expect=1)
    assert out.read_text() == "precious"
    record = run_json("ocr", str(fixtures / "scanned.png"), "-o", str(out), "--force")
    assert "CARREL" in out.read_text()
    assert record["dest"] == str(out)


# ----------------------------------------------------------------- plumbing


def test_help_works():
    result = run("ocr", "--help")
    for flag in ("--lang", "--to", "--redo", "--force", "-o"):
        assert flag in result.output


def test_default_dest_naming(tmp_path: Path):
    assert default_dest(tmp_path / "a.png", "txt") == tmp_path / "a.txt"
    assert default_dest(tmp_path / "a.pdf", "pdf") == tmp_path / "a.ocr.pdf"
    assert default_dest(tmp_path / "a.pdf", "md") == tmp_path / "a.md"


@needs("tesseract")
def test_ocr_file_plain_function(fixtures, tmp_path: Path):
    # the TUI/MCP entry point works without any click context
    record = ocr_file(fixtures / "scanned.png", tmp_path / "plain.txt")
    assert set(record) == {"src", "dest", "engine", "chars"}
    assert record["engine"] == "tesseract"
    assert "CARREL" in (tmp_path / "plain.txt").read_text()


@needs("tesseract")
def test_json_flag_emits_single_json_object(fixtures, tmp_path: Path):
    result = run("--json", "ocr", str(fixtures / "scanned.png"), "-o", str(tmp_path / "o.txt"))
    record = json.loads(result.output)  # raises if anything but one JSON doc
    assert record["src"].endswith("scanned.png")
