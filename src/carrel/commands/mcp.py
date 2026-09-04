"""carrel mcp — stdio MCP server (pure stdlib JSON-RPC 2.0).

Transport per the MCP stdio spec: newline-delimited JSON — ONE JSON-RPC
message per line on stdin/stdout, no Content-Length framing, no SDK.

Ten tools, each a thin shim over a command module's library entry point
(pack.pack_paths, search.search_index, inspect.inspect_path, convert.convert_file,
diff.diff_files, redact's text engine, doctor.build_report, DeskDB for tags and
notes, index.index_paths when the build provides it). Nothing here walks a
tree or estimates tokens on its own. Two resource templates expose file text
and desk search as `carrel://` URIs.

Every tool failure is returned as `isError: true` carrying the same message the
CLI would print (CarrelError text, install hints included) — never a crash.
"""

from __future__ import annotations

import importlib
import inspect as pyinspect
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import unquote

import click

from carrel._product import PRODUCT
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError
from carrel.core.textextract import extract_text

DEFAULT_PROTOCOL_VERSION = "2025-06-18"
CONVERT_CONTENT_CAP = 1024 * 1024  # bytes of converted text returned inline
_PACK_FORMATS = ("json", "md", "xml")
_DIFF_MODES = ("auto", "text", "struct", "pdf", "image")
_URI_FILE = "carrel://file/"
_URI_SEARCH = "carrel://search/"
RESOURCE_NOT_FOUND = -32002


def _pack_accepts(param: str) -> bool:
    """True when pack.pack_paths takes `param` (spec 16 adds query/top; pass-through only)."""
    from carrel.commands.pack import pack_paths

    return param in pyinspect.signature(pack_paths).parameters


_PACK_HAS_QUERY = _pack_accepts("query")
_PACK_HAS_TOP = _pack_accepts("top")


