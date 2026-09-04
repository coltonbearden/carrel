"""Tests for spec 17: DeskDB schema migrations, `carrel catalog`, `carrel index --status`.

Every CLI invocation passes --root at a tmp_path desk so no .carrel is ever
created inside the repo.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from carrel.cli import cli
from carrel.commands.index import index_paths
from carrel.core import db as dbmod
from carrel.core.db import MIGRATIONS, SCHEMA_VERSION, DeskDB
from carrel.core.output import CarrelInputError

# The schema shipped in v0.1.2 (no user_version stamp). Kept verbatim on purpose:
# a desk created by that release must open under the migration machinery.
V012_SCHEMA = """
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

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0):
    return json.loads(run("--json", *args, expect=expect).output)


@pytest.fixture
def desk(tmp_path: Path, tmp_copy) -> Path:
    """tmp desk root holding copies of two text fixtures."""
    tmp_copy("sample.txt")
    tmp_copy("sample.md")
    return tmp_path


@pytest.fixture
def catalogued(desk: Path) -> Path:
    """Indexed desk with 2 tags + 1 note spread over both files."""
    run_json("--root", str(desk), "index")
    run("--root", str(desk), "tag", "add", str(desk / "sample.txt"), "alpha", "Beta")
    run("--root", str(desk), "tag", "add", str(desk / "sample.md"), "gamma")
    run("--root", str(desk), "note", "add", str(desk / "sample.md"), "remember the milk")
    run("--root", str(desk), "note", "add", str(desk / "sample.txt"), "first note")
    return desk


def snapshot(root: Path) -> dict[str, object]:
    """tag ls + note ls --json for both fixture files (the acceptance comparison)."""
    out: dict[str, object] = {}
    for name in ("sample.txt", "sample.md"):
        f = str(root / name)
        out[f"tags:{name}"] = run_json("--root", str(root), "tag", "ls", f)
        out[f"notes:{name}"] = run_json("--root", str(root), "note", "ls", f)
    return out


# ------------------------------------------------------------- migrations


def test_fresh_db_is_schema_version_1(tmp_path: Path):
    with DeskDB(tmp_path) as db:
        assert db.schema_version() == 1 == SCHEMA_VERSION
    raw = sqlite3.connect(tmp_path / ".carrel" / "carrel.db")
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    raw.close()


def test_migrations_are_ordered_and_v1_is_the_schema():
    versions = [v for v, _ in MIGRATIONS]
    assert versions == sorted(versions) and versions[0] == 1
    assert MIGRATIONS[0][1] == dbmod._SCHEMA
    assert versions[-1] == SCHEMA_VERSION


def test_v012_database_is_stamped_1_with_data_intact(desk: Path):
    carrel_dir = desk / ".carrel"
    carrel_dir.mkdir()
    raw = sqlite3.connect(carrel_dir / "carrel.db")
    raw.executescript(V012_SCHEMA)
    raw.execute(
        "INSERT INTO files (id, path, size, mtime, type, indexed_at) VALUES (1,'sample.txt',5,1.0,'txt',2.0)"
    )
    raw.execute("INSERT INTO docs (rowid, content, path) VALUES (1,'quixotic zephyr','sample.txt')")
    raw.execute("INSERT INTO tags (file_id, tag) VALUES (1,'legacy')")
    raw.execute("INSERT INTO notes (file_id, created, body) VALUES (1, 3.0, 'old note')")
    raw.commit()
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    raw.close()

    with DeskDB(desk) as db:
        assert db.schema_version() == 1
        assert db.counts() == {"files": 1, "docs": 1, "tags": 1, "notes": 1}
        assert db.tags_of(desk / "sample.txt") == ["legacy"]
        assert [n["body"] for n in db.notes_of(desk / "sample.txt")] == ["old note"]
        assert [r["path"] for r in db.fts_search("quixotic")] == ["sample.txt"]


def test_newer_schema_is_refused_with_exit_4(desk: Path):
    with DeskDB(desk):
        pass
    raw = sqlite3.connect(desk / ".carrel" / "carrel.db")
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
    raw.commit()
    raw.close()
    with pytest.raises(CarrelInputError, match="upgrade"), DeskDB(desk):
        pass
    run("--root", str(desk), "catalog", "status", expect=4)


