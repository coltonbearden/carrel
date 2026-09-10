"""carrel intake — the inbox that files itself: read, name, file, index, tag.

One command for the whole accounting-inbox pipeline, with no shell in the
middle: for every file that lands in INBOX it reads the document's own fields
(`carrel fields`), finds its reference numbers (`carrel refs`), builds a name
from them (`carrel rename`'s template engine), moves it into a dated folder
under DEST (`core.fsops`, collision-safe, desk row following), then — when a
desk exists under --root — re-indexes it, saves the fields as desk metadata
and tags it with every reference it carries.

Dry-run is the default: `carrel intake ~/inbox --to ~/filed` prints the plan
and touches nothing. `--apply` performs it; `--watch` keeps going.

Nothing is ever destroyed (D-014). A scanned PDF is OCRed into a searchable
copy which becomes the filed document, and the untouched original is moved to
`DEST/_originals/<filed name>`; without ocrmypdf the file is filed as-is and
its record says `ocr: "unavailable"`.
"""

from __future__ import annotations

import functools
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import click

from carrel.commands.fields import KINDS, extract_fields, save_fields
from carrel.commands.refs import tag_for
from carrel.commands.rename import DEFAULT_TEMPLATE, UnresolvedPlaceholderError, build_name
from carrel.core import adapters
from carrel.core import patterns as pat
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
from carrel.core.fsops import move_file, uncollide
from carrel.core.output import (
    CarrelError,
    CarrelInputError,
    ExitCode,
    emit,
    fail,
    progress,
)
from carrel.core.textextract import extract_text

LAYOUTS: tuple[str, ...] = ("ym", "period", "flat")
ORIGINALS_DIR = "_originals"
_SCANNED_CHARS = 20  # a PDF with less extracted text than this is treated as a scan
SAVE_CONFIDENCE = ("high", "medium", "user")  # low fallbacks (mtime, file name) are not facts


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


def _root_of(ctx: click.Context) -> Path:
    return Path((ctx.obj or {}).get("root", ".")).resolve()


def _root_is_default(ctx: click.Context) -> bool:
    """True when the user did not pass a global --root: the desk then follows --to.

    Filing into a fresh directory is the normal case, and `--root` insists the
    directory already exists — so intake defaults its desk to the destination
    rather than the working directory.
    """
    parent = ctx.parent
    if parent is None:
        return True
    source = parent.get_parameter_source("root")
    return source is None or source.name == "DEFAULT"


# ------------------------------------------------------------------ layout


def fiscal_quarter(when: date, fiscal_start: int) -> tuple[int, int]:
    """(fiscal year, quarter 1-4) for `when` in a year starting in month `fiscal_start`.

    A calendar fiscal year (`--fiscal-start 1`) is the plain year. Otherwise the
    year is named after the calendar year it ends in, the convention US federal
    and most corporate calendars use: with a July start, 2026-08-03 is FY2027 Q1.
    """
    if not 1 <= fiscal_start <= 12:
        raise CarrelInputError(f"--fiscal-start must be a month 1-12 (got {fiscal_start})")
    offset = (when.month - fiscal_start) % 12
    year = when.year if fiscal_start == 1 or when.month < fiscal_start else when.year + 1
    return year, offset // 3 + 1


def destination_dir(dest_root: Path, when: date, layout: str, fiscal_start: int) -> Path:
    """`DEST/YYYY/MM`, `DEST/FY2027/Q1`, or `DEST` itself."""
    if layout == "flat":
        return dest_root
    if layout == "ym":
        return dest_root / f"{when.year:04d}" / f"{when.month:02d}"
    year, quarter = fiscal_quarter(when, fiscal_start)
    return dest_root / f"FY{year:04d}" / f"Q{quarter}"


def _document_date(fields: dict[str, Any], path: Path) -> date:
    value = fields.get("date", {}).get("value")
    if value:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            pass
    from datetime import datetime

    return datetime.fromtimestamp(path.stat().st_mtime).date()


# --------------------------------------------------------------------- ocr


