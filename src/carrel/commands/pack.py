"""carrel pack — bundle files/directories into one LLM-ready context document.

`pack_paths()` is the library entry point (reused by the desk TUI and the MCP
server); the click command `cmd` is a thin wrapper around it.
"""

from __future__ import annotations

import dataclasses
import json as jsonlib
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import click

from carrel._product import PRODUCT
from carrel.core.adapters import MissingDependencyError
from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelInputError, emit
from carrel.core.textextract import extract_text

CHARS_PER_TOKEN = 3.6
_ALWAYS_SKIP_DIRS = frozenset({".git", ".carrel"})

# chars-per-token safety factor when pre-splitting an oversized file, per
# format: json escapes newlines/quotes (worst case 2x), xml only "]]>".
_SPLIT_SAFETY = {"md": 0.97, "xml": 0.92, "json": 0.5}

_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".csv": "csv",
    ".sh": "bash",
    ".bash": "bash",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".css": "css",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".ini": "ini",
    ".cfg": "ini",
    ".txt": "",
    ".text": "",
    ".pdf": "text",
}


def estimate_tokens(text: str) -> int:
    """Crude LLM token estimate: ceil(chars / 3.6)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------
# .gitignore (simple matcher — see cmd docstring for documented limits)


@dataclass(frozen=True)
class _IgnoreFile:
    base: Path
    patterns: tuple[tuple[str, bool], ...]  # (pattern, dir_only)


def _load_ignore(directory: Path) -> _IgnoreFile | None:
    gi = directory / ".gitignore"
    if not gi.is_file():
        return None
    patterns: list[tuple[str, bool]] = []
    try:
        lines = gi.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue  # comments; negation is NOT supported (documented)
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if line:
            patterns.append((line, dir_only))
    return _IgnoreFile(directory, tuple(patterns)) if patterns else None


def _ancestor_ignores(top: Path) -> tuple[_IgnoreFile, ...]:
    """.gitignore files above `top`, stopping at the repo root (dir with .git)."""
    found: list[_IgnoreFile] = []
    for d in top.parents:
        ig = _load_ignore(d)
        if ig:
            found.append(ig)
        if (d / ".git").exists():
            break
    return tuple(reversed(found))


def _ignored(path: Path, is_dir: bool, ignores: tuple[_IgnoreFile, ...]) -> bool:
    for ig in ignores:
        try:
            rel = path.relative_to(ig.base).as_posix()
        except ValueError:
            continue
        for pat, dir_only in ig.patterns:
            if dir_only and not is_dir:
                continue
            if "/" in pat:
                if fnmatch(rel, pat.lstrip("/")):
                    return True
            elif fnmatch(path.name, pat):
                return True
    return False


# --------------------------------------------------------------------------
# data model


@dataclass(frozen=True)
class PackEntry:
    path: str  # display path (POSIX, relative to root)
    size: int  # bytes on disk
    ftype: str  # FileType value ("txt", "pdf", "unknown", ...)
    content: str | None  # extracted text; None when skipped/tree-only
    tokens_est: int
    skipped: str | None = None  # reason, or None when included
    continued: bool = False  # True on split pieces in chunked output

    @property
    def included(self) -> bool:
        return self.skipped is None


@dataclass
class PackResult:
    fmt: str
    root: Path
    meta: dict[str, Any]
    tree: str
    entries: list[PackEntry]
    documents: list[str]  # one rendered document, or N parts when chunked

    @property
    def document(self) -> str:
        return self.documents[0]

    @property
    def files(self) -> list[PackEntry]:
        return [e for e in self.entries if e.included]

    def stats(self) -> dict[str, Any]:
        return {
            "files": [
                {
                    "path": e.path,
                    "type": e.ftype,
                    "bytes": e.size,
                    "tokens_est": e.tokens_est,
                    "skipped": e.skipped,
                }
                for e in self.entries
            ],
            "totals": {
                "files": len(self.entries),
                "included": self.meta["files_included"],
                "skipped": self.meta["files_skipped"],
                "bytes": self.meta["bytes"],
                "tokens_est": self.meta["tokens_est"],
            },
        }


# --------------------------------------------------------------------------
# extraction


def _looks_text(path: Path) -> bool:
    try:
        head = path.open("rb").read(8192)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            head[:-3].decode("utf-8")  # chunk may cut a multibyte char
            return True
        except UnicodeDecodeError:
            return False


def _extract(path: Path, ftype: FileType, ocr: bool) -> tuple[str | None, str | None]:
    """(content, skip_reason) — exactly one is None."""
    if ftype is FileType.UNKNOWN:  # plain-text source file (.py, .toml, ...)
        try:
            return path.read_text(encoding="utf-8", errors="replace"), None
        except OSError as e:
            return None, f"unreadable ({e.__class__.__name__})"
    try:
        return extract_text(path, ocr=ocr), None
    except MissingDependencyError as e:
        return None, f"needs {e.adapter.name}"
    except CarrelInputError:
        try:  # e.g. invalid JSON: fall back to the raw bytes as text
            return path.read_text(encoding="utf-8", errors="replace"), None
        except OSError as e:
            return None, f"unreadable ({e.__class__.__name__})"


# --------------------------------------------------------------------------
# tree rendering


def _render_tree(root_label: str, entries: list[PackEntry]) -> str:
    tree: dict[str, Any] = {}
    for e in entries:
        node = tree
        parts = e.path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = e
    lines = [root_label.rstrip("/") + "/"]

    def rec(node: dict[str, Any], prefix: str) -> None:
        dirs = sorted(k for k, v in node.items() if isinstance(v, dict))
        files = sorted(k for k, v in node.items() if not isinstance(v, dict))
        items = dirs + files
        for i, name in enumerate(items):
            val = node[name]
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            if isinstance(val, dict):
                lines.append(f"{prefix}{branch}{name}/")
                rec(val, prefix + ("    " if last else "│   "))
            else:
                note = (
                    f"  [skipped: {val.skipped}] ({_human_size(val.size)})" if val.skipped else ""
                )
                lines.append(f"{prefix}{branch}{name}{note}")

    rec(tree, "")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# format renderers — signature: (meta, tree|None, entries, part|None) -> str


def _header_lines(meta: dict[str, Any], part: tuple[int, int] | None) -> list[str]:
    lines = [
        f"generated-by: {meta['generated_by']}",
        f"root: {meta['root']}",
        f"files: {meta['files_included']} included, {meta['files_skipped']} skipped",
        f"tokens_est: {meta['tokens_est']}",
    ]
    if meta.get("omitted_budget"):
        lines.append(
            f"omitted over --max-bytes budget: {len(meta['omitted_budget'])} file(s): "
            + ", ".join(meta["omitted_budget"])
        )
    if meta.get("tree_only"):
        lines.append("tree-only: file contents omitted")
    if part:
        lines.append(f"part: {part[0]}/{part[1]}")
    return lines


def _fence_for(text: str) -> str:
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _lang_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return _LANG.get(suffix, suffix.lstrip("."))


def _md_section(e: PackEntry) -> str:
    content = (e.content or "").rstrip("\n")
    fence = _fence_for(content)
    title = f"### `{e.path}`" + (" (continued)" if e.continued else "")
    return f"{title}\n\n{fence}{_lang_for(e.path)}\n{content}\n{fence}\n"


def _render_md(
    meta: dict[str, Any], tree: str | None, entries: list[PackEntry], part: tuple[int, int] | None
) -> str:
    out = [f"# {PRODUCT['name']} pack", ""]
    out += [f"- {ln}" for ln in _header_lines(meta, part)]
    if tree is not None:
        fence = _fence_for(tree)
        out += ["", "## Tree", "", fence, tree, fence]
    if entries:
        out += ["", "## Files", ""]
        out += [_md_section(e) for e in entries]
    return "\n".join(out).rstrip("\n") + "\n"


def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _render_xml(
    meta: dict[str, Any], tree: str | None, entries: list[PackEntry], part: tuple[int, int] | None
) -> str:
    attrs = {
        "generated-by": meta["generated_by"],
        "root": meta["root"],
        "files": str(meta["files_included"]),
        "tokens-est": str(meta["tokens_est"]),
    }
    if meta.get("omitted_budget"):
        attrs["omitted-budget"] = str(len(meta["omitted_budget"]))
    if part:
        attrs["part"] = f"{part[0]}/{part[1]}"
    attr_s = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
    out = [f"<context {attr_s}>"]
    if tree is not None:
        out.append(f"<tree>{_cdata(tree)}</tree>")
    for e in entries:
        fa = f'path={quoteattr(e.path)} tokens-est="{e.tokens_est}"'
        if e.continued:
            fa += ' continued="true"'
        out.append(f"<file {fa}>{_cdata(e.content or '')}</file>")
    out.append("</context>")
    return "\n".join(out) + "\n"


def _render_json(
    meta: dict[str, Any], tree: str | None, entries: list[PackEntry], part: tuple[int, int] | None
) -> str:
    m = dict(meta)
    if part:
        m["part"] = f"{part[0]}/{part[1]}"
    obj = {
        "meta": m,
        "tree": tree or "",
        "files": [
            {
                "path": e.path,
                "tokens_est": e.tokens_est,
                "content": e.content or "",
                **({"continued": True} if e.continued else {}),
            }
            for e in entries
        ],
    }
    return jsonlib.dumps(obj, indent=2, ensure_ascii=False) + "\n"


_RENDERERS = {"md": _render_md, "xml": _render_xml, "json": _render_json}


# --------------------------------------------------------------------------
# chunking


def _split_entry(e: PackEntry, fmt: str, meta: dict[str, Any], budget: int) -> list[PackEntry]:
    """Split one oversized file on line boundaries into budget-sized pieces."""
    render = _RENDERERS[fmt]
    empty = dataclasses.replace(e, content="", continued=True)
    overhead = estimate_tokens(render(meta, None, [empty], (1, 1)))
    avail = int((budget - overhead) * CHARS_PER_TOKEN * _SPLIT_SAFETY[fmt])
    if avail < 1:
        raise CarrelInputError(f"--chunk {budget} is too small to fit any content of {e.path}")
    chunks: list[str] = []
    buf: list[str] = []
    buflen = 0
    for line in (e.content or "").splitlines(keepends=True):
        while len(line) > avail:  # pathological single line: hard-split
            if buf:
                chunks.append("".join(buf))
                buf, buflen = [], 0
            chunks.append(line[:avail])
            line = line[avail:]
        if buf and buflen + len(line) > avail:
            chunks.append("".join(buf))
            buf, buflen = [], 0
        if line:
            buf.append(line)
            buflen += len(line)
    if buf:
        chunks.append("".join(buf))
    return [
        dataclasses.replace(e, content=c, tokens_est=estimate_tokens(c), continued=i > 0)
        for i, c in enumerate(chunks)
    ]


def _chunked_documents(
    fmt: str, meta: dict[str, Any], tree: str, entries: list[PackEntry], budget: int
) -> list[str]:
    render = _RENDERERS[fmt]

    def doc_tokens(group: list[PackEntry], with_tree: bool) -> int:
        return estimate_tokens(render(meta, tree if with_tree else None, group, (1, 1)))

    pieces: list[PackEntry] = []
    for e in entries:
        if doc_tokens([e], False) > budget:
            pieces.extend(_split_entry(e, fmt, meta, budget))
        else:
            pieces.append(e)

    groups: list[list[PackEntry]] = []
    cur: list[PackEntry] = []
    for p in pieces:
        if not cur and not groups and doc_tokens([p], True) > budget:
            groups.append([])  # tree alone fills part 1
            cur = [p]
        elif cur and doc_tokens([*cur, p], not groups) > budget:
            groups.append(cur)
            cur = [p]
        else:
            cur.append(p)
    if cur or not groups:
        groups.append(cur)
    n = len(groups)
    return [render(meta, tree if i == 0 else None, g, (i + 1, n)) for i, g in enumerate(groups)]


# --------------------------------------------------------------------------
# core


def pack_paths(
    paths: Sequence[Path | str],
    *,
    fmt: str = "md",
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    no_gitignore: bool = False,
    max_bytes: int | None = None,
    max_file_bytes: int | None = None,
    chunk: int | None = None,
    tree_only: bool = False,
    ocr: bool = False,
) -> PackResult:
    """Walk `paths` and render a context pack; see the `pack` command --help."""
    if fmt not in _RENDERERS:
        raise CarrelInputError(f"unknown pack format: {fmt} (choose md, xml or json)")
    if chunk is not None and chunk <= 0:
        raise CarrelInputError("--chunk must be a positive token count")
    tops = [Path(p).resolve() for p in paths]
    if not tops:
        raise CarrelInputError("no paths given")
    for t in tops:
        if not t.exists():
            raise CarrelInputError(f"no such path: {t}")
    common = Path(os.path.commonpath([str(t) for t in tops]))
    root = common if common.is_dir() else common.parent

    def rel_of(p: Path) -> str:
        return p.relative_to(root).as_posix()

    def _excluded(p: Path) -> bool:
        return any(fnmatch(rel_of(p), g) or fnmatch(p.name, g) for g in exclude)

    seen: set[Path] = set()
    collected: list[Path] = []

    def _add(p: Path) -> None:
        if p not in seen:
            seen.add(p)
            collected.append(p)

    def _walk_dir(d: Path, ignores: tuple[_IgnoreFile, ...]) -> None:
        if not no_gitignore:
            ig = _load_ignore(d)
            if ig:
                ignores = (*ignores, ig)
        try:
            children = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        # deterministic order: dirs first, alphabetical
        for sub in (c for c in children if c.is_dir()):
            if sub.name in _ALWAYS_SKIP_DIRS or sub.is_symlink():
                continue
            if _excluded(sub):
                continue
            if not no_gitignore and _ignored(sub, True, ignores):
                continue
            _walk_dir(sub, ignores)
        for f in (c for c in children if c.is_file()):
            if _excluded(f):
                continue
            if not no_gitignore and _ignored(f, False, ignores):
                continue
            if include and not any(fnmatch(rel_of(f), g) or fnmatch(f.name, g) for g in include):
                continue
            _add(f)

    for t in tops:
        if t.is_file():
            _add(t)  # explicitly named files are always packed
        else:
            _walk_dir(t, () if no_gitignore else _ancestor_ignores(t))

    entries: list[PackEntry] = []
    used = 0
    omitted: list[str] = []
    budget_hit = False
    for f in collected:
        rel = rel_of(f)
        try:
            size = f.stat().st_size
        except OSError:
            continue
        ftype = detect(f)
        content: str | None = None
        skipped: str | None = None
        if max_file_bytes is not None and size > max_file_bytes:
            skipped = "exceeds --max-file-bytes"
        elif ftype is FileType.UNKNOWN and not _looks_text(f):
            skipped = "binary"
        elif ftype.is_image and not ocr:
            skipped = "binary"  # images are listed, never inlined (use --ocr)
        elif budget_hit or (max_bytes is not None and used + size > max_bytes):
            budget_hit = True
            skipped = "over --max-bytes budget"
            omitted.append(rel)
        elif tree_only:
            used += size
        else:
            content, skipped = _extract(f, ftype, ocr)
            if skipped is None:
                used += size
        tokens = estimate_tokens(content) if content else 0
        entries.append(PackEntry(rel, size, ftype.value, content, tokens, skipped))

    included = [e for e in entries if e.included]
    meta: dict[str, Any] = {
        "generated_by": f"{PRODUCT['name']} {PRODUCT['version']}",
        "root": str(root),
        "files_included": len(included),
        "files_skipped": len(entries) - len(included),
        "bytes": sum(e.size for e in included),
        "tokens_est": sum(e.tokens_est for e in included),
    }
    if omitted:
        meta["omitted_budget"] = omitted
    if tree_only:
        meta["tree_only"] = True

    tree = _render_tree(root.name or str(root), entries)
    body = [] if tree_only else included
    if chunk:
        documents = _chunked_documents(fmt, meta, tree, body, chunk)
    else:
        documents = [_RENDERERS[fmt](meta, tree, body, None)]
    return PackResult(
        fmt=fmt, root=root, meta=meta, tree=tree, entries=entries, documents=documents
    )


# --------------------------------------------------------------------------
# CLI


def _print_stats_table(data: dict[str, Any]) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title="pack stats")
    for col in ("path", "type", "size", "tokens_est", "note"):
        table.add_column(col)
    for row in data["files"]:
        table.add_row(
            row["path"],
            row["type"],
            _human_size(row["bytes"]),
            str(row["tokens_est"]),
            row["skipped"] or "",
        )
    totals = data["totals"]
    table.add_section()
    table.add_row(
        "TOTAL",
        f"{totals['included']} in / {totals['skipped']} skip",
        _human_size(totals["bytes"]),
        str(totals["tokens_est"]),
        "",
    )
    Console().print(table)
    if data.get("written"):
        click.echo("wrote " + ", ".join(data["written"]), err=True)


@click.command(name="pack")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write here instead of stdout (with --chunk: OUT.part1..N).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["md", "xml", "json"]),
    default="md",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--include", multiple=True, metavar="GLOB", help="Only pack files matching GLOB (repeatable)."
)
@click.option(
    "--exclude", multiple=True, metavar="GLOB", help="Drop files/dirs matching GLOB (repeatable)."
)
@click.option("--no-gitignore", is_flag=True, help="Do not honor .gitignore files.")
@click.option(
    "--max-bytes",
    type=int,
    metavar="N",
    help="Stop adding file contents once N total bytes are packed; "
    "omissions are noted in the header.",
)
@click.option(
    "--max-file-bytes", type=int, metavar="N", help="Skip any single file larger than N bytes."
)
@click.option(
    "--chunk",
    type=int,
    metavar="TOKENS",
    help="Split into OUT.part1..N, each at most TOKENS estimated "
    "tokens (requires -o). Files are never split mid-file "
    "unless one alone exceeds the budget; then it is split on "
    "line boundaries with (continued) markers.",
)
@click.option("--tree-only", is_flag=True, help="Emit header + tree only, no contents.")
@click.option(
    "--ocr", is_flag=True, help="OCR images and scanned PDFs (needs tesseract / ocrmypdf)."
)
@click.option(
    "--stats",
    "show_stats",
    is_flag=True,
    help="Print a per-file token table instead of the pack "
    "(the pack is still written when -o is given).",
)
@click.pass_context
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    output: Path | None,
    fmt: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    no_gitignore: bool,
    max_bytes: int | None,
    max_file_bytes: int | None,
    chunk: int | None,
    tree_only: bool,
    ocr: bool,
    show_stats: bool,
) -> None:
    """Bundle PATH... (files or directories) into one LLM-ready context document.

    Formats: md (default: header + fenced tree + per-file fenced sections,
    fences lengthened on collision), xml (<context><tree/><file/></context>
    with CDATA, Claude-friendly), json ({meta, tree, files}). Token estimates
    are ceil(chars / 3.6), labeled tokens_est.

    .gitignore handling is a deliberately simple per-directory matcher:
    plain names and `*` globs match anywhere below their .gitignore; a
    trailing `/` restricts a pattern to directories; patterns containing `/`
    match relative to their .gitignore's directory. Negation (`!pattern`) is
    NOT supported — such lines are ignored. `.git` and `.carrel` are always
    skipped. Binaries outside the supported set are listed in the tree as
    [skipped: binary] with their size, never inlined; images are only read
    (OCR) with --ocr.
    """
    if chunk is not None and chunk <= 0:
        raise click.UsageError("--chunk must be a positive token count")
    if chunk and not output:
        raise click.UsageError("--chunk requires -o/--output (parts are named OUT.part1..N)")
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json and not output and not show_stats:
        fmt = "json"  # global --json: stdout must be one JSON document

    result = pack_paths(
        list(paths),
        fmt=fmt,
        include=include,
        exclude=exclude,
        no_gitignore=no_gitignore,
        max_bytes=max_bytes,
        max_file_bytes=max_file_bytes,
        chunk=chunk,
        tree_only=tree_only,
        ocr=ocr,
    )

    written: list[Path] = []
    if output is not None:
        if chunk:
            for i, doc in enumerate(result.documents, 1):
                part = output.with_name(f"{output.name}.part{i}")
                part.write_text(doc)
                written.append(part)
        else:
            output.write_text(result.document)
            written.append(output)

    if show_stats:
        data = result.stats()
        if written:
            data["written"] = [str(p) for p in written]
        emit(ctx, data, human=_print_stats_table)
        return
    if written:
        summary = {"written": [str(p) for p in written], **result.meta}
        emit(
            ctx,
            summary,
            human=lambda d: click.echo(
                f"wrote {', '.join(d['written'])} "
                f"({d['files_included']} files, ~{d['tokens_est']} tokens_est)",
                err=True,
            ),
        )
        return
    click.echo(result.document, nl=False)