def test_failed_migration_rolls_back_and_leaves_version(desk: Path, monkeypatch):
    with DeskDB(desk) as db:
        db.add_tags(desk / "sample.txt", ["keep"])
    monkeypatch.setattr(
        dbmod,
        "MIGRATIONS",
        [*MIGRATIONS, (SCHEMA_VERSION + 1, "CREATE TABLE extra (x); INSERT INTO nope VALUES (1);")],
    )
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    with pytest.raises(sqlite3.OperationalError), DeskDB(desk):
        pass
    raw = sqlite3.connect(desk / ".carrel" / "carrel.db")
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "extra" not in names  # the whole step was one transaction
    assert raw.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1
    raw.close()


def test_migration_applies_a_new_step_once(desk: Path, monkeypatch):
    with DeskDB(desk):
        pass
    monkeypatch.setattr(
        dbmod, "MIGRATIONS", [*MIGRATIONS, (SCHEMA_VERSION + 1, "CREATE TABLE extra (x);")]
    )
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    with DeskDB(desk) as db:
        assert db.schema_version() == SCHEMA_VERSION + 1
    with DeskDB(desk) as db:  # reopening does not re-run (CREATE TABLE would fail)
        assert db.schema_version() == SCHEMA_VERSION + 1


# ------------------------------------------------------------ core helpers


def test_counts_and_stale(desk: Path):
    run_json("--root", str(desk), "index")
    with DeskDB(desk) as db:
        assert db.counts() == {"files": 2, "docs": 2, "tags": 0, "notes": 0}
        assert db.stale() == {"changed": [], "missing": []}
    txt = desk / "sample.txt"
    txt.write_text(txt.read_text() + "\nmore\n")
    (desk / "sample.md").unlink()
    with DeskDB(desk) as db:
        assert db.stale() == {"changed": ["sample.txt"], "missing": ["sample.md"]}
        assert db.indexed_paths() == {"sample.txt", "sample.md"}


def test_tag_only_file_is_not_changed_but_unindexed(desk: Path):
    run("--root", str(desk), "tag", "add", str(desk / "sample.txt"), "solo")
    with DeskDB(desk) as db:
        assert db.stale() == {"changed": [], "missing": []}
        assert db.indexed_paths() == set()
    status = run_json("--root", str(desk), "catalog", "status")
    assert status["stale"] == {"changed": 0, "missing": 0, "unindexed": 2}
    assert status["examples"]["unindexed"] == ["sample.md", "sample.txt"]


def test_export_catalog_only_files_with_tags_or_notes(catalogued: Path):
    with DeskDB(catalogued) as db:
        doc = db.export_catalog()
    assert doc["schema"] == SCHEMA_VERSION and doc["root"] == str(catalogued.resolve())
    assert [f["path"] for f in doc["files"]] == ["sample.md", "sample.txt"]
    by_path = {f["path"]: f for f in doc["files"]}
    assert by_path["sample.txt"]["tags"] == ["alpha", "beta"]  # normalised + sorted
    assert [n["body"] for n in by_path["sample.md"]["notes"]] == ["remember the milk"]
    assert isinstance(by_path["sample.md"]["notes"][0]["created"], float)


def test_import_catalog_validates_shape(desk: Path):
    with DeskDB(desk) as db:
        for bad in (
            [],
            {"files": []},
            {"schema": "1", "files": []},
            {"schema": 1},
            {"schema": 1, "files": [{"tags": []}]},
            {"schema": 1, "files": [{"path": "a", "tags": [1]}]},
            {"schema": 1, "files": [{"path": "a", "notes": [{"body": "x"}]}]},
        ):
            with pytest.raises(CarrelInputError, match="invalid catalog"):
                db.import_catalog(bad)
        with pytest.raises(CarrelInputError, match="newer"):
            db.import_catalog({"schema": 99, "files": []})


# ------------------------------------------------------------------ export


def test_export_stdout_shape_and_determinism(catalogued: Path):
    a = run("--root", str(catalogued), "catalog", "export").output
    b = run("--root", str(catalogued), "--json", "catalog", "export").output
    da, dbb = json.loads(a), json.loads(b)
    assert list(da) == ["schema", "product", "version", "exported", "root", "files"]
    assert da["schema"] == 1 and da["product"] == "carrel"
    from carrel._product import PRODUCT

    assert da["version"] == PRODUCT["version"]
    del da["exported"], dbb["exported"]
    assert da == dbb
    assert [f["path"] for f in da["files"]] == ["sample.md", "sample.txt"]
    assert da["files"][1] == {
        "path": "sample.txt",
        "tags": ["alpha", "beta"],
        "notes": [
            {"created": pytest.approx(da["files"][1]["notes"][0]["created"]), "body": "first note"}
        ],
    }


