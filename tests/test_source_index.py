"""Spec 22 — source and config files are indexed, so search and `pack --query`
reach source trees.

Before this, `carrel index` skipped every type `detect()` returned UNKNOWN for,
which was every source file, while `pack` happily packed the same files. These
tests pin the new behaviour, the `.gitignore` walk that makes it safe, and the
`files.type` contract the desk TUI depends on.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from carrel.cli import cli
from carrel.commands.sign import _manifest_entry_path
from carrel.core.db import DeskDB
from carrel.core.filetypes import FileType, detect, source_language

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\nexc: {result.exception!r}"
    )
    return result


def run_json(*args: str, expect: int = 0):
    return json.loads(run(*args, "--json", expect=expect).output)


def tree(tmp_path: Path) -> Path:
    """A small source tree: three source files, one doc, one gitignored build dir."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "build").mkdir()
    (root / "node_modules" / "leftpad").mkdir(parents=True)
    (root / "pkg" / "auth.py").write_text("def login():\n    return 'perspicacious token'\n")
    (root / "pkg" / "util.rs").write_text("fn helper() { /* perspicacious */ }\n")
    (root / "pyproject.toml").write_text('[project]\nname = "perspicacious"\n')
    (root / "README.md").write_text("# Notes\n\nA perspicacious readme.\n")
    (root / "build" / "generated.py").write_text("PERSPICACIOUS = 'built artifact'\n")
    (root / "node_modules" / "leftpad" / "index.js").write_text("// perspicacious vendor\n")
    (root / ".gitignore").write_text("build/\nnode_modules/\n")
    return root


# ------------------------------------------------------------------ detection


def test_source_extensions_detect_as_code(tmp_path: Path):
    for name in ("a.py", "a.rs", "a.toml", "a.yaml", "a.go", "a.ts"):
        f = tmp_path / name
        f.write_text("x\n")
        assert detect(f) is FileType.CODE, name
        assert detect(f).is_code


def test_extensionless_build_files_detect_as_code(tmp_path: Path):
    for name in ("Makefile", "Dockerfile", "justfile"):
        f = tmp_path / name
        f.write_text("x\n")
        assert detect(f) is FileType.CODE, name


def test_richer_types_are_not_downgraded_to_code(tmp_path: Path):
    """.json/.xml/.csv/.md keep their own FileType — they have real extractors."""
    for name, expected in (
        ("a.json", FileType.JSON),
        ("a.xml", FileType.XML),
        ("a.csv", FileType.CSV),
        ("a.md", FileType.MD),
        ("a.txt", FileType.TXT),
    ):
        f = tmp_path / name
        f.write_text("{}\n")
        assert detect(f) is expected, name


def test_unknown_stays_unknown(tmp_path: Path):
    f = tmp_path / "mystery.bin"
    f.write_bytes(b"\x00\x01\x02")
    assert detect(f) is FileType.UNKNOWN
    assert source_language(f) is None


def test_source_fixture_detects_and_extracts(fixtures: Path):
    from carrel.core.textextract import extract_text

    sample = fixtures / "sample.py"
    assert detect(sample) is FileType.CODE
    assert "cartulary shelfmark" in extract_text(sample)


# ------------------------------------------------------------------ indexing


def test_index_reaches_source_and_search_finds_it(tmp_path: Path):
    root = tree(tmp_path)
    summary = run_json("--root", str(root), "index", str(root))
    assert summary["indexed"] == 4  # auth.py, util.rs, pyproject.toml, README.md
    hits = {h["path"] for h in run_json("--root", str(root), "search", "perspicacious")}
    assert hits == {"pkg/auth.py", "pkg/util.rs", "pyproject.toml", "README.md"}


def test_gitignored_dirs_are_not_indexed(tmp_path: Path):
    root = tree(tmp_path)
    run_json("--root", str(root), "index", str(root))
    hits = {h["path"] for h in run_json("--root", str(root), "search", "perspicacious")}
    assert not any(h.startswith(("build/", "node_modules/")) for h in hits)


def test_no_gitignore_opts_back_in(tmp_path: Path):
    root = tree(tmp_path)
    summary = run_json("--root", str(root), "index", str(root), "--no-gitignore")
    assert summary["indexed"] == 6  # the four above plus the two ignored files
    hits = {h["path"] for h in run_json("--root", str(root), "search", "perspicacious")}
    assert "build/generated.py" in hits and "node_modules/leftpad/index.js" in hits


def test_gitignore_negation_re_includes_a_file(tmp_path: Path):
    """`!pattern` re-includes a file its own rule excluded."""
    root = tree(tmp_path)
    (root / "pkg" / "vendor.py").write_text("VENDOR = 'perspicacious'\n")
    (root / ".gitignore").write_text("build/\nnode_modules/\n*.py\n!pkg/vendor.py\n")
    run_json("--root", str(root), "index", str(root))
    hits = {h["path"] for h in run_json("--root", str(root), "search", "perspicacious")}
    assert "pkg/vendor.py" in hits
    assert "pkg/auth.py" not in hits  # still excluded by *.py


