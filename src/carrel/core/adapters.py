"""Single adapter layer for every external binary carrel touches.

Command modules never call subprocess directly — they use have()/require()/run().
`carrel doctor` renders this registry as the capability report.

Resolution order for an adapter (D-008): the `CARREL_BIN_<NAME>` environment
variable, when set, names the exact binary to use and PATH is not searched;
otherwise the first of `Adapter.binaries` found on PATH wins. A set-but-missing
override counts as missing (never a silent fallback) and the error names it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from carrel.core.output import CarrelError, ExitCode


class MissingDependencyError(CarrelError):
    exit_code = ExitCode.MISSING_DEP

    def __init__(self, adapter: Adapter) -> None:
        self.adapter = adapter
        override = adapter.override()
        where = (
            f" (override {adapter.env_var}={override} not found)" if override is not None else ""
        )
        super().__init__(
            f"'{adapter.name}' is required for this operation but was not found{where}.\n"
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


#: How to install a package on each platform, most specific first. `apt`, `brew`
#: and `winget` hold the *package name* for that manager; `anywhere` is one
#: cross-platform command (pipx) that makes the other three moot; `url` is the
#: vendor page for a binary no manager on any platform packages.
#:
#: Every name here was resolved against the real registry before it was written
#: down — `formulae.brew.sh/api/formula/<n>.json` for brew, `winget search` for
#: winget — because a confidently wrong package name costs a user more than no
#: hint at all: `apt install poppler` and `brew install poppler-utils` both fail,
#: and neither says why.
@dataclass(frozen=True, slots=True)
class Hints:
    apt: str | None = None
    brew: str | None = None
    winget: str | None = None
    anywhere: str | None = None
    url: str | None = None


#: the binary that proves a package manager is usable here
_MANAGER_BIN = {"apt": "apt", "brew": "brew", "winget": "winget"}
#: which manager to name first, by platform
_MANAGER_ORDER = {
    "darwin": ("brew", "winget", "apt"),
    "win32": ("winget", "brew", "apt"),
}
_DEFAULT_ORDER = ("apt", "brew", "winget")
_INSTALL_CMD = {
    "apt": "sudo apt install {}",
    "brew": "brew install {}",
    "winget": "winget install --id {}",
}


def render_hint(hints: Hints, name: str) -> str:
    """The install line to show *here*: this platform's manager, then any usable one.

    Picked at render time rather than baked in, so one wheel serves every
    platform. A manager actually on PATH wins; failing that the platform's
    conventional one is still named, because "install Homebrew, then this" is a
    better answer than silence.
    """
    order = _MANAGER_ORDER.get(sys.platform, _DEFAULT_ORDER)
    # a manager actually on PATH first — a WSL box with brew, a Mac with apt via
    # a port tree — since that is a command the user can run right now
    for manager in order:
        if getattr(hints, manager) and shutil.which(_MANAGER_BIN[manager]):
            return _INSTALL_CMD[manager].format(getattr(hints, manager))
    # else the platform's *own* manager, if it packages this at all: "install
    # Homebrew, then this" is a good answer on a Mac, and `brew install` is a
    # useless one on Windows, so the fallback never crosses platforms.
    primary = order[0]
    if getattr(hints, primary):
        return _INSTALL_CMD[primary].format(getattr(hints, primary))
    # `anywhere` is the fallback, not the first choice: `weasyprint` has a Debian
    # package and a pipx one, and on Debian `apt` is the better answer — pipx is
    # what to say on the platform where nothing native exists.
    if hints.anywhere:
        return hints.anywhere
    if hints.url:
        return f"no package for {sys.platform} — build or download from {hints.url}"
    return f"install '{name}' and ensure it is on PATH"


@dataclass(frozen=True)
class Adapter:
    name: str
    binaries: tuple[str, ...]
    version_args: tuple[str, ...]
    hints: Hints
    purpose: str

    @property
    def install_hint(self) -> str:
        """This platform's install line (see `render_hint`)."""
        return render_hint(self.hints, self.name)

    @property
    def env_var(self) -> str:
        """`CARREL_BIN_<NAME>` — the override variable for this adapter (D-008)."""
        return "CARREL_BIN_" + self.name.upper().replace("-", "_")

    def override(self) -> str | None:
        """The pinned binary path from the environment, or None when unset/empty."""
        value = os.environ.get(self.env_var, "").strip()
        return value or None

    def resolve(self) -> str | None:
        override = self.override()
        if override is not None:
            # exact path only — a stale override must never fall back to PATH
            path = Path(override).expanduser()
            if _is_executable(path):
                return str(path)
            return None
        for candidate in self.binaries:
            found = shutil.which(candidate)
            if found:
                return found
        return None


def _is_executable(path: Path) -> bool:
    """True when `path` is a file the OS would actually run.

    `os.access(X_OK)` is plain existence on Windows, which would let a stale
    override that points at a README count as found (the silent fallback
    D-008 forbids). There, executability is the PATHEXT suffix set — the same
    rule `shutil.which` applies.
    """
    if not path.is_file():
        return False
    if os.name != "nt":
        return os.access(path, os.X_OK)
    pathext = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return path.suffix.lower() in {ext.lower() for ext in pathext.split(os.pathsep) if ext}


