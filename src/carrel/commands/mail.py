"""carrel mail — attachments, mailbox splitting, threads and Outlook exports.

Email files are first-class desk types (`.eml`, `.mbox`; see core.mail), so
`index`, `search`, `pack`, `inspect`, `convert`, `refs` and `fields` already
read them. This group covers what those cannot: saving attachments as files,
splitting a mailbox into one `.eml` per message, grouping messages into
threads, and converting an Outlook `.pst` through `readpst` (pst-utils).

`attachments_of()`, `split_mbox()` and `threads_of()` are the library entry
points (MCP `carrel_mail`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters, mail
from carrel.core.filetypes import FileType, detect, detect_or_die
from carrel.core.fsops import uncollide, within
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


def _unplanned(dest: Path, taken: set[Path]) -> Path:
    """First variant this run has not already claimed (ignoring what is on disk)."""
    candidate, n = dest, 0
    while candidate in taken:
        n += 1
        candidate = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
    return candidate


def _messages(path: Path) -> Iterator[tuple[str, Any]]:
    """(where, message) pairs: the file itself for eml, `file#n` per message for mbox."""
    ftype = detect_or_die(path)
    if ftype is FileType.EML:
        yield str(path), mail.parse_eml(path)
    elif ftype is FileType.MBOX:
        for n, msg in enumerate(mail.iter_mbox(path), 1):
            yield f"{path}#{n}", msg
    else:
        raise CarrelInputError(f"not an email file (eml/mbox): {path} ({ftype.value})")


def _mail_files(
    paths: Sequence[Path], root: Path | None = None, *, confine_to: Path | None = None
) -> list[Path]:
    """Explicit files as given; directories walked like `index` for eml/mbox files."""
    from carrel.commands.index import _walk
    from carrel.core.ignore import ancestor_ignores

    out: list[Path] = []
    for p in paths:
        if not p.exists():
            raise CarrelInputError(f"no such path: {p}")
        if p.is_file():
            if within(p, confine_to):  # mirrors index._walk's own file branch
                out.append(p)
        elif within(p, confine_to):
            # `_walk` checks what it finds; the top it is handed is ours to check
            seed = ancestor_ignores(p.resolve(), root)
            out.extend(f for f in _walk(p, seed, confine_to=confine_to) if detect(f).is_mail)
    return out


# ---------------------------------------------------------------- attachments


def attachments_of(
    paths: Sequence[Path | str], out_dir: Path | str, *, force: bool = False
) -> list[dict[str, Any]]:
    """Save every attachment of the given eml/mbox files into `out_dir`.

    Returns [{message, attachments: [{filename, path, size, sha256, content_type}]}]
    per message. Names are sanitised, and two attachments saved in one run never
    land on the same path — inline images called `image001.png` in every message
    of a thread are the normal case, so the second gets `image001-1.png` even
    with `force`. `force` allows overwriting files that were already in
    `out_dir` before the run.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    taken: set[Path] = set()
    records: list[dict[str, Any]] = []
    for path in (Path(p) for p in paths):
        for where, msg in _messages(path):
            saved: list[dict[str, Any]] = []
            for filename, content_type, data in mail.attachment_parts(msg):
                dest = out / mail.safe_filename(filename)
                # `taken` alone when forcing: pre-existing files may be replaced,
                # but this run's own outputs must never collide with each other
                dest = uncollide(dest, taken) if not force else _unplanned(dest, taken)
                taken.add(dest)
                dest.write_bytes(data)
                saved.append(
                    {
                        "filename": filename,
                        "path": str(dest),
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "content_type": content_type,
                    }
                )
            records.append({"message": where, "attachments": saved})
    return records


# ---------------------------------------------------------------------- split


def _split_name(template: str, *, n: int, width: int, info: dict[str, Any]) -> str:
    date = (info.get("date") or "")[:10] or "undated"
    subject = mail.slug(info.get("subject") or "no-subject")
    ident = mail.slug((info.get("message_id") or "").strip("<>") or f"msg-{n}", 40)
    name = (
        template.replace("{n}", f"{n:0{width}d}")
        .replace("{date}", date)
        .replace("{subject}", subject)
        .replace("{id}", ident)
    )
    safe = mail.safe_filename(name, fallback=f"{n:0{width}d}.eml")
    return safe if safe.lower().endswith(".eml") else f"{safe}.eml"


