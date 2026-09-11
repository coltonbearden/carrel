"""carrel refs — find reference numbers in files and link the files that share them.

Kinds come from `core.patterns`, the registry `redact --builtin` draws from
too: label-driven document references (invoice, po, order, check, account,
tracking, ticket) and self-describing identifiers with check digits (iban,
routing, ein, vat, isbn, gtin, doi, ups, usps). PII kinds are available only
when named with --kind. Text comes from `core.textextract`, so every supported
type works — PDFs report page numbers (pdftotext separates pages with form
feeds), everything else line numbers.

`--tag` writes `ref:<kind>:<value>` tags into the desk db under --root, which
is what makes `tag find ref:invoice:inv-2026-0042` and `search --tag …` link an
invoice PDF to the remittance email and the bank export that mention it.
`--link` prints that grouping directly, without touching the desk.

`scan_refs()` / `link_refs()` are the library entry points (MCP `carrel_refs`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click

from carrel.core import patterns as pat
from carrel.core.adapters import MissingDependencyError
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect
from carrel.core.output import (
    CarrelError,
    CarrelInputError,
    ExitCode,
    emit,
    fail,
    handled,
    progress,
    root_of,
)
from carrel.core.textextract import extract_text


def tag_for(ref: dict[str, Any]) -> str:
    """`ref:<kind>:<value>` — lower-case, whitespace squeezed out (a tag has no spaces)."""
    value = re.sub(r"\s+", "", str(ref["value"]))
    return f"ref:{ref['kind']}:{value}".lower()


def _candidates(paths: Sequence[Path], *, ocr: bool, root: Path | None) -> list[Path]:
    """Explicit files as given; directories walked like `index` (hidden/ignored skipped).

    Every path is checked before anything is scanned, so a typo in the last
    argument fails the run (exit 4) without partial work. The `.gitignore`
    rules of the ancestors up to `root` (or the repo root) seed the walk, as
    `index_paths` does, so `refs repo/sub` honours `repo/.gitignore`.
    """
    from carrel.commands.index import _walk
    from carrel.core.ignore import ancestor_ignores

    out: list[Path] = []
    for p in paths:
        if not p.exists():
            raise CarrelInputError(f"no such path: {p}")
        if p.is_file():
            out.append(p)
            continue
        for f in _walk(p, ancestor_ignores(p.resolve(), root)):
            ftype = detect(f)
            if ftype is FileType.UNKNOWN or (ftype.is_image and not ocr):
                continue
            out.append(f)
    return out


candidate_files = _candidates  # shared with `fields` and `rename`


def refs_in_file(
    path: Path, chosen: Sequence[pat.Pattern], *, ocr: bool = False
) -> list[dict[str, Any]]:
    """`find_refs` over the file's extracted text (raises like `extract_text`)."""
    return pat.find_refs(extract_text(path, ocr=ocr), chosen)