def _str_array(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


_ROOT_PROP = {"type": "string", "description": "Desk root (default: server --root / cwd)."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "carrel_search",
        "description": "Full-text search the carrel desk index (.carrel/carrel.db) "
        "under a root directory. Requires a prior `carrel index` run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "FTS5 match query."},
                "root": _ROOT_PROP,
                "limit": {"type": "integer", "description": "Max results.", "default": 20},
                "types": _str_array('Only these file types (e.g. ["pdf", "md"]).'),
                "tags": _str_array("Only files carrying every one of these tags."),
            },
            "required": ["query"],
        },
    },
    {
        "name": "carrel_pack",
        "description": "Pack a file or directory into LLM-ready context: file tree "
        "plus extracted text of supported files (text, pdf, office, ebook).",
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
                "format": {
                    "type": "string",
                    "enum": list(_PACK_FORMATS),
                    "default": "json",
                    "description": "json: structured object; md/xml: rendered pack document.",
                },
                "include": _str_array("Only pack files matching these globs."),
                "exclude": _str_array("Drop files/dirs matching these globs."),
                "root": _ROOT_PROP,
                **(
                    {
                        "query": {
                            "type": "string",
                            "description": "Relevance-rank files by this desk-index query.",
                        }
                    }
                    if _PACK_HAS_QUERY
                    else {}
                ),
                **(
                    {"top": {"type": "integer", "description": "Max query hits to pack."}}
                    if _PACK_HAS_TOP
                    else {}
                ),
            },
            "required": ["path"],
        },
    },
    {
        "name": "carrel_inspect",
        "description": "Metadata for one file: detected type, size, mtime, sha256, mime guess "
        "and per-type detail (pages, dimensions, headings, columns, ...).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to inspect."},
                "deep": {
                    "type": "boolean",
                    "description": "Add exiftool's full tag table when installed.",
                    "default": False,
                },
                "root": _ROOT_PROP,
            },
            "required": ["path"],
        },
    },
    {
        "name": "carrel_tag",
        "description": "Manage desk tags: add/rm/ls tags on a file, or find files by tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "rm", "ls", "find"]},
                "path": {"type": "string", "description": "File (add/rm/ls)."},
                "tags": _str_array("Tags to add/remove, or all-of tags to find."),
                "root": _ROOT_PROP,
            },
            "required": ["action"],
        },
    },
    {
        "name": "carrel_note",
        "description": "Attach a free-text note to a file in the desk db, or list its notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "ls"]},
                "path": {"type": "string", "description": "File the note belongs to."},
                "body": {"type": "string", "description": "Note text (add)."},
                "root": _ROOT_PROP,
            },
            "required": ["action", "path"],
        },
    },
    {
        "name": "carrel_index",
        "description": "Build or refresh the desk full-text index under root "
        "(default: the whole root). Returns indexed/skipped/pruned counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": _str_array("Files or directories to index (default: root)."),
                "update": {
                    "type": "boolean",
                    "description": "Treat paths as individual files; no walking.",
                    "default": False,
                },
                "prune": {
                    "type": "boolean",
                    "description": "Drop index rows whose files are gone.",
                    "default": False,
                },
                "ocr": {
                    "type": "boolean",
                    "description": "OCR images and scanned PDFs (needs tesseract / ocrmypdf).",
                    "default": False,
                },
                "root": _ROOT_PROP,
            },
            "required": [],
        },
    },
    {
        "name": "carrel_convert",
        "description": "Convert a file to another supported type. Text targets also return "
        "the converted content inline (capped at 1 MiB).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Source file."},
                "to": {
                    "type": "string",
                    "description": "Target type: pdf, md, txt, html, json, xml, csv, png, "
                    "jpg, ico, docx, odt, epub.",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Directory for the output (default: next to the source).",
                },
                "force": {
                    "type": "boolean",
                    "description": "Overwrite an existing output.",
                    "default": False,
                },
                "root": _ROOT_PROP,
            },
            "required": ["path", "to"],
        },
    },
    {
        "name": "carrel_diff",
        "description": "Compare two files (text / struct / pdf / image). `differ` is data, "
        "never an error.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "First file."},
                "b": {"type": "string", "description": "Second file."},
                "mode": {"type": "string", "enum": list(_DIFF_MODES), "default": "auto"},
                "root": _ROOT_PROP,
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "carrel_redact",
        "description": "Redact patterns from a text file's contents and return the result. "
        "Never writes; PDFs must go through the CLI (`carrel redact FILE.pdf -o OUT.pdf`).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Text file (txt/md/html/json/csv/xml)."},
                "builtin": _str_array("Builtin patterns: email, phone, ssn, ipv4, cc."),
                "pattern": _str_array("Custom regexes to redact."),
                "replacement": {
                    "type": "string",
                    "description": "Replacement text for matches.",
                    "default": "█",
                },
                "root": _ROOT_PROP,
            },
            "required": ["path"],
        },
    },
    {
        "name": "carrel_doctor",
        "description": "Environment report: external tools found (with versions or install "
        "hints), per-command status, and the capability table gating each command.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

_SCHEMA_BY_NAME = {t["name"]: t["inputSchema"] for t in TOOLS}


# ---------------------------------------------------------------------------
# argument helpers
# ---------------------------------------------------------------------------


def _resolve(raw: str | Path, default_root: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (default_root / path)


def _root(args: dict[str, Any], default_root: Path) -> Path:
    return _resolve(args.get("root") or ".", default_root).resolve()


def _str_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CarrelInputError(f"argument {key!r} must be an array of strings")
    return list(value)


def _choice(args: dict[str, Any], key: str, choices: tuple[str, ...], default: str) -> str:
    value = str(args.get(key) or default)
    if value not in choices:
        raise CarrelInputError(f"{key} must be one of {', '.join(choices)} (got {value!r})")
    return value


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _check_required(name: str, args: dict[str, Any]) -> None:
    missing = [k for k in _SCHEMA_BY_NAME[name].get("required", []) if args.get(k) is None]
    if missing:
        raise CarrelInputError(f"missing required argument(s) for {name}: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


def _tool_search(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.search import search_index

    root = _root(args, default_root)
    query = str(args["query"])
    types = set(_str_list(args, "types")) or None
    tags = _str_list(args, "tags") or None
    hits = search_index(root, query, limit=int(args.get("limit") or 20), types=types, tags=tags)
    return {"query": query, "root": str(root), "count": len(hits), "results": hits}


def _tool_pack(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.pack import pack_paths

    root = _root(args, default_root)
    path = _resolve(args["path"], root)
    fmt = _choice(args, "format", _PACK_FORMATS, "json")
    tree_only = bool(args.get("tree_only") or False)
    max_bytes = args.get("max_bytes")
    kwargs: dict[str, Any] = {
        "fmt": fmt,
        "include": _str_list(args, "include"),
        "exclude": _str_list(args, "exclude"),
        "max_bytes": int(max_bytes) if max_bytes is not None else None,
        "tree_only": tree_only,
    }
    if _PACK_HAS_QUERY and args.get("query"):
        kwargs["query"] = str(args["query"])
        if _PACK_HAS_TOP and args.get("top") is not None:
            kwargs["top"] = int(args["top"])
    result = pack_paths([path], **kwargs)

    entries = [
        {
            "path": e.path,
            "type": e.ftype,
            "size": e.size,
            "tokens_est": e.tokens_est,
            "skipped": e.skipped,
        }
        for e in result.entries
    ]
    payload: dict[str, Any] = {
        "root": str(result.root),
        "format": fmt,
        "meta": result.meta,
        "entries": entries,
        "omitted": list(result.meta.get("omitted_budget", [])),
    }
    if fmt == "json":
        payload["tree"] = result.tree
        payload["files"] = (
            []
            if tree_only
            else [
                {"path": e.path, "tokens_est": e.tokens_est, "content": e.content or ""}
                for e in result.files
            ]
        )
    else:
        payload["document"] = result.document
    return payload


def _tool_inspect(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.inspect import inspect_path

    path = _resolve(args["path"], _root(args, default_root))
    return inspect_path(path, deep=bool(args.get("deep") or False))


def _tool_tag(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    action = _choice(args, "action", ("add", "rm", "ls", "find"), "")
    root = _root(args, default_root)
    tags = _str_list(args, "tags")

    if action == "find":
        if not tags:
            raise CarrelInputError("carrel_tag find requires a non-empty `tags` array")
        if not DeskDB.exists(root):
            return {"root": str(root), "tags": tags, "paths": []}
        with DeskDB(root) as db:
            return {"root": str(root), "tags": tags, "paths": db.find_by_tags(tags)}

    if not args.get("path"):
        raise CarrelInputError(f"carrel_tag {action} requires `path`")
    path = _resolve(args["path"], root)
    if action in ("add", "rm") and not tags:
        raise CarrelInputError(f"carrel_tag {action} requires a non-empty `tags` array")

    if action == "add":
        if not path.is_file():
            raise CarrelInputError(f"no such file: {path}")
        with DeskDB(root) as db:
            db.add_tags(path, tags)
            return {"path": db.rel(path), "tags": db.tags_of(path)}

    # rm / ls never create a desk db as a side effect (same as the CLI)
    if not DeskDB.exists(root):
        return {"path": str(path), "tags": []}
    with DeskDB(root) as db:
        if action == "rm":
            db.rm_tags(path, tags)
        return {"path": db.rel(path), "tags": db.tags_of(path)}


def _tool_note(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    action = _choice(args, "action", ("add", "ls"), "")
    root = _root(args, default_root)
    path = _resolve(args["path"], root)

    if action == "add":
        body = str(args.get("body") or "").strip()
        if not body:
            raise CarrelInputError("carrel_note add requires a non-empty `body`")
        if not path.is_file():
            raise CarrelInputError(f"no such file: {path}")
        with DeskDB(root) as db:
            note_id = db.add_note(path, body)
            newest = db.notes_of(path)[0]
            return {
                "id": note_id,
                "path": db.rel(path),
                "created": _iso(newest["created"]),
                "body": body,
            }

    if not DeskDB.exists(root):
        return {"path": str(path), "notes": []}
    with DeskDB(root) as db:
        notes = [{"created": _iso(r["created"]), "body": r["body"]} for r in db.notes_of(path)]
        return {"path": db.rel(path), "notes": notes}


def _tool_index(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    # index_paths is added by spec 17 (catalog); resolved at call time so this
    # build degrades to a clean tool error when it is absent.
    try:
        module = importlib.import_module("carrel.commands.index")
        index_paths: Callable[..., dict[str, Any]] | None = getattr(module, "index_paths", None)
    except ImportError:
        index_paths = None
    if index_paths is None:
        raise CarrelError(
            "carrel_index is unavailable in this build (carrel.commands.index has no "
            f"index_paths) — run `{PRODUCT['cli']} index --root DIR` from the CLI instead"
        )
    root = _root(args, default_root)
    paths = [_resolve(p, root) for p in _str_list(args, "paths")] or None
    result = index_paths(
        root,
        paths,
        update=bool(args.get("update") or False),
        prune=bool(args.get("prune") or False),
        ocr=bool(args.get("ocr") or False),
    )
    return {"root": str(root), **result}


def _tool_convert(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.convert import convert_file, normalize_target

    root = _root(args, default_root)
    src = _resolve(args["path"], root)
    to = str(args["to"])
    dest_type = normalize_target(to)
    if dest_type is None:
        known = sorted(t.value for t in FileType if t is not FileType.UNKNOWN)
        raise CarrelInputError(f"unknown target type '{to}' (choose from: {', '.join(known)})")
    out_dir = _resolve(args["out_dir"], root) if args.get("out_dir") else src.parent
    dest = (out_dir / src.name).with_suffix(f".{dest_type.value}")
    info = convert_file(src, dest, force=bool(args.get("force") or False))

    payload: dict[str, Any] = {
        "output": info["dest"],
        "type": dest_type.value,
        "via": info["via"],
        "src": info["src"],
    }
    if info.get("dests"):
        payload["outputs"] = info["dests"]
    if dest_type.is_text:
        raw = Path(info["dest"]).read_bytes()
        payload["truncated"] = len(raw) > CONVERT_CONTENT_CAP
        payload["content"] = raw[:CONVERT_CONTENT_CAP].decode("utf-8", errors="replace")
    return payload


def _tool_diff(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.diff import diff_files

    root = _root(args, default_root)
    mode = _choice(args, "mode", _DIFF_MODES, "auto")
    result = diff_files(_resolve(args["a"], root), _resolve(args["b"], root), mode=mode)
    return {**result, "differ": not result["identical"]}


def _tool_redact(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.redact import _check_still_parses, _compile_rules, _redact_text

    root = _root(args, default_root)
    src = _resolve(args["path"], root)
    builtin = _str_list(args, "builtin")
    patterns = tuple(_str_list(args, "pattern"))
    replacement = args.get("replacement")
    replacement = "█" if replacement is None else str(replacement)
    ftype = detect_or_die(src)
    if ftype is FileType.PDF:
        raise CarrelInputError(
            "carrel_redact works on text files only (it returns redacted content and never "
            f"writes); redact PDFs from the CLI: `{PRODUCT['cli']} redact {src} -o OUT.pdf "
            "--builtin email,phone`"
        )
    if not ftype.is_text:
        raise CarrelInputError(f"redact supports text files and PDFs, got {ftype.value}: {src}")
    try:
        rules = _compile_rules(patterns, ",".join(builtin) if builtin else None)
    except click.UsageError as e:
        raise CarrelInputError(e.message) from e
    try:
        content = src.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise CarrelInputError(f"{src} is not valid UTF-8 text: {e}") from e
    redacted, counts = _redact_text(content, rules, replacement)
    _check_still_parses(redacted, ftype, replacement)
    return {
        "path": str(src),
        "type": ftype.value,
        "content": redacted,
        "hits": sum(counts.values()),
        "matches": counts,
    }


def _tool_doctor(args: dict[str, Any], default_root: Path) -> dict[str, Any]:
    from carrel.commands.doctor import CAPABILITIES, build_report

    report = build_report()
    report["capabilities"] = {
        name: {
            "required": list(spec["required"]),
            "optional": list(spec["optional"]),
            "note": spec["note"],
            **({"extra": list(spec["extra"])} if spec.get("extra") else {}),
        }
        for name, spec in sorted(CAPABILITIES.items())
    }
    return report


_TOOL_IMPLS: dict[str, Callable[[dict[str, Any], Path], dict[str, Any]]] = {
    "carrel_search": _tool_search,
    "carrel_pack": _tool_pack,
    "carrel_inspect": _tool_inspect,
    "carrel_tag": _tool_tag,
    "carrel_note": _tool_note,
    "carrel_index": _tool_index,
    "carrel_convert": _tool_convert,
    "carrel_diff": _tool_diff,
    "carrel_redact": _tool_redact,
    "carrel_doctor": _tool_doctor,
}


# ---------------------------------------------------------------------------
# resources
# ---------------------------------------------------------------------------

RESOURCE_TEMPLATES: list[dict[str, Any]] = [
    {
        "uriTemplate": _URI_FILE + "{path}",
        "name": "file text",
        "description": "Extracted text of one file (relative paths resolve against the "
        "server root; URL-encode the path).",
        "mimeType": "text/plain",
    },
    {
        "uriTemplate": _URI_SEARCH + "{query}",
        "name": "desk search",
        "description": "carrel_search results for a URL-encoded FTS5 query, as JSON.",
        "mimeType": "application/json",
    },
]


class _ResourceNotFoundError(Exception):
    """Unknown scheme/shape or a file URI that does not point at a file."""


def _read_resource(uri: str, default_root: Path) -> dict[str, Any]:
    if uri.startswith(_URI_FILE):
        rel = unquote(uri[len(_URI_FILE) :])
        path = _resolve(rel, default_root) if rel else None
        if path is None or not path.is_file():
            raise _ResourceNotFoundError(uri)
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": extract_text(path)}]}
    if uri.startswith(_URI_SEARCH):
        query = unquote(uri[len(_URI_SEARCH) :])
        if not query:
            raise _ResourceNotFoundError(uri)
        payload = _tool_search({"query": query}, default_root)
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
    raise _ResourceNotFoundError(uri)


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
        "isError": False,
    }


def _tool_error(e: Exception) -> dict[str, Any]:
    body: dict[str, Any] = {"error": str(e)}
    if isinstance(e, CarrelError):
        body["exit_code"] = int(e.exit_code)
    return {"content": [{"type": "text", "text": json.dumps(body)}], "isError": True}


def _call_tool(params: dict[str, Any], default_root: Path) -> dict[str, Any]:
    name = str(params.get("name") or "")
    impl = _TOOL_IMPLS[name]
    arguments = params.get("arguments") or {}
    try:
        if not isinstance(arguments, dict):
            raise CarrelInputError("`arguments` must be a JSON object")
        _check_required(name, arguments)
        return _tool_result(impl(arguments, default_root))
    except Exception as e:  # noqa: BLE001 — tool failures are data, not crashes
        return _tool_error(e)


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
            "capabilities": {"tools": {}, "resources": {}},
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
        if name not in _TOOL_IMPLS:
            return None if is_notification else _error(mid, -32602, f"unknown tool: {name}")
        result = _call_tool(params, default_root)
    elif method == "resources/templates/list":
        result = {"resourceTemplates": RESOURCE_TEMPLATES}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "resources/read":
        uri = str(params.get("uri") or "")
        try:
            result = _read_resource(uri, default_root)
        except _ResourceNotFoundError:
            return (
                None
                if is_notification
                else _error(mid, RESOURCE_NOT_FOUND, f"resource not found: {uri}")
            )
        except Exception as e:  # noqa: BLE001 — e.g. no index / missing pdftotext: report, keep serving
            return None if is_notification else _error(mid, -32603, f"cannot read {uri}: {e}")
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
    """Serve the desk as an MCP server on stdio: 10 tools (search, pack, inspect,
    tag, note, index, convert, diff, redact, doctor) and carrel:// file/search resources."""
    ctx.ensure_object(dict)
    serve(sys.stdin, sys.stdout, default_root=ctx.obj.get("root", "."))
