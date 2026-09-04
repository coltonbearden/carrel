"""Unit tests for carrel.core.adapters (spec 00-core Acceptance)."""

from __future__ import annotations

import shutil

import pytest
from conftest import needs

from carrel.core import adapters
from carrel.core.adapters import ADAPTERS, Adapter, MissingDependencyError
from carrel.core.output import ExitCode

# spec 00-core: registry must cover these names
REQUIRED_ADAPTERS = {
    "pandoc",
    "pdftotext",
    "pdftoppm",
    "pdfimages",
    "qpdf",
    "gs",
    "weasyprint",
    "tesseract",
    "ocrmypdf",
    "magick",
    "exiftool",
    "ffmpeg",
    "pngquant",
    "icotool",
    "jq",
    "mlr",
    "rg",
    "fd",
    "sqlite3",
    "inotifywait",
    "espeak-ng",
    "piper",
    "edge-tts",
    "gpg",
    "claude",
}


def test_registry_covers_spec():
    missing = REQUIRED_ADAPTERS - set(ADAPTERS)
    assert not missing, f"ADAPTERS registry missing: {sorted(missing)}"


def test_registry_entries_well_formed():
    for name, a in ADAPTERS.items():
        assert a.name == name
        assert a.binaries and all(a.binaries)
        assert a.install_hint
        assert a.purpose


def test_have_matches_which():
    """have() agrees with PATH lookup for every candidate list."""
    for name, a in ADAPTERS.items():
        expected = any(shutil.which(b) for b in a.binaries)
        assert adapters.have(name) == expected, name


@needs("pandoc")
def test_have_pandoc_true_on_this_box():
    # spec acceptance: adapters.have('pandoc') → True on the dev machine
    assert adapters.have("pandoc") is True


@needs("pdftotext")
def test_require_returns_resolved_path():
    path = adapters.require("pdftotext")
    assert path == shutil.which("pdftotext")
    assert path.startswith("/")


def test_require_missing_binary_raises_with_hint(monkeypatch):
    fake = Adapter(
        name="frobnicator",
        binaries=("definitely-not-a-real-binary-xyz",),
        version_args=("--version",),
        install_hint="sudo apt install frobnicator",
        purpose="frobnicates test expectations",
    )
    monkeypatch.setitem(ADAPTERS, "frobnicator", fake)
    assert adapters.have("frobnicator") is False
    with pytest.raises(MissingDependencyError) as exc:
        adapters.require("frobnicator")
    msg = str(exc.value)
    assert "frobnicator" in msg
    assert "sudo apt install frobnicator" in msg  # actionable install hint
    assert exc.value.exit_code == ExitCode.MISSING_DEP == 3
    assert adapters.version_of("frobnicator") is None


def test_require_unknown_name_raises():
    """Names absent from the registry raise a hinted MissingDependencyError (exit 3)."""
    with pytest.raises(adapters.MissingDependencyError) as exc:
        adapters.require("nonexistent-tool-xyz")
    assert "nonexistent-tool-xyz" in str(exc.value)
    assert "PATH" in str(exc.value)
    assert exc.value.exit_code == 3


@needs("qpdf")
def test_run_text_mode():
    proc = adapters.run("qpdf", "--version")
    assert proc.returncode == 0
    assert isinstance(proc.stdout, str)
    assert "qpdf" in proc.stdout.lower()


@needs("qpdf")
def test_run_binary_mode():
    proc = adapters.run("qpdf", "--version", binary=True)
    assert proc.returncode == 0
    assert isinstance(proc.stdout, bytes)


@needs("jq")
def test_run_with_input_and_nonzero_rc():
    proc = adapters.run("jq", ".a", input='{"a": 42}')
    assert proc.returncode == 0
    assert proc.stdout.strip() == "42"
    # run() never raises on failure — callers inspect returncode
    proc = adapters.run("jq", ".", input="{not json")
    assert proc.returncode != 0
    assert proc.stderr


@needs("gpg")
def test_version_of_present_binary():
    v = adapters.version_of("gpg")
    assert v and v != "?"