def scan_refs(
    paths: Sequence[Path | str],
    *,
    kinds: Sequence[str] | None = None,
    extra: Sequence[str] = (),
    ocr: bool = False,
    tag_root: Path | str | None = None,
    root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """One record per scanned file: {path, refs: [...]}, plus `tags` when tagging.

    `kinds` are registry names (default: every reference + identifier kind);
    `extra` are `NAME=REGEX` specs. With `tag_root`, every reference becomes a
    `ref:<kind>:<value>` tag on the file in the desk under that root — written
    in one short transaction after the scan, so a long OCR run never holds the
    desk locked and a failed run leaves no half-written tags. `root` bounds the
    ancestor `.gitignore` walk (default: the git repo root). A file whose text
    cannot be extracted yields {path, refs: [], error, kind} with kind
    `missing_dependency` (a binary is absent), `bad_input` or `error`, so one
    bad file never aborts the scan. A path that does not exist raises
    CarrelInputError before anything is scanned.
    """
    chosen = pat.resolve_kinds(kinds) + [pat.parse_extra(e) for e in extra]
    bound = Path(root).resolve() if root is not None else None
    targets = _candidates([Path(p) for p in paths], ocr=ocr, root=bound)
    ctx = click.get_current_context(silent=True)
    records: list[dict[str, Any]] = []
    for f in targets:
        progress(f"refs: {f}", ctx)
        record: dict[str, Any] = {"path": str(f), "refs": []}
        try:
            record["refs"] = refs_in_file(f, chosen, ocr=ocr)
        except MissingDependencyError as e:
            record.update({"error": str(e), "kind": "missing_dependency"})
        except CarrelInputError as e:
            record.update({"error": str(e), "kind": "bad_input"})
        except CarrelError as e:  # e.g. a tool timeout: report, keep scanning
            record.update({"error": str(e), "kind": "error"})
        except Exception as e:  # noqa: BLE001 — an unreadable/odd file (PermissionError, csv.Error, …) is a record, never an abort
            record.update({"error": f"{e.__class__.__name__}: {e}", "kind": "error"})
        if tag_root is not None and record["refs"]:
            record["tags"] = sorted({tag_for(r) for r in record["refs"]})
        records.append(record)
    if tag_root is not None:
        tagged = [r for r in records if r.get("tags")]
        if tagged:
            with DeskDB(tag_root) as db:
                for record in tagged:
                    db.add_tags(Path(record["path"]).resolve(), record["tags"])
    return records


def link_refs(records: Sequence[dict[str, Any]], *, all_: bool = False) -> list[dict[str, Any]]:
    """Group scan records by reference: [{kind, value, files, count}] (shared ones unless all_)."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        for ref in record["refs"]:
            key = (ref["kind"], ref["value"])
            group = groups.setdefault(
                key, {"kind": ref["kind"], "value": ref["value"], "files": [], "count": 0}
            )
            if record["path"] not in group["files"]:
                group["files"].append(record["path"])
            group["count"] += int(ref["count"])
    out = [g for g in groups.values() if all_ or len(g["files"]) > 1]
    order = {name: i for i, name in enumerate(pat.PATTERNS)}
    out.sort(key=lambda g: (-len(g["files"]), order.get(g["kind"], len(order)), g["value"]))
    for g in out:
        g["files"].sort()
    return out


# ------------------------------------------------------------------- output


def _where(ref: dict[str, Any], paged: bool) -> str:
    if paged:
        return "p. " + ", ".join(str(p) for p in ref["pages"])
    return "line " + ", ".join(str(n) for n in ref["lines"])


def _human_files(records: list[dict[str, Any]]) -> None:
    for record in records:
        click.echo(record["path"])
        if record.get("error"):
            click.echo(f"  error: {record['error']}", err=True)
            continue
        if not record["refs"]:
            click.echo("  (no references)")
            continue
        paged = any(len(r["pages"]) > 1 or r["pages"] != [1] for r in record["refs"])
        width = max(len(r["kind"]) for r in record["refs"])
        for ref in record["refs"]:
            check = "  ✓" if ref["valid"] else ""
            click.echo(
                f"  {ref['kind']:<{width}}  {ref['value']}  x{ref['count']}  "
                f"{_where(ref, paged)}{check}"
            )
        if record.get("tags"):
            click.echo(f"  tagged: {', '.join(record['tags'])}")


def _human_links(groups: list[dict[str, Any]]) -> None:
    if not groups:
        click.echo("no shared references", err=True)
        return
    for g in groups:
        click.echo(f"{g['kind']} {g['value']}  ({len(g['files'])} files, {g['count']} occurrences)")
        for f in g["files"]:
            click.echo(f"  {f}")


@click.command(name="refs")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "--kind",
    "kinds_csv",
    metavar="K1,K2",
    help="Only these kinds, comma-separated. Default: every reference and identifier kind "
    f"({', '.join(pat.REFERENCE_KINDS)}); PII kinds "
    f"({', '.join(pat.kinds('pii'))}) only when named.",
)
@click.option(
    "--pattern",
    "extra",
    multiple=True,
    metavar="NAME=REGEX",
    help="Extra kind to look for (repeatable). A (?P<v1>…) group is the value; "
    "otherwise the whole match is.",
)
@click.option(
    "--tag",
    "tag_",
    is_flag=True,
    help="Tag each file in the desk db under --root with ref:<kind>:<value>.",
)
@click.option(
    "--link",
    is_flag=True,
    help="Group by reference instead of by file: which files share each value.",
)
@click.option("--all", "all_", is_flag=True, help="With --link, also list values seen once.")
@click.option(
    "--ocr", is_flag=True, help="OCR images and scanned PDFs (needs tesseract / ocrmypdf)."
)
@click.option("--fail-empty", is_flag=True, help="Exit 5 when no reference was found.")
@click.pass_context
@handled
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    kinds_csv: str | None,
    extra: tuple[str, ...],
    tag_: bool,
    link: bool,
    all_: bool,
    ocr: bool,
    fail_empty: bool,
) -> None:
    """Find reference numbers (invoice, PO, IBAN, routing, tracking, …) in PATH...

    Directories are walked like `index` (hidden and .gitignored entries
    skipped; images only with --ocr). Every supported file type works; the
    text comes from the same spine `pack` and `index` use. Values with a check
    digit (iban, routing, isbn, gtin, cc) are reported only when it verifies.
    JSON output is a list of {path, refs: [{kind, value, count, valid, pages,
    lines}]} — or, with --link, [{kind, value, files, count}]. Kinds are shared
    with `redact --builtin`.
    """
    kinds = [k for k in kinds_csv.split(",") if k.strip()] if kinds_csv else None
    try:
        pat.resolve_kinds(kinds)
        for spec in extra:
            pat.parse_extra(spec)
    except CarrelInputError as e:  # bad flag values are usage errors (exit 2)
        raise click.UsageError(str(e)) from e
    if all_ and not link:
        raise click.UsageError("--all only applies with --link")

    root = root_of(ctx)
    records = scan_refs(
        list(paths),
        kinds=kinds,
        extra=extra,
        ocr=ocr,
        tag_root=root if tag_ else None,
        root=root,
    )
    if link:
        emit(ctx, link_refs(records, all_=all_), human=_human_links)
    else:
        emit(ctx, records, human=_human_files)

    missing = [r for r in records if r.get("kind") == "missing_dependency"]
    if missing and len(missing) == len(records):
        fail(
            f"nothing scanned — {len(missing)} file(s) need a missing tool:\n{missing[0]['error']}",
            ExitCode.MISSING_DEP,
        )
    if fail_empty and not any(r["refs"] for r in records):
        fail("no references found (--fail-empty)", ExitCode.EMPTY)