def looks_scanned(path: Path, ftype: FileType) -> bool:
    """A PDF whose text layer is (nearly) empty — the shape `ocr` exists for."""
    if ftype is not FileType.PDF:
        return False
    try:
        return len(extract_text(path).strip()) < _SCANNED_CHARS
    except CarrelError:
        return False


def _ocr_copy(src: Path, workdir: Path) -> tuple[Path, str]:
    """(searchable copy, status) for a scanned PDF; the source is never modified."""
    from carrel.commands.ocr import ocr_file

    dest = workdir / src.name
    record = ocr_file(src, dest, to="pdf")
    return Path(record["dest"]), "ocred"


# ------------------------------------------------------------------ record


def _record(src: Path, action: str, **extra: Any) -> dict[str, Any]:
    return {"src": str(src), "dest": None, "action": action, **extra}


def process_file(
    src: Path,
    dest_root: Path,
    *,
    apply: bool,
    template: str = DEFAULT_TEMPLATE,
    layout: str = "ym",
    fiscal_start: int = 1,
    date_order: str = "mdy",
    ocr: bool | None = None,
    want_refs: bool = True,
    index: bool = True,
    tags: Sequence[str] = (),
    fallback: str | None = None,
    desk_root: Path | None = None,
    taken: set[Path] | None = None,
) -> dict[str, Any]:
    """Plan (or perform) the intake of one file; returns its record.

    `ocr` None means "OCR a scan when ocrmypdf is available"; True demands it
    (MissingDependencyError propagates, so the caller can exit 3 before moving
    anything); False never OCRs. `taken` collects planned destinations so a
    dry-run over several files does not plan the same name twice.
    """
    taken = taken if taken is not None else set()
    ftype = detect(src)
    if ftype is FileType.UNKNOWN:
        return _record(src, "skip", reason="unsupported file type")

    ocr_status = "not needed"
    original: Path | None = None
    filed_source = src
    tmpdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if ocr is not False and looks_scanned(src, ftype):
            if ocr is True:
                adapters.require("ocrmypdf")  # explicit request, missing binary → exit 3
            if adapters.have("ocrmypdf"):
                if apply:
                    tmpdir = tempfile.TemporaryDirectory(prefix="carrel-intake-")
                    filed_source, ocr_status = _ocr_copy(src, Path(tmpdir.name))
                    original = src
                else:
                    ocr_status = "would ocr"
                    original = src
            else:
                ocr_status = "unavailable"

        try:
            fields = extract_fields(filed_source, date_order=date_order, ocr=False)["fields"]
        except adapters.MissingDependencyError as e:
            # the same shape `index` and `refs` use: a per-file record, and exit 3
            # only when a missing tool is the reason nothing at all could be read
            return _record(src, "error", reason=str(e), kind="missing_dependency", ocr=ocr_status)
        except CarrelError as e:
            return _record(src, "error", reason=str(e), ocr=ocr_status)

        refs: list[dict[str, Any]] = []
        if want_refs:
            try:
                refs = pat.find_refs(extract_text(filed_source), None)
            except CarrelError:
                refs = []

        meta_now: dict[str, str] = {}
        if desk_root is not None and DeskDB.exists(desk_root):
            with DeskDB(desk_root) as db:
                meta_now = {r["key"]: r["value"] for r in db.meta_of(src)}
        try:
            name, sources = build_name(
                filed_source, template, fields=fields, meta=meta_now, refs=refs, fallback=fallback
            )
        except UnresolvedPlaceholderError as e:
            return _record(src, "skip", reason=str(e), ocr=ocr_status)
        except CarrelError as e:
            return _record(src, "error", reason=str(e), ocr=ocr_status)

        when = _document_date(fields, filed_source)
        target_dir = destination_dir(dest_root, when, layout, fiscal_start)
        dest = uncollide(target_dir / name, taken)
        taken.add(dest)

        record = _record(
            src,
            "filed" if apply else "plan",
            dest=str(dest),
            ocr=ocr_status,
            fields={k: v["value"] for k, v in fields.items()},
            refs=[{"kind": r["kind"], "value": r["value"]} for r in refs],
            sources=sources,
        )
        if original is not None:
            record["original"] = str(uncollide(dest_root / ORIGINALS_DIR / dest.name, taken))
            taken.add(Path(record["original"]))
        if not apply:
            return record

        move_file(filed_source, dest, desk_root=desk_root if original is None else None)
        if original is not None:
            move_file(original, Path(record["original"]), desk_root=desk_root)
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()

    _register(dest, record, fields, refs, tags, index=index, desk_root=desk_root)
    return record


