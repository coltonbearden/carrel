"""carrel audiobook — narrate txt/md/pdf files into audio.

`audiobook_file()` is the library entry point (reused by the desk TUI);
the click command `cmd` is a thin wrapper around it.

Pipeline:

- text prep: txt/pdf go through the shared textextract spine; markdown is
  stripped for speech (headings → "Chapter: <title>." with pauses, fenced
  code → "[code omitted]", links → link text, images → alt text).
- engine: --engine auto prefers piper > edge-tts > espeak-ng (probed via
  the adapter registry); only espeak-ng is assumed to exist. espeak text
  is chunked (~4000 chars at sentence boundaries), synthesized to WAV
  pieces and concatenated with the stdlib wave module.
- encode: ffmpeg turns WAV into mp3/ogg at 128k with title/track metadata.
  `--format wav` works with espeak alone; a non-wav target without ffmpeg
  degrades with an install hint (exit 3).
- --split-chapters: markdown H1s (H2s as fallback) or the PDF outline
  produce one file per chapter, named OUT-NN-slug.EXT.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.adapters import MissingDependencyError
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, progress
from carrel.core.textextract import extract_text

FORMATS = ("mp3", "ogg", "wav")
ENGINES = ("auto", "espeak", "piper", "edge-tts")
DEFAULT_RATE = 170  # words per minute (espeak's unit)
CHUNK_CHARS = 4000  # espeak synthesis chunk size

_ENGINE_ADAPTER = {"espeak": "espeak-ng", "piper": "piper", "edge-tts": "edge-tts"}
_AUTO_ORDER = ("piper", "edge-tts", "espeak-ng")  # best voice first

# ------------------------------------------------------------ markdown prep

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^ {0,3}([-*_])( *\1){2,}\s*$")
_LIST_RE = re.compile(r"^\s{0,8}(?:[-*+]|\d{1,3}[.)])\s+")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_IMG_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<(?:https?|mailto):[^>]*>")
_CODE_RE = re.compile(r"`+([^`]*)`+")
_EMPH_RE = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _spoken_inline(text: str) -> str:
    """Strip inline markdown down to what a voice should say."""
    text = _IMG_RE.sub(lambda m: m.group(1), text)  # alt text (or nothing)
    text = _LINK_RE.sub(lambda m: m.group(1), text)  # link text, drop URL
    text = _AUTOLINK_RE.sub("", text)  # bare URLs are noise
    text = _CODE_RE.sub(lambda m: m.group(1), text)  # inline code as text
    for _ in range(2):  # nested **bold *em***
        text = _EMPH_RE.sub(lambda m: m.group(2), text)
    return re.sub(r"  +", " ", text).rstrip()


def md_to_speech(md_text: str) -> str:
    """Markdown → narration text. Blank lines are the pause markers."""
    out: list[str] = []
    fence: str | None = None
    for line in md_text.splitlines():
        stripped = line.strip()
        if fence:  # inside a code block
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            out += ["", "[code omitted]", ""]
            continue
        m = _HEADING_RE.match(line)
        if m:
            title = _spoken_inline(m.group(2)).strip()
            if title and title[-1] not in ".!?":
                title += "."
            out += ["", f"Chapter: {title}", ""]
            continue
        if _HR_RE.match(line):
            out.append("")
            continue
        line = _QUOTE_RE.sub("", line)
        line = _LIST_RE.sub("", line)
        out.append(_spoken_inline(line))
    # collapse blank runs so pauses stay single
    lines: list[str] = []
    blank = True
    for ln in out:
        if ln:
            lines.append(ln)
            blank = False
        elif not blank:
            lines.append("")
            blank = True
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def _split_level(
    lines: list[str],
    level: int,
    fallback_title: str,
) -> tuple[list[tuple[str, str]], int]:
    """Split markdown lines at headings of `level` (fence-aware).

    Returns (chapters as (title, body-md incl. heading line), headed count).
    """
    chapters: list[tuple[str, str]] = []
    cur_title: str | None = None
    cur: list[str] = []
    fence: str | None = None
    headed = 0

    def close() -> None:
        if cur_title is not None or any(ln.strip() for ln in cur):
            chapters.append((cur_title or fallback_title, "\n".join(cur)))

    for line in lines:
        stripped = line.strip()
        if fence:
            cur.append(line)
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            cur.append(line)
            continue
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == level:
            close()
            cur_title = _spoken_inline(m.group(2)).strip() or fallback_title
            cur = [line]
            headed += 1
            continue
        cur.append(line)
    close()
    return chapters, headed


def md_chapters(md_text: str, fallback_title: str) -> list[tuple[str, str]]:
    """Chapters of a markdown doc: split on H1s, else H2s, else one chapter."""
    lines = md_text.splitlines()
    for level in (1, 2):
        chapters, headed = _split_level(lines, level, fallback_title)
        if headed >= 2:
            return chapters
    return [(fallback_title, md_text)]


# ----------------------------------------------------------------- pdf prep


def _pdf_page_text(src: Path, first: int, last: int) -> str:
    proc = adapters.run("pdftotext", "-layout", "-f", str(first), "-l", str(last), str(src), "-")
    return proc.stdout if proc.returncode == 0 else ""


def pdf_chapters(src: Path) -> list[tuple[str, str]] | None:
    """Chapters from the PDF outline (top two levels); None when no outline."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(src))
        outline = reader.outline
    except Exception:  # noqa: BLE001 — pypdf raises assorted errors on odd outlines; fall back to whole-document
        return None

    entries: list[tuple[str, int]] = []

    def walk(items: list, depth: int) -> None:
        for item in items:
            if isinstance(item, list):  # children of the previous entry
                if depth < 2:
                    walk(item, depth + 1)
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:  # noqa: BLE001, S112 — unresolvable destination: skip this entry, keep the rest
                continue
            if page is None:
                continue
            title = str(getattr(item, "title", "") or "").strip()
            entries.append((title or f"Section {len(entries) + 1}", page))

    walk(outline or [], 1)
    if len(entries) < 2:
        return None
    entries.sort(key=lambda e: e[1])

    n_pages = len(reader.pages)
    chapters: list[tuple[str, str]] = []
    if entries[0][1] > 0:  # front matter before chapter 1
        pre = _pdf_page_text(src, 1, entries[0][1])
        if pre.strip():
            chapters.append((src.stem, pre))
    for i, (title, page) in enumerate(entries):
        last = entries[i + 1][1] if i + 1 < len(entries) else n_pages
        chapters.append((title, _pdf_page_text(src, page + 1, max(last, page + 1))))
    return chapters


