"""Single adapter layer for every external binary carrel touches.

Command modules never call subprocess directly — they use have()/require()/run().
`carrel doctor` renders this registry as the capability report.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from carrel.core.output import CarrelError, ExitCode


class MissingDependencyError(CarrelError):
    exit_code = ExitCode.MISSING_DEP

    def __init__(self, adapter: Adapter) -> None:
        self.adapter = adapter
        super().__init__(
            f"'{adapter.name}' is required for this operation but was not found.\n"
            f"  purpose: {adapter.purpose}\n"
            f"  install: {adapter.install_hint}"
        )


class ToolTimeoutError(CarrelError):
    """An external binary exceeded its timeout (exit 1 with the binary named)."""

    def __init__(self, name: str, timeout: float) -> None:
        self.tool = name
        self.timeout = timeout
        super().__init__(
            f"'{name}' timed out after {timeout:g}s — try a smaller input, "
            "or re-run with --debug to see the command"
        )


@dataclass(frozen=True)
class Adapter:
    name: str
    binaries: tuple[str, ...]
    version_args: tuple[str, ...]
    install_hint: str
    purpose: str

    def resolve(self) -> str | None:
        for candidate in self.binaries:
            path = shutil.which(candidate)
            if path:
                return path
        return None


def _a(
    name: str,
    purpose: str,
    hint: str,
    *,
    binaries: tuple[str, ...] | None = None,
    version_args: tuple[str, ...] = ("--version",),
) -> Adapter:
    return Adapter(name, binaries or (name,), version_args, hint, purpose)


ADAPTERS: dict[str, Adapter] = {
    a.name: a
    for a in [
        _a("pandoc", "document conversion hub (md/html/txt…)", "sudo apt install pandoc"),
        _a(
            "pdftotext",
            "PDF text extraction",
            "sudo apt install poppler-utils",
            version_args=("-v",),
        ),
        _a(
            "pdftoppm",
            "PDF page rasterization / thumbnails",
            "sudo apt install poppler-utils",
            version_args=("-v",),
        ),
        _a(
            "pdfimages",
            "extract embedded PDF images",
            "sudo apt install poppler-utils",
            version_args=("-v",),
        ),
        _a("qpdf", "PDF surgery (linearize/decrypt)", "sudo apt install qpdf"),
        _a("gs", "PDF render/compress, ICC profiles", "sudo apt install ghostscript"),
        _a("weasyprint", "HTML/CSS → PDF rendering", "sudo apt install weasyprint"),
        _a("tesseract", "OCR engine", "sudo apt install tesseract-ocr"),
        _a("ocrmypdf", "add OCR text layer to PDFs", "sudo apt install ocrmypdf"),
        _a(
            "magick",
            "ImageMagick image operations",
            "sudo apt install imagemagick",
            binaries=("magick", "convert"),
        ),
        _a(
            "exiftool",
            "deep metadata inspection",
            "sudo apt install libimage-exiftool-perl",
            version_args=("-ver",),
        ),
        _a(
            "ffmpeg",
            "audio encoding (audiobooks)",
            "sudo apt install ffmpeg",
            version_args=("-version",),
        ),
        _a(
            "ffprobe",
            "media metadata (durations)",
            "sudo apt install ffmpeg",
            version_args=("-version",),
        ),
        _a("pngquant", "PNG optimization", "sudo apt install pngquant"),
        _a("icotool", ".ico build/extract", "sudo apt install icoutils"),
        _a("jq", "JSON processing", "sudo apt install jq"),
        _a("mlr", "CSV/TSV/JSON transforms (miller)", "sudo apt install miller"),
        _a("rg", "fast content search (ripgrep)", "sudo apt install ripgrep"),
        _a("fd", "fast file finding", "sudo apt install fd-find", binaries=("fd", "fdfind")),
        _a("sqlite3", "SQLite CLI (index db is stdlib; CLI optional)", "sudo apt install sqlite3"),
        _a(
            "inotifywait",
            "filesystem event tap (watch fallback)",
            "sudo apt install inotify-tools",
            version_args=("--help",),
        ),
        _a("espeak-ng", "text-to-speech (baseline voice)", "sudo apt install espeak-ng"),
        _a(
            "piper",
            "text-to-speech (natural voice, preferred if present)",
            "pipx install piper-tts",
        ),
        _a("edge-tts", "text-to-speech (cloud, preferred if present)", "pipx install edge-tts"),
        _a("gpg", "detached signatures for manifests", "sudo apt install gnupg"),
        _a(
            "claude",
            "Claude Code CLI (agent workflows, marketplace)",
            "see https://code.claude.com/docs",
        ),
    ]
}


def _lookup(name: str) -> Adapter:
    """Registered adapter, or an ad-hoc one so unknown names still fail with a hint."""
    return ADAPTERS.get(name) or _a(
        name, "unregistered tool", f"install '{name}' and ensure it is on PATH"
    )


def have(name: str) -> bool:
    return _lookup(name).resolve() is not None


def require(name: str) -> str:
    adapter = _lookup(name)
    path = adapter.resolve()
    if path is None:
        raise MissingDependencyError(adapter)
    return path


def run(
    name: str,
    *args: str,
    input: bytes | str | None = None,
    timeout: int = 120,
    binary: bool = False,
) -> subprocess.CompletedProcess:
    """Run an adapter binary. check=False — callers inspect returncode."""
    path = require(name)
    text = not binary
    if input is not None and text and isinstance(input, bytes):
        input = input.decode()
    try:
        return subprocess.run(
            [path, *args],
            input=input,
            capture_output=True,
            text=text,
            errors="replace" if text else None,  # tool output is never allowed to crash us
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ToolTimeoutError(name, timeout) from e


def version_of(name: str) -> str | None:
    adapter = _lookup(name)
    if adapter.resolve() is None:
        return None
    try:
        proc = run(name, *adapter.version_args, timeout=15)
    except (CarrelError, OSError, ValueError, subprocess.SubprocessError):
        return "?"
    out = (proc.stdout or proc.stderr or "").strip().splitlines()
    return out[0][:80] if out else "?"
