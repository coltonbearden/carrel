"""Tests for `carrel audiobook` (spec 09)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.commands.audiobook import (
    audiobook_file,
    chunk_text,
    md_chapters,
    md_to_speech,
    pdf_chapters,
)
from carrel.core import adapters
from carrel.core.output import CarrelInputError

espeak = needs("espeak-ng")


def run(*args: str) -> CliRunner.Result:
    return CliRunner().invoke(cli, list(args))


def all_output(res) -> str:
    try:
        return res.output + res.stderr
    except (ValueError, AttributeError):
        return res.output


def is_wav(path: Path) -> bool:
    return path.read_bytes()[:4] == b"RIFF"


# ------------------------------------------------------------------ help


def test_help_lists_flags():
    res = run("audiobook", "--help")
    assert res.exit_code == 0
    for flag in ("--voice", "--rate", "--engine", "--split-chapters", "--format", "-o"):
        assert flag in res.output


# ------------------------------------------------------- markdown prep


def test_md_to_speech_strips_syntax(fixtures: Path):
    spoken = md_to_speech((fixtures / "sample.md").read_text())
    # headings become chapter announcements followed by a pause (blank line)
    assert "Chapter: Chapter One: The Reading Room.\n\n" in spoken
    assert "Chapter: Furniture.\n\n" in spoken
    assert "#" not in spoken
    # fenced code replaced, its contents gone
    assert "[code omitted]" in spoken
    assert "def shelve" not in spoken and "```" not in spoken
    # inline code kept as text, backticks gone
    assert "Some inline code and a fenced block:" in spoken
    # links keep their text, lose their URL; emphasis markers stripped
    assert "desk project" in spoken
    assert "https://example.com" not in spoken
    assert "melodious cartography" in spoken and "*" not in spoken
    # list bullets stripped but item text kept
    assert "one squeaky chair" in spoken and "- a desk" not in spoken


def test_md_to_speech_images_and_blockquotes():
    spoken = md_to_speech(
        "> A quoted thought.\n\n![a lonely lamp](lamp.png) and ![](decor.png) here.\n"
    )
    assert "A quoted thought." in spoken and ">" not in spoken
    assert "a lonely lamp" in spoken
    assert "lamp.png" not in spoken and "decor.png" not in spoken


def test_md_chapters_splits_on_h1(fixtures: Path):
    chapters = md_chapters((fixtures / "sample.md").read_text(), "sample")
    assert [t for t, _ in chapters] == [
        "Chapter One: The Reading Room",
        "Chapter Two: The Catalogue",
    ]
    assert "melodious cartography" in chapters[0][1]
    assert "desk project" in chapters[1][1]


def test_md_chapters_falls_back_to_h2_then_single():
    two_h2 = "## First\n\nalpha\n\n## Second\n\nbeta\n"
    assert [t for t, _ in md_chapters(two_h2, "x")] == ["First", "Second"]
    flat = "just a paragraph\n\nanother paragraph\n"
    assert md_chapters(flat, "fallback") == [("fallback", flat)]


def test_md_chapters_ignores_headings_inside_fences():
    md = "# Real\n\ntext\n\n```\n# not a chapter\n```\n\n# Also Real\n\nmore\n"
    chapters = md_chapters(md, "x")
    assert [t for t, _ in chapters] == ["Real", "Also Real"]
    assert "# not a chapter" in chapters[0][1]


# ---------------------------------------------------------------- chunking


def test_chunk_text_respects_limit_and_sentences():
    sentence = "The quick brown fox jumps over the lazy dog once more. "
    text = sentence * 60  # ~3300 chars
    chunks = chunk_text(text, limit=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert all(c.rstrip().endswith(".") for c in chunks)  # sentence boundaries
    rejoined = " ".join(chunks)
    assert rejoined.count("quick brown fox") == 60


def test_chunk_text_hard_splits_runon():
    chunks = chunk_text("x" * 2500, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert sum(len(c) for c in chunks) == 2500


# --------------------------------------------------------- synthesis (wav)


@espeak
def test_txt_to_wav_forced_espeak(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run(
        "--json", "audiobook", str(src), "--engine", "espeak", "--format", "wav", "--rate", "300"
    )
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    out = src.with_suffix(".wav")
    assert rec["src"] == str(src)
    assert rec["outputs"] == [str(out)]
    assert rec["engine"] == "espeak-ng"
    assert rec["chars"] > 0
    assert out.stat().st_size > 1024 and is_wav(out)
    if adapters.have("ffprobe"):
        assert rec["duration_s"] > 0
    else:
        assert rec["duration_s"] is None


@espeak
def test_auto_engine_falls_through_to_espeak(tmp_copy, monkeypatch):
    real_have = adapters.have
    monkeypatch.setattr(
        adapters, "have", lambda name: False if name in ("piper", "edge-tts") else real_have(name)
    )
    result = audiobook_file(tmp_copy("sample.txt"), fmt="wav", rate=300)
    assert result["engine"] == "espeak-ng"
    assert Path(result["outputs"][0]).stat().st_size > 1024


@espeak
def test_split_chapters_md_two_files(tmp_copy, tmp_path: Path):
    """Acceptance: --split-chapters on the 2-chapter md fixture → 2 files."""
    src = tmp_copy("sample.md")
    out = tmp_path / "book.wav"
    res = run(
        "--json",
        "audiobook",
        str(src),
        "-o",
        str(out),
        "--split-chapters",
        "--format",
        "wav",
        "--rate",
        "300",
    )
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    assert len(rec["outputs"]) == 2
    names = [Path(p).name for p in rec["outputs"]]
    assert names[0].startswith("book-01-chapter-one")
    assert names[1].startswith("book-02-chapter-two")
    for p in rec["outputs"]:
        path = Path(p)
        assert path.stat().st_size > 1024 and is_wav(path)


@espeak
@needs("pdftotext")
def test_pdf_to_wav(tmp_copy):
    """Acceptance: pdf fixture → audio."""
    src = tmp_copy("text+image.pdf")
    result = audiobook_file(src, fmt="wav", engine="espeak", rate=300)
    out = Path(result["outputs"][0])
    assert out.stat().st_size > 1024 and is_wav(out)
    assert result["chars"] > 0


@needs("pdftotext")
def test_pdf_without_outline_has_no_chapters(fixtures: Path):
    assert pdf_chapters(fixtures / "b.pdf") is None


@espeak
@needs("pdftotext")
def test_pdf_outline_split(tmp_path: Path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "outlined.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    for _i, (key, title, line) in enumerate(
        [
            ("ch1", "Part One", "Opening words of part one."),
            ("ch2", "Part Two", "Closing words of part two."),
        ]
    ):
        c.drawString(72, 720, line)
        c.bookmarkPage(key)
        c.addOutlineEntry(title, key, level=0)
        c.showPage()
    c.save()

    chapters = pdf_chapters(pdf)
    assert chapters is not None and [t for t, _ in chapters] == ["Part One", "Part Two"]
    assert "part one" in chapters[0][1].lower()

    result = audiobook_file(
        pdf, tmp_path / "out.wav", fmt="wav", engine="espeak", rate=300, split_chapters=True
    )
    names = [Path(p).name for p in result["outputs"]]
    assert names == ["out-01-part-one.wav", "out-02-part-two.wav"]
    assert all(is_wav(Path(p)) for p in result["outputs"])


# ------------------------------------------------------------- mp3 / ffmpeg


@espeak
@needs("ffmpeg")
@needs("ffprobe")
def test_md_to_mp3_real(tmp_copy):
    """Acceptance: md fixture → mp3 exists, >1KB, ffprobe duration > 0."""
    src = tmp_copy("sample.md")
    res = run("--json", "audiobook", str(src), "--rate", "300")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    out = src.with_suffix(".mp3")
    assert rec["outputs"] == [str(out)]
    assert out.stat().st_size > 1024
    assert rec["duration_s"] > 0
    # title metadata was written from the filename stem
    probe = adapters.run(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format_tags=title",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(out),
    )
    assert probe.stdout.strip() == "sample"


def test_missing_ffmpeg_nonwav_exits_3(tmp_copy, monkeypatch):
    """Acceptance: absent ffmpeg + non-wav target → exit 3 with hint."""
    real_have = adapters.have
    monkeypatch.setattr(
        adapters, "have", lambda name: False if name == "ffmpeg" else real_have(name)
    )
    src = tmp_copy("sample.txt")
    res = run("audiobook", str(src), "--format", "mp3")
    assert res.exit_code == 3
    out = all_output(res)
    assert "ffmpeg" in out and "apt install ffmpeg" in out
    assert not src.with_suffix(".mp3").exists()


@espeak
def test_wav_needs_no_ffmpeg(tmp_copy, monkeypatch):
    """--format wav works with espeak alone even when ffmpeg is 'absent'."""
    real_have = adapters.have
    monkeypatch.setattr(
        adapters, "have", lambda name: False if name in ("ffmpeg", "ffprobe") else real_have(name)
    )
    src = tmp_copy("sample.txt")
    res = run("--json", "audiobook", str(src), "--format", "wav", "--rate", "300")
    assert res.exit_code == 0, all_output(res)
    rec = json.loads(res.stdout)
    assert rec["duration_s"] is None  # no ffprobe → null
    assert is_wav(src.with_suffix(".wav"))


# -------------------------------------------------------------- bad input


@pytest.mark.skipif(adapters.have("piper"), reason="piper installed here")
def test_forced_missing_engine_exits_3(tmp_copy):
    src = tmp_copy("sample.txt")
    res = run("audiobook", str(src), "--engine", "piper", "--format", "wav")
    assert res.exit_code == 3
    out = all_output(res)
    assert "piper" in out and "pipx install piper-tts" in out


def test_unsupported_type_exits_4(tmp_copy):
    res = run("audiobook", str(tmp_copy("sample.png")), "--format", "wav")
    assert res.exit_code == 4
    assert "supported: txt, md, pdf" in all_output(res)


def test_missing_source_exits_4(tmp_path: Path):
    res = run("audiobook", str(tmp_path / "nope.md"))
    assert res.exit_code == 4
    assert "no such file" in all_output(res)


def test_bad_output_extension_exits_4(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    res = run("audiobook", str(src), "-o", str(tmp_path / "out.flac"))
    assert res.exit_code == 4
    assert "flac" in all_output(res)


def test_unknown_format_flag_is_usage_error(tmp_copy):
    res = run("audiobook", str(tmp_copy("sample.txt")), "--format", "flac")
    assert res.exit_code == 2


@espeak
def test_empty_source_exits_4(tmp_path: Path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n")
    with pytest.raises(CarrelInputError):
        audiobook_file(empty, fmt="wav")


# ------------------------------------------------------------- library API


@espeak
def test_audiobook_file_library_api(tmp_copy, tmp_path: Path):
    src = tmp_copy("sample.txt")
    dest = tmp_path / "narrated.wav"
    result = audiobook_file(src, dest, engine="espeak", rate=300, fmt="wav")
    assert set(result) == {"src", "outputs", "engine", "duration_s", "chars"}
    assert result["outputs"] == [str(dest)]
    assert dest.exists() and is_wav(dest)