def test_export_to_file_refuses_overwrite_without_force(catalogued: Path, tmp_path: Path):
    out = tmp_path / "exports" / "desk.json"
    summary = run_json("--root", str(catalogued), "catalog", "export", "-o", str(out))
    assert summary == {"out": str(out), "files": 2, "tags": 3, "notes": 2}
    doc = json.loads(out.read_text())
    assert len(doc["files"]) == 2
    result = run("--root", str(catalogued), "catalog", "export", "-o", str(out), expect=1)
    assert "--force" in result.stderr
    human = run("--root", str(catalogued), "catalog", "export", "-o", str(out), "--force")
    assert "wrote" in human.output and "2 file(s)" in human.output


def test_export_without_desk_exits_4(desk: Path):
    result = run("--root", str(desk), "catalog", "export", expect=4)
    assert "no desk db" in result.stderr
    assert not (desk / ".carrel").exists()  # read-only: no side-effect directory


# ------------------------------------------------------------------ import


def test_round_trip_export_wipe_index_import(catalogued: Path, tmp_path: Path):
    before = snapshot(catalogued)
    assert before["tags:sample.txt"]["tags"] == ["alpha", "beta"]
    assert len(before["notes:sample.md"]) == 1
    out = tmp_path / "desk.json"
    run("--root", str(catalogued), "catalog", "export", "-o", str(out))

    shutil.rmtree(catalogued / ".carrel")
    run_json("--root", str(catalogued), "index")
    assert snapshot(catalogued)["tags:sample.txt"]["tags"] == []

    first = run_json("--root", str(catalogued), "catalog", "import", str(out))
    assert first == {
        "tags_added": 3,
        "notes_added": 2,
        "files_touched": 2,
        "skipped_missing": 0,
        "tags_removed": 0,
        "notes_removed": 0,
        "skipped_outside": 0,
    }
    assert snapshot(catalogued) == before

    second = run_json("--root", str(catalogued), "catalog", "import", str(out))
    assert second["tags_added"] == 0 and second["notes_added"] == 0
    assert second["files_touched"] == 0
    assert snapshot(catalogued) == before


def test_import_replace_restores_exactly_the_exported_set(catalogued: Path, tmp_path: Path):
    out = tmp_path / "desk.json"
    run("--root", str(catalogued), "catalog", "export", "-o", str(out))
    before = snapshot(catalogued)
    run("--root", str(catalogued), "tag", "add", str(catalogued / "sample.txt"), "extra")
    run("--root", str(catalogued), "note", "add", str(catalogued / "sample.txt"), "stray")
    assert snapshot(catalogued) != before

    merged = run_json("--root", str(catalogued), "catalog", "import", str(out))
    assert merged["tags_added"] == 0 and merged["notes_added"] == 0
    assert "extra" in snapshot(catalogued)["tags:sample.txt"]["tags"]  # merge keeps extras

    result = run("--root", str(catalogued), "catalog", "import", str(out), "--replace")
    assert "removed 4 tag(s) and 3 note(s)" in result.output
    assert snapshot(catalogued) == before
    replaced = run_json("--root", str(catalogued), "catalog", "import", str(out), "--replace")
    assert replaced["tags_removed"] == 3 and replaced["notes_removed"] == 2
    assert replaced["tags_added"] == 3 and replaced["notes_added"] == 2


def test_import_skips_missing_files(catalogued: Path, tmp_path: Path):
    doc = json.loads(run("--root", str(catalogued), "catalog", "export").output)
    doc["files"].append({"path": "ghost.txt", "tags": ["boo"], "notes": []})
    src = tmp_path / "with-ghost.json"
    src.write_text(json.dumps(doc))
    result = run_json("--root", str(catalogued), "catalog", "import", str(src))
    assert result["skipped_missing"] == 1 and result["tags_added"] == 0
    human = run("--root", str(catalogued), "catalog", "import", str(src))
    assert "skipped 1" in human.stderr
    with DeskDB(catalogued) as db:
        assert db.get_file(catalogued / "ghost.txt") is None


def test_import_registers_untracked_file_and_normalises_tags(desk: Path, tmp_path: Path):
    src = tmp_path / "c.json"
    src.write_text(
        json.dumps(
            {
                "schema": 1,
                "files": [{"path": "sample.md", "tags": ["  Mixed ", "mixed"], "notes": []}],
            }
        )
    )
    result = run_json("--root", str(desk), "catalog", "import", str(src))
    assert result["tags_added"] == 1 and result["files_touched"] == 1
    assert run_json("--root", str(desk), "tag", "ls", str(desk / "sample.md"))["tags"] == ["mixed"]


