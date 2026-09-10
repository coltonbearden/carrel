"""DeskDB — the .carrel/carrel.db SQLite store (index, tags, notes).

Schema versioning
-----------------
`PRAGMA user_version` records the schema version. `MIGRATIONS` is the ordered
list of `(version, sql)` steps; opening a desk applies every step above the
stored version inside one transaction and then stamps the new version.
Version 1 is the v0.1.2 layout exactly, so a pre-v0.2.0 database (user_version
0 with the tables already present) is recognised and stamped 1 untouched.
Version 2 (v0.4.0) adds the `meta` table: typed key/value fields per file
(`carrel meta`, `search --meta`; automation that writes fields names itself
in `source`).

**Adding a migration is the only sanctioned way to change the schema.** Never
edit `_SCHEMA` or an existing migration in place: append a new
`(N + 1, "ALTER TABLE …")` entry to `MIGRATIONS` and bump nothing else — the
version is derived from the list.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from carrel.core.output import CarrelInputError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    hash TEXT,
    type TEXT NOT NULL,
    indexed_at REAL
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(content, path UNINDEXED);
CREATE TABLE IF NOT EXISTS tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    UNIQUE(file_id, tag)
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    body TEXT NOT NULL
);
"""

# v2: typed key/value metadata per file. `kind` is str|num|date|bool (value is
# stored in canonical text form: Decimal digits, ISO date, true/false); `source`
# records who wrote it (user, fields, refs, intake, …) so automation can be told
# apart from hand-entered facts.
_META_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'str',
    source TEXT NOT NULL DEFAULT 'user',
    updated REAL NOT NULL,
    UNIQUE(file_id, key)
);
CREATE INDEX IF NOT EXISTS meta_key_value ON meta(key, value);
"""

# (version, sql) — applied in order; version 1 == the v0.1.2 layout (`_SCHEMA`).
MIGRATIONS: list[tuple[int, str]] = [
    (1, _SCHEMA),
    (2, _META_SQL),
]

META_KINDS: tuple[str, ...] = ("str", "num", "date", "bool")
META_OPS: tuple[str, ...] = ("!=", ">=", "<=", "=", ">", "<", "~", "?")
_META_KEY_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")
_NUM_RE = re.compile(r"[-+]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\Z")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_COND_RE = re.compile(r"([A-Za-z0-9_.\-]+)\s*(!=|>=|<=|=|>|<|~|\?)\s*(?![=<>!~?])(.*)\Z", re.DOTALL)
# Literal SQL fragments per operator: the user's operator string never reaches the
# query text, only the fragment it selects does.
_NUM_CMP: dict[str, str] = {
    ">": "(m.kind='num' AND CAST(m.value AS REAL) > ?)",
    ">=": "(m.kind='num' AND CAST(m.value AS REAL) >= ?)",
    "<": "(m.kind='num' AND CAST(m.value AS REAL) < ?)",
    "<=": "(m.kind='num' AND CAST(m.value AS REAL) <= ?)",
}
_TEXT_CMP: dict[str, str] = {
    ">": "m.value > ?",
    ">=": "m.value >= ?",
    "<": "m.value < ?",
    "<=": "m.value <= ?",
}
_NON_NUM_TEXT_CMP: dict[str, str] = {
    ">": "(m.kind<>'num' AND m.value > ?)",
    ">=": "(m.kind<>'num' AND m.value >= ?)",
    "<": "(m.kind<>'num' AND m.value < ?)",
    "<=": "(m.kind<>'num' AND m.value <= ?)",
}
_META_EXISTS = "EXISTS (SELECT 1 FROM meta m WHERE m.file_id=f.id AND m.key=? {cmp})"
_LEADING_ZERO_RE = re.compile(r"[-+]?0\d")
_BOOL_WORDS: dict[str, str] = {
    "true": "true", "yes": "true", "on": "true",
    "false": "false", "no": "false", "off": "false",
}  # fmt: skip

SCHEMA_VERSION: int = MIGRATIONS[-1][0]

# tables a version-0 (pre-v0.2.0) database must already have to be stamped 1 as-is
_V1_TABLES = frozenset({"files", "docs", "tags", "notes"})


def file_hash(path: Path, algo: str = "blake2b") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DeskDB:
    """Context-managed handle on the desk database under `root`."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).resolve()
        self.dir = self.root / ".carrel"
        self.path = self.dir / "carrel.db"
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> DeskDB:
        if not self.root.is_dir():
            raise CarrelInputError(f"desk root is not a directory: {self.root}")
        self.dir.mkdir(exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        try:
            self._migrate()
        except Exception:
            self._conn.close()
            self._conn = None
            raise
        self._conn.execute("PRAGMA foreign_keys=ON")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._conn is None:
            return
        self._conn.commit()
        self._conn.close()
        self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DeskDB must be used as a context manager")
        return self._conn

    @staticmethod
    def exists(root: Path | str = ".") -> bool:
        return (Path(root).resolve() / ".carrel" / "carrel.db").is_file()

    def rel(self, path: Path | str) -> str:
        """Desk-relative POSIX path — the key every table and export uses.

        Always forward slashes: `files.path` is read straight back out by
        `export_catalog`, so a native separator here would make a catalog
        written on one platform unimportable on another (D-009 exists to move
        tags and notes between machines).
        """
        p = Path(path).resolve()
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.as_posix()

    # -- schema / migrations -------------------------------------------------
    def _migrate(self) -> None:
        """Bring the database to SCHEMA_VERSION (one transaction), or refuse a newer one."""
        conn = self.conn
        current = self.schema_version()
        if current == 0 and self._has_v1_layout():
            # pre-v0.2.0 desk: tables exist, version never stamped → it IS version 1
            conn.execute("PRAGMA user_version = 1")
            current = 1
        if current > SCHEMA_VERSION:
            raise CarrelInputError(
                f"{self.path} is desk schema version {current}, but this build supports "
                f"up to {SCHEMA_VERSION} — upgrade carrel to open it"
            )
        pending = [(v, sql) for v, sql in MIGRATIONS if v > current]
        if not pending:
            return
        target = pending[-1][0]
        script = "BEGIN;\n" + "\n".join(sql for _, sql in pending)
        script += f"\nPRAGMA user_version = {int(target)};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def _has_v1_layout(self) -> bool:
        names = {
            r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return names >= _V1_TABLES

    def schema_version(self) -> int:
        """The stored `PRAGMA user_version` (0 = never stamped)."""
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    # -- files -------------------------------------------------------------
    def upsert_file(self, path: Path, *, ftype: str, with_hash: bool = False) -> int:
        stat = path.stat()
        digest = file_hash(path) if with_hash else None
        cur = self.conn.execute(
            """INSERT INTO files (path, size, mtime, hash, type) VALUES (?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE
               SET size=excluded.size, mtime=excluded.mtime, type=excluded.type,
                   hash=COALESCE(excluded.hash, files.hash)
               RETURNING id""",
            (self.rel(path), stat.st_size, stat.st_mtime, digest, ftype),
        )
        return cur.fetchone()[0]

    def get_file(self, path: Path | str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM files WHERE path=?", (self.rel(path),)).fetchone()

    @staticmethod
    def _row_fresh(row: sqlite3.Row, path: Path) -> bool:
        if row["indexed_at"] is None:
            return False
        stat = path.stat()
        return row["size"] == stat.st_size and abs(row["mtime"] - stat.st_mtime) < 1e-6

    def is_fresh(self, path: Path) -> bool:
        row = self.get_file(path)
        if row is None:
            return False
        return self._row_fresh(row, path)

    # -- fts ---------------------------------------------------------------
    def set_content(self, file_id: int, path: Path | str, content: str) -> None:
        self.conn.execute("DELETE FROM docs WHERE rowid=?", (file_id,))
        self.conn.execute(
            "INSERT INTO docs (rowid, content, path) VALUES (?,?,?)",
            (file_id, content, self.rel(path)),
        )
        self.conn.execute("UPDATE files SET indexed_at=? WHERE id=?", (time.time(), file_id))

    def fts_search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT f.path, f.type, bm25(docs) AS score,
                      snippet(docs, 0, '[', ']', ' … ', 12) AS snip
               FROM docs JOIN files f ON f.id = docs.rowid
               WHERE docs MATCH ? ORDER BY score LIMIT ?""",
            (query, limit),
        ).fetchall()

    def prune(self) -> int:
        gone = [
            row["id"]
            for row in self.conn.execute("SELECT id, path FROM files")
            if not (self.root / row["path"]).exists()
        ]
        for fid in gone:
            self.conn.execute("DELETE FROM docs WHERE rowid=?", (fid,))
            self.conn.execute("DELETE FROM files WHERE id=?", (fid,))
        return len(gone)

    # -- status --------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        """Row counts: files, docs (FTS rows), tags, notes, meta."""
        return {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 — fixed table names
            for table in ("files", "docs", "tags", "notes", "meta")
        }

    def indexed_paths(self) -> set[str]:
        """Root-relative paths that have searchable text (indexed_at set)."""
        return {
            r["path"]
            for r in self.conn.execute("SELECT path FROM files WHERE indexed_at IS NOT NULL")
        }

    def stale(self) -> dict[str, list[str]]:
        """Indexed files that drifted: `changed` (size/mtime differ) and `missing` (gone).

        Files registered only via tag/note (never indexed) are not "changed" — the
        caller reports them as unindexed from a walk.
        """
        changed: list[str] = []
        missing: list[str] = []
        for row in self.conn.execute("SELECT * FROM files ORDER BY path"):
            path = self.root / row["path"]
            if not path.exists():
                missing.append(row["path"])
            elif row["indexed_at"] is not None and not self._row_fresh(row, path):
                changed.append(row["path"])
        return {"changed": changed, "missing": missing}

    # -- tags / notes --------------------------------------------------------
    def ensure_file(self, path: Path) -> int:
        from carrel.core.filetypes import detect

        row = self.get_file(path)
        if row:
            return row["id"]
        return self.upsert_file(path, ftype=detect(path).value)

    def add_tags(self, path: Path, tags: list[str]) -> None:
        fid = self.ensure_file(path)
        for tag in tags:
            self.conn.execute(
                "INSERT OR IGNORE INTO tags (file_id, tag) VALUES (?,?)",
                (fid, tag.strip().lower()),
            )

    def rm_tags(self, path: Path, tags: list[str]) -> None:
        row = self.get_file(path)
        if not row:
            return
        for tag in tags:
            self.conn.execute(
                "DELETE FROM tags WHERE file_id=? AND tag=?", (row["id"], tag.strip().lower())
            )

    def tags_of(self, path: Path) -> list[str]:
        row = self.get_file(path)
        if not row:
            return []
        return [
            r["tag"]
            for r in self.conn.execute(
                "SELECT tag FROM tags WHERE file_id=? ORDER BY tag", (row["id"],)
            )
        ]

    def find_by_tags(self, tags: list[str]) -> list[str]:
        tags = [t.strip().lower() for t in tags]
        marks = ",".join("?" for _ in tags)
        return [
            r["path"]
            for r in self.conn.execute(
                f"""SELECT f.path FROM files f JOIN tags t ON t.file_id=f.id
                WHERE t.tag IN ({marks})
                GROUP BY f.id HAVING COUNT(DISTINCT t.tag)=? ORDER BY f.path""",  # noqa: S608 — only `?` marks are interpolated
                (*tags, len(tags)),
            )
        ]

    def add_note(self, path: Path, body: str) -> int:
        fid = self.ensure_file(path)
        cur = self.conn.execute(
            "INSERT INTO notes (file_id, created, body) VALUES (?,?,?) RETURNING id",
            (fid, time.time(), body),
        )
        return cur.fetchone()[0]

    def notes_of(self, path: Path) -> list[sqlite3.Row]:
        row = self.get_file(path)
        if not row:
            return []
        return self.conn.execute(
            "SELECT created, body FROM notes WHERE file_id=? ORDER BY created DESC, id DESC",
            (row["id"],),
        ).fetchall()

    # -- meta (typed key/value fields, schema v2) ---------------------------------
    def set_meta(
        self,
        path: Path,
        key: str,
        value: str,
        *,
        kind: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        """Set one field on a file (registering the file if needed); returns the stored row.

        `kind` is inferred from the value when None (see `coerce_meta`); a
        value that does not fit an explicit kind raises CarrelInputError.
        """
        fid = self.ensure_file(path)
        k = normalize_meta_key(key)
        kind_, canonical = coerce_meta(value, kind)
        self.conn.execute(
            """INSERT INTO meta (file_id, key, value, kind, source, updated) VALUES (?,?,?,?,?,?)
               ON CONFLICT(file_id, key) DO UPDATE
               SET value=excluded.value, kind=excluded.kind, source=excluded.source,
                   updated=excluded.updated""",
            (fid, k, canonical, kind_, source, time.time()),
        )
        return {"key": k, "value": canonical, "kind": kind_, "source": source}

    def meta_of(self, path: Path | str) -> list[dict[str, Any]]:
        """Every field on a file, sorted by key: [{key, value, kind, source, updated}]."""
        row = self.get_file(path)
        if not row:
            return []
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT key, value, kind, source, updated FROM meta WHERE file_id=? ORDER BY key",
                (row["id"],),
            )
        ]

    def get_meta(self, path: Path | str, key: str) -> dict[str, Any] | None:
        row = self.get_file(path)
        if not row:
            return None
        hit = self.conn.execute(
            "SELECT key, value, kind, source, updated FROM meta WHERE file_id=? AND key=?",
            (row["id"], normalize_meta_key(key)),
        ).fetchone()
        return dict(hit) if hit else None

    def rm_meta(self, path: Path | str, keys: list[str]) -> int:
        """Delete the named fields; returns how many rows went (unknown keys are a no-op)."""
        row = self.get_file(path)
        if not row:
            return 0
        removed = 0
        for key in keys:
            cur = self.conn.execute(
                "DELETE FROM meta WHERE file_id=? AND key=?", (row["id"], normalize_meta_key(key))
            )
            removed += cur.rowcount
        return removed

    def meta_keys(self) -> dict[str, int]:
        """Every key in the desk with the number of files carrying it."""
        return {
            r["key"]: int(r["n"])
            for r in self.conn.execute(
                "SELECT key, COUNT(*) AS n FROM meta GROUP BY key ORDER BY key"
            )
        }

    def find_by_meta(self, conditions: list[str]) -> list[str]:
        """Root-relative paths of files satisfying every condition (AND).

        A condition is `key OP value` with OP one of = != > >= < <= ~ (contains,
        case-insensitive) or the bare `key?` (the field exists). Numeric values
        compare numerically against `num` fields; everything else compares as
        text, which is chronological for ISO dates.
        """
        parsed = [parse_meta_condition(c) for c in conditions]
        if not parsed:
            raise CarrelInputError("meta find needs at least one condition (e.g. vendor=acme)")
        clauses: list[str] = []
        params: list[Any] = []
        for key, op, value in parsed:
            cmp, cmp_params = _meta_comparison(op, value)
            clauses.append(_META_EXISTS.format(cmp=cmp))
            params.extend([key, *cmp_params])
        sql = "SELECT f.path FROM files f WHERE " + " AND ".join(clauses) + " ORDER BY f.path"  # noqa: S608 — fragments are fixed templates; every user value is a `?` parameter
        return [r["path"] for r in self.conn.execute(sql, params)]

    def meta_for_paths(self, paths: list[str]) -> dict[str, dict[str, str]]:
        """{path: {key: value}} for the given root-relative paths, in one query per 500 paths."""
        out: dict[str, dict[str, str]] = {p: {} for p in paths}
        for start in range(0, len(paths), 500):
            chunk = paths[start : start + 500]
            marks = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"""SELECT f.path AS path, m.key AS key, m.value AS value FROM meta m
                    JOIN files f ON f.id = m.file_id WHERE f.path IN ({marks})
                    ORDER BY f.path, m.key""",  # noqa: S608 — only `?` marks are interpolated
                chunk,
            )
            for r in rows:
                out[r["path"]][r["key"]] = r["value"]
        return out

    def meta_table(self, keys: list[str] | None = None) -> tuple[list[str], list[dict[str, str]]]:
        """(columns, rows) for every file carrying at least one field, sorted by path.

        Columns are `path` followed by the requested keys (or every key, sorted);
        a missing field is the empty string so the rows are rectangular.
        """
        wanted = [normalize_meta_key(k) for k in keys] if keys else sorted(self.meta_keys())
        rows: list[dict[str, str]] = []
        for f in self.conn.execute(
            "SELECT id, path FROM files f WHERE EXISTS (SELECT 1 FROM meta m WHERE m.file_id=f.id)"
            " ORDER BY path"
        ):
            values = {
                r["key"]: r["value"]
                for r in self.conn.execute(
                    "SELECT key, value FROM meta WHERE file_id=?", (f["id"],)
                )
            }
            rows.append({"path": f["path"], **{k: values.get(k, "") for k in wanted}})
        return ["path", *wanted], rows

    # -- catalog export / import ---------------------------------------------
    def export_catalog(self) -> dict[str, Any]:
        """Tags, notes and meta for every file that has at least one, sorted by path.

        Deterministic: same desk → byte-identical JSON. Returns
        `{"schema": SCHEMA_VERSION, "root": <abs>, "files": [{path, tags, notes, meta}]}`;
        the CLI layer adds product/version/exported. `meta` rows omit `updated`
        so two exports of the same facts are identical.
        """
        rows = self.conn.execute(
            """SELECT id, path FROM files f
               WHERE EXISTS (SELECT 1 FROM tags t WHERE t.file_id=f.id)
                  OR EXISTS (SELECT 1 FROM notes n WHERE n.file_id=f.id)
                  OR EXISTS (SELECT 1 FROM meta m WHERE m.file_id=f.id)
               ORDER BY path"""
        ).fetchall()
        files: list[dict[str, Any]] = []
        for row in rows:
            tags = [
                r["tag"]
                for r in self.conn.execute(
                    "SELECT tag FROM tags WHERE file_id=? ORDER BY tag", (row["id"],)
                )
            ]
            notes = [
                {"created": r["created"], "body": r["body"]}
                for r in self.conn.execute(
                    "SELECT created, body FROM notes WHERE file_id=? ORDER BY created, body",
                    (row["id"],),
                )
            ]
            meta = [
                {"key": r["key"], "value": r["value"], "kind": r["kind"], "source": r["source"]}
                for r in self.conn.execute(
                    "SELECT key, value, kind, source FROM meta WHERE file_id=? ORDER BY key",
                    (row["id"],),
                )
            ]
            files.append({"path": row["path"], "tags": tags, "notes": notes, "meta": meta})
        return {"schema": SCHEMA_VERSION, "root": str(self.root), "files": files}

    def import_catalog(self, data: dict[str, Any], *, replace: bool = False) -> dict[str, int]:
        """Merge a catalog document (see `export_catalog`) into this desk.

        Tags are `INSERT OR IGNORE`; notes are deduplicated on
        (file_id, created, body); meta fields are set to the document's value
        (counted under `meta_set` only when the stored value actually changed),
        so importing twice changes nothing. With `replace`, every existing tag,
        note and field is deleted first (counted under `tags_removed` /
        `notes_removed` / `meta_removed`). Entries whose file is not on disk under
        the root are skipped (`skipped_missing`), never created.
        Raises CarrelInputError for a malformed document or a newer `schema`.
        """
        files = _validate_catalog(data)
        result = {
            "tags_added": 0,
            "notes_added": 0,
            "meta_set": 0,
            "files_touched": 0,
            "skipped_missing": 0,
            "tags_removed": 0,
            "notes_removed": 0,
            "meta_removed": 0,
            "skipped_outside": 0,
        }
        if replace:
            for table, key in (
                ("tags", "tags_removed"),
                ("notes", "notes_removed"),
                ("meta", "meta_removed"),
            ):
                result[key] = int(
                    self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 — fixed table names
                )
                self.conn.execute(f"DELETE FROM {table}")  # noqa: S608
        for entry in files:
            path = (self.root / entry["path"]).resolve()
            if not path.is_relative_to(self.root):
                result["skipped_outside"] += 1
                continue
            if not path.is_file():
                result["skipped_missing"] += 1
                continue
            fid = self.ensure_file(path)
            touched = False
            for tag in entry["tags"]:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO tags (file_id, tag) VALUES (?,?)",
                    (fid, tag.strip().lower()),
                )
                if cur.rowcount:
                    result["tags_added"] += 1
                    touched = True
            for note in entry["notes"]:
                dup = self.conn.execute(
                    "SELECT 1 FROM notes WHERE file_id=? AND created=? AND body=?",
                    (fid, note["created"], note["body"]),
                ).fetchone()
                if dup is None:
                    self.conn.execute(
                        "INSERT INTO notes (file_id, created, body) VALUES (?,?,?)",
                        (fid, note["created"], note["body"]),
                    )
                    result["notes_added"] += 1
                    touched = True
            for field in entry["meta"]:
                current = self.conn.execute(
                    "SELECT value, kind, source FROM meta WHERE file_id=? AND key=?",
                    (fid, field["key"]),
                ).fetchone()
                if current and tuple(current) == (field["value"], field["kind"], field["source"]):
                    continue
                self.conn.execute(
                    """INSERT INTO meta (file_id, key, value, kind, source, updated)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(file_id, key) DO UPDATE
                       SET value=excluded.value, kind=excluded.kind, source=excluded.source,
                           updated=excluded.updated""",
                    (
                        fid,
                        field["key"],
                        field["value"],
                        field["kind"],
                        field["source"],
                        time.time(),
                    ),
                )
                result["meta_set"] += 1
                touched = True
            if touched:
                result["files_touched"] += 1
        return result


def _validate_catalog(data: Any) -> list[dict[str, Any]]:
    """Shape-check a catalog document; return its `files` list (normalised)."""
    if not isinstance(data, dict):
        raise CarrelInputError("invalid catalog: top level must be a JSON object")
    schema = data.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        raise CarrelInputError("invalid catalog: missing or non-integer 'schema'")
    if schema > SCHEMA_VERSION:
        raise CarrelInputError(
            f"catalog schema {schema} is newer than this build supports ({SCHEMA_VERSION}) — "
            "upgrade carrel to import it"
        )
    files = data.get("files")
    if not isinstance(files, list):
        raise CarrelInputError("invalid catalog: 'files' must be a list")
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(files):
        where = f"files[{i}]"
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not entry["path"]
        ):
            raise CarrelInputError(f"invalid catalog: {where} needs a non-empty string 'path'")
        tags = entry.get("tags", [])
        notes = entry.get("notes", [])
        meta = entry.get("meta", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
            raise CarrelInputError(f"invalid catalog: {where}.tags must be a list of strings")
        if not isinstance(notes, list):
            raise CarrelInputError(f"invalid catalog: {where}.notes must be a list")
        if not isinstance(meta, list):
            raise CarrelInputError(f"invalid catalog: {where}.meta must be a list")
        fields: list[dict[str, str]] = []
        for j, field in enumerate(meta):
            if (
                not isinstance(field, dict)
                or not isinstance(field.get("key"), str)
                or not isinstance(field.get("value"), str)
                or not isinstance(field.get("kind", "str"), str)
                or not isinstance(field.get("source", "user"), str)
            ):
                raise CarrelInputError(
                    f"invalid catalog: {where}.meta[{j}] needs string 'key' and 'value'"
                )
            kind = field.get("kind", "str")
            if kind not in META_KINDS:
                raise CarrelInputError(
                    f"invalid catalog: {where}.meta[{j}].kind must be one of {', '.join(META_KINDS)}"
                )
            try:
                key = normalize_meta_key(field["key"])
                kind, value = coerce_meta(field["value"], kind)  # canonical, or refuse
            except CarrelInputError as e:
                raise CarrelInputError(f"invalid catalog: {where}.meta[{j}]: {e}") from e
            fields.append(
                {"key": key, "value": value, "kind": kind, "source": field.get("source", "user")}
            )
        for j, note in enumerate(notes):
            if (
                not isinstance(note, dict)
                or not isinstance(note.get("created"), int | float)
                or isinstance(note.get("created"), bool)
                or not isinstance(note.get("body"), str)
            ):
                raise CarrelInputError(
                    f"invalid catalog: {where}.notes[{j}] needs numeric 'created' and string 'body'"
                )
        out.append(
            {
                "path": entry["path"],
                "tags": tags,
                "notes": [{"created": float(n["created"]), "body": n["body"]} for n in notes],
                "meta": fields,
            }
        )
    return out


# ------------------------------------------------------------------ meta helpers


def normalize_meta_key(key: str) -> str:
    """Lower-case, trimmed key limited to [a-z0-9_.-] (raises CarrelInputError)."""
    k = key.strip().lower()
    if not _META_KEY_RE.match(k):
        raise CarrelInputError(
            f"invalid meta key {key!r}: use letters, digits, '_', '.' or '-' (up to 64 chars)"
        )
    return k


def canonical_number(text: str) -> str:
    """Plain decimal text for a numeric string: no exponent, no trailing zeros, no thousands separators."""
    try:
        d = Decimal(text.strip().replace(",", ""))
    except InvalidOperation as e:
        raise CarrelInputError(f"not a number: {text!r}") from e
    if not d.is_finite():
        raise CarrelInputError(f"not a number: {text!r}")
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def coerce_meta(value: str, kind: str | None) -> tuple[str, str]:
    """(kind, canonical value): infer the kind when None, else validate against it.

    Inference: `true`/`false` → bool, a plain number → num, `YYYY-MM-DD` → date,
    anything else → str. Explicit kinds are strict (raise CarrelInputError).
    """
    text = str(value).strip()
    if kind is None:
        low = text.lower()
        if low in ("true", "false"):
            return "bool", low
        if _NUM_RE.match(text) and not _LEADING_ZERO_RE.match(text):
            # `02134`, `0042`: an identifier that happens to be digits, not a number
            return "num", canonical_number(text)
        if _ISO_DATE_RE.match(text):
            try:
                date.fromisoformat(text)
            except ValueError:
                return "str", text
            return "date", text
        return "str", text
    if kind not in META_KINDS:
        raise CarrelInputError(f"unknown meta kind {kind!r} (choose from: {', '.join(META_KINDS)})")
    if kind == "str":
        return "str", text
    if kind == "num":
        return "num", canonical_number(text)
    if kind == "date":
        try:
            return "date", date.fromisoformat(text).isoformat()
        except ValueError as e:
            raise CarrelInputError(f"not an ISO date (YYYY-MM-DD): {text!r}") from e
    low = text.lower()
    if low in _BOOL_WORDS:
        return "bool", _BOOL_WORDS[low]
    if low in ("1", "0"):
        return "bool", "true" if low == "1" else "false"
    raise CarrelInputError(f"not a boolean: {text!r}")


def _meta_comparison(op: str, value: str) -> tuple[str, list[Any]]:
    """SQL fragment (against alias `m`) and parameters for one condition operator.

    A numeric literal compares numerically against `num` fields *and* as text
    against everything else (so `zip=02134` on a str field still matches);
    `=`/`!=` are case-insensitive on text and also accept bool spellings
    (`paid=yes`); ordering on text is lexical, which is chronological for ISO
    dates and lets a `due<2027` prefix work.
    """
    if op == "?":
        return "", []
    if op == "~":
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return "AND m.value LIKE ? ESCAPE '\\'", [f"%{escaped}%"]
    text = value.strip()
    literals: list[str] = [text]
    if text.lower() in _BOOL_WORDS:
        literals.append(_BOOL_WORDS[text.lower()])
    if op in ("=", "!="):
        # "equal under any interpretation": as text (case-insensitive), as a bool
        # spelling, or numerically against a num field; != is the negation
        equal = " OR ".join("m.value = ? COLLATE NOCASE" for _ in literals)
        params: list[Any] = list(literals)
        if _NUM_RE.match(text):
            equal += " OR (m.kind='num' AND CAST(m.value AS REAL) = ?)"
            params.append(float(Decimal(canonical_number(text))))
        return ("AND (" + equal + ")" if op == "=" else "AND NOT (" + equal + ")"), params
    if op not in _NUM_CMP:  # parse_meta_condition guarantees this; belt and braces
        raise CarrelInputError(f"unsupported operator {op!r}")
    if _NUM_RE.match(text):
        number = float(Decimal(canonical_number(text)))
        return "AND (" + _NUM_CMP[op] + " OR " + _NON_NUM_TEXT_CMP[op] + ")", [number, text]
    return "AND " + _TEXT_CMP[op], [text]


def parse_meta_condition(cond: str) -> tuple[str, str, str]:
    """`key OP value` (or bare `key?`) → (key, op, value); raises CarrelInputError."""
    m = _COND_RE.match(cond.strip())
    if not m:
        raise CarrelInputError(
            f"bad condition {cond!r}: expected KEY OP VALUE with OP one of "
            f"{' '.join(META_OPS)} (or KEY? for 'has the field')"
        )
    key, op, value = m.group(1), m.group(2), m.group(3).strip()
    if op == "?" and value:
        raise CarrelInputError(f"bad condition {cond!r}: 'KEY?' takes no value")
    if op != "?" and not value:
        raise CarrelInputError(f"bad condition {cond!r}: missing value after {op}")
    return normalize_meta_key(key), op, value
