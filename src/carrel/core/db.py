"""DeskDB — the .carrel/carrel.db SQLite store (index, tags, notes).

Schema versioning
-----------------
`PRAGMA user_version` records the schema version. `MIGRATIONS` is the ordered
list of `(version, sql)` steps; opening a desk applies every step above the
stored version inside one transaction and then stamps the new version.
Version 1 is the v0.1.2 layout exactly, so a pre-v0.2.0 database (user_version
0 with the tables already present) is recognised and stamped 1 untouched.

**Adding a migration is the only sanctioned way to change the schema.** Never
edit `_SCHEMA` or an existing migration in place: append a new
`(N + 1, "ALTER TABLE …")` entry to `MIGRATIONS` and bump nothing else — the
version is derived from the list.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
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

# (version, sql) — applied in order; version 1 == the v0.1.2 layout (`_SCHEMA`).
MIGRATIONS: list[tuple[int, str]] = [
    (1, _SCHEMA),
]

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
        p = Path(path).resolve()
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

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
        """Row counts: files, docs (FTS rows), tags, notes."""
        return {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 — fixed table names
            for table in ("files", "docs", "tags", "notes")
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
            "SELECT created, body FROM notes WHERE file_id=? ORDER BY created DESC",
            (row["id"],),
        ).fetchall()

    # -- catalog export / import ---------------------------------------------
    def export_catalog(self) -> dict[str, Any]:
        """Tags + notes for every file that has at least one, sorted by path.

        Deterministic: same desk → byte-identical JSON. Returns
        `{"schema": SCHEMA_VERSION, "root": <abs>, "files": [{path, tags, notes}]}`;
        the CLI layer adds product/version/exported.
        """
        rows = self.conn.execute(
            """SELECT id, path FROM files f
               WHERE EXISTS (SELECT 1 FROM tags t WHERE t.file_id=f.id)
                  OR EXISTS (SELECT 1 FROM notes n WHERE n.file_id=f.id)
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
            files.append({"path": row["path"], "tags": tags, "notes": notes})
        return {"schema": SCHEMA_VERSION, "root": str(self.root), "files": files}

    def import_catalog(self, data: dict[str, Any], *, replace: bool = False) -> dict[str, int]:
        """Merge a catalog document (see `export_catalog`) into this desk.

        Tags are `INSERT OR IGNORE`; notes are deduplicated on
        (file_id, created, body), so importing twice changes nothing. With
        `replace`, every existing tag and note is deleted first (counted under
        `tags_removed` / `notes_removed`). Entries whose file is not on disk under
        the root are skipped (`skipped_missing`), never created.
        Raises CarrelInputError for a malformed document or a newer `schema`.
        """
        files = _validate_catalog(data)
        result = {
            "tags_added": 0,
            "notes_added": 0,
            "files_touched": 0,
            "skipped_missing": 0,
            "tags_removed": 0,
            "notes_removed": 0,
        }
        if replace:
            result["tags_removed"] = int(
                self.conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            )
            result["notes_removed"] = int(
                self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            )
            self.conn.execute("DELETE FROM tags")
            self.conn.execute("DELETE FROM notes")
        for entry in files:
            path = (self.root / entry["path"]).resolve()
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
        if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
            raise CarrelInputError(f"invalid catalog: {where}.tags must be a list of strings")
        if not isinstance(notes, list):
            raise CarrelInputError(f"invalid catalog: {where}.notes must be a list")
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
            }
        )
    return out