@pytest.mark.parametrize(
    ("content", "needle"),
    [
        ("{not json", "invalid JSON"),
        ('{"schema": 99, "files": []}', "newer"),
        ('{"schema": 1}', "invalid catalog"),
        ("[1, 2]", "top level"),
    ],
)
def test_import_bad_documents_exit_4(desk: Path, tmp_path: Path, content: str, needle: str):
    src = tmp_path / "bad.json"
    src.write_text(content)
    result = run("--root", str(desk), "catalog", "import", str(src), expect=4)
    assert needle in result.stderr


def test_import_unreadable_file_exits_4(desk: Path, tmp_path: Path):
    result = run("--root", str(desk), "catalog", "import", str(tmp_path / "nope.json"), expect=4)
    assert "cannot read" in result.stderr


# ------------------------------------------------------------------ status


def test_status_reports_changed_and_missing(catalogued: Path):
    clean = run_json("--root", str(catalogued), "catalog", "status")
    assert clean["schema_version"] == 1
    assert clean["db_path"] == str(catalogued / ".carrel" / "carrel.db")
    assert clean["counts"] == {"files": 2, "docs": 2, "tags": 3, "notes": 2}
    assert clean["stale"] == {"changed": 0, "missing": 0, "unindexed": 0}
    human = run("--root", str(catalogued), "catalog", "status")
    assert "hint" not in human.output

    txt = catalogued / "sample.txt"
    txt.write_text(txt.read_text() + "\nchanged line\n")
    (catalogued / "sample.md").unlink()
    (catalogued / "new.txt").write_text("brand new")
    status = run_json("--root", str(catalogued), "catalog", "status")
    assert status["stale"] == {"changed": 1, "missing": 1, "unindexed": 1}
    assert status["examples"] == {
        "changed": ["sample.txt"],
        "missing": ["sample.md"],
        "unindexed": ["new.txt"],
    }
    human = run("--root", str(catalogued), "catalog", "status")
    assert "hint" in human.output and "--prune" in human.output and "sample.md" in human.output


def test_index_status_prints_same_payload(catalogued: Path):
    (catalogued / "sample.md").unlink()
    via_catalog = run_json("--root", str(catalogued), "catalog", "status")
    via_index = run_json("--root", str(catalogued), "index", "--status")
    assert via_index == via_catalog
    assert via_index["stale"]["missing"] == 1
    # --status never indexes: counts unchanged after the call
    assert (
        run_json("--root", str(catalogued), "catalog", "status")["counts"] == via_catalog["counts"]
    )


def test_status_without_desk_exits_4(desk: Path):
    assert "no desk db" in run("--root", str(desk), "catalog", "status", expect=4).stderr
    assert "no desk db" in run("--root", str(desk), "index", "--status", expect=4).stderr
    assert not (desk / ".carrel").exists()


def test_status_examples_capped_at_five(desk: Path):
    for i in range(7):
        (desk / f"f{i}.txt").write_text(f"file {i}")
    run_json("--root", str(desk), "index")
    for i in range(7):
        (desk / f"f{i}.txt").unlink()
    status = run_json("--root", str(desk), "catalog", "status")
    assert status["stale"]["missing"] == 7
    assert len(status["examples"]["missing"]) == 5


# -------------------------------------------------------------------- help


@pytest.mark.parametrize("path", [[], ["export"], ["import"], ["status"]])
def test_help_and_json_flag(path: list[str]):
    result = run("catalog", *path, "--help")
    assert "Usage:" in result.output and "--json" in result.output
    run("catalog", *path, "--json", "--help")


def test_index_help_mentions_status():
    assert "--status" in run("index", "--help").output


# -------------------------------------------------------- index_paths seam


def test_index_paths_signature_for_mcp():
    sig = inspect.signature(index_paths)
    assert list(sig.parameters) == ["root", "paths", "update", "prune", "ocr"]
    for name in ("update", "prune", "ocr"):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters[name].default is False
    assert sig.parameters["paths"].default is None


def test_index_paths_returns_counts_without_click_context(desk: Path):
    first = index_paths(desk)
    assert first["indexed"] == 2 and first["skipped"] == 0 and first["pruned"] == 0
    assert first["errors"] == []
    (desk / "sample.md").unlink()
    second = index_paths(desk, prune=True)
    assert second == {"indexed": 0, "skipped": 1, "pruned": 1, "errors": []}
    hook = index_paths(desk, [desk / "sample.txt", desk / "nope.bin"], update=True)
    assert hook["skipped"] == 2  # fresh file + missing file, never an error
    with pytest.raises(CarrelInputError):
        index_paths(desk, [desk / "missing-dir"])
