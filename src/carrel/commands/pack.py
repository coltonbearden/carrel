"""carrel pack — bundle files/directories into one LLM-ready context document.

`pack_paths()` is the library entry point (reused by the desk TUI and the MCP
server); the click command `cmd` is a thin wrapper around it.

v2 (spec 16) adds query-driven selection (`--query`, ranked by the desk FTS
index), git-aware selection (`--since REF` / `--changed` via the `git`
adapter), `.gitignore` negation (`!pattern`, last match wins), content
de-duplication (`--dedupe-content`), exact token counts (`--tokenizer exact`,
tiktoken `o200k_base` from the `tokens` extra) and a structural `--outline`
pass. Every new capability is keyword-only and off by default: with the
defaults, `pack_paths` behaves and renders exactly as v1 did.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import json as jsonlib
import math
import os
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

import click

from carrel._product import PRODUCT
from carrel.core import adapters
from carrel.core.adapters import Adapter, MissingDependencyError
from carrel.core.db import DeskDB, file_hash
from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelError, CarrelInputError, ExitCode, emit, fail
from carrel.core.textextract import extract_text

CHARS_PER_TOKEN = 3.6
DEFAULT_TOP = 20
TOKENIZERS = ("heuristic", "exact")
EXACT_ENCODING = "o200k_base"
_ALWAYS_SKIP_DIRS = frozenset({".git", ".carrel"})

# chars-per-token safety factor when pre-splitting an oversized file, per
# format: json escapes newlines/quotes (worst case 2x), xml only "]]>".
_SPLIT_SAFETY = {"md": 0.97, "xml": 0.92, "json": 0.5}

# the `tokens` extra is a Python package, not a binary, but it degrades exactly
# like one: exit 3 with the install hint (MissingDependencyError semantics).
_TIKTOKEN = Adapter(
    name="tiktoken",
    binaries=("tiktoken",),
    version_args=(),
    install_hint=(
        f"uv tool install '{PRODUCT['package']}[tokens]' "
        "(or `uv sync --extra tokens` from a checkout)"
    ),
    purpose=f"exact token counts for `{PRODUCT['cli']} pack --tokenizer exact`",
)

TokenCounter = Callable[[str], int]

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


def exact_token_counter(encoding: str = EXACT_ENCODING) -> TokenCounter:
    """A tiktoken-backed counter, or MissingDependencyError (exit 3) without the extra."""
    try:
        import tiktoken
    except ImportError as e:
        raise MissingDependencyError(_TIKTOKEN) from e
    try:
        enc = tiktoken.get_encoding(encoding)
    except Exception as e:  # tiktoken fetches the BPE table on first use; offline → clean error
        raise CarrelError(
            f"tiktoken could not load encoding {encoding!r}: {e} "
            "(first use needs network access to fetch the vocabulary; it is cached afterwards)"
        ) from e

    def count(text: str) -> int:
        return len(enc.encode(text, disallowed_special=()))

    return count


def _token_counter(tokenizer: str) -> TokenCounter:
    if tokenizer == "heuristic":
        return estimate_tokens
    if tokenizer == "exact":
        return exact_token_counter()
    raise CarrelInputError(f"unknown tokenizer: {tokenizer} (choose {' or '.join(TOKENIZERS)})")


def _tok_key(meta: dict[str, Any]) -> str:
    """Name of the token field: `tokens` under an exact tokenizer, else `tokens_est`."""
    return "tokens" if meta.get("tokenizer") else "tokens_est"


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
class _IgnoreRule:
    pattern: str
    dir_only: bool
    negate: bool


@dataclass(frozen=True)
class _IgnoreFile:
    base: Path
    rules: tuple[_IgnoreRule, ...]  # in file order; the last matching rule wins


def _load_ignore(directory: Path) -> _IgnoreFile | None:
    gi = directory / ".gitignore"
    if not gi.is_file():
        return None
    rules: list[_IgnoreRule] = []
    try:
        lines = gi.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:].strip()
        elif line.startswith("\\!"):
            line = line[1:]  # escaped literal "!"
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if line:
            rules.append(_IgnoreRule(line, dir_only, negate))
    return _IgnoreFile(directory, tuple(rules)) if rules else None


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


def _rule_matches(rule: _IgnoreRule, rel: str, name: str, is_dir: bool) -> bool:
    if rule.dir_only and not is_dir:
        return False
    if "/" in rule.pattern:
        return fnmatch(rel, rule.pattern.lstrip("/"))
    return fnmatch(name, rule.pattern)


def _ignored(path: Path, is_dir: bool, ignores: tuple[_IgnoreFile, ...]) -> bool:
    """Git semantics: rules apply in order (outer .gitignore first, then file
    order); the last matching rule decides, `!pattern` re-includes."""
    result = False
    for ig in ignores:
        try:
            rel = path.relative_to(ig.base).as_posix()
        except ValueError:
            continue
        for rule in ig.rules:
            if _rule_matches(rule, rel, path.name, is_dir):
                result = not rule.negate
    return result


# --------------------------------------------------------------------------
# data model


@dataclass(frozen=True)
class PackEntry:
    path: str  # display path (POSIX, relative to root)
    size: int  # bytes on disk
    ftype: str  # FileType value ("txt", "pdf", "unknown", ...)
    content: str | None  # extracted text; None when skipped/tree-only
    tokens_est: int  # token count under the active tokenizer (name is historical)
    skipped: str | None = None  # reason, or None when included
    continued: bool = False  # True on split pieces in chunked output
    score: float | None = None  # bm25 rank under --query (lower is better)
    same_as: str | None = None  # --dedupe-content: path of the identical file packed first
    outline: tuple[str, ...] | None = None  # --outline: structural lines

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
        key = _tok_key(self.meta)
        rows: list[dict[str, Any]] = []
        for e in self.entries:
            row: dict[str, Any] = {
                "path": e.path,
                "type": e.ftype,
                "bytes": e.size,
                key: e.tokens_est,
                "skipped": e.skipped,
            }
            if e.score is not None:
                row["score"] = e.score
            if e.same_as is not None:
                row["same_as"] = e.same_as
            if e.outline is not None:
                row["outline"] = list(e.outline)
            rows.append(row)
        totals: dict[str, Any] = {
            "files": len(self.entries),
            "included": self.meta["files_included"],
            "skipped": self.meta["files_skipped"],
            "bytes": self.meta["bytes"],
            key: self.meta[key],
        }
        for extra in (
            "tokenizer",
            "query",
            "top",
            "hits",
            "since",
            "changed",
            "untracked",
            "deduped",
        ):
            if extra in self.meta:
                totals[extra] = self.meta[extra]
        if "removed" in self.meta:
            totals["removed"] = list(self.meta["removed"])
        return {"files": rows, "totals": totals}


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
# outline (--outline: structure only, tree-only cost class)

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _outline_py(source: str) -> list[str]:
    try:
        module = ast.parse(source)
    except (SyntaxError, ValueError):
        return ["[unparsable]"]
    items: list[str] = []
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            items.append(f"L{node.lineno} class {node.name}")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            items.append(f"L{node.lineno} {kind} {node.name}")
    return items


def _outline_md(source: str) -> list[str]:
    items: list[str] = []
    in_fence = False
    for n, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _MD_HEADING.match(line)
        if m:
            items.append(f"L{n} {m.group(1)} {m.group(2)}")
    return items


def _outline_of(path: Path) -> tuple[str, ...]:
    suffix = path.suffix.lower()
    if suffix not in (".py", ".md", ".markdown"):
        return ()  # other types: size only (rendered on the tree line)
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ("[unreadable]",)
    return tuple(_outline_py(source) if suffix == ".py" else _outline_md(source))


# --------------------------------------------------------------------------
# tree rendering


def _tree_note(e: PackEntry) -> str:
    if e.same_as is not None:
        return f"  [same as {e.same_as}]"
    if e.skipped:
        return f"  [skipped: {e.skipped}] ({_human_size(e.size)})"
    parts: list[str] = []
    if e.outline is not None and not e.outline:
        parts.append(f"({_human_size(e.size)})")
    if e.score is not None:
        parts.append(f"[score {e.score:.3g}]")
    return ("  " + " ".join(parts)) if parts else ""


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
                lines.append(f"{prefix}{branch}{name}{_tree_note(val)}")
                if val.outline:
                    indent = prefix + ("    " if last else "│   ") + "  "
                    lines.extend(f"{indent}{item}" for item in val.outline)

    rec(tree, "")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# format renderers — signature: (meta, tree|None, entries, part|None) -> str


def _header_lines(meta: dict[str, Any], part: tuple[int, int] | None) -> list[str]:
    key = _tok_key(meta)
    lines = [
        f"generated-by: {meta['generated_by']}",
        f"root: {meta['root']}",
        f"files: {meta['files_included']} included, {meta['files_skipped']} skipped",
        f"{key}: {meta[key]}",
    ]
    if meta.get("tokenizer"):
        lines.append(f"tokenizer: {meta['tokenizer']}")
    if "query" in meta:
        hits = meta["hits"]
        how = f"{hits} hit(s)" if hits else "no hits"
        lines.append(f"query: {meta['query']!r} (top {meta['top']}, {how})")
    if meta.get("untracked"):
        lines.append(
            f"changed: {meta['changed']} vs {meta['since']} (+ untracked), "
            f"{len(meta['removed'])} removed"
        )
    elif "since" in meta:
        lines.append(
            f"since: {meta['since']} ({meta['changed']} changed, {len(meta['removed'])} removed)"
        )
    if meta.get("removed"):
        lines.append("removed: " + ", ".join(meta["removed"]))
    if meta.get("omitted_budget"):
        lines.append(
            f"omitted over --max-bytes budget: {len(meta['omitted_budget'])} file(s): "
            + ", ".join(meta["omitted_budget"])
        )
    if "deduped" in meta:
        lines.append(f"deduped: {meta['deduped']} identical file(s) not inlined")
    if meta.get("outline"):
        lines.append("outline: structure only, file contents omitted")
    elif meta.get("tree_only"):
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
    key = _tok_key(meta)
    xkey = key.replace("_", "-")
    attrs = {
        "generated-by": meta["generated_by"],
        "root": meta["root"],
        "files": str(meta["files_included"]),
        xkey: str(meta[key]),
    }
    if meta.get("tokenizer"):
        attrs["tokenizer"] = meta["tokenizer"]
    if "query" in meta:
        attrs["query"] = meta["query"]
        attrs["top"] = str(meta["top"])
        attrs["hits"] = str(meta["hits"])
    if "since" in meta:
        attrs["since"] = meta["since"]
        attrs["changed"] = str(meta["changed"])
    if meta.get("untracked"):
        attrs["untracked"] = "true"
    if "removed" in meta:
        attrs["removed"] = str(len(meta["removed"]))
    if meta.get("omitted_budget"):
        attrs["omitted-budget"] = str(len(meta["omitted_budget"]))
    if "deduped" in meta:
        attrs["deduped"] = str(meta["deduped"])
    if meta.get("outline"):
        attrs["outline"] = "true"
    if part:
        attrs["part"] = f"{part[0]}/{part[1]}"
    attr_s = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
    out = [f"<context {attr_s}>"]
    if tree is not None:
        out.append(f"<tree>{_cdata(tree)}</tree>")
    for e in entries:
        fa = f'path={quoteattr(e.path)} {xkey}="{e.tokens_est}"'
        if e.score is not None:
            fa += f' score="{e.score}"'
        if e.continued:
            fa += ' continued="true"'
        out.append(f"<file {fa}>{_cdata(e.content or '')}</file>")
    out.append("</context>")
    return "\n".join(out) + "\n"


def _json_file(e: PackEntry, key: str) -> dict[str, Any]:
    obj: dict[str, Any] = {"path": e.path, key: e.tokens_est, "content": e.content or ""}
    if e.score is not None:
        obj["score"] = e.score
    if e.continued:
        obj["continued"] = True
    return obj


def _json_outline_file(e: PackEntry) -> dict[str, Any]:
    obj: dict[str, Any] = {"path": e.path, "bytes": e.size, "outline": list(e.outline or ())}
    if e.score is not None:
        obj["score"] = e.score
    return obj


def _render_json(
    meta: dict[str, Any], tree: str | None, entries: list[PackEntry], part: tuple[int, int] | None
) -> str:
    m = dict(meta)
    if part:
        m["part"] = f"{part[0]}/{part[1]}"
    key = _tok_key(meta)
    if meta.get("outline"):
        files = [_json_outline_file(e) for e in entries]
    else:
        files = [_json_file(e, key) for e in entries]
    obj = {"meta": m, "tree": tree or "", "files": files}
    return jsonlib.dumps(obj, indent=2, ensure_ascii=False) + "\n"


_RENDERERS = {"md": _render_md, "xml": _render_xml, "json": _render_json}


# --------------------------------------------------------------------------
# chunking


def _split_entry(
    e: PackEntry,
    fmt: str,
    meta: dict[str, Any],
    budget: int,
    count: TokenCounter = estimate_tokens,
) -> list[PackEntry]:
    """Split one oversized file on line boundaries into budget-sized pieces."""
    render = _RENDERERS[fmt]
    empty = dataclasses.replace(e, content="", continued=True)
    overhead = count(render(meta, None, [empty], (1, 1)))
    avail = int((budget - overhead) * CHARS_PER_TOKEN * _SPLIT_SAFETY[fmt])
    if avail < 1:
        raise CarrelInputError(f"--chunk {budget} is too small to fit any content of {e.path}")

    def split(avail: int) -> list[str]:
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
        return chunks

    def fits(chunks: list[str]) -> bool:
        return all(
            count(render(meta, None, [dataclasses.replace(e, content=c, continued=True)], (1, 1)))
            <= budget
            for c in chunks
        )

    # the chars/token ratio is only a heuristic (and an exact tokenizer may
    # disagree with it on dense text): tighten until every piece really fits.
    chunks = split(avail)
    while not fits(chunks):
        avail = int(avail * 0.8)
        if avail < 1:
            raise CarrelInputError(f"--chunk {budget} is too small to fit any content of {e.path}")
        chunks = split(avail)
    return [
        dataclasses.replace(e, content=c, tokens_est=count(c), continued=i > 0)
        for i, c in enumerate(chunks)
    ]


def _chunked_documents(
    fmt: str,
    meta: dict[str, Any],
    tree: str,
    entries: list[PackEntry],
    budget: int,
    count: TokenCounter = estimate_tokens,
) -> list[str]:
    render = _RENDERERS[fmt]

    def doc_tokens(group: list[PackEntry], with_tree: bool) -> int:
        return count(render(meta, tree if with_tree else None, group, (1, 1)))

    pieces: list[PackEntry] = []
    for e in entries:
        if doc_tokens([e], False) > budget:
            pieces.extend(_split_entry(e, fmt, meta, budget, count))
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
# git-aware selection (--since / --changed) — all git calls via the adapter


def _git(*args: str) -> str:
    """Run git through the adapter; non-zero exit → CarrelInputError with git's first stderr line."""
    proc = adapters.run("git", "-c", "core.quotePath=false", *args)
    if proc.returncode != 0:
        first = next((ln for ln in (proc.stderr or "").splitlines() if ln.strip()), "")
        raise CarrelInputError(first.strip() or f"git {' '.join(args)} failed ({proc.returncode})")
    return proc.stdout or ""


