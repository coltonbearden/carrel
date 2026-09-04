"""carrel redact — remove sensitive strings from text files and PDFs.

Text types (txt/md/html/json/csv/xml) get plain regex replacement on the raw
text; JSON/XML outputs are re-parsed afterwards so a redaction can never ship
a broken file. PDFs get *true* redaction: every page is rasterized (pdftoppm,
200 dpi), tesseract's TSV word boxes are matched against the patterns (with
adjacent words joined per line so multi-word patterns work), matched boxes are
painted black, and the pages are reassembled into an image-only PDF — no text
layer survives. The result is verified with pdftotext when available.
"""

from __future__ import annotations

import functools
import json as jsonlib
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail, progress

RASTER_DPI = 200
BOX_PAD = 2  # px of padding around each blacked-out word box


# ------------------------------------------------------------------ patterns


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _cc_valid(match: re.Match) -> bool:
    digits = re.sub(r"[ -]", "", match.group(0))
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


# name -> (regex, validator) — validator may reject a raw regex hit (cc/Luhn)
BUILTINS: dict[str, tuple[str, Callable[[re.Match], bool] | None]] = {
    "email": (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", None),
    "phone": (r"(?<!\d)(?:\+?1[-. ])?(?:\(\d{3}\)[-. ]?|\d{3}[-. ])\d{3}[-. ]\d{4}(?!\d)", None),
    "ssn": (r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)", None),
    "ipv4": (
        r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)",
        None,
    ),
    "cc": (r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)", _cc_valid),
}


@dataclass
class Rule:
    name: str
    regex: re.Pattern
    validator: Callable[[re.Match], bool] | None = None

    def hits(self, text: str) -> list[re.Match]:
        return [m for m in self.regex.finditer(text) if self.validator is None or self.validator(m)]


def _compile_rules(patterns: tuple[str, ...], builtin_csv: str | None) -> list[Rule]:
    rules: list[Rule] = []
    if builtin_csv:
        for name in (n.strip() for n in builtin_csv.split(",") if n.strip()):
            if name not in BUILTINS:
                raise click.UsageError(
                    f"unknown --builtin {name!r} (choose from: {', '.join(BUILTINS)})"
                )
            pattern, validator = BUILTINS[name]
            rules.append(Rule(name, re.compile(pattern), validator))
    for pattern in patterns:
        try:
            rules.append(Rule(pattern, re.compile(pattern)))
        except re.error as e:
            raise click.UsageError(f"bad --pattern {pattern!r}: {e}") from e
    if not rules:
        raise click.UsageError("nothing to redact: pass --pattern REGEX and/or --builtin LIST")
    return rules


# --------------------------------------------------------------- text redact