# ------------------------------------------------------------------- engines


def _pick_engine(engine: str) -> str:
    """CLI engine choice → adapter name; auto falls through to espeak-ng."""
    if engine != "auto":
        name = _ENGINE_ADAPTER[engine]
        adapters.require(name)  # exit 3 with hint when absent
        return name
    for name in _AUTO_ORDER:
        if adapters.have(name):
            return name
    raise MissingDependencyError(adapters.ADAPTERS["espeak-ng"])


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split text into ≤limit-char chunks at sentence (then hard) boundaries."""
    chunks: list[str] = []
    cur = ""

    def add(piece: str, sep: str) -> None:
        nonlocal cur
        if cur and len(cur) + len(sep) + len(piece) > limit:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}{sep}{piece}" if cur else piece

    for para in re.split(r"\n{2,}", text):
        para = " ".join(para.split())
        if not para:
            continue
        first = True
        for sent in _SENT_RE.split(para):
            while len(sent) > limit:  # pathological run-on sentence
                add(sent[:limit], "\n\n" if first else " ")
                sent, first = sent[limit:], False
            if sent:
                add(sent, "\n\n" if first else " ")
                first = False
    if cur:
        chunks.append(cur)
    return chunks


def _concat_wavs(pieces: list[Path], dest: Path) -> None:
    """Append same-format WAV frames into dest (stdlib wave)."""
    with wave.open(str(dest), "wb") as out:
        params = None
        for piece in pieces:
            with wave.open(str(piece), "rb") as w:
                key = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                if params is None:
                    params = key
                    out.setparams(w.getparams())
                elif key != params:
                    raise CarrelError("cannot concatenate: WAV pieces disagree on audio parameters")
                out.writeframes(w.readframes(w.getnframes()))


def _tool_error(name: str, proc: Any) -> CarrelError:
    err = (proc.stderr or "").strip().splitlines()
    return CarrelError(f"{name} failed ({proc.returncode}): {err[-1] if err else '?'}")


def _synth_espeak(text: str, dest: Path, voice: str | None, rate: int) -> None:
    args = ["-s", str(rate)] + (["-v", voice] if voice else [])
    with tempfile.TemporaryDirectory(prefix="carrel-espeak-") as td:
        pieces: list[Path] = []
        for i, chunk in enumerate(chunk_text(text)):
            piece = Path(td) / f"piece-{i:04d}.wav"
            proc = adapters.run(
                "espeak-ng", *args, "--stdin", "-w", str(piece), input=chunk, timeout=600
            )
            if proc.returncode != 0 or not piece.exists():
                raise _tool_error("espeak-ng", proc)
            pieces.append(piece)
        if not pieces:
            raise CarrelError("nothing to synthesize (empty text)")
        _concat_wavs(pieces, dest)


def _synth_piper(text: str, dest: Path, voice: str | None, rate: int) -> None:
    # piper has no wpm; approximate via length_scale relative to the default
    args = (["-m", voice] if voice else []) + [
        "--length_scale",
        f"{DEFAULT_RATE / max(rate, 1):.2f}",
        "-f",
        str(dest),
    ]
    proc = adapters.run("piper", *args, input=text, timeout=1800)
    if proc.returncode != 0 or not dest.exists():
        raise _tool_error("piper (pass --voice /path/to/model.onnx)", proc)


def _synth_edge(text: str, dest: Path, voice: str | None, rate: int) -> None:
    # edge-tts emits mp3; decode to WAV so the shared encode step applies
    adapters.require("ffmpeg")
    pct = round((rate - DEFAULT_RATE) / DEFAULT_RATE * 100)
    with tempfile.TemporaryDirectory(prefix="carrel-edge-") as td:
        txt = Path(td) / "text.txt"
        txt.write_text(text)
        media = Path(td) / "edge.mp3"
        args = ["--file", str(txt), "--write-media", str(media), "--rate", f"{pct:+d}%"] + (
            ["--voice", voice] if voice else []
        )
        proc = adapters.run("edge-tts", *args, timeout=1800)
        if proc.returncode != 0 or not media.exists():
            raise _tool_error("edge-tts", proc)
        proc = adapters.run("ffmpeg", "-y", "-i", str(media), str(dest), timeout=1800)
        if proc.returncode != 0 or not dest.exists():
            raise _tool_error("ffmpeg", proc)


_SYNTH: dict[str, Callable[[str, Path, str | None, int], None]] = {
    "espeak-ng": _synth_espeak,
    "piper": _synth_piper,
    "edge-tts": _synth_edge,
}


# -------------------------------------------------------------- encode + IO


def _encode(wav: Path, dest: Path, fmt: str, title: str, track: int | None) -> None:
    if fmt == "wav":
        shutil.move(str(wav), dest)
        return
    codec = {"mp3": "libmp3lame", "ogg": "libvorbis"}[fmt]
    args = ["-y", "-i", str(wav), "-c:a", codec, "-b:a", "128k", "-metadata", f"title={title}"]
    if track is not None:
        args += ["-metadata", f"track={track}"]
    proc = adapters.run("ffmpeg", *args, str(dest), timeout=1800)
    if proc.returncode != 0 or not dest.exists():
        raise _tool_error("ffmpeg", proc)


def _duration_s(paths: list[Path]) -> float | None:
    if not adapters.have("ffprobe"):
        return None
    total = 0.0
    for p in paths:
        proc = adapters.run(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(p),
        )
        try:
            total += float(proc.stdout.strip())
        except ValueError:
            return None
    return round(total, 2)


def _slug(title: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "chapter"


def _prepare_chapters(src: Path, ftype: FileType, split: bool) -> list[tuple[str, str]]:
    """[(title, narration text)] — one entry unless splitting finds chapters."""
    if ftype is FileType.MD:
        raw = src.read_text(errors="replace")
        if split:
            parts = md_chapters(raw, src.stem)
            if len(parts) > 1:
                return [(title, md_to_speech(body)) for title, body in parts]
        return [(src.stem, md_to_speech(raw))]
    if ftype is FileType.PDF and split:
        chapters = pdf_chapters(src)
        if chapters and len(chapters) > 1:
            return chapters
    return [(src.stem, extract_text(src))]


def audiobook_file(
    src: Path | str,
    out: Path | str | None = None,
    *,
    voice: str | None = None,
    rate: int = DEFAULT_RATE,
    engine: str = "auto",
    split_chapters: bool = False,
    fmt: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Narrate one txt/md/pdf file; returns the JSON-shaped result dict.

    Raises CarrelInputError (exit 4) for unsupported input,
    MissingDependencyError (exit 3) when a needed binary is absent,
    CarrelError (exit 1) on tool failure.
    """
    src = Path(src)
    ftype = detect_or_die(src)
    if ftype not in (FileType.TXT, FileType.MD, FileType.PDF):
        raise CarrelInputError(
            f"cannot narrate {ftype.value} files: {src} (supported: txt, md, pdf)"
        )
    if engine not in ENGINES:
        raise CarrelInputError(f"unknown engine '{engine}' (choose from: {', '.join(ENGINES)})")
    if rate < 1:
        raise CarrelInputError(f"--rate must be positive (got {rate})")

    out = Path(out) if out is not None else None
    if fmt is None:
        fmt = out.suffix.lstrip(".").lower() if out and out.suffix else "mp3"
    if fmt not in FORMATS:
        raise CarrelInputError(
            f"unsupported audio format '{fmt}' (choose from: {', '.join(FORMATS)})"
        )
    if fmt != "wav" and not adapters.have("ffmpeg"):
        raise MissingDependencyError(adapters.ADAPTERS["ffmpeg"])

    engine_name = _pick_engine(engine)
    synth = _SYNTH[engine_name]

    chapters = _prepare_chapters(src, ftype, split_chapters)
    total_chars = sum(len(text) for _, text in chapters)
    if not any(text.strip() for _, text in chapters):
        raise CarrelInputError(f"no narratable text found in {src}")

    out = out or src.with_suffix(f".{fmt}")
    if out.suffix.lstrip(".").lower() != fmt:
        out = out.with_suffix(f".{fmt}")
    if out.parent != Path("."):
        out.parent.mkdir(parents=True, exist_ok=True)

    multi = len(chapters) > 1
    outputs: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="carrel-audiobook-") as td:
        for i, (title, text) in enumerate(chapters, start=1):
            dest = out.parent / f"{out.stem}-{i:02d}-{_slug(title)}.{fmt}" if multi else out
            if on_progress:
                on_progress(
                    f"[{i}/{len(chapters)}] narrating: {title} ({len(text)} chars, {engine_name})"
                )
            wav = Path(td) / f"chapter-{i:02d}.wav"
            synth(text, wav, voice, rate)
            _encode(wav, dest, fmt, title if multi else out.stem, i if multi else None)
            outputs.append(dest)

    return {
        "src": str(src),
        "outputs": [str(p) for p in outputs],
        "engine": engine_name,
        "duration_s": _duration_s(outputs),
        "chars": total_chars,
    }


