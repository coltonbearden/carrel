"""carrel rename — file names from what the document says: `{date}_{vendor}_{ref}{ext}`.

Placeholders are filled from `fields` (vendor, invoice number, dates, total),
the desk's `meta` fields, the reference scanner and the file itself:

    {date} {date:%Y-%m} {yyyy} {mm}   the document date (fields.date → meta.date → mtime)
    {vendor} {ref} {total}            fields / meta (ref: invoice_no, else the first reference)
    {fields.NAME} {meta.KEY}          any extracted field / desk field by name
    {type} {stem} {name} {ext} {sha8} the file itself (ext keeps its dot)

Values are slugified (letters, digits, `.`, `_`, `-`; spaces → `_`). A file
whose template has an unresolved placeholder is skipped (or gets --fallback).
Dry-run is the default; --apply renames next to the source, never overwrites
(collisions get -1, -2, …) and the desk row — tags, notes, fields — follows
the file (core.fsops). `build_name()` is reused by `intake`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import click

from carrel.core import patterns as pat
from carrel.core.db import DeskDB
from carrel.core.filetypes import detect
from carrel.core.fsops import guard_worktree, move_file, uncollide
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

DEFAULT_TEMPLATE = "{date}_{vendor}_{ref}{ext}"
_PLACEHOLDER = re.compile(r"\{(?P<name>[a-z][a-z0-9_.]*)(?::(?P<fmt>[^}]+))?\}")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(value: str, *, lower: bool = False) -> str:
    s = _UNSAFE.sub("_", value.strip()).strip("._")
    s = re.sub(r"_{2,}", "_", s)
    return s.lower() if lower else s


class UnresolvedPlaceholderError(CarrelInputError):
    """A template placeholder had no value for this file."""


def _sha8(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def _doc_date(fields: dict[str, Any], meta: dict[str, str], path: Path) -> tuple[date, str]:
    """(date, source) — the document date from fields, else the desk, else the file's mtime."""
    for source, value in (
        ("fields", fields.get("date", {}).get("value")),
        ("meta", meta.get("date")),
    ):
        if value:
            try:
                return date.fromisoformat(str(value)), source
            except ValueError:
                continue
    return datetime.fromtimestamp(path.stat().st_mtime).date(), "mtime"


