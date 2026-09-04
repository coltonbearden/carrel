"""Unit tests for carrel.core.adapters (spec 00-core Acceptance)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import needs

from carrel.core import adapters
from carrel.core.adapters import ADAPTERS, Adapter, MissingDependencyError
from carrel.core.output import ExitCode

# spec 00-core registry, minus the unwired entries spec 19 removed, plus `git`
REQUIRED_ADAPTERS = {
    "pandoc",
    "pdftotext",
    "pdftoppm",
    "pdfimages",
    "qpdf",
    "weasyprint",
    "tesseract",
    "ocrmypdf",
    "magick",
    "exiftool",
    "ffmpeg",
    "ffprobe",
    "icotool",
    "espeak-ng",
    "piper",
    "edge-tts",
    "gpg",
    "git",
}

# spec 19: registered but wired to no command → removed (re-add with the command that uses them)
REMOVED_ADAPTERS = {"gs", "pngquant", "jq", "mlr", "rg", "fd", "sqlite3", "inotifywait", "claude"}


def test_registry_covers_spec():
    missing = REQUIRED_ADAPTERS - set(ADAPTERS)
    assert not missing, f"ADAPTERS registry missing: {sorted(missing)}"


def test_registry_has_git_and_no_dead_entries():
    assert "git" in ADAPTERS
    assert ADAPTERS["git"].version_args == ("--version",)
    assert "pack" in ADAPTERS["git"].purpose
    assert "apt install git" in ADAPTERS["git"].install_hint
    still_there = REMOVED_ADAPTERS & set(ADAPTERS)
    assert not still_there, f"unwired adapters should be gone: {sorted(still_there)}"


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


@needs("pandoc")
def test_run_with_input_and_nonzero_rc():
    proc = adapters.run("pandoc", "-f", "markdown", "-t", "plain", input="# forty-two\n")
    assert proc.returncode == 0
    assert "forty-two" in proc.stdout
    # run() never raises on failure — callers inspect returncode
    proc = adapters.run("pandoc", "-f", "no-such-format-xyz", "-t", "plain", input="x\n")
    assert proc.returncode != 0
    assert proc.stderr


@needs("gpg")
def test_version_of_present_binary():
    v = adapters.version_of("gpg")
    assert v and v != "?"


@needs("git")
def test_git_adapter_runs():
    proc = adapters.run("git", "--version")
    assert proc.returncode == 0
    assert proc.stdout.startswith("git version")
    assert adapters.version_of("git").startswith("git version")


# --- CARREL_BIN_<NAME> override (spec 19, D-008) -------------------------------


def _fake_binary(tmp_path: Path, name: str, banner: str) -> Path:
    exe = tmp_path / name
    exe.write_text(f"#!/bin/sh\necho '{banner}'\n")
    exe.chmod(0o755)
    return exe


def test_override_env_var_name():
    assert ADAPTERS["pandoc"].env_var == "CARREL_BIN_PANDOC"
    assert ADAPTERS["espeak-ng"].env_var == "CARREL_BIN_ESPEAK_NG"
    assert ADAPTERS["edge-tts"].env_var == "CARREL_BIN_EDGE_TTS"


def test_override_unset_or_empty_means_path_lookup(monkeypatch):
    monkeypatch.delenv("CARREL_BIN_PANDOC", raising=False)
    assert ADAPTERS["pandoc"].override() is None
    monkeypatch.setenv("CARREL_BIN_PANDOC", "   ")
    assert ADAPTERS["pandoc"].override() is None
    assert adapters.have("pandoc") == (shutil.which("pandoc") is not None)


def test_override_nonexistent_path_counts_as_missing(monkeypatch):
    monkeypatch.setenv("CARREL_BIN_PANDOC", "/nonexistent/dir/pandoc")
    assert adapters.have("pandoc") is False  # even if pandoc is on PATH — no silent fallback
    assert adapters.version_of("pandoc") is None
    with pytest.raises(MissingDependencyError) as exc:
        adapters.require("pandoc")
    msg = str(exc.value)
    assert "override CARREL_BIN_PANDOC=/nonexistent/dir/pandoc not found" in msg
    assert "sudo apt install pandoc" in msg  # install hint still present
    assert exc.value.exit_code == 3


def test_override_non_executable_file_counts_as_missing(tmp_path, monkeypatch):
    plain = tmp_path / "pandoc"
    plain.write_text("not a program\n")
    plain.chmod(0o644)
    monkeypatch.setenv("CARREL_BIN_PANDOC", str(plain))
    assert adapters.have("pandoc") is False


def test_override_uses_exact_path_and_skips_path_search(tmp_path, monkeypatch):
    exe = _fake_binary(tmp_path, "my-pandoc", "pandoc 99.0 (pinned)")
    monkeypatch.setenv("CARREL_BIN_PANDOC", str(exe))

    def never(*_a, **_k):
        pytest.fail("PATH must not be searched when CARREL_BIN_PANDOC is set")

    monkeypatch.setattr(adapters.shutil, "which", never)
    assert adapters.have("pandoc") is True
    assert adapters.require("pandoc") == str(exe)
    proc = adapters.run("pandoc", "anything")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "pandoc 99.0 (pinned)"
    assert adapters.version_of("pandoc") == "pandoc 99.0 (pinned)"


def test_override_expands_home(tmp_path, monkeypatch):
    exe = _fake_binary(tmp_path, "gpg", "gpg (fake) 9.9")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CARREL_BIN_GPG", "~/gpg")
    assert adapters.require("gpg") == str(exe)


def test_override_for_multi_candidate_adapter(tmp_path, monkeypatch):
    # magick tries ("magick", "convert") on PATH; the override wins outright
    exe = _fake_binary(tmp_path, "im7", "Version: ImageMagick 7.fake")
    monkeypatch.setenv("CARREL_BIN_MAGICK", str(exe))
    assert adapters.require("magick") == str(exe)


def test_override_ignored_for_other_adapters(tmp_path, monkeypatch):
    exe = _fake_binary(tmp_path, "x", "x")
    monkeypatch.setenv("CARREL_BIN_PANDOC", str(exe))
    assert adapters.have("qpdf") == (shutil.which("qpdf") is not None)


# --- doctor renders the override (spec 19 acceptance) ---------------------------


def test_doctor_json_marks_stale_override_missing(monkeypatch):
    from click.testing import CliRunner

    from carrel.cli import cli

    monkeypatch.setenv("CARREL_BIN_PANDOC", "/nonexistent")
    result = CliRunner().invoke(cli, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    (row,) = [a for a in report["adapters"] if a["name"] == "pandoc"]
    assert row["found"] is False and row["path"] is None
    assert row["override"] == {"var": "CARREL_BIN_PANDOC", "path": "/nonexistent"}
    assert "CARREL_BIN_PANDOC=/nonexistent not found" in row["install_hint"]
    assert "sudo apt install pandoc" in row["install_hint"]
    # human table names the override too
    human = CliRunner().invoke(cli, ["doctor"])
    assert human.exit_code == 0
    assert "via CARREL_BIN_PANDOC" in human.output


@needs("pandoc")
def test_doctor_reports_found_via_override(monkeypatch):
    from click.testing import CliRunner

    from carrel.cli import cli

    real = shutil.which("pandoc")
    monkeypatch.setenv("CARREL_BIN_PANDOC", real)
    result = CliRunner().invoke(cli, ["doctor", "--json"])
    report = json.loads(result.output)
    (row,) = [a for a in report["adapters"] if a["name"] == "pandoc"]
    assert row["found"] is True and row["path"] == real
    assert row["override"]["var"] == "CARREL_BIN_PANDOC"
    assert row["version"] and row["version"] != "?"
    human = CliRunner().invoke(cli, ["doctor"])
    assert "via CARREL_BIN_PANDOC" in human.output


def test_doctor_adapter_list_matches_registry():
    from carrel.commands.doctor import build_report

    names = [a["name"] for a in build_report()["adapters"]]
    assert names == list(ADAPTERS)
    assert "git" in names
    assert not (REMOVED_ADAPTERS & set(names))
    for row in build_report()["adapters"]:
        assert "override" in row  # key always present (None when unset)