def _git_root(path: Path) -> Path:
    return Path(_git("-C", str(path), "rev-parse", "--show-toplevel").strip()).resolve()


def _git_changed(root: Path, *, since: str | None, changed: bool) -> set[Path]:
    """Absolute paths named by `git diff --name-only REF` (+ untracked for --changed)."""
    top = _git_root(root)
    names: list[str] = []
    ref = since if since is not None else "HEAD"
    names += _git("-C", str(top), "diff", "--name-only", "-z", ref).split("\0")
    if changed:
        names += _git("-C", str(top), "ls-files", "--others", "--exclude-standard", "-z").split(
            "\0"
        )
    return {(top / n).resolve() for n in names if n}


# --------------------------------------------------------------------------
# query-driven selection (--query) — desk FTS index under the desk root


class BadQueryError(CarrelInputError):
    """Malformed FTS5 syntax in --query (the CLI reports it as a usage error, exit 2)."""


def _query_hits(desk_root: Path, query: str, top: int) -> dict[Path, float]:
    """Absolute path → bm25 score for the top FTS hits (lower is better)."""
    if not DeskDB.exists(desk_root):
        raise CarrelInputError(
            f"--query needs a desk index but none exists under {desk_root} — "
            f"run `{PRODUCT['cli']} index --root {desk_root}` first"
        )
    hits: dict[Path, float] = {}
    with DeskDB(desk_root) as db:
        try:
            rows = db.fts_search(query, limit=top)
        except sqlite3.OperationalError as e:
            raise BadQueryError(f"bad search query {query!r}: {e}") from e
        for row in rows:
            p = (db.root / row["path"]).resolve()
            hits.setdefault(p, float(row["score"]))
    return hits


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
    query: str | None = None,
    top: int = DEFAULT_TOP,
    desk_root: Path | str | None = None,
    since: str | None = None,
    changed: bool = False,
    dedupe_content: bool = False,
    tokenizer: str = "heuristic",
    outline: bool = False,
) -> PackResult:
    """Walk `paths` and render a context pack; see the `pack` command --help.

    Keyword-only v2 options (all default to v1 behavior):
      query/top/desk_root — keep only FTS hits from the desk index under
        `desk_root` (default: the pack root), emitted in relevance order.
      since/changed — keep only files `git diff --name-only REF` (resp. HEAD
        plus untracked) reports; deleted ones are listed in meta["removed"].
      dedupe_content — inline identical content once (meta["deduped"]).
      tokenizer — "heuristic" (ceil(chars/3.6), field `tokens_est`) or
        "exact" (tiktoken o200k_base, field `tokens`).
      outline — structure only (py defs/classes, md headings), no contents.
    """
    if fmt not in _RENDERERS:
        raise CarrelInputError(f"unknown pack format: {fmt} (choose md, xml or json)")
    if chunk is not None and chunk <= 0:
        raise CarrelInputError("--chunk must be a positive token count")
    if since is not None and changed:
        raise CarrelInputError("--since and --changed are mutually exclusive")
    if outline and chunk:
        raise CarrelInputError("--outline cannot be combined with --chunk")
    if top < 1:
        raise CarrelInputError("--top must be a positive integer")
    count = _token_counter(tokenizer)
    tops = [Path(p).resolve() for p in paths]
    if not tops:
        raise CarrelInputError("no paths given")
    for t in tops:
        if not t.exists():
            raise CarrelInputError(f"no such path: {t}")
    common = Path(os.path.commonpath([str(t) for t in tops]))
    root = common if common.is_dir() else common.parent
    if outline:
        tree_only = True

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

    # -- git-aware narrowing -------------------------------------------------
    removed: list[str] = []
    n_changed = 0
    if since is not None or changed:
        git_set = _git_changed(root, since=since, changed=changed)
        collected = [p for p in collected if p in git_set]
        n_changed = len(collected)
        for p in sorted(git_set):
            if not p.exists() and p.is_relative_to(root):
                removed.append(rel_of(p))

    # -- query narrowing (relevance order) ---------------------------------
    scores: dict[Path, float] = {}
    n_hits = 0
    if query is not None:
        desk = Path(desk_root).resolve() if desk_root is not None else root
        scores = _query_hits(desk, query, top)
        hit_set = set(scores)
        collected = sorted(
            (p for p in collected if p in hit_set), key=lambda p: (scores[p], rel_of(p))
        )
        n_hits = len(collected)

    # -- extraction ----------------------------------------------------------
    entries: list[PackEntry] = []
    used = 0
    omitted: list[str] = []
    budget_hit = False
    hashes: dict[str, str] = {}
    deduped = 0
    for f in collected:
        rel = rel_of(f)
        try:
            size = f.stat().st_size
        except OSError:
            continue
        ftype = detect(f)
        content: str | None = None
        skipped: str | None = None
        same_as: str | None = None
        digest: str | None = None
        if max_file_bytes is not None and size > max_file_bytes:
            skipped = "exceeds --max-file-bytes"
        elif ftype is FileType.UNKNOWN and not _looks_text(f):
            skipped = "binary"
        elif ftype.is_image and not ocr:
            skipped = "binary"  # images are listed, never inlined (use --ocr)
        elif dedupe_content and (digest := _safe_hash(f)) is not None and digest in hashes:
            same_as = hashes[digest]
            skipped = f"same as {same_as}"
            deduped += 1
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
        if skipped is None and digest is not None:
            hashes[digest] = rel
        tokens = count(content) if content else 0
        entries.append(
            PackEntry(
                rel,
                size,
                ftype.value,
                content,
                tokens,
                skipped,
                score=scores.get(f),
                same_as=same_as,
                outline=_outline_of(f) if outline and skipped is None else None,
            )
        )

    included = [e for e in entries if e.included]
    tok_key = "tokens" if tokenizer == "exact" else "tokens_est"
    meta: dict[str, Any] = {
        "generated_by": f"{PRODUCT['name']} {PRODUCT['version']}",
        "root": str(root),
        "files_included": len(included),
        "files_skipped": len(entries) - len(included),
        "bytes": sum(e.size for e in included),
        tok_key: sum(e.tokens_est for e in included),
    }
    if tokenizer == "exact":
        meta["tokenizer"] = f"exact (tiktoken {EXACT_ENCODING})"
    if query is not None:
        meta["query"] = query
        meta["top"] = top
        meta["hits"] = n_hits
    if since is not None or changed:
        meta["since"] = since if since is not None else "HEAD"
        meta["changed"] = n_changed
        meta["removed"] = removed
        if changed:
            meta["untracked"] = True
    if omitted:
        meta["omitted_budget"] = omitted
    if dedupe_content:
        meta["deduped"] = deduped
    if outline:
        meta["outline"] = True
    if tree_only:
        meta["tree_only"] = True

    tree = _render_tree(root.name or str(root), entries)
    body = included if outline else ([] if tree_only else included)
    if chunk:
        documents = _chunked_documents(fmt, meta, tree, body, chunk, count)
    elif outline and fmt != "json":
        documents = [_RENDERERS[fmt](meta, tree, [], None)]  # outline lives in the tree
    else:
        documents = [_RENDERERS[fmt](meta, tree, body, None)]
    return PackResult(
        fmt=fmt, root=root, meta=meta, tree=tree, entries=entries, documents=documents
    )