def _register(
    dest: Path,
    record: dict[str, Any],
    fields: dict[str, Any],
    refs: Sequence[dict[str, Any]],
    tags: Sequence[str],
    *,
    index: bool,
    desk_root: Path | None,
) -> None:
    """Index the filed file, save its fields and tag its references.

    `intake --apply` is a write command, so it creates the desk under
    `desk_root` (the destination unless --root says otherwise) the way
    `carrel index` does — a filed archive that cannot be searched would miss
    the point. `--no-index` skips the full-text pass only; fields and tags are
    still recorded.
    """
    if desk_root is None:
        return
    if index:
        from carrel.commands.index import index_paths

        summary = index_paths(desk_root, [dest], update=True)
        record["indexed"] = summary["indexed"]
    keep = {k: v for k, v in fields.items() if v["confidence"] in SAVE_CONFIDENCE}
    wanted_tags = sorted(
        {*(tag_for(r) for r in refs), *(t.strip().lower() for t in tags if t.strip())}
    )
    with DeskDB(desk_root) as db:
        if keep:
            record["saved"] = save_fields(db, dest, {"fields": keep}, source="intake")
        if wanted_tags:
            db.add_tags(dest, list(wanted_tags))
            record["tags"] = wanted_tags
    _ = KINDS  # save_fields owns the kind mapping


# -------------------------------------------------------------------- walk


def inbox_files(inbox: Path, glob: str | None, recursive: bool) -> list[Path]:
    """Files waiting in the inbox: hidden entries and the originals folder are never taken."""
    entries = inbox.rglob("*") if recursive else inbox.iterdir()
    out: list[Path] = []
    for p in sorted(entries):
        if not p.is_file() or p.name.startswith("."):
            continue
        if ORIGINALS_DIR in p.parts:
            continue
        if glob and not _fnmatch(p.name, glob):
            continue
        out.append(p)
    return out


