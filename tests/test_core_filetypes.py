"""Unit tests for carrel.core.filetypes (spec 00-core Acceptance: detect() on fixtures)."""

from __future__ import annotations

import pytest

from carrel.core.filetypes import (
    SUPPORTED_EXTENSIONS,
    FileType,
    detect,
    detect_or_die,
    sniff,
)
from carrel.core.output import CarrelInputError

# every fixture in the support matrix → its expected type
FIXTURE_TYPES = [
    ("sample.txt", FileType.TXT),
    ("sample.md", FileType.MD),
    ("sample.html", FileType.HTML),
    ("sample.json", FileType.JSON),
    ("records.json", FileType.JSON),
    ("sample.xml", FileType.XML),
    ("sample.csv", FileType.CSV),
    ("sample.png", FileType.PNG),
    ("scanned.png", FileType.PNG),
    ("sample.jpg", FileType.JPG),
    ("sample-copy.jpg", FileType.JPG),
    ("sample-resized.jpg", FileType.JPG),
    ("sample.ico", FileType.ICO),
    ("text+image.pdf", FileType.PDF),
    ("form.pdf", FileType.PDF),
    ("scanned.pdf", FileType.PDF),
    ("b.pdf", FileType.PDF),
]


@pytest.mark.parametrize(("name", "expected"), FIXTURE_TYPES)
def test_detect_fixture(fixtures, name, expected):
    path = fixtures / name
    assert path.is_file(), f"fixture missing: run tests/fixtures/generate.py ({name})"
    assert detect(path) is expected
    assert detect_or_die(path) is expected


def test_support_matrix_covered(fixtures):
    """Every supported FileType (except UNKNOWN) has at least one fixture."""
    present = {expected for _, expected in FIXTURE_TYPES}
    assert present == set(FileType) - {FileType.UNKNOWN}


def test_magic_overrides_extension(fixtures, tmp_path):
    """Bytes are trusted over the file name."""
    disguised = tmp_path / "actually-a-pdf.txt"
    disguised.write_bytes((fixtures / "b.pdf").read_bytes())
    assert detect(disguised) is FileType.PDF

    disguised_png = tmp_path / "art.csv"
    disguised_png.write_bytes((fixtures / "sample.png").read_bytes())
    assert detect(disguised_png) is FileType.PNG


def test_extension_used_when_magic_inconclusive(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("# plain markdown\n")
    assert sniff(p) is None
    assert detect(p) is FileType.MD


def test_unknown_type(tmp_path):
    p = tmp_path / "blob.zzz"
    p.write_bytes(b"\x00\x01\x02 nothing recognizable")
    assert detect(p) is FileType.UNKNOWN


def test_detect_or_die_missing_file(tmp_path):
    with pytest.raises(CarrelInputError, match="no such file"):
        detect_or_die(tmp_path / "nope.pdf")


def test_detect_or_die_directory(tmp_path):
    with pytest.raises(CarrelInputError, match="not a regular file"):
        detect_or_die(tmp_path)


def test_detect_or_die_unsupported(tmp_path):
    p = tmp_path / "blob.zzz"
    p.write_bytes(b"junk")
    with pytest.raises(CarrelInputError, match="unsupported file type"):
        detect_or_die(p)


def test_type_properties():
    assert FileType.PNG.is_image and FileType.JPG.is_image and FileType.ICO.is_image
    assert not FileType.PDF.is_image
    for t in (FileType.MD, FileType.TXT, FileType.HTML, FileType.JSON, FileType.XML, FileType.CSV):
        assert t.is_text
    assert not FileType.PDF.is_text and not FileType.PNG.is_text


def test_supported_extensions_registry():
    for ext in (
        ".pdf",
        ".md",
        ".jpg",
        ".jpeg",
        ".png",
        ".ico",
        ".txt",
        ".html",
        ".htm",
        ".json",
        ".xml",
        ".csv",
    ):
        assert ext in SUPPORTED_EXTENSIONS