def _safe_hash(path: Path) -> str | None:
    try:
        return file_hash(path)
    except OSError:
        return None


# --------------------------------------------------------------------------
# CLI


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


def _print_stats_table(data: dict[str, Any]) -> None:
    from rich.console import Console
    from rich.table import Table

    totals = data["totals"]
    key = "tokens" if "tokens" in totals else "tokens_est"
    with_score = any("score" in row for row in data["files"])
    table = Table(title="pack stats")
    cols = ["path", "type", "size", key, *(["score"] if with_score else []), "note"]
    for col in cols:
        table.add_column(col)
    for row in data["files"]:
        cells = [row["path"], row["type"], _human_size(row["bytes"]), str(row[key])]
        if with_score:
            cells.append("" if row.get("score") is None else f"{row['score']:.3g}")
        cells.append(row["skipped"] or "")
        table.add_row(*cells)
    table.add_section()
    total_cells = [
        "TOTAL",
        f"{totals['included']} in / {totals['skipped']} skip",
        _human_size(totals["bytes"]),
        str(totals[key]),
    ]
    if with_score:
        total_cells.append("")
    notes = [f"{k}: {totals[k]}" for k in ("tokenizer", "deduped") if k in totals]
    if "removed" in totals:
        notes.append(f"removed: {len(totals['removed'])}")
    total_cells.append("; ".join(notes))
    table.add_row(*total_cells)
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
    help="Split into OUT.part1..N, each at most TOKENS tokens under the active "
    "--tokenizer (requires -o). Files are never split mid-file "
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
@click.option(
    "--query",
    metavar="TEXT",
    help="Pack only files the desk index under --root ranks for TEXT (FTS5 "
    "syntax), in relevance order. Requires a prior `index` run.",
)
@click.option(
    "--top",
    type=int,
    default=DEFAULT_TOP,
    show_default=True,
    metavar="N",
    help="With --query: consider at most the N best-ranked hits.",
)
@click.option(
    "--since",
    metavar="REF",
    help="Pack only files changed since git REF (`git diff --name-only REF`); "
    "deleted files are listed as removed, not packed.",
)
@click.option(
    "--changed",
    is_flag=True,
    help="Pack only uncommitted changes: files differing from HEAD plus "
    "untracked files (not --since).",
)
@click.option(
    "--dedupe-content",
    is_flag=True,
    help="Inline identical file contents once; later copies are tree-listed "
    "as [same as <first path>].",
)
@click.option(
    "--tokenizer",
    type=click.Choice(list(TOKENIZERS)),
    default="heuristic",
    show_default=True,
    help="Token counting: heuristic = ceil(chars/3.6) labeled tokens_est; "
    f"exact = tiktoken {EXACT_ENCODING} labeled tokens (needs the "
    f"'{PRODUCT['package']}[tokens]' extra).",
)
@click.option(
    "--outline",
    is_flag=True,
    help="Structure instead of contents (tree-only cost): .py top-level "
    "def/class names with line numbers, .md headings; other types show "
    "size only. Not with --chunk.",
)
@click.option(
    "--fail-empty",
    is_flag=True,
    help="Exit 5 when no file is packed (e.g. --query without hits, --since with no changes).",
)
@click.pass_context
@_handled
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
    query: str | None,
    top: int,
    since: str | None,
    changed: bool,
    dedupe_content: bool,
    tokenizer: str,
    outline: bool,
    fail_empty: bool,
) -> None:
    """Bundle PATH... (files or directories) into one LLM-ready context document.

    Formats: md (default: header + fenced tree + per-file fenced sections,
    fences lengthened on collision), xml (<context><tree/><file/></context>
    with CDATA, Claude-friendly), json ({meta, tree, files}). Token counts
    are ceil(chars / 3.6) labeled tokens_est by default; --tokenizer exact
    counts with tiktoken (o200k_base) and labels the field tokens.

    Selection: --query ranks files through the desk index under --root (build
    it with the `index` command) and emits hits in relevance order;
    --since REF / --changed narrow to what git reports as changed (deleted
    files are listed in the header as removed; --since REF compares REF with
    the working tree). --query combines with either git selector and with the
    usual --include/--exclude filters (intersection); --since and --changed
    exclude each other.

    .gitignore handling is a deliberately simple per-directory matcher:
    plain names and `*` globs match anywhere below their .gitignore; a
    trailing `/` restricts a pattern to directories; patterns containing `/`
    match relative to their .gitignore's directory; `!pattern` re-includes,
    with git's ordering rule (last matching line wins) — the negation is
    honored. `.git` and `.carrel` are always skipped. Binaries outside the
    supported set are listed in the tree as [skipped: binary] with their
    size, never inlined; images are only read (OCR) with --ocr.
    """
    if chunk is not None and chunk <= 0:
        raise click.UsageError("--chunk must be a positive token count")
    if chunk and not output:
        raise click.UsageError("--chunk requires -o/--output (parts are named OUT.part1..N)")
    if since is not None and changed:
        raise click.UsageError("--since and --changed are mutually exclusive")
    if outline and chunk:
        raise click.UsageError("--outline cannot be combined with --chunk")
    if top < 1:
        raise click.UsageError("--top must be a positive integer")
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json and not output and not show_stats:
        fmt = "json"  # global --json: stdout must be one JSON document
    desk_root = Path((ctx.obj or {}).get("root", ".")).resolve()

    try:
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
            query=query,
            top=top,
            desk_root=desk_root,
            since=since,
            changed=changed,
            dedupe_content=dedupe_content,
            tokenizer=tokenizer,
            outline=outline,
        )
    except BadQueryError as e:
        raise click.UsageError(str(e)) from e
    if fail_empty and result.meta["files_included"] == 0:
        what = f"no files matched --query {query!r}" if query is not None else "no files to pack"
        fail(what, ExitCode.EMPTY)

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
        key = _tok_key(result.meta)
        emit(
            ctx,
            summary,
            human=lambda d: click.echo(
                f"wrote {', '.join(d['written'])} ({d['files_included']} files, ~{d[key]} {key})",
                err=True,
            ),
        )
        return
    click.echo(result.document, nl=False)