def _fnmatch(name: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(name, pattern)


def run_intake(
    inbox: Path | str,
    dest_root: Path | str,
    *,
    apply: bool = False,
    glob: str | None = None,
    recursive: bool = False,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Process every file waiting in `inbox`; see `process_file` for the options."""
    inbox = Path(inbox).resolve()
    dest_root = Path(dest_root).resolve()
    if not inbox.is_dir():
        raise CarrelInputError(f"no such directory: {inbox}")
    ctx = click.get_current_context(silent=True)
    taken: set[Path] = set()
    records: list[dict[str, Any]] = []
    for f in inbox_files(inbox, glob, recursive):
        progress(f"intake: {f}", ctx)
        records.append(process_file(f, dest_root, apply=apply, taken=taken, **kwargs))
    return records


# ------------------------------------------------------------------ output


def _human(applied: bool) -> Callable[[list[dict[str, Any]]], None]:
    def _print(records: list[dict[str, Any]]) -> None:
        filed = 0
        for rec in records:
            name = Path(rec["src"]).name
            if rec["action"] in ("skip", "error"):
                click.echo(f"{rec['action']:<5}  {name}  ({rec.get('reason')})")
                continue
            filed += 1
            verb = "filed" if applied else "plan "
            click.echo(f"{verb}  {name} -> {rec['dest']}")
            detail = []
            if rec.get("ocr") not in (None, "not needed"):
                detail.append(f"ocr: {rec['ocr']}")
            if rec.get("tags"):
                detail.append(f"tags: {', '.join(rec['tags'])}")
            if rec.get("saved"):
                detail.append(f"fields: {', '.join(rec['saved'])}")
            if detail:
                click.echo(f"         {' · '.join(detail)}")
        if applied:
            click.echo(f"{filed} file(s) filed.")
        else:
            click.echo(f"dry-run: {filed} file(s) would be filed — re-run with --apply.")

    return _print


@click.command(name="intake")
@click.argument("inbox", type=click.Path(path_type=Path))
@click.option(
    "--to",
    "dest_root",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Where filed documents land (created if missing).",
)
@click.option(
    "--apply/--dry-run",
    "apply_",
    default=False,
    help="Perform the intake. Default is a dry-run that only prints the plan.",
)
@click.option(
    "--watch",
    "watch_",
    is_flag=True,
    help="Keep watching INBOX and file what arrives (implies --apply).",
)
@click.option("--once", is_flag=True, help="With --watch: stop after the first batch.")
@click.option(
    "--timeout",
    "timeout_",
    type=click.FloatRange(min_open=True, min=0),
    default=None,
    metavar="SECS",
    help="With --watch: stop after SECS.",
)
@click.option(
    "--glob",
    "glob_",
    default=None,
    metavar="PATTERN",
    help="Only take files whose name matches (e.g. '*.pdf').",
)
@click.option("--recursive", is_flag=True, help="Take files from subdirectories of INBOX too.")
@click.option(
    "--stable",
    type=click.FloatRange(min_open=True, min=0),
    default=2.0,
    show_default=True,
    metavar="SECS",
    help="With --watch: wait until a file's size and mtime hold still for SECS.",
)
@click.option(
    "--template",
    default=DEFAULT_TEMPLATE,
    show_default=True,
    help="Name template (see `carrel rename --help` for the placeholders).",
)
@click.option(
    "--by",
    "layout",
    type=click.Choice(LAYOUTS),
    default="ym",
    show_default=True,
    help="Folder layout under --to: ym = YYYY/MM, period = FY<year>/Q<n>, flat = no subfolders.",
)
@click.option(
    "--fiscal-start",
    type=click.IntRange(1, 12),
    default=1,
    show_default=True,
    metavar="MM",
    help="With --by period: the month the fiscal year starts in.",
)
@click.option(
    "--date-order",
    type=click.Choice(["mdy", "dmy"]),
    default="mdy",
    show_default=True,
    help="How to read an ambiguous slashed date in the document.",
)
@click.option(
    "--ocr/--no-ocr",
    "ocr_",
    default=None,
    help="Force or forbid OCR of scanned PDFs. Default: OCR them when ocrmypdf is installed.",
)
@click.option(
    "--refs/--no-refs",
    "want_refs",
    default=True,
    show_default=True,
    help="Find reference numbers and tag the filed file with them.",
)
@click.option(
    "--index/--no-index",
    "index_",
    default=True,
    show_default=True,
    help="Re-index the filed file in the desk under --root.",
)
@click.option(
    "--tag",
    "tags",
    multiple=True,
    metavar="TAG",
    help="Extra tag for every filed file (repeatable).",
)
@click.option(
    "--fallback",
    default=None,
    metavar="TEXT",
    help="Use TEXT for a name placeholder that has no value instead of skipping the file.",
)
@click.option("--fail-empty", is_flag=True, help="Exit 5 when there was nothing to file.")
@click.pass_context
@_handled
def cmd(
    ctx: click.Context,
    inbox: Path,
    dest_root: Path,
    apply_: bool,
    watch_: bool,
    once: bool,
    timeout_: float | None,
    glob_: str | None,
    recursive: bool,
    stable: float,
    template: str,
    layout: str,
    fiscal_start: int,
    date_order: str,
    ocr_: bool | None,
    want_refs: bool,
    index_: bool,
    tags: tuple[str, ...],
    fallback: str | None,
    fail_empty: bool,
) -> None:
    """File everything waiting in INBOX into --to, named after what the documents say.

    Per file: read its fields (vendor, invoice number, dates, totals), find its
    reference numbers, build a name from the --template, move it into
    --to/YYYY/MM (or FY<year>/Q<n> with --by period), then re-index it, save
    the fields as desk metadata and tag it with every reference — all against
    the desk under the global --root (default: --to).

    Scanned PDFs are OCRed into a searchable copy which becomes the filed
    document; the untouched original moves to --to/_originals. Nothing is
    overwritten (colliding names get -1, -2, … suffixes) and nothing is
    deleted. JSON: [{src, dest, action: plan|filed|skip|error, fields, refs,
    tags, ocr, reason}]. Exit 3 when a missing optional binary is the reason
    nothing could be read at all, 1 when some files errored during --apply,
    5 with --fail-empty when there was nothing to file.
    """
    inbox = inbox.resolve()
    if not inbox.is_dir():
        raise CarrelInputError(f"no such directory: {inbox}")
    if watch_:
        apply_ = True
    dest_root = dest_root.resolve()
    if apply_:
        dest_root.mkdir(parents=True, exist_ok=True)
    desk_root = dest_root if _root_is_default(ctx) else _root_of(ctx)
    if inbox == dest_root:
        raise click.UsageError("INBOX and --to must be different directories")

    options: dict[str, Any] = {
        "template": template,
        "layout": layout,
        "fiscal_start": fiscal_start,
        "date_order": date_order,
        "ocr": ocr_,
        "want_refs": want_refs,
        "index": index_,
        "tags": tags,
        "fallback": fallback,
        "desk_root": desk_root,
    }
    records = run_intake(inbox, dest_root, apply=apply_, glob=glob_, recursive=recursive, **options)
    if watch_:
        records += _watch_loop(
            ctx,
            inbox,
            dest_root,
            options,
            glob=glob_,
            recursive=recursive,
            stable=stable,
            once=once,
            timeout=timeout_,
        )
    emit(ctx, records, human=_human(applied=apply_))
    if fail_empty and not records:
        fail("nothing to file (--fail-empty)", ExitCode.EMPTY)
    missing = [r for r in records if r.get("kind") == "missing_dependency"]
    if missing and len(missing) == len(records):
        fail(
            f"nothing filed — {len(missing)} file(s) need a missing tool:\n{missing[0]['reason']}",
            ExitCode.MISSING_DEP,
        )
    if apply_ and any(r["action"] == "error" for r in records):
        fail("some files could not be filed (see the records)", ExitCode.ERROR)


def _watch_loop(
    ctx: click.Context,
    inbox: Path,
    dest_root: Path,
    options: dict[str, Any],
    *,
    glob: str | None,
    recursive: bool,
    stable: float,
    once: bool,
    timeout: float | None,
) -> list[dict[str, Any]]:
    """Keep filing what arrives, waiting for each file to stop changing first."""
    from watchdog.observers import Observer

    from carrel.commands.watch import _make_handler, _Watcher

    watcher = _Watcher(
        on={"created", "modified"},
        glob=glob,
        debounce_ms=500,
        runs=(),
        json_lines=False,
        stable=stable,
    )
    observer = Observer()
    observer.schedule(_make_handler(watcher), str(inbox), recursive=recursive)
    progress(f"intake watching {inbox} -> {dest_root} — Ctrl-C to stop", ctx)
    deadline = time.monotonic() + timeout if timeout is not None else None
    records: list[dict[str, Any]] = []
    taken: set[Path] = set()
    observer.start()
    try:
        while not watcher.stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            for _event, path in watcher.drain():
                if not path.is_file() or ORIGINALS_DIR in path.parts:
                    continue
                progress(f"intake: {path}", ctx)
                record = process_file(path, dest_root, apply=True, taken=taken, **options)
                records.append(record)
                progress(
                    f"{record['action']:<5}  {path.name}"
                    f"{' -> ' + str(record['dest']) if record.get('dest') else ''}",
                    ctx,
                )
                if once:
                    watcher.stop.set()
            watcher.stop.wait(0.05)
    except KeyboardInterrupt:
        progress("stopped", ctx)
    finally:
        observer.stop()
        observer.join(timeout=5)
    return records
