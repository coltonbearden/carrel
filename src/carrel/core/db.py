"""DeskDB — the .carrel/carrel.db SQLite store (index, tags, notes)."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

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
        self._conn.executescript(_SCHEMA)
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

    def is_fresh(self, path: Path) -> bool:
        row = self.get_file(path)
        if row is None or row["indexed_at"] is None:
            return False
        stat = path.stat()
        return row["size"] == stat.st_size and abs(row["mtime"] - stat.st_mtime) < 1e-6

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
