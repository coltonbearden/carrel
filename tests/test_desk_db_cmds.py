"""Tests for the desk-db commands: carrel index / search / tag / note.

Every invocation passes --root pointing at a tmp_path desk, so no .carrel
directory is ever created in the repo. Fixture sentinels: sample.txt
"quixotic zephyr", sample.md "melodious cartography", text+image.pdf
"palimpsest harbor".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs
from pypdf import PdfWriter

from carrel.cli import cli

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\n"
        f"stderr: {result.stderr}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0):
    result = run("--json", *args, expect=expect)
    return json.loads(result.output)


def make_pdf(path: Path, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


@pytest.fixture
def desk(tmp_path: Path, tmp_copy) -> Path:
    """tmp desk root holding copies of the text fixtures."""
    tmp_copy("sample.txt")
    tmp_copy("sample.md")
    return tmp_path


# ------------------------------------------------------------------- index


def test_index_builds_db_and_counts(desk: Path):
    summary = run_json("--root", str(desk), "index")
    assert summary == {"indexed": 2, "skipped": 0, "pruned": 0, "errors": []}
    assert (desk / ".carrel" / "carrel.db").is_file()


def test_index_unchanged_reindex_skips_all(desk: Path):
    run_json("--root", str(desk), "index")
    summary = run_json("--root", str(desk), "index")
    assert summary["indexed"] == 0
    assert summary["skipped"] == 2


def test_index_reindexes_modified_file(desk: Path):
    run_json("--root", str(desk), "index")
    txt = desk / "sample.txt"
    txt.write_text(txt.read_text() + "\nfreshly added xylograph line\n")
    summary = run_json("--root", str(desk), "index")
    assert summary["indexed"] == 1 and summary["skipped"] == 1
    hits = run_json("--root", str(desk), "search", "xylograph")
    assert [h["path"] for h in hits] == ["sample.txt"]


def test_index_prune_removes_deleted_files(desk: Path):
    run_json("--root", str(desk), "index")
    (desk / "sample.md").unlink()
    summary = run_json("--root", str(desk), "index", "--prune")
    assert summary["pruned"] == 1
    assert run_json("--root", str(desk), "search", "melodious") == []


def test_index_skips_hidden_dirs_and_unsupported_files(desk: Path):
    hidden = desk / ".secrets"
    hidden.mkdir()
    (hidden / "inner.txt").write_text("clandestine gobbledygook")
    (desk / "script.py").write_text("print('not a supported type')")
    summary = run_json("--root", str(desk), "index")
    assert summary["indexed"] == 2  # only the two visible supported fixtures
    assert run_json("--root", str(desk), "search", "clandestine") == []


def test_index_explicit_subpath_only(desk: Path):
    sub = desk / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("subterranean bivouac")
    summary = run_json("--root", str(desk), "index", str(sub))
    assert summary["indexed"] == 1
    hits = run_json("--root", str(desk), "search", "subterranean")
    assert [h["path"] for h in hits] == ["sub/deep.txt"]


def test_index_missing_path_exits_4(desk: Path):
    run("--root", str(desk), "index", str(desk / "nope"), expect=4)


@needs("pdftotext")
def test_index_pdf_then_search_embedded_word(tmp_path: Path, tmp_copy):
    tmp_copy("text+image.pdf")
    summary = run_json("--root", str(tmp_path), "index")
    assert summary["indexed"] == 1 and summary["errors"] == []
    hits = run_json("--root", str(tmp_path), "search", "palimpsest")
    assert [h["path"] for h in hits] == ["text+image.pdf"]
    assert "palimpsest" in hits[0]["snippet"].lower()


def test_index_update_reindexes_named_files_only(desk: Path):
    run_json("--root", str(desk), "index")
    txt = desk / "sample.txt"
    txt.write_text(txt.read_text() + "\nnimbus catamaran\n")
    md = desk / "sample.md"
    md.write_text(md.read_text() + "\nnot reindexed sesquipedalian\n")
    summary = run_json("--root", str(desk), "index", "--update", str(txt))
    assert summary["indexed"] == 1
    assert run_json("--root", str(desk), "search", "catamaran") != []
    assert run_json("--root", str(desk), "search", "sesquipedalian") == []


def test_index_update_if_indexed_is_silent_noop_without_db(tmp_path: Path, tmp_copy):
    f = tmp_copy("sample.txt")
    result = run("--root", str(tmp_path), "index", "--update", str(f), "--if-indexed")
    assert result.output == ""
    assert not (tmp_path / ".carrel").exists()  # never creates a db


def test_index_update_skips_unsupported_and_missing_quietly(desk: Path):
    run_json("--root", str(desk), "index")
    weird = desk / "hook_output.py"
    weird.write_text("x = 1")
    summary = run_json(
        "--root", str(desk), "index", "--update", str(weird), str(desk / "ghost.txt")
    )
    assert summary["indexed"] == 0 and summary["errors"] == []
    assert summary["skipped"] == 2


def test_index_update_without_files_is_usage_error(desk: Path):
    run("--root", str(desk), "index", "--update", expect=2)


# ------------------------------------------------------------------- search


def test_search_finds_md_and_txt_sentinels(desk: Path):
    run_json("--root", str(desk), "index")
    hits = run_json("--root", str(desk), "search", "melodious")
    assert [h["path"] for h in hits] == ["sample.md"]
    hits = run_json("--root", str(desk), "search", "quixotic")
    assert [h["path"] for h in hits] == ["sample.txt"]
    assert set(hits[0]) == {"path", "score", "snippet"}
    assert isinstance(hits[0]["score"], float)
    assert "quixotic" in hits[0]["snippet"].lower()


@pytest.fixture
def two_docs(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text("# alpha\n\nthe shared word is bumfuzzle\n")
    (tmp_path / "b.txt").write_text("bravo text also says bumfuzzle here\n")
    run_json("--root", str(tmp_path), "index")
    return tmp_path


def test_search_type_filter(two_docs: Path):
    root = str(two_docs)
    assert len(run_json("--root", root, "search", "bumfuzzle")) == 2
    hits = run_json("--root", root, "search", "bumfuzzle", "--type", "md")
    assert [h["path"] for h in hits] == ["a.md"]
    hits = run_json("--root", root, "search", "bumfuzzle", "--type", "md,txt")
    assert len(hits) == 2


def test_search_bad_type_is_usage_error(two_docs: Path):
    run("--root", str(two_docs), "search", "bumfuzzle", "--type", "wav", expect=2)


def test_search_tag_filter(two_docs: Path):
    root = str(two_docs)
    run_json("--root", root, "tag", "add", str(two_docs / "a.md"), "work")
    hits = run_json("--root", root, "search", "bumfuzzle", "--tag", "work")
    assert [h["path"] for h in hits] == ["a.md"]
    # AND semantics across repeated --tag
    hits = run_json("--root", root, "search", "bumfuzzle", "--tag", "work", "--tag", "absent")
    assert hits == []


def test_search_limit(two_docs: Path):
    hits = run_json("--root", str(two_docs), "search", "bumfuzzle", "--limit", "1")
    assert len(hits) == 1


def test_search_fail_empty_exits_5(desk: Path):
    run_json("--root", str(desk), "index")
    run("--root", str(desk), "search", "bananaphone", "--fail-empty", expect=5)
    assert run_json("--root", str(desk), "search", "bananaphone") == []  # exit 0 without flag


def test_search_without_index_errors_and_creates_nothing(tmp_path: Path):
    result = run("--root", str(tmp_path), "search", "anything", expect=1)
    assert "index" in result.stderr
    assert not (tmp_path / ".carrel").exists()


# --------------------------------------------------------------------- tag


def test_tag_add_normalizes_and_ls(desk: Path):
    md = str(desk / "sample.md")
    data = run_json("--root", str(desk), "tag", "add", md, "Reading", "  DESK ")
    assert data["tags"] == ["desk", "reading"]
    data = run_json("--root", str(desk), "tag", "ls", md)
    assert data["path"] == "sample.md" and data["tags"] == ["desk", "reading"]


def test_tag_find_requires_all_tags(desk: Path):
    root = str(desk)
    run_json("--root", root, "tag", "add", str(desk / "sample.md"), "reading", "desk")
    run_json("--root", root, "tag", "add", str(desk / "sample.txt"), "reading")
    assert run_json("--root", root, "tag", "find", "reading") == ["sample.md", "sample.txt"]
    assert run_json("--root", root, "tag", "find", "reading", "desk") == ["sample.md"]
    assert run_json("--root", root, "tag", "find", "nonexistent") == []


def test_tag_rm(desk: Path):
    md = str(desk / "sample.md")
    run_json("--root", str(desk), "tag", "add", md, "keep", "drop")
    data = run_json("--root", str(desk), "tag", "rm", md, "drop")
    assert data["tags"] == ["keep"]
    # rm on an untagged/unknown file is a quiet no-op
    data = run_json("--root", str(desk), "tag", "rm", str(desk / "sample.txt"), "keep")
    assert data["tags"] == []


def test_tag_ls_all_counts(desk: Path):
    root = str(desk)
    run_json("--root", root, "tag", "add", str(desk / "sample.md"), "shared", "solo")
    run_json("--root", root, "tag", "add", str(desk / "sample.txt"), "shared")
    data = run_json("--root", root, "tag", "ls")
    assert data["tags"] == {"shared": 2, "solo": 1}


def test_tag_add_missing_file_exits_4(desk: Path):
    run("--root", str(desk), "tag", "add", str(desk / "ghost.txt"), "x", expect=4)


def test_tag_readonly_ops_do_not_create_db(tmp_path: Path):
    assert run_json("--root", str(tmp_path), "tag", "find", "anything") == []
    assert run_json("--root", str(tmp_path), "tag", "ls") == {"tags": {}}
    assert not (tmp_path / ".carrel").exists()


# -------------------------------------------------------------------- note


def test_note_add_and_ls_newest_first(desk: Path):
    md = str(desk / "sample.md")
    first = run_json("--root", str(desk), "note", "add", md, "first note")
    assert first["path"] == "sample.md" and isinstance(first["id"], int)
    datetime.fromisoformat(first["created"])  # ISO timestamp
    run_json("--root", str(desk), "note", "add", md, "second note")
    notes = run_json("--root", str(desk), "note", "ls", md)
    assert [n["body"] for n in notes] == ["second note", "first note"]
    for n in notes:
        datetime.fromisoformat(n["created"])


def test_note_ls_empty_and_missing_db(desk: Path, tmp_path_factory):
    assert run_json("--root", str(desk), "note", "ls", str(desk / "sample.txt")) == []
    bare = tmp_path_factory.mktemp("bare")
    (bare / "f.txt").write_text("x")
    assert run_json("--root", str(bare), "note", "ls", str(bare / "f.txt")) == []
    assert not (bare / ".carrel").exists()


def test_note_add_missing_file_exits_4(desk: Path):
    run("--root", str(desk), "note", "add", str(desk / "ghost.txt"), "hi", expect=4)


def test_note_pdf_add_then_pdf_lists_it(tmp_path: Path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    out = tmp_path / "annotated.pdf"
    data = run_json(
        "--root",
        str(tmp_path),
        "note",
        "pdf-add",
        str(src),
        "hello margin note",
        "--page",
        "2",
        "--pos",
        "100,700",
        "-o",
        str(out),
    )
    assert data["page"] == 2 and data["contents"] == "hello margin note"
    annots = run_json("--root", str(tmp_path), "note", "pdf", str(out))
    assert {"page": 2, "subtype": "FreeText", "contents": "hello margin note"} in annots
    # source untouched
    assert run_json("--root", str(tmp_path), "note", "pdf", str(src)) == []


def test_note_pdf_add_default_output_name(tmp_path: Path):
    src = make_pdf(tmp_path / "doc.pdf")
    data = run_json("--root", str(tmp_path), "note", "pdf-add", str(src), "sticky")
    expected = tmp_path / "doc.annotated.pdf"
    assert data["output"] == str(expected) and expected.is_file()
    annots = run_json("--root", str(tmp_path), "note", "pdf", str(expected))
    assert annots and annots[0]["contents"] == "sticky"


def test_note_pdf_add_bad_page_exits_4(tmp_path: Path):
    src = make_pdf(tmp_path / "doc.pdf")
    run("--root", str(tmp_path), "note", "pdf-add", str(src), "x", "--page", "9", expect=4)


def test_note_pdf_add_bad_pos_is_usage_error(tmp_path: Path):
    src = make_pdf(tmp_path / "doc.pdf")
    run("--root", str(tmp_path), "note", "pdf-add", str(src), "x", "--pos", "oops", expect=2)


def test_note_pdf_on_non_pdf_exits_4(desk: Path):
    run("--root", str(desk), "note", "pdf", str(desk / "sample.txt"), expect=4)
    run("--root", str(desk), "note", "pdf-add", str(desk / "sample.txt"), "x", expect=4)


# --------------------------------------------------------------- plumbing


def test_helps_work():
    run("index", "--help")
    run("search", "--help")
    for sub in ("add", "rm", "ls", "find"):
        run("tag", sub, "--help")
    for sub in ("add", "ls", "pdf", "pdf-add"):
        run("note", sub, "--help")


def test_json_output_is_single_document(desk: Path):
    result = run("--json", "--root", str(desk), "index")
    json.loads(result.output)  # raises if anything besides one JSON doc on stdout
