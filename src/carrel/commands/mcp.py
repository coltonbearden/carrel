"""carrel mcp — stdio MCP server (pure stdlib JSON-RPC 2.0).

Transport per the MCP stdio spec: newline-delimited JSON — ONE JSON-RPC
message per line on stdin/stdout, no Content-Length framing, no SDK.

Every tool (see TOOLS) is a thin shim over a command module's library entry
point (pack.pack_paths, search.search_index, inspect.inspect_path,
convert.convert_file, diff.diff_files, redact's text engine, doctor.build_report,
refs.scan_refs, fields.fields_for, mail.attachments_of/threads_of, DeskDB for tags, notes and meta
fields, index.index_paths).
Nothing here walks a tree or estimates tokens on its own. Two resource
templates expose file text and desk search as `carrel://` URIs.

Every tool failure is returned as `isError: true` carrying the same message the
CLI would print (CarrelError text, install hints included) — never a crash.

Every path the client names — tool arguments, a client-supplied `root`, and both
`carrel://` resource URIs — is confined to the directory the server was started
in (`Desk`, below), as is every destination a tool *derives* (`confined_dest`).
`--allow-outside-root` lifts it for the session.
"""

from __future__ import annotations

import contextlib
import inspect as pyinspect
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import unquote

import click

from carrel._product import PRODUCT
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.fsops import OutsideRootError, confined_dest, within
from carrel.core.output import CarrelError, CarrelInputError
from carrel.core.patterns import PATTERNS
from carrel.core.textextract import extract_text

#: Newest first. The methods this server exposes — `initialize`, `tools/list`,
#: `tools/call` and the two `resources/*` — are identical across all three
#: revisions. The one wire difference is JSON-RPC **batching**, which the older
#: two allow and 2025-06-18 removed: `_handle_batch` implements it, because
#: advertising a revision means speaking it. A version outside this tuple is
#: answered with the newest we support; the MCP spec has the server name a
#: version it actually speaks and lets the client decide.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
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
                "meta": _str_array(
                    "Only files whose fields satisfy every condition "
                    "(vendor=acme, total>1000, due<2026-11-01, paid?)."
                ),
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
                "builtin": _str_array(f"Builtin patterns: {', '.join(PATTERNS)}."),
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
    {
        "name": "carrel_meta",
        "description": "Typed key/value fields on desk files: set, get, ls or rm fields on a "
        "file, or find files by conditions (vendor=acme, total>1000, due<2026-11-01, paid?).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["set", "get", "ls", "rm", "find"]},
                "path": {"type": "string", "description": "File (set/get/ls/rm)."},
                "fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Fields to set, {key: value}; kinds are inferred (set).",
                },
                "key": {"type": "string", "description": "Field name (get)."},
                "keys": _str_array("Field names to remove (rm)."),
                "conditions": _str_array("Conditions every file must satisfy (find)."),
                "source": {
                    "type": "string",
                    "description": "Who writes the fields (set).",
                    "default": "agent",
                },
                "root": _ROOT_PROP,
            },
            "required": ["action"],
        },
    },
    {
        "name": "carrel_fields",
        "description": "Extract vendor, invoice number, PO, dates, subtotal/tax/total, currency, "
        "IBAN and account last-4 from a document (invoice, receipt, statement) with a confidence "
        "per field; optionally save them as desk meta fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory."},
                "profile": {
                    "type": "string",
                    "enum": ["auto", "invoice", "receipt", "statement"],
                    "default": "auto",
                },
                "date_order": {"type": "string", "enum": ["mdy", "dmy"], "default": "mdy"},
                "ocr": {
                    "type": "boolean",
                    "description": "OCR images and scanned PDFs.",
                    "default": False,
                },
                "save": {
                    "type": "boolean",
                    "description": "Write the fields into the desk under root (source: fields).",
                    "default": False,
                },
                "root": _ROOT_PROP,
            },
            "required": ["path"],
        },
    },
    {
        "name": "carrel_mail",
        "description": "Email files (eml/mbox): save a message's attachments into a directory, "
        "or group the messages of files/directories into threads.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["attachments", "threads"]},
                "path": {
                    "type": "string",
                    "description": "eml/mbox file (attachments) or file/directory (threads).",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Where attachments are written (attachments).",
                },
                "force": {
                    "type": "boolean",
                    "description": "Overwrite same-named attachments instead of suffixing.",
                    "default": False,
                },
                "root": _ROOT_PROP,
            },
            "required": ["action", "path"],
        },
    },
    {
        "name": "carrel_refs",
        "description": "Find reference numbers (invoice, PO, order, check, account, tracking, "
        "ticket, IBAN, routing, EIN, VAT, ISBN, GTIN, DOI, UPS, USPS) in a file or directory; "
        "optionally tag files with ref:<kind>:<value> or group files by shared value.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to scan."},
                "kinds": _str_array(
                    f"Only these kinds (default: reference + identifier kinds). Known: "
                    f"{', '.join(PATTERNS)}."
                ),
                "patterns": _str_array("Extra NAME=REGEX kinds; a (?P<v1>…) group is the value."),
                "tag": {
                    "type": "boolean",
                    "description": "Tag each file in the desk under root with ref:<kind>:<value>.",
                    "default": False,
                },
                "link": {
                    "type": "boolean",
                    "description": "Return {references: [{kind, value, files, count}]} instead.",
                    "default": False,
                },
                "all": {
                    "type": "boolean",
                    "description": "With link, include values seen in one file only.",
                    "default": False,
                },
                "ocr": {
                    "type": "boolean",
                    "description": "OCR images and scanned PDFs (needs tesseract / ocrmypdf).",
                    "default": False,
                },
                "root": _ROOT_PROP,
            },
            "required": ["path"],
        },
    },
]