def build_name(
    path: Path,
    template: str,
    *,
    fields: dict[str, Any] | None = None,
    meta: dict[str, str] | None = None,
    refs: Sequence[dict[str, Any]] | None = None,
    fallback: str | None = None,
    lower: bool = False,
    max_len: int = 120,
) -> tuple[str, dict[str, str]]:
    """Render `template` for `path`; returns (relative name, {placeholder: source}).

    `fields` is a `fields.extract_fields()["fields"]` map, `meta` a desk
    `{key: value}` map, `refs` a `find_refs` list; all optional. A literal `/`
    in the template files into subfolders (`{yyyy}/{mm}/{name}`); placeholder
    values never contain one. Raises UnresolvedPlaceholderError when a
    placeholder has no value and no `fallback`.
    """
    fields = fields or {}
    meta = meta or {}
    refs = list(refs or [])
    sources: dict[str, str] = {}
    when: tuple[date, str] | None = None

    def field_value(name: str) -> tuple[str | None, str]:
        info = fields.get(name)
        if info and info.get("value"):
            return str(info["value"]), "fields"
        if meta.get(name):
            return meta[name], "meta"
        return None, ""

    def resolve(name: str, fmt: str | None) -> str | None:
        nonlocal when
        if name in ("date", "yyyy", "mm"):
            when = when or _doc_date(fields, meta, path)
            sources[name] = when[1]
            if name == "yyyy":
                return f"{when[0].year:04d}"
            if name == "mm":
                return f"{when[0].month:02d}"
            return when[0].strftime(fmt) if fmt else when[0].isoformat()
        if name == "ref":
            value, src = field_value("invoice_no")
            if value is None and refs:
                value, src = str(refs[0]["value"]), "refs"
            sources[name] = src
            return value
        if name in ("vendor", "total"):
            value, src = field_value(name)
            sources[name] = src
            return value
        if name.startswith("fields."):
            value = fields.get(name[7:], {}).get("value")
            sources[name] = "fields"
            return str(value) if value else None
        if name.startswith("meta."):
            sources[name] = "meta"
            return meta.get(name[5:]) or None
        sources[name] = "file"
        if name == "type":
            return detect(path).value
        if name == "stem":
            return path.stem
        if name == "name":
            return path.name
        if name == "ext":
            return path.suffix
        if name == "sha8":
            return _sha8(path)
        raise CarrelInputError(f"unknown placeholder {{{name}}} in template {template!r}")

    def substitute(m: re.Match[str]) -> str:
        name, fmt = m.group("name"), m.group("fmt")
        value = resolve(name, fmt)
        if value is None or not str(value).strip():
            if fallback is None:
                raise UnresolvedPlaceholderError(f"no value for {{{name}}}")
            value, sources[name] = fallback, "fallback"
        if name in ("ext", "name"):
            return (
                slugify(value, lower=lower) if name == "name" else value.lower() if lower else value
            )
        return slugify(value, lower=lower)

    rendered = _PLACEHOLDER.sub(substitute, template).replace("\\", "/")
    parts = [part for part in rendered.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        raise CarrelInputError(f"template {template!r} renders to an unusable name")
    leaf = Path(parts[-1])
    stem, suffix = leaf.stem, leaf.suffix
    if len(stem) > max_len:
        stem = stem[:max_len].rstrip("._-")
    return "/".join([*parts[:-1], stem + suffix]), sources


def plan_renames(
    paths: Sequence[Path | str],
    template: str,
    *,
    date_order: str = "mdy",
    fallback: str | None = None,
    lower: bool = False,
    max_len: int = 120,
    desk_root: Path | str | None = None,
    ocr: bool = False,
) -> list[dict[str, Any]]:
    """[{src, dest, action: rename|skip, reason?, sources}] for files (directories walked like `refs`)."""
    from carrel.commands.fields import extract_fields
    from carrel.commands.refs import candidate_files

    root = Path(desk_root).resolve() if desk_root else None
    targets = candidate_files([Path(p) for p in paths], ocr=ocr, root=root)
    ctx = click.get_current_context(silent=True)
    meta_by_path: dict[Path, dict[str, str]] = {}
    if root is not None and DeskDB.exists(root):
        with DeskDB(root) as db:
            for f in targets:
                meta_by_path[f] = {r["key"]: r["value"] for r in db.meta_of(f.resolve())}
    plan: list[dict[str, Any]] = []
    taken: set[Path] = set()
    for f in targets:
        progress(f"rename: {f}", ctx)
        entry: dict[str, Any] = {"src": str(f), "dest": None, "action": "skip"}
        try:
            fields = extract_fields(f, date_order=date_order, ocr=ocr)["fields"]
            refs = pat.find_refs(_text_of(f, ocr), None)
            name, sources = build_name(
                f,
                template,
                fields=fields,
                meta=meta_by_path.get(f),
                refs=refs,
                fallback=fallback,
                lower=lower,
                max_len=max_len,
            )
        except UnresolvedPlaceholderError as e:
            entry["reason"] = str(e)
            plan.append(entry)
            continue
        except CarrelError as e:
            entry["reason"] = str(e)
            plan.append(entry)
            continue
        except Exception as e:  # noqa: BLE001 — one unreadable file is a plan entry, never an abort
            entry["reason"] = f"{e.__class__.__name__}: {e}"
            plan.append(entry)
            continue
        dest = f.parent / name
        if dest == f:
            entry.update(
                {"dest": str(dest), "reason": "already named that way", "sources": sources}
            )
            plan.append(entry)
            continue
        dest = uncollide(dest, taken)
        taken.add(dest)
        entry.update({"dest": str(dest), "action": "rename", "sources": sources})
        plan.append(entry)
    return plan


def _text_of(path: Path, ocr: bool) -> str:
    from carrel.core.textextract import extract_text

    return extract_text(path, ocr=ocr)


def apply_plan(plan: list[dict[str, Any]], *, desk_root: Path | None) -> None:
    """Perform the planned renames; a failure marks that entry and the rest still run."""
    for entry in plan:
        if entry["action"] != "rename":
            continue
        try:
            move_file(Path(entry["src"]), Path(entry["dest"]), desk_root=desk_root)
        except (OSError, CarrelError) as e:
            # one unwritable destination must not discard the record of every
            # file already renamed
            entry.update({"action": "error", "reason": f"{e.__class__.__name__}: {e}"})
            continue
        entry["action"] = "renamed"


def _human_plan(applied: bool) -> Callable[[list[dict[str, Any]]], None]:
    def _print(plan: list[dict[str, Any]]) -> None:
        n = 0
        for entry in plan:
            if entry["action"] in ("skip", "error"):
                click.echo(f"{entry['action']:<7} {entry['src']}  ({entry['reason']})")
            else:
                n += 1
                verb = "renamed" if applied else "rename "
                click.echo(f"{verb} {entry['src']} -> {Path(entry['dest']).name}")
        if applied:
            click.echo(f"{n} file(s) renamed.")
        else:
            click.echo(f"dry-run: {n} rename(s) planned — re-run with --apply to execute.")

    return _print


@click.command(name="rename")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "--template",
    default=DEFAULT_TEMPLATE,
    show_default=True,
    help="Name template; see the placeholders in the command description.",
)
@click.option(
    "--apply/--dry-run",
    "apply_",
    default=False,
    help="Execute the renames. Default is a dry-run that only prints the plan.",
)
@click.option(
    "--date-order",
    type=click.Choice(["mdy", "dmy"]),
    default="mdy",
    show_default=True,
    help="How to read an ambiguous slashed date in the document.",
)
@click.option(
    "--fallback",
    default=None,
    metavar="TEXT",
    help="Use TEXT for a placeholder that has no value instead of skipping the file.",
)
@click.option("--lower", is_flag=True, help="Lower-case the rendered name.")
@click.option(
    "--max-len",
    default=120,
    show_default=True,
    type=click.IntRange(min=8),
    help="Cap the stem length.",
)
@click.option(
    "--ocr",
    is_flag=True,
    help="OCR images and scanned PDFs to read their fields (needs tesseract / ocrmypdf).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Rename even when a PATH is a file git tracks (see the description).",
)
@click.pass_context
@handled
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    template: str,
    apply_: bool,
    date_order: str,
    fallback: str | None,
    lower: bool,
    max_len: int,
    ocr: bool,
    force: bool,
) -> None:
    """Plan (default) or perform (--apply) renaming PATH... from the documents' own fields.

    Placeholders: {date} (or {date:%Y-%m}), {yyyy}, {mm}, {vendor}, {ref},
    {total}, {fields.NAME}, {meta.KEY}, {type}, {stem}, {name}, {ext}, {sha8}.
    Dates come from the document (then the desk, then mtime); {ref} is the
    invoice number or the first reference found. Values are slugified; a file
    with an unresolved placeholder is skipped unless --fallback is given.
    Renames happen next to the source (a literal / in the template files
    into subfolders), never overwrite (-1, -2, … suffixes), and carry the desk
    row under --root along. JSON: [{src, dest, action: rename|renamed|skip,
    reason, sources}].

    --apply refuses (exit 2) when a PATH would rename a file git is tracking,
    where a new name breaks imports, tests and history. Untracked files inside a
    repository are fine; --force overrides.
    """
    if not _PLACEHOLDER.search(template):
        raise click.UsageError(f"--template has no placeholders: {template!r}")
    if apply_:
        # every PATH, not just directories: a shell glob (`rename src/*.py --apply`)
        # arrives as a list of files and is exactly the 2026-09-10 incident.
        # Renames land next to their source, so guarding the inputs covers the
        # destinations. Guarded after the template check so a bad template
        # reports itself.
        guard_worktree(paths, force=force, what="rename --apply")
    root = root_of(ctx)
    plan = plan_renames(
        list(paths),
        template,
        date_order=date_order,
        fallback=fallback,
        lower=lower,
        max_len=max_len,
        desk_root=root,
        ocr=ocr,
    )
    unknown = [e for e in plan if e.get("reason", "").startswith("unknown placeholder")]
    if unknown and len(unknown) == len(plan):
        raise click.UsageError(unknown[0]["reason"])
    if apply_:
        apply_plan(plan, desk_root=root)
    emit(ctx, plan, human=_human_plan(applied=apply_))
    if apply_ and any(e["action"] == "error" for e in plan):
        fail("some files could not be renamed (see the records)", ExitCode.ERROR)
    if (
        not any(e["action"] in ("rename", "renamed") for e in plan)
        and plan
        and all(e.get("kind") == "missing_dependency" for e in plan)
    ):
        fail("nothing renamed", ExitCode.MISSING_DEP)