def split_mbox(
    box: Path | str,
    out_dir: Path | str,
    *,
    template: str = "{n}_{date}_{subject}.eml",
    force: bool = False,
) -> list[dict[str, Any]]:
    """Write one .eml per message of `box` into `out_dir`.

    Returns [{n, path, subject, date, message_id}]. The bytes are the ones
    stored in the mailbox (only mboxrd `>From ` escaping is undone), so a
    message's own encoding, folding and DKIM signature survive the split.
    Names come from `--template`; two messages that render the same name get
    `-1`, `-2`, … suffixes rather than overwriting each other, and without
    `force` a name that already exists in `out_dir` stops the run **before**
    anything is written.
    """
    box = Path(box)
    if detect_or_die(box) is not FileType.MBOX:
        raise CarrelInputError(f"not an mbox file: {box}")
    if "/" in template or "\\" in template:
        raise CarrelInputError(f"--template is a file name, not a path (got: {template!r})")
    if not template.lower().endswith(".eml"):
        raise CarrelInputError(f"--template must end with .eml (got: {template!r})")
    out = Path(out_dir)
    width = max(1, len(str(mail.count_mbox(box))))

    # plan every destination first: a collision must not leave half a mailbox written
    planned: list[tuple[Path, bytes, dict[str, Any]]] = []
    taken: set[Path] = set()
    for n, raw in enumerate(mail.iter_mbox_raw(box), 1):
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        info = mail.summary(msg)
        dest = out / _split_name(template, n=n, width=width, info=info)
        if dest.exists() and not force:
            raise CarrelError(f"refusing to overwrite existing file: {dest} (pass --force)")
        dest = _unplanned(dest, taken) if force else uncollide(dest, taken)
        taken.add(dest)
        planned.append((dest, raw, {"n": n, **info}))

    out.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for dest, raw, info in planned:
        dest.write_bytes(raw)
        written.append(
            {
                "n": info["n"],
                "path": str(dest),
                "subject": info["subject"],
                "date": info["date"],
                "message_id": info["message_id"],
            }
        )
    return written


# -------------------------------------------------------------------- threads


def threads_of(
    paths: Sequence[Path | str],
    *,
    root: Path | None = None,
    confine_to: Path | None = None,
) -> list[dict[str, Any]]:
    """Thread groups over every message in the given eml/mbox files or directories."""
    summaries: list[dict[str, Any]] = []
    for path in _mail_files([Path(p) for p in paths], root, confine_to=confine_to):
        for where, msg in _messages(path):
            summaries.append({**mail.summary(msg), "where": where})
    return mail.thread_groups(summaries)


# ------------------------------------------------------------------------ pst


def pst_export(src: Path | str, out_dir: Path | str, *, fmt: str = "eml") -> dict[str, Any]:
    """Convert an Outlook .pst/.ost through readpst into eml files (or one mbox per folder)."""
    src = Path(src)
    if not src.is_file():
        raise CarrelInputError(f"no such file: {src}")
    if src.suffix.lower() not in (".pst", ".ost"):
        raise CarrelInputError(f"not an Outlook export (.pst/.ost): {src}")
    adapters.require("readpst")  # exit 3 before creating an output directory
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    before = {p for p in out.rglob("*") if p.is_file()}
    # readpst(1): -e = one file per message with an extension; -r = "recursive",
    # all emails of a folder in a file called `mbox` inside it. -M is MH format
    # (extension-less files), which is neither of the two shapes we offer.
    flag = "-e" if fmt == "eml" else "-r"
    proc = adapters.run("readpst", "-q", flag, "-o", str(out), str(src), timeout=3600)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise CarrelError(f"readpst failed (rc={proc.returncode}): {err[-1] if err else '?'}")
    files = sorted(str(p) for p in out.rglob("*") if p.is_file() and p not in before)
    return {
        "src": str(src),
        "out_dir": str(out),
        "format": fmt,
        "files": len(files),
        "via": "readpst",
    }


# ------------------------------------------------------------------------ CLI


@click.group(name="mail")
def cmd() -> None:
    """Attachments, mailbox splitting, threads and Outlook exports for eml/mbox files."""


def _human_attachments(records: list[dict[str, Any]]) -> None:
    total = 0
    for rec in records:
        click.echo(rec["message"])
        for a in rec["attachments"]:
            total += 1
            click.echo(
                f"  {a['filename']} -> {a['path']}  ({a['size']} bytes, {a['content_type']})"
            )
        if not rec["attachments"]:
            click.echo("  (no attachments)")
    click.echo(f"{total} attachment(s) written.")


