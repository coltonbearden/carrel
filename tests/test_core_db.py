"""Unit tests for carrel.core.db.DeskDB (spec 00-core Acceptance: full roundtrip)."""

from __future__ import annotations

import pytest

from carrel.core.db import DeskDB, file_hash


@pytest.fixture
def desk(tmp_path, tmp_copy):
    """A tmp desk root containing copies of a few fixtures."""
    tmp_copy("sample.txt")
    tmp_copy("sample.md")
    tmp_copy("sample.png")
    return tmp_path


def test_creates_db_under_root(desk):
    assert not DeskDB.exists(desk)
    with DeskDB(desk):
        pass
    assert (desk / ".carrel" / "carrel.db").is_file()
    assert DeskDB.exists(desk)


def test_upsert_roundtrip(desk):
    f = desk / "sample.txt"
    with DeskDB(desk) as db:
        fid = db.upsert_file(f, ftype="txt")
        assert isinstance(fid, int)
        row = db.get_file(f)
        assert row["path"] == "sample.txt"  # stored relative to root
        assert row["size"] == f.stat().st_size
        assert row["type"] == "txt"
        assert row["hash"] is None

        # re-upsert: same id, hash filled in and then preserved by COALESCE
        fid2 = db.upsert_file(f, ftype="txt", with_hash=True)
        assert fid2 == fid
        assert db.get_file(f)["hash"] == file_hash(f)
        db.upsert_file(f, ftype="txt")  # no hash requested
        assert db.get_file(f)["hash"] == file_hash(f)


def test_persistence_across_reopen(desk):
    f = desk / "sample.txt"
    with DeskDB(desk) as db:
        db.upsert_file(f, ftype="txt")
    with DeskDB(desk) as db:
        assert db.get_file(f) is not None


def test_fts_insert_and_search(desk):
    f = desk / "sample.txt"
    with DeskDB(desk) as db:
        fid = db.upsert_file(f, ftype="txt")
        db.set_content(fid, f, f.read_text())

        hits = db.fts_search("quixotic")
        assert len(hits) == 1
        assert hits[0]["path"] == "sample.txt"
        assert "quixotic" in hits[0]["snip"]

        assert db.fts_search("bananaphone") == []

        # re-index replaces, doesn't duplicate
        db.set_content(fid, f, "totally new content about lighthouses")
        assert db.fts_search("quixotic") == []
        assert len(db.fts_search("lighthouses")) == 1


def test_is_fresh(desk):
    f = desk / "sample.txt"
    with DeskDB(desk) as db:
        assert not db.is_fresh(f)  # unknown file
        fid = db.upsert_file(f, ftype="txt")
        assert not db.is_fresh(f)  # known but never indexed
        db.set_content(fid, f, "x")
        assert db.is_fresh(f)
        # modifying the file on disk (without re-upserting) makes it stale
        f.write_text(f.read_text() + "more")
        assert not db.is_fresh(f)


def test_tags_roundtrip(desk):
    f = desk / "sample.md"
    with DeskDB(desk) as db:
        db.add_tags(f, ["Reading", "reading", "  DESK "])  # normalized + deduped
        assert db.tags_of(f) == ["desk", "reading"]

        db.add_tags(desk / "sample.txt", ["reading"])
        assert db.find_by_tags(["reading"]) == ["sample.md", "sample.txt"]
        assert db.find_by_tags(["reading", "desk"]) == ["sample.md"]  # AND semantics

        db.rm_tags(f, ["reading"])
        assert db.tags_of(f) == ["desk"]
        db.rm_tags(desk / "nonexistent.txt", ["reading"])  # no-op, no error


def test_notes_roundtrip(desk):
    f = desk / "sample.md"
    with DeskDB(desk) as db:
        nid = db.add_note(f, "first note")
        assert isinstance(nid, int)
        db.add_note(f, "second note")
        notes = db.notes_of(f)
        assert [n["body"] for n in notes] == ["second note", "first note"]  # newest first
        assert db.notes_of(desk / "nonexistent.txt") == []


def test_prune(desk):
    f = desk / "sample.png"
    with DeskDB(desk) as db:
        fid = db.upsert_file(f, ftype="png")
        db.set_content(fid, f, "png placeholder text")
        f.unlink()
        assert db.prune() == 1
        assert db.get_file(f) is None
        assert db.fts_search("placeholder") == []
        assert db.prune() == 0


def test_rel_paths_outside_root(desk, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "far.txt"
    outside.write_text("far away")
    with DeskDB(desk) as db:
        # absolute when not under root — and POSIX-separated like every other key
        assert db.rel(outside) == outside.resolve().as_posix()
