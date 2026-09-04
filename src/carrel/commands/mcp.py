"""carrel mcp — stdio MCP server (pure stdlib JSON-RPC 2.0).

Transport per the MCP stdio spec: newline-delimited JSON — ONE JSON-RPC
message per line on stdin/stdout, no Content-Length framing.

The three tool bodies below are implemented directly against the core
primitives (DeskDB, textextract, filetypes). Richer per-type detail lives in
the CLI command modules (pack/search/inspect); once those land their impl
functions can be reused here without changing the wire surface.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sys
from collections.abc import Iterator
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any, TextIO

import click

from carrel._product import PRODUCT
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError
from carrel.core.textextract import extract_text

DEFAULT_PROTOCOL_VERSION = "2025-06-18"
_SHA256_CAP = 512 * 1024 * 1024  # skip hashing files >= 512 MB
_SKIP_DIRS = {".git", ".carrel", "__pycache__", "node_modules"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "carrel_search",
        "description": "Full-text search the carrel desk index (.carrel/carrel.db) "
        "under a root directory. Requires a prior `carrel index` run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "FTS5 match query."},
                "root": {"type": "string", "description": "Desk root (default: server cwd)."},
                "limit": {"type": "integer", "description": "Max results.", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "carrel_pack",
        "description": "Pack a file or directory into LLM-ready context: file tree "
        "plus extracted text contents of supported files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to pack."},
                "max_bytes": {
                    "type": "integer",
                    "description": "Content budget in bytes; files past it are listed but omitted.",
                },
                "tree_only": {
                    "type": "boolean",
                    "description": "Tree without contents.",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "carrel_inspect",
        "description": "Metadata for one file: detected type, size, mtime, sha256, mime guess.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to inspect."},
            },
            "required": ["path"],
        },
    },
]


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


def _resolve(raw: str, default_root: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (default_root / path)


def _tool_search(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    query = args["query"]
    root = _resolve(args.get("root") or ".", default_root)
    limit = int(args.get("limit") or 20)
    if not DeskDB.exists(root):
        raise CarrelInputError(
            f"no {PRODUCT['cli']} index under {root} — "
            f"run `{PRODUCT['cli']} index --root {root}` first"
        )
    with DeskDB(root) as db:
        rows = db.fts_search(query, limit=limit)
    return {
        "query": query,
        "root": str(root),
        "count": len(rows),
        "results": [
            {"path": r["path"], "type": r["type"], "score": r["score"], "snippet": r["snip"]}
            for r in rows
        ],
    }


def _walk(path: Path) -> Iterator[Path]:
    """Deterministic walk: dirs first, alphabetical; skips .git/.carrel/hidden dirs."""
    if path.is_file():
        yield path
        return
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for entry in entries:
        if entry.is_dir():
            if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            yield from _walk(entry)
        elif entry.is_file():
            yield entry


def _tokens_est(text: str) -> int:
    return ceil(len(text) / 3.6)


def _tool_pack(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    path = _resolve(args["path"], default_root)
    if not path.exists():
        raise CarrelInputError(f"no such path: {path}")
    max_bytes = args.get("max_bytes")
    tree_only = bool(args.get("tree_only") or False)
    base = path if path.is_dir() else path.parent

    tree: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    omitted: list[str] = []
    used = 0
    for f in _walk(path):
        rel = str(f.relative_to(base))
        ftype = detect(f)
        size = f.stat().st_size
        entry: dict[str, Any] = {"path": rel, "type": ftype.value, "size": size}
        extractable = ftype.is_text or ftype is FileType.PDF
        if not extractable:
            entry["skipped"] = "binary"
        tree.append(entry)
        if tree_only or not extractable:
            continue
        try:
            text = extract_text(f)
        except CarrelError as e:  # per-file degradation (e.g. pdftotext missing)
            entry["error"] = str(e).splitlines()[0]
            continue
        nbytes = len(text.encode())
        if max_bytes is not None and used + nbytes > int(max_bytes):
            omitted.append(rel)
            continue
        used += nbytes
        files.append({"path": rel, "tokens_est": _tokens_est(text), "content": text})

    return {
        "root": str(path),
        "tree": tree,
        "files": files,
        "omitted": omitted,
        "meta": {
            "file_count": len(tree),
            "packed": len(files),
            "content_bytes": used,
            "tokens_est": sum(f["tokens_est"] for f in files),
            "tree_only": tree_only,
        },
    }


def _sha256(path: Path) -> str | None:
    if path.stat().st_size >= _SHA256_CAP:
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tool_inspect(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    path = _resolve(args["path"], default_root)
    ftype = detect_or_die(path)
    st = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "type": ftype.value,
        "mime": mimetypes.guess_type(path.name)[0],
        "sha256": _sha256(path),
    }


_TOOL_IMPLS = {
    "carrel_search": _tool_search,
    "carrel_pack": _tool_pack,
    "carrel_inspect": _tool_inspect,
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _handle(msg: Any, default_root: Path) -> dict[str, Any] | None:
    """Handle one decoded message; None means no response (notification)."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request: expected a JSON object")
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    if method == "initialize":
        result: Any = {
            # echo the client's requested version — we speak plain tools either way
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": PRODUCT["name"], "version": PRODUCT["version"]},
        }
    elif method == "notifications/initialized":
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = str(params.get("name") or "")
        impl = _TOOL_IMPLS.get(name)
        if impl is None:
            return None if is_notification else _error(mid, -32602, f"unknown tool: {name}")
        try:
            payload = impl(params.get("arguments") or {}, default_root)
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}
                ],
                "isError": False,
            }
        except Exception as e:  # noqa: BLE001 — tool failures are data, not crashes
            result = {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                "isError": True,
            }
    else:
        return None if is_notification else _error(mid, -32601, f"method not found: {method}")

    return None if is_notification else {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin: TextIO, stdout: TextIO, default_root: Path | str = ".") -> None:
    """Serve newline-delimited JSON-RPC until EOF (clean exit)."""
    root = Path(default_root).resolve()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            response: dict[str, Any] | None = _error(None, -32700, f"parse error: {e}")
        else:
            response = _handle(msg, root)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            stdout.flush()


@click.command(name="mcp")
@click.pass_context
def cmd(ctx: click.Context) -> None:
    """Serve the desk as an MCP server on stdio (search/pack/inspect tools)."""
    ctx.ensure_object(dict)
    serve(sys.stdin, sys.stdout, default_root=ctx.obj.get("root", "."))