def test_negation_cannot_escape_an_excluded_directory(tmp_path: Path):
    """Matches git: a file under an excluded directory cannot be re-included.

    Verified against `git check-ignore -v`, which reports build/generated.py as
    ignored by the `build/` rule even with `!build/generated.py` present.
    """
    root = tree(tmp_path)
    (root / ".gitignore").write_text("build/\nnode_modules/\n!build/generated.py\n")
    run_json("--root", str(root), "index", str(root))
    hits = {h["path"] for h in run_json("--root", str(root), "search", "perspicacious")}
    assert "build/generated.py" not in hits


def test_no_source_indexes_documents_only(tmp_path: Path):
    root = tree(tmp_path)
    summary = run_json("--root", str(root), "index", str(root), "--no-source")
    assert summary["indexed"] == 1  # README.md only
    hits = {h["path"] for h in run_json("--root", str(root), "search", "perspicacious")}
    assert hits == {"README.md"}


def test_search_type_code_filters(tmp_path: Path):
    root = tree(tmp_path)
    run_json("--root", str(root), "index", str(root))
    hits = {
        h["path"]
        for h in run_json("--root", str(root), "search", "perspicacious", "--type", "code")
    }
    assert hits == {"pkg/auth.py", "pkg/util.rs", "pyproject.toml"}
    assert "README.md" not in hits


def test_indexed_type_round_trips_through_filetype(tmp_path: Path):
    """desk/app.py does FileType(info["type"]) — the stored value must be a member."""
    root = tree(tmp_path)
    run_json("--root", str(root), "index", str(root))
    with DeskDB(root) as db:
        row = db.get_file(root / "pkg" / "auth.py")
        assert row is not None
        assert FileType(row["type"]) is FileType.CODE


def test_update_mode_indexes_a_source_file(tmp_path: Path):
    """The carrel-agent PostToolUse hook path: reindex one file Claude wrote."""
    root = tree(tmp_path)
    run_json("--root", str(root), "index", str(root))
    target = root / "pkg" / "auth.py"
    target.write_text("def login():\n    return 'grandiloquent token'\n")
    summary = run_json("--root", str(root), "index", "--update", str(target))
    assert summary["indexed"] == 1 and summary["skipped"] == 0
    hits = [h["path"] for h in run_json("--root", str(root), "search", "grandiloquent")]
    assert hits == ["pkg/auth.py"]


# ------------------------------------------------------------------ pack --query


def test_pack_query_ranks_a_source_file(tmp_path: Path):
    """The inverse of the old cookbook assertion: a .py hit is now packable."""
    root = tree(tmp_path)
    run_json("--root", str(root), "index", str(root))
    obj = run_json("--root", str(root), "pack", str(root), "--query", "perspicacious", "--top", "2")
    packed = [f["path"] for f in obj["files"]]
    assert packed, "query returned no files"
    assert any(p.endswith((".py", ".rs", ".toml")) for p in packed)


# ------------------------------------------------- cross-platform path keys
# `rel()` resolves against the real filesystem, so a Windows path cannot be
# constructed here; these pin the POSIX output that `.as_posix()` guarantees on
# every platform. `files.path` feeds export_catalog, so a native separator would
# make a catalog written on Windows unimportable on Linux.


def test_db_rel_returns_forward_slashes(tmp_path: Path):
    root = tmp_path / "desk"
    (root / "sub").mkdir(parents=True)
    target = root / "sub" / "deep.txt"
    target.write_text("x\n")
    with DeskDB(root) as db:
        assert db.rel(target) == "sub/deep.txt"


def test_manifest_entry_path_returns_forward_slashes(tmp_path: Path):
    base = tmp_path / "docs"
    (base / "inner").mkdir(parents=True)
    target = base / "inner" / "a.txt"
    target.write_text("x\n")
    assert _manifest_entry_path(target, base) == "inner/a.txt"


# ------------------------------------------------------------------ diff


def test_diff_auto_mode_handles_two_source_files(tmp_path: Path):
    """A source file is text-like: auto mode must text-diff it, not exit 4."""
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("def hello():\n    return 'world'\n")
    b.write_text("def hello():\n    return 'there'\n")
    result = run("diff", str(a), str(b), expect=1)  # exit 1 = inputs differ
    assert "there" in result.output or "world" in result.output


def test_diff_identical_source_files_exits_0(tmp_path: Path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    for f in (a, b):
        f.write_text("SAME = 1\n")
    run("diff", str(a), str(b), expect=0)