_SCHEMA_BY_NAME = {t["name"]: t["inputSchema"] for t in TOOLS}


# ---------------------------------------------------------------------------
# argument helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Desk:
    """The server's launch root and whether paths are confined to it.

    `root` is `--root` if the user gave one, else the working directory the
    server was started in — already resolved. Every path a client names reaches
    the filesystem through `resolve`, so confinement cannot be forgotten at a
    call site: there is no other way in.
    """

    root: Path
    confined: bool = True

    @property
    def walk_boundary(self) -> Path | None:
        """The root a directory walk must not escape, or None when unconfined.

        `Desk.resolve` covers the paths a *client* names. A walk finds its own,
        and a symlinked file inside the tree resolves outside it — so every tool
        that walks passes this down: `carrel_pack`, `carrel_index`, `carrel_refs`,
        `carrel_fields` and `carrel_mail action=threads`. Adding a sixth means
        adding it here; `test_no_tool_reads_through_a_symlink_planted_in_the_desk`
        drives the whole registry so a miss fails rather than ships.
        """
        return self.root if self.confined else None

    def resolve(self, raw: str | Path, base: Path | None = None) -> Path:
        """Make `raw` absolute against `base` (default: the launch root), then confine it.

        Symlinks are resolved *before* the check, so a link inside the root that
        points outside it is refused rather than followed.
        """
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (base if base is not None else self.root) / path
        real = path.resolve()
        if not within(real, self.walk_boundary):
            # `raw`, not `real`: naming where a symlink points would let a client
            # enumerate link targets across the desk, which is the existence
            # oracle `_read_resource` refuses to become two screens below.
            raise OutsideRootError(
                f"{raw} is outside the server root {self.root} — "
                "carrel mcp only reads and writes under the directory it was "
                "started in; restart it with --allow-outside-root to lift this"
            )
        return real


def _root(args: dict[str, Any], desk: Desk) -> Path:
    """The desk root for one call: the client's `root` argument, confined."""
    return desk.resolve(args.get("root") or ".")


def _inside(rows: list[Any], desk: Desk, root: Path, key: str | None = None) -> list[Any]:
    """Drop stored rows whose file lies outside the boundary.

    The desk index is written by whoever ran `carrel index`, and the CLI follows
    symlinks by design (D-021) — so a desk indexed from the shell can hold rows
    pointing anywhere, and a confined server would serve their paths and their
    text. Confining the *walk* stops the server writing such rows; it cannot
    unwrite the ones already there, and `--prune` keeps them because the target
    still exists. Every tool that returns stored paths filters through here.

    Paths are stored root-relative, so they are joined to `root` before the test.
    """
    if not desk.confined:
        return rows

    def keep(row: Any) -> bool:
        raw = row if key is None else row[key]
        return within(root / str(raw), desk.walk_boundary)

    return [row for row in rows if keep(row)]


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