def _a(
    name: str,
    purpose: str,
    hints: Hints,
    *,
    binaries: tuple[str, ...] | None = None,
    version_args: tuple[str, ...] = ("--version",),
) -> Adapter:
    return Adapter(name, binaries or (name,), version_args, hints, purpose)


#: poppler ships pdftotext, pdftoppm and pdfimages as one package everywhere.
_POPPLER = Hints(apt="poppler-utils", brew="poppler", winget="oschwartz10612.Poppler")
_FFMPEG = Hints(apt="ffmpeg", brew="ffmpeg", winget="Gyan.FFmpeg")

ADAPTERS: dict[str, Adapter] = {
    a.name: a
    for a in [
        _a(
            "pandoc",
            "document conversion hub (md/html/txt…)",
            Hints(apt="pandoc", brew="pandoc", winget="JohnMacFarlane.Pandoc"),
        ),
        _a("pdftotext", "PDF text extraction", _POPPLER, version_args=("-v",)),
        _a("pdftoppm", "PDF page rasterization / thumbnails", _POPPLER, version_args=("-v",)),
        _a("pdfimages", "extract embedded PDF images", _POPPLER, version_args=("-v",)),
        _a(
            "qpdf",
            "PDF surgery (linearize/decrypt)",
            Hints(apt="qpdf", brew="qpdf", winget="QPDF.QPDF"),
        ),
        # a Python package: pipx serves every platform and no winget entry exists
        _a(
            "weasyprint",
            "HTML/CSS → PDF rendering",
            Hints(apt="weasyprint", brew="weasyprint", anywhere="pipx install weasyprint"),
        ),
        _a(
            "tesseract",
            "OCR engine",
            Hints(apt="tesseract-ocr", brew="tesseract", winget="UB-Mannheim.TesseractOCR"),
        ),
        _a(
            "ocrmypdf",
            "add OCR text layer to PDFs",
            Hints(apt="ocrmypdf", brew="ocrmypdf", anywhere="pipx install ocrmypdf"),
        ),
        _a(
            "magick",
            "ImageMagick image operations",
            Hints(apt="imagemagick", brew="imagemagick", winget="ImageMagick.ImageMagick"),
            binaries=("magick", "convert"),
        ),
        _a(
            "exiftool",
            "deep metadata inspection",
            Hints(apt="libimage-exiftool-perl", brew="exiftool", winget="OliverBetz.ExifTool"),
            version_args=("-ver",),
        ),
        _a("ffmpeg", "audio encoding (audiobooks)", _FFMPEG, version_args=("-version",)),
        _a("ffprobe", "media metadata (durations)", _FFMPEG, version_args=("-version",)),
        # no winget package: the vendor page is the honest answer
        _a(
            "icotool",
            ".ico build/extract",
            Hints(apt="icoutils", brew="icoutils", url="https://www.nongnu.org/icoutils/"),
        ),
        _a(
            "espeak-ng",
            "text-to-speech (baseline voice)",
            Hints(apt="espeak-ng", brew="espeak-ng", winget="eSpeak-NG.eSpeak-NG"),
        ),
        _a(
            "piper",
            "text-to-speech (natural voice, preferred if present)",
            Hints(anywhere="pipx install piper-tts"),
        ),
        _a(
            "edge-tts",
            "text-to-speech (cloud, preferred if present)",
            Hints(anywhere="pipx install edge-tts"),
        ),
        _a(
            "gpg",
            "detached signatures for manifests",
            Hints(apt="gnupg", brew="gnupg", winget="GnuPG.Gpg4win"),
        ),
        _a(
            "git",
            "changed-file lists for pack --since/--changed",
            Hints(apt="git", brew="git", winget="Git.Git"),
        ),
        _a(
            "readpst",
            "Outlook .pst/.ost export → eml or mbox (mail pst)",
            Hints(apt="pst-utils", brew="libpst", url="https://www.five-ten-sg.com/libpst/"),
            version_args=("-V",),
        ),
    ]
}


def _lookup(name: str) -> Adapter:
    """Registered adapter, or an ad-hoc one so unknown names still fail with a hint."""
    return ADAPTERS.get(name) or _a(name, "unregistered tool", Hints())


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
    drop_env: Sequence[str] = (),
) -> subprocess.CompletedProcess:
    """Run an adapter binary. check=False — callers inspect returncode.

    `drop_env` removes variables from the child's environment. It exists for
    `git`, which lets `GIT_DIR` in the environment override an explicit `-C`:
    carrel invoked from a git hook or `git rebase -x` would otherwise be told
    about the hook's repository no matter which directory it asked about.
    """
    path = require(name)
    text = not binary
    if input is not None and text and isinstance(input, bytes):
        input = input.decode()
    env = None
    if drop_env:
        dropped = set(drop_env)
        env = {k: v for k, v in os.environ.items() if k not in dropped}
    try:
        return subprocess.run(
            [path, *args],
            input=input,
            capture_output=True,
            text=text,
            # every tool here speaks UTF-8. Without this, `text=True` decodes
            # with locale.getencoding() — cp1252 on a stock Windows box — so a
            # PDF containing "café" came back from pdftotext as "cafÃ©".
            encoding="utf-8" if text else None,
            errors="replace" if text else None,  # tool output is never allowed to crash us
            timeout=timeout,
            check=False,
            env=env,
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