def _redact_text(content: str, rules: list[Rule], replacement: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for rule in rules:
        n = 0

        def repl(m: re.Match[str], rule: Rule = rule) -> str:
            nonlocal n
            if rule.validator is not None and not rule.validator(m):
                return m.group(0)
            n += 1
            return replacement

        content = rule.regex.sub(repl, content)
        counts[rule.name] = n
    return content, counts


def _check_still_parses(text: str, ftype: FileType, replacement: str) -> None:
    """A redacted JSON/XML file must still parse — never ship a broken one."""
    try:
        if ftype is FileType.JSON:
            jsonlib.loads(text)
        elif ftype is FileType.XML:
            ET.fromstring(text)
    except (ValueError, ET.ParseError) as e:
        raise CarrelError(
            f"redaction would break {ftype.value} syntax ({e}); "
            f"pick a --replacement without structural characters "
            f"(current: {replacement!r})"
        ) from e


# ---------------------------------------------------------------- pdf redact


@dataclass
class _Word:
    text: str
    box: tuple[int, int, int, int]  # left, top, width, height


@dataclass
class _Line:
    words: list[_Word] = field(default_factory=list)

    def joined(self) -> tuple[str, list[tuple[int, int, _Word]]]:
        """Words joined by single spaces + (start, end, word) char spans."""
        spans: list[tuple[int, int, _Word]] = []
        parts: list[str] = []
        pos = 0
        for word in self.words:
            if parts:
                pos += 1  # the joining space
            spans.append((pos, pos + len(word.text), word))
            parts.append(word.text)
            pos += len(word.text)
        return " ".join(parts), spans


def _tsv_lines(png: Path) -> list[_Line]:
    """Tesseract word boxes for one page image, grouped into text lines."""
    proc = adapters.run("tesseract", str(png), "stdout", "tsv", timeout=300)
    if proc.returncode != 0:
        raise CarrelError(
            f"tesseract failed on {png.name} (rc={proc.returncode}): {(proc.stderr or '').strip()}"
        )
    lines: dict[tuple[str, ...], _Line] = {}
    for row in proc.stdout.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":  # level 5 = word
            continue
        text = cols[11].strip()
        if not text:
            continue
        key = tuple(cols[1:5])  # page, block, paragraph, line
        left, top, width, height = (int(v) for v in cols[6:10])
        lines.setdefault(key, _Line()).words.append(_Word(text, (left, top, width, height)))
    return list(lines.values())


def _redact_pdf(
    src: Path, dest: Path, rules: list[Rule], ctx: click.Context | None
) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    adapters.require("tesseract")  # exit 3 before any work if OCR is unavailable
    counts: dict[str, int] = {rule.name: 0 for rule in rules}
    page_counts: dict[str, int] = {}

    with tempfile.TemporaryDirectory(prefix="carrel-redact-") as td:
        prefix = Path(td) / "page"
        proc = adapters.run(
            "pdftoppm", "-r", str(RASTER_DPI), "-png", str(src), str(prefix), timeout=600
        )
        if proc.returncode != 0:
            raise CarrelError(
                f"pdftoppm failed (rc={proc.returncode}): {(proc.stderr or '').strip()}"
            )
        pngs = sorted(Path(td).glob("page-*.png"))
        if not pngs:
            raise CarrelInputError(f"{src}: pdftoppm produced no pages — empty or corrupt PDF?")

        pages: list[Image.Image] = []
        for page_no, png in enumerate(pngs, start=1):
            progress(f"redact: page {page_no}/{len(pngs)} …", ctx)
            img = Image.open(png).convert("RGB")
            draw = ImageDraw.Draw(img)
            hit_boxes: list[tuple[int, int, int, int]] = []
            for line in _tsv_lines(png):
                text, spans = line.joined()
                for rule in rules:
                    for m in rule.hits(text):
                        counts[rule.name] += 1
                        page_counts[str(page_no)] = page_counts.get(str(page_no), 0) + 1
                        hit_boxes += [w.box for a, b, w in spans if a < m.end() and b > m.start()]
            for left, top, width, height in hit_boxes:
                draw.rectangle(
                    (
                        max(0, left - BOX_PAD),
                        max(0, top - BOX_PAD),
                        left + width + BOX_PAD,
                        top + height + BOX_PAD,
                    ),
                    fill=(0, 0, 0),
                )
            pages.append(img)

        dest.parent.mkdir(parents=True, exist_ok=True)
        pages[0].save(
            dest, format="PDF", resolution=float(RASTER_DPI), save_all=True, append_images=pages[1:]
        )

    verified: bool | None = None
    if adapters.have("pdftotext"):
        proc = adapters.run("pdftotext", "-layout", str(dest), "-")
        remaining = proc.stdout if proc.returncode == 0 else ""
        leftovers = [rule.name for rule in rules if rule.hits(remaining)]
        if leftovers:
            raise CarrelError(
                f"redaction verification failed: {dest} still matches "
                f"{', '.join(leftovers)} via pdftotext"
            )
        verified = True

    return {"matches": counts, "pages": page_counts, "verified": verified}


# ----------------------------------------------------------------- CLI shell


def _handled(fn: Callable) -> Callable:
    """Convert CarrelError into a clean message + exit code (unless --debug)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = click.get_current_context(silent=True)
        try:
            return fn(*args, **kwargs)
        except CarrelError as e:
            if ctx is not None and ctx.obj and ctx.obj.get("debug"):
                raise
            fail(str(e), e.exit_code)

    return wrapper


def _human(record: dict[str, Any]) -> None:
    click.echo(f"redact: {record['src']}")
    for name, count in record["matches"].items():
        click.echo(f"  {name}: {count} match(es)")
    if record.get("pages"):
        per_page = ", ".join(f"p{p}: {n}" for p, n in record["pages"].items())
        click.echo(f"  per page: {per_page}")
    if record["total"] == 0:
        click.echo("  note: 0 matches — output is an unmodified copy")
    if record.get("verified"):
        click.echo("  verified: output no longer matches any pattern")
    click.echo(f"  wrote: {record['dest']}")


@click.command(name="redact")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--pattern",
    "patterns",
    multiple=True,
    metavar="REGEX",
    help="Custom regex to redact (repeatable).",
)
@click.option(
    "--builtin",
    "builtin_csv",
    metavar="LIST",
    help=f"Comma-separated builtins: {', '.join(BUILTINS)}.",
)
@click.option(
    "--replacement",
    default="█",
    show_default=True,
    help="Replacement text for matches (text files only).",
)
@click.option(
    "-o", "--out", type=click.Path(path_type=Path), help="Output file. Default: SRC.redacted.<ext>."
)
@click.option("--fail-empty", is_flag=True, help="Exit 5 when nothing matched.")
@click.option("--force", is_flag=True, help="Allow overwriting an existing output file.")
@click.pass_context
@_handled
def cmd(
    ctx: click.Context,
    src: Path,
    patterns: tuple[str, ...],
    builtin_csv: str | None,
    replacement: str,
    out: Path | None,
    fail_empty: bool,
    force: bool,
) -> None:
    """Redact sensitive strings from a text file or PDF.

    Text files get regex replacement (JSON/XML are re-parsed afterwards so
    they stay valid). PDFs are truly redacted: pages are rasterized, matched
    words are painted over, and the output carries no text layer at all.
    Requires tesseract for PDFs.
    """
    rules = _compile_rules(patterns, builtin_csv)
    ftype = detect_or_die(src)
    if ftype is not FileType.PDF and not ftype.is_text:
        raise CarrelInputError(f"redact supports text files and PDFs, got {ftype.value}: {src}")

    dest = out or src.with_name(f"{src.stem}.redacted{src.suffix}")
    if dest.exists() and not force:
        raise CarrelError(f"refusing to overwrite existing file: {dest} (pass --force)")

    record: dict[str, Any] = {"src": str(src), "dest": str(dest)}
    if ftype is FileType.PDF:
        record.update(_redact_pdf(src, dest, rules, ctx))
    else:
        try:
            content = src.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise CarrelInputError(f"{src} is not valid UTF-8 text: {e}") from e
        redacted, counts = _redact_text(content, rules, replacement)
        _check_still_parses(redacted, ftype, replacement)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(redacted, encoding="utf-8")
        record["matches"] = counts

    record["total"] = sum(record["matches"].values())
    emit(ctx, record, human=_human)
    if fail_empty and record["total"] == 0:
        fail("no matches for the requested patterns (--fail-empty)", ExitCode.EMPTY)