@cmd.command("attachments")
@click.argument("files", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "--out-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to write attachments into (created if missing).",
)
@click.option(
    "--force", is_flag=True, help="Overwrite same-named files instead of suffixing -1, -2, …"
)
@click.option("--fail-empty", is_flag=True, help="Exit 5 when no attachment was found.")
@click.pass_context
@handled
def attachments(
    ctx: click.Context, files: tuple[Path, ...], out_dir: Path, force: bool, fail_empty: bool
) -> None:
    """Save every attachment of FILES (eml or mbox) into --out-dir.

    File names are sanitised (no separators, no leading dots); collisions get
    -1, -2, … suffixes unless --force. JSON: one record per message with the
    written paths, sizes and sha256 digests.
    """
    for f in files:
        progress(f"mail: {f}", ctx)
    records = attachments_of(list(files), out_dir, force=force)
    emit(ctx, records, human=_human_attachments)
    if fail_empty and not any(r["attachments"] for r in records):
        fail("no attachments found (--fail-empty)", ExitCode.EMPTY)


def _human_split(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        click.echo(f"{r['n']}: {r['path']}  ({r['date'] or 'undated'}) {r['subject'] or ''}")
    click.echo(f"{len(rows)} message(s) written.")


@cmd.command("split")
@click.argument("box", type=click.Path(path_type=Path))
@click.option(
    "--out-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to write the .eml files into (created if missing).",
)
@click.option(
    "--template",
    default="{n}_{date}_{subject}.eml",
    show_default=True,
    help="File name template: {n} index, {date} YYYY-MM-DD, {subject} slug, {id} message id.",
)
@click.option("--force", is_flag=True, help="Overwrite existing files.")
@click.pass_context
@handled
def split(ctx: click.Context, box: Path, out_dir: Path, template: str, force: bool) -> None:
    """Split BOX (an mbox) into one .eml file per message under --out-dir.

    Names come from --template; messages are numbered in mailbox order and
    the bytes are written as stored. Refuses to overwrite without --force.
    JSON: [{n, path, subject, date, message_id}].
    """
    emit(ctx, split_mbox(box, out_dir, template=template, force=force), human=_human_split)


def _human_threads(groups: list[dict[str, Any]]) -> None:
    if not groups:
        click.echo("no messages", err=True)
        return
    for g in groups:
        click.echo(f"{g['root_subject'] or '(no subject)'}  ({len(g['messages'])} message(s))")
        for m in g["messages"]:
            indent = "  " * m["depth"]
            who = ", ".join(m["from"]) if m["from"] else "?"
            click.echo(f"{indent}{m['date'] or 'undated'}  {who}  {m['where']}")


@cmd.command("threads")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.pass_context
@handled
def threads(ctx: click.Context, paths: tuple[Path, ...]) -> None:
    """Group the messages in PATHS (eml/mbox files or directories) into threads.

    Threads follow Message-ID / In-Reply-To / References; `depth` is the
    reply-chain length when the parent is present. JSON: [{root_subject,
    first_date, messages: [{where, message_id, date, from, subject, depth}]}].
    """
    emit(ctx, threads_of(list(paths), root=root_of(ctx)), human=_human_threads)


@cmd.command("pst")
@click.argument("src", type=click.Path(path_type=Path))
@click.option(
    "--out-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory readpst writes into (one subfolder per mail folder).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["eml", "mbox"]),
    default="eml",
    show_default=True,
    help="One .eml per message (readpst -e), or one mbox file per mail folder (readpst -r).",
)
@click.pass_context
@handled
def pst(ctx: click.Context, src: Path, out_dir: Path, fmt: str) -> None:
    """Convert an Outlook SRC (.pst/.ost) into eml or mbox files via readpst.

    `--format eml` writes one .eml per message (readpst -e); `--format mbox`
    writes one `mbox` file per mail folder (readpst -r), which `carrel mail
    split` can then take apart.

    Needs readpst (sudo apt install pst-utils); exit 3 with that hint
    otherwise. JSON: {src, out_dir, format, files, via}.
    """
    emit(
        ctx,
        pst_export(src, out_dir, fmt=fmt),
        human=lambda d: click.echo(
            f"{d['src']} -> {d['out_dir']}: {d['files']} file(s) [{d['via']}]"
        ),
    )