# ----------------------------------------------------------------------- CLI


def _human(result: dict[str, Any]) -> None:
    for p in result["outputs"]:
        click.echo(f"{result['src']} -> {p}")
    dur = result["duration_s"]
    tail = f", {dur}s audio" if dur is not None else ""
    click.echo(f"engine: {result['engine']} ({result['chars']} chars{tail})")


@click.command(name="audiobook")
@click.argument("src", metavar="SRC", type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--output",
    "out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output audio file (default: SRC with audio extension).",
)
@click.option(
    "--voice", default=None, help="Voice: espeak voice name, piper model path, or edge-tts voice."
)
@click.option(
    "--rate",
    type=click.IntRange(min=80, max=450),
    default=DEFAULT_RATE,
    show_default=True,
    help="Speech rate in words per minute.",
)
@click.option(
    "--engine",
    type=click.Choice(ENGINES),
    default="auto",
    show_default=True,
    help="TTS engine; auto prefers piper > edge-tts > espeak-ng.",
)
@click.option(
    "--split-chapters",
    is_flag=True,
    help="One file per chapter (markdown H1/H2, or the PDF outline).",
)
@click.option("--force", is_flag=True, help="Overwrite existing output files.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(FORMATS),
    default=None,
    help="Audio format (default: from -o extension, else mp3).",
)
@click.pass_context
def cmd(
    ctx: click.Context,
    src: Path,
    out: Path | None,
    voice: str | None,
    rate: int,
    engine: str,
    split_chapters: bool,
    force: bool,
    fmt: str | None,
) -> None:
    """Narrate SRC (txt, md, pdf) into an audiobook.

    Markdown is stripped for speech: headings become spoken chapter
    announcements, code blocks become "[code omitted]", links read their
    text. mp3/ogg need ffmpeg; --format wav works with espeak-ng alone.
    Existing outputs are never overwritten without --force. With --json,
    prints {src, outputs, engine, duration_s, chars}.
    """
    try:
        if not force:
            resolved_fmt = fmt or (out.suffix.lstrip(".").lower() if out else "mp3")
            base = out or Path(src).with_suffix(f".{resolved_fmt}")
            clashes = [base] if base.exists() else []
            if split_chapters:
                clashes += sorted(base.parent.glob(f"{base.stem}-[0-9][0-9]-*.{resolved_fmt}"))
            if clashes:
                raise CarrelError(
                    f"refusing to overwrite existing output: {clashes[0]} (use --force)"
                )
        result = audiobook_file(
            src,
            out,
            voice=voice,
            rate=rate,
            engine=engine,
            split_chapters=split_chapters,
            fmt=fmt,
            on_progress=lambda msg: progress(msg, ctx),
        )
    except CarrelError as e:
        if ctx.obj and ctx.obj.get("debug"):
            raise
        click.echo(f"error: {e}", err=True)
        sys.exit(int(e.exit_code))
    emit(ctx, result, human=_human)