def _rel(path: Path, root: Path) -> str:
    """Root-relative POSIX path like `DeskDB.rel`, without opening a desk."""
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _check_required(name: str, args: dict[str, Any]) -> None:
    missing = [k for k in _SCHEMA_BY_NAME[name].get("required", []) if args.get(k) is None]
    if missing:
        raise CarrelInputError(f"missing required argument(s) for {name}: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


def _tool_search(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.search import search_index

    root = _root(args, desk)
    query = str(args["query"])
    types = set(_str_list(args, "types")) or None
    tags = _str_list(args, "tags") or None
    meta = _str_list(args, "meta") or None
    hits = _inside(
        search_index(
            root, query, limit=int(args.get("limit") or 20), types=types, tags=tags, meta=meta
        ),
        desk,
        root,
        "path",
    )
    return {"query": query, "root": str(root), "count": len(hits), "results": hits}


def _tool_pack(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.pack import pack_paths

    root = _root(args, desk)
    path = desk.resolve(args["path"], root)
    fmt = _choice(args, "format", _PACK_FORMATS, "json")
    tree_only = bool(args.get("tree_only") or False)
    max_bytes = args.get("max_bytes")
    kwargs: dict[str, Any] = {
        "fmt": fmt,
        "include": _str_list(args, "include"),
        "exclude": _str_list(args, "exclude"),
        "max_bytes": int(max_bytes) if max_bytes is not None else None,
        "tree_only": tree_only,
        # the desk root bounds the ancestor-.gitignore walk. Without it `pack_paths`
        # falls back to the packed path itself, so `_ancestor_ignores(t, t)` returns
        # nothing and the desk's own .gitignore is ignored — the #41 bug, reached
        # through MCP instead of the CLI (D-019).
        "desk_root": root,
        # the walk finds its own paths; Desk.resolve only covers the ones the
        # client named, and a symlinked file inside the tree resolves outside it
        "confine_to": desk.walk_boundary,
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
    if result.empty_reason is not None:
        # The whole point of the CLI's exit 5 is that an agent must not read a
        # valid-looking empty document as a successful pack. The tool has no
        # exit code, so it carries the same sentence — FTS5 AND-s the terms of
        # a `query`, so a natural-language question usually matches nothing.
        payload["empty_reason"] = result.empty_reason
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


def _tool_inspect(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.inspect import inspect_path

    path = desk.resolve(args["path"], _root(args, desk))
    return inspect_path(path, deep=bool(args.get("deep") or False))


def _tool_tag(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    action = _choice(args, "action", ("add", "rm", "ls", "find"), "")
    root = _root(args, desk)
    tags = _str_list(args, "tags")

    if action == "find":
        if not tags:
            raise CarrelInputError("carrel_tag find requires a non-empty `tags` array")
        if not DeskDB.exists(root):
            return {"root": str(root), "tags": tags, "paths": []}
        with DeskDB(root) as db:
            found = _inside(db.find_by_tags(tags), desk, root)
            return {"root": str(root), "tags": tags, "paths": found}

    if not args.get("path"):
        raise CarrelInputError(f"carrel_tag {action} requires `path`")
    path = desk.resolve(args["path"], root)
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


def _tool_note(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    action = _choice(args, "action", ("add", "ls"), "")
    root = _root(args, desk)
    path = desk.resolve(args["path"], root)

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


def _tool_index(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.index import index_paths

    root = _root(args, desk)
    paths = [desk.resolve(p, root) for p in _str_list(args, "paths")] or None
    result = index_paths(
        root,
        paths,
        update=bool(args.get("update") or False),
        prune=bool(args.get("prune") or False),
        ocr=bool(args.get("ocr") or False),
        confine_to=desk.walk_boundary,
    )
    return {"root": str(root), **result}


def _tool_convert(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.convert import convert_file, normalize_target

    root = _root(args, desk)
    src = desk.resolve(args["path"], root)
    to = str(args["to"])
    dest_type = normalize_target(to)
    if dest_type is None:
        known = sorted(t.value for t in FileType if t is not FileType.UNKNOWN)
        raise CarrelInputError(f"unknown target type '{to}' (choose from: {', '.join(known)})")
    out_dir = desk.resolve(args["out_dir"], root) if args.get("out_dir") else src.parent
    # the client names `path` and `out_dir`; `dest` is ours, and a symlink sitting
    # at it writes through to wherever it points (a dangling one creates it)
    dest = confined_dest(
        (out_dir / src.name).with_suffix(f".{dest_type.value}"), desk.walk_boundary
    )
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


def _tool_diff(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.diff import diff_files

    root = _root(args, desk)
    mode = _choice(args, "mode", _DIFF_MODES, "auto")
    result = diff_files(desk.resolve(args["a"], root), desk.resolve(args["b"], root), mode=mode)
    return {**result, "differ": not result["identical"]}


def _tool_redact(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.redact import _check_still_parses, _compile_rules, _redact_text

    root = _root(args, desk)
    src = desk.resolve(args["path"], root)
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


def _tool_doctor(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
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


def _tool_meta(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.meta import meta_map

    action = _choice(args, "action", ("set", "get", "ls", "rm", "find"), "")
    root = _root(args, desk)

    if action == "find":
        from carrel.core.db import parse_meta_condition

        conditions = _str_list(args, "conditions")
        if not conditions:
            raise CarrelInputError("carrel_meta find requires a non-empty `conditions` array")
        for c in conditions:  # syntax is checked even without a desk, so typos fail loudly
            parse_meta_condition(c)
        if not DeskDB.exists(root):
            return {"root": str(root), "conditions": conditions, "files": []}
        with DeskDB(root) as db:
            paths = _inside(db.find_by_meta(conditions), desk, root)
            by_path = db.meta_for_paths(paths)
            files = [{"path": p, "meta": by_path[p]} for p in paths]
        return {"root": str(root), "conditions": conditions, "files": files}

    if action == "ls" and not args.get("path"):
        if not DeskDB.exists(root):
            return {"root": str(root), "keys": {}}
        with DeskDB(root) as db:
            return {"root": str(root), "keys": db.meta_keys()}

    if not args.get("path"):
        raise CarrelInputError(f"carrel_meta {action} requires `path`")
    path = desk.resolve(args["path"], root)  # Desk.resolve already resolves symlinks
    key = str(args.get("key") or "")
    keys = _str_list(args, "keys")
    if action == "get" and not key:
        raise CarrelInputError("carrel_meta get requires `key`")
    if action == "rm" and not keys:
        raise CarrelInputError("carrel_meta rm requires a non-empty `keys` array")

    if action == "set":
        fields = args.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise CarrelInputError("carrel_meta set requires a non-empty `fields` object")
        for k, v in fields.items():
            if v is None:
                raise CarrelInputError(f"field {k!r} is null — use action `rm` to clear a field")
            if not isinstance(v, (str, int, float)):  # bool is an int: JSON true → "true"
                raise CarrelInputError(
                    f"field {k!r} must be a string, number or boolean, got {type(v).__name__}"
                )
        if not path.is_file():
            raise CarrelInputError(f"no such file: {path}")
        source = str(args.get("source") or "agent")
        with DeskDB(root) as db:
            for k, v in fields.items():
                db.set_meta(
                    path, str(k), str(v).lower() if isinstance(v, bool) else str(v), source=source
                )
            return {"path": db.rel(path), "meta": meta_map(db, path)}

    # get / ls / rm never create a desk db as a side effect (same as the CLI);
    # the payload shape does not depend on whether a desk exists
    rel = _rel(path, root)
    if not DeskDB.exists(root):
        if action == "get":
            return {"path": rel, "key": key, "value": None, "kind": None, "source": None}
        if action == "rm":
            return {"path": rel, "removed": 0, "meta": {}}
        return {"path": rel, "meta": {}, "fields": []}
    with DeskDB(root) as db:
        if action == "get":
            row = db.get_meta(path, key)
            return {
                "path": db.rel(path),
                "key": key,
                "value": row["value"] if row else None,
                "kind": row["kind"] if row else None,
                "source": row["source"] if row else None,
            }
        if action == "rm":
            removed = db.rm_meta(path, keys)
            return {"path": db.rel(path), "removed": removed, "meta": meta_map(db, path)}
        rows = [{**r, "updated": _iso(r["updated"])} for r in db.meta_of(path)]
        return {"path": db.rel(path), "meta": meta_map(db, path), "fields": rows}


def _tool_refs(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.refs import link_refs, scan_refs

    root = _root(args, desk)
    path = desk.resolve(args["path"], root)
    kinds = _str_list(args, "kinds") or None
    records = scan_refs(
        [path],
        kinds=kinds,
        extra=_str_list(args, "patterns"),
        ocr=bool(args.get("ocr") or False),
        tag_root=root if args.get("tag") else None,
        # `root` bounds the ancestor-.gitignore walk (the CLI passes it too). Without
        # it the seed climbed to the git worktree root, so a `*` rule *above* a
        # confined desk silently emptied the result — the v0.3.1 incident, reached
        # through MCP — and the confined server read a file above its own boundary.
        root=root,
        confine_to=desk.walk_boundary,
    )
    if args.get("link"):
        groups = link_refs(records, all_=bool(args.get("all") or False))
        return {"root": str(root), "path": str(path), "references": groups}
    return {"root": str(root), "path": str(path), "files": records}


def _tool_fields(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.fields import fields_for

    root = _root(args, desk)
    path = desk.resolve(args["path"], root)
    records = fields_for(
        [path],
        profile=_choice(args, "profile", ("auto", "invoice", "receipt", "statement"), "auto"),
        date_order=_choice(args, "date_order", ("mdy", "dmy"), "mdy"),
        ocr=bool(args.get("ocr") or False),
        save_root=root if args.get("save") else None,
        # not `save_root`: whether the ancestor-.gitignore walk is bounded must not
        # depend on the unrelated `save` flag (see carrel_refs above)
        walk_root=root,
        confine_to=desk.walk_boundary,
    )
    return {"root": str(root), "path": str(path), "files": records}


def _tool_mail(args: dict[str, Any], desk: Desk) -> dict[str, Any]:
    from carrel.commands.mail import attachments_of, threads_of

    action = _choice(args, "action", ("attachments", "threads"), "")
    root = _root(args, desk)
    path = desk.resolve(args["path"], root)
    if action == "threads":
        threads = threads_of([path], root=root, confine_to=desk.walk_boundary)
        return {"root": str(root), "path": str(path), "threads": threads}
    if not args.get("out_dir"):
        raise CarrelInputError("carrel_mail attachments requires `out_dir`")
    out_dir = desk.resolve(args["out_dir"], root)
    records = attachments_of(
        [path],
        out_dir,
        force=bool(args.get("force") or False),
        confine_to=desk.walk_boundary,
    )
    return {"root": str(root), "path": str(path), "out_dir": str(out_dir), "messages": records}


_TOOL_IMPLS: dict[str, Callable[[dict[str, Any], Desk], dict[str, Any]]] = {
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
    "carrel_meta": _tool_meta,
    "carrel_fields": _tool_fields,
    "carrel_mail": _tool_mail,
    "carrel_refs": _tool_refs,
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


def _read_resource(uri: str, desk: Desk) -> dict[str, Any]:
    if uri.startswith(_URI_FILE):
        rel = unquote(uri[len(_URI_FILE) :])
        # A URI outside the root is "not found", not a distinct refusal: the
        # resource protocol has one failure shape, and naming the boundary here
        # would turn `resources/read` into an existence oracle for the disk.
        try:
            path = desk.resolve(rel) if rel else None
        except OutsideRootError as e:
            raise _ResourceNotFoundError(uri) from e
        if path is None or not path.is_file():
            raise _ResourceNotFoundError(uri)
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": extract_text(path)}]}
    if uri.startswith(_URI_SEARCH):
        query = unquote(uri[len(_URI_SEARCH) :])
        if not query:
            raise _ResourceNotFoundError(uri)
        payload = _tool_search({"query": query}, desk)
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


def _call_tool(params: dict[str, Any], desk: Desk) -> dict[str, Any]:
    name = str(params.get("name") or "")
    impl = _TOOL_IMPLS[name]
    arguments = params.get("arguments") or {}
    try:
        if not isinstance(arguments, dict):
            raise CarrelInputError("`arguments` must be a JSON object")
        _check_required(name, arguments)
        return _tool_result(impl(arguments, desk))
    except Exception as e:  # noqa: BLE001 — tool failures are data, not crashes
        return _tool_error(e)


def _negotiate(requested: Any) -> str:
    """Echo a protocol version we speak; otherwise answer with the newest one."""
    return str(requested) if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION


def _handle_batch(batch: list[Any], desk: Desk) -> list[dict[str, Any]] | dict[str, Any] | None:
    """One JSON-RPC batch → an array of the replies its requests earned.

    Legal in the 2024-11-05 and 2025-03-26 revisions this server advertises;
    removed in 2025-06-18, which is why it is accepted rather than required. A
    batch of nothing but notifications earns no reply at all, per JSON-RPC 2.0 —
    and an empty array is itself an invalid request.
    """
    if not batch:
        return _error(None, -32600, "invalid request: empty batch")
    replies = [reply for reply in (_handle(m, desk) for m in batch) if reply is not None]
    return replies or None


def _handle(msg: Any, desk: Desk) -> dict[str, Any] | None:
    """Handle one decoded message; None means no response (notification)."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request: expected a JSON object")
    method = msg.get("method")
    mid = msg.get("id")
    # The raw value, not `... or {}`: that coerced every *falsy* non-object —
    # `[]`, `0`, `""`, `false` — to an empty dict, so the type check below saw a
    # dict and a malformed request was answered as "unknown tool" or, worse, with
    # the resource-not-found shape reserved for real lookups.
    params = msg.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        # JSON-RPC 2.0 allows an array here. Every handler below reads `params`
        # with .get(), so an array took the whole server down mid-session with
        # an AttributeError — the one thing this module promises never to do.
        return (
            None
            if "id" not in msg
            else _error(mid, -32602, "invalid params: expected a JSON object")
        )
    is_notification = "id" not in msg

    if method == "initialize":
        result: Any = {
            # A version we speak is echoed; anything else is answered with the
            # newest we support. Echoing an unknown string would claim a
            # revision this server has never been run against.
            "protocolVersion": _negotiate(params.get("protocolVersion")),
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
        result = _call_tool(params, desk)
    elif method == "resources/templates/list":
        result = {"resourceTemplates": RESOURCE_TEMPLATES}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "resources/read":
        uri = str(params.get("uri") or "")
        try:
            result = _read_resource(uri, desk)
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


def serve(
    stdin: TextIO,
    stdout: TextIO,
    default_root: Path | str = ".",
    *,
    allow_outside_root: bool = False,
) -> None:
    """Serve newline-delimited JSON-RPC until EOF (clean exit).

    `default_root` is the desk root and, unless `allow_outside_root`, the
    boundary every client-named path is confined to.
    """
    desk = Desk(Path(default_root).resolve(), confined=not allow_outside_root)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            response: list[dict[str, Any]] | dict[str, Any] | None = _error(
                None, -32700, f"parse error: {e}"
            )
        else:
            response = _handle_batch(msg, desk) if isinstance(msg, list) else _handle(msg, desk)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            stdout.flush()


_TOOL_SUMMARY = ", ".join(t["name"].removeprefix("carrel_") for t in TOOLS)


@click.command(
    name="mcp",
    help=f"Serve the desk as an MCP server on stdio: {len(TOOLS)} tools ({_TOOL_SUMMARY}) "
    "and carrel:// file/search resources. Every path a client names is confined "
    "to the desk root (--root, default the current directory).",
)
@click.option(
    "--allow-outside-root",
    is_flag=True,
    help="Let clients read and write outside the desk root. Off by default: "
    "the server refuses any path that resolves outside it.",
)
@click.pass_context
def cmd(ctx: click.Context, allow_outside_root: bool) -> None:
    ctx.ensure_object(dict)
    # MCP frames are UTF-8 by specification, but Python wires stdio to the
    # locale encoding — cp1252 on a stock Windows box, with errors="strict".
    # A document containing CJK, an em dash or an emoji would then raise
    # mid-session and take the server down for the agent talking to it.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # not a real TextIOWrapper under some hosts
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8")
    serve(
        sys.stdin,
        sys.stdout,
        default_root=ctx.obj.get("root", "."),
        allow_outside_root=allow_outside_root,
    )
