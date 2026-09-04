"""Tests for `carrel pack` (spec 05).

Self-contained: builds its own tmp trees (no conftest helpers, no
tests/fixtures/ dependency — those are built concurrently in wave 1).
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs
from PIL import Image

from carrel.cli import cli
from carrel.commands import pack as pack_mod
from carrel.commands.pack import PackResult, estimate_tokens, pack_paths
from carrel.core import adapters
from carrel.core.output import CarrelInputError

A_TXT = "hello world alpha beta\n" * 5
NOTES_TXT = "note line here\n" * 3
README_MD = "# Title\n\nInline ```code``` fence collision.\n"


@pytest.fixture()
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    (root / "sub").mkdir()
    (root / "build").mkdir()
    (root / "a.txt").write_text(A_TXT)
    (root / "docs" / "readme.md").write_text(README_MD)
    (root / "data.json").write_text('{"k": "v"}')
    (root / "sub" / "notes.txt").write_text(NOTES_TXT)
    (root / "ignored.log").write_text("secret log\n")
    (root / "build" / "artifact.txt").write_text("built artifact\n")
    (root / ".gitignore").write_text("*.log\nbuild/\n!keep.log\n")
    Image.new("RGB", (4, 4), "red").save(root / "pic.png")
    return root


def run(*args: str) -> CliRunner.Result:
    return CliRunner().invoke(cli, list(args))


# --------------------------------------------------------------------- md


def test_md_default_contains_tree_and_every_text_file(proj: Path):
    res = run("pack", str(proj))
    assert res.exit_code == 0, res.output
    out = res.output
    # header block
    assert "generated-by: carrel" in out
    assert "root:" in out and "tokens_est:" in out
    # tree present with the root label
    assert "## Tree" in out and "proj/" in out
    assert "├──" in out or "└──" in out
    # every text fixture inlined
    assert "hello world alpha beta" in out  # a.txt
    assert "Inline" in out  # docs/readme.md
    assert "note line here" in out  # sub/notes.txt
    assert "k: v" in out  # data.json via textextract


def test_md_fence_collision_lengthens_fence(proj: Path):
    res = run("pack", str(proj))
    assert "````markdown" in res.output  # readme.md contains ``` -> 4-tick fence


def test_tree_dirs_first_alphabetical(proj: Path):
    res = run("pack", str(proj), "--tree-only")
    lines = res.output.splitlines()
    idx = {
        name: next(i for i, ln in enumerate(lines) if name in ln)
        for name in ("docs/", "sub/", "a.txt", "data.json")
    }
    assert idx["docs/"] < idx["sub/"] < idx["a.txt"] < idx["data.json"]


# ------------------------------------------------------ filters / ignores


def test_gitignore_honored(proj: Path):
    out = run("pack", str(proj)).output
    assert "ignored.log" not in out and "secret log" not in out
    assert "artifact.txt" not in out and "built artifact" not in out


def test_no_gitignore_flag(proj: Path):
    out = run("pack", str(proj), "--no-gitignore").output
    assert "secret log" in out
    assert "built artifact" in out


def test_exclude_glob(proj: Path):
    out = run("pack", str(proj), "--exclude", "*.json", "--exclude", "sub").output
    assert "data.json" not in out
    assert "notes.txt" not in out and "note line here" not in out
    assert "hello world alpha beta" in out


def test_include_glob(proj: Path):
    out = run("pack", str(proj), "--include", "*.txt").output
    assert "hello world alpha beta" in out
    assert "readme.md" not in out and "data.json" not in out


def test_binary_image_listed_not_inlined(proj: Path):
    out = run("pack", str(proj)).output
    assert "pic.png" in out
    assert "[skipped: binary]" in out
    assert "(" in out.split("pic.png", 1)[1].splitlines()[0]  # size annotation
    # not a file section
    assert "### `pic.png`" not in out


# ----------------------------------------------------------------- formats


def test_xml_parses_with_cdata_intact(proj: Path):
    res = run("pack", str(proj), "--format", "xml")
    assert res.exit_code == 0, res.output
    root = ET.fromstring(res.output)
    assert root.tag == "context"
    assert root.find("tree") is not None and "proj/" in root.find("tree").text
    files = {f.get("path"): f.text for f in root.findall("file")}
    assert files["a.txt"] == A_TXT
    assert files["docs/readme.md"] == README_MD  # backticks survive CDATA
    assert "pic.png" not in files
    assert int(root.get("files")) == len(files)


def test_json_format_structure_and_tokens(proj: Path):
    res = run("pack", str(proj), "--format", "json")
    obj = json.loads(res.output)
    assert set(obj) == {"meta", "tree", "files"}
    # 5 = a.txt, docs/readme.md, data.json, sub/notes.txt, .gitignore (text too)
    assert obj["meta"]["files_included"] == len(obj["files"]) == 5
    assert obj["meta"]["tokens_est"] > 0
    for f in obj["files"]:
        assert set(f) >= {"path", "tokens_est", "content"}
        assert f["tokens_est"] > 0
    by_path = {f["path"]: f for f in obj["files"]}
    assert by_path["a.txt"]["content"] == A_TXT
    assert by_path["a.txt"]["tokens_est"] == estimate_tokens(A_TXT)


def test_global_json_flag_emits_json_pack(proj: Path):
    res = run("--json", "pack", str(proj))
    obj = json.loads(res.output)
    assert obj["meta"]["files_included"] == 5


# ---------------------------------------------------------------- tree-only


def test_tree_only_has_no_contents(proj: Path):
    for extra in ([], ["--format", "xml"], ["--format", "json"]):
        res = run("pack", str(proj), "--tree-only", *extra)
        assert res.exit_code == 0
        assert "a.txt" in res.output  # listed in tree
        assert "hello world alpha beta" not in res.output
        assert "note line here" not in res.output
    obj = json.loads(run("pack", str(proj), "--tree-only", "--format", "json").output)
    assert obj["files"] == []


# ------------------------------------------------------------------ budgets


def test_max_file_bytes_skips_large_file(proj: Path):
    limit = len(NOTES_TXT) + 1  # a.txt is bigger, notes.txt fits
    out = run("pack", str(proj), "--max-file-bytes", str(limit)).output
    assert "note line here" in out
    assert "hello world alpha beta" not in out
    assert "[skipped: exceeds --max-file-bytes]" in out


def test_max_bytes_stops_adding_and_notes_omissions(proj: Path):
    readme_size = len(README_MD)
    res = pack_paths([proj], max_bytes=readme_size + 1)
    assert res.meta["files_included"] == 1  # walk order: docs/readme.md first
    assert res.meta["omitted_budget"]  # everything after is omitted
    assert "omitted over --max-bytes budget" in res.document
    assert "hello world alpha beta" not in res.document


# ----------------------------------------------------------------- chunking


def test_chunk_requires_output(proj: Path):
    res = run("pack", str(proj), "--chunk", "100")
    assert res.exit_code == 2


def test_chunking_parts_within_budget(proj: Path, tmp_path: Path):
    big = proj / "big.txt"
    big.write_text(("x" * 60 + "\n") * 200)  # ~3.4k tokens alone
    budget = 500
    out = tmp_path / "pack.md"
    res = run("pack", str(proj), "-o", str(out), "--chunk", str(budget))
    assert res.exit_code == 0, res.output
    parts = sorted(tmp_path.glob("pack.md.part*"), key=lambda p: int(p.name.rsplit("part", 1)[1]))
    assert len(parts) >= 2
    assert not out.exists()  # only OUT.partN files
    joined = ""
    for p in parts:
        text = p.read_text()
        assert estimate_tokens(text) <= budget
        assert "generated-by: carrel" in text  # same header in every part
        joined += text
    # big file was split on line boundaries with (continued) markers
    assert "(continued)" in joined
    assert joined.count("x" * 60) == 200  # no content lost
    assert "hello world alpha beta" in joined
    # tree only in part 1
    assert "## Tree" in parts[0].read_text()
    assert "## Tree" not in parts[1].read_text()


def test_chunk_small_file_not_split(proj: Path, tmp_path: Path):
    out = tmp_path / "p.xml"
    res = run("pack", str(proj / "a.txt"), "-o", str(out), "--chunk", "5000", "--format", "xml")
    assert res.exit_code == 0, res.output
    part1 = tmp_path / "p.xml.part1"
    assert part1.exists()
    root = ET.fromstring(part1.read_text())
    assert [f.get("continued") for f in root.findall("file")] == [None]


# -------------------------------------------------------------------- stats


def test_stats_json(proj: Path):
    res = run("--json", "pack", str(proj), "--stats")
    obj = json.loads(res.output)
    assert {"files", "totals"} <= set(obj)
    assert obj["totals"]["included"] == 5
    assert obj["totals"]["tokens_est"] > 0
    skipped = [f for f in obj["files"] if f["skipped"]]
    assert any(f["path"] == "pic.png" for f in skipped)


def test_stats_human_table(proj: Path):
    res = run("pack", str(proj), "--stats")
    assert res.exit_code == 0
    assert "pack stats" in res.output
    assert "TOTAL" in res.output


# ------------------------------------------------------------ misc / library


def test_single_file_argument(proj: Path):
    res = run("pack", str(proj / "a.txt"))
    assert res.exit_code == 0
    assert "hello world alpha beta" in res.output
    assert "readme.md" not in res.output


def test_output_file_written(proj: Path, tmp_path: Path):
    out = tmp_path / "ctx.md"
    res = run("pack", str(proj), "-o", str(out))
    assert res.exit_code == 0
    assert "hello world alpha beta" in out.read_text()


def test_unknown_extension_text_is_packed(proj: Path):
    (proj / "script.py").write_text("print('from python')\n")
    out = run("pack", str(proj)).output
    assert "from python" in out
    assert "```python" in out


def test_pack_paths_library_api(proj: Path):
    res = pack_paths([proj], fmt="md")
    assert isinstance(res, PackResult)
    assert res.document == res.documents[0]
    assert len(res.files) == 5
    assert res.meta["tokens_est"] == sum(e.tokens_est for e in res.files)
    with pytest.raises(CarrelInputError):
        pack_paths([proj / "missing.txt"])
    with pytest.raises(CarrelInputError):
        pack_paths([proj], fmt="yaml")


def test_estimate_tokens_formula():
    assert estimate_tokens("") == 0
    assert estimate_tokens("x" * 36) == 10  # ceil(36 / 3.6)
    assert estimate_tokens("x") == 1


def test_help_documents_gitignore_limits(proj: Path):
    res = run("pack", "--help")
    assert res.exit_code == 0
    assert "negation" in res.output.lower()
    assert "--chunk" in res.output and "--tree-only" in res.output


# ===================================================================== v2
# spec 16: --query, --since/--changed, .gitignore negation,
# --dedupe-content, --tokenizer exact, --outline

REPO_ROOT = Path(__file__).resolve().parents[1]


def _meta_and_files(res: CliRunner.Result) -> tuple[dict, list[dict]]:
    assert res.exit_code == 0, res.output
    obj = json.loads(res.output)
    return obj["meta"], obj["files"]


# ------------------------------------------------------------------ --query


@pytest.fixture()
def indexed(tmp_path: Path) -> Path:
    """Six text files, three of which contain the word 'sentinel' (with
    different densities so bm25 ranks them distinctly), plus an FTS index."""
    root = tmp_path / "desk"
    (root / "sub").mkdir(parents=True)
    (root / "dense.txt").write_text("sentinel sentinel sentinel\n")
    (root / "sub" / "sparse.txt").write_text("the sentinel stands guard " + "filler words " * 40)
    (root / "medium.md").write_text("# Notes\n\nA sentinel and another sentinel here.\n")
    (root / "plain1.txt").write_text("nothing to see here\n")
    (root / "plain2.txt").write_text("still nothing relevant\n")
    (root / "plain3.txt").write_text("lorem ipsum dolor\n")
    res = run("--root", str(root), "index", str(root))
    assert res.exit_code == 0, res.output
    return root


def test_query_returns_only_hits_in_relevance_order(indexed: Path):
    res = run("--root", str(indexed), "pack", str(indexed), "--query", "sentinel", "--json")
    meta, files = _meta_and_files(res)
    paths = [f["path"] for f in files]
    assert set(paths) == {"dense.txt", "sub/sparse.txt", "medium.md"}
    assert not any(p.startswith("plain") for p in paths)
    scores = [f["score"] for f in files]
    assert scores == sorted(scores), "files must be emitted in bm25 order (lower = better)"
    assert paths[0] == "dense.txt"  # densest match ranks first
    assert meta["query"] == "sentinel" and meta["top"] == 20 and meta["hits"] == 3
    assert meta["files_included"] == 3
    # the header also carries the query
    md = run("--root", str(indexed), "pack", str(indexed), "--query", "sentinel").output
    assert "query: 'sentinel' (top 20, 3 hit(s))" in md
    assert "[score " in md  # per-file score in the tree
    assert "nothing to see here" not in md


def test_query_top_limits_hits(indexed: Path):
    res = run(
        "--root", str(indexed), "pack", str(indexed), "--query", "sentinel", "--top", "1", "--json"
    )
    meta, files = _meta_and_files(res)
    assert [f["path"] for f in files] == ["dense.txt"]
    assert meta["top"] == 1 and meta["hits"] == 1


def test_query_respects_other_filters(indexed: Path):
    res = run(
        "--root",
        str(indexed),
        "pack",
        str(indexed),
        "--query",
        "sentinel",
        "--exclude",
        "*.md",
        "--json",
    )
    _, files = _meta_and_files(res)
    assert "medium.md" not in {f["path"] for f in files}
    # PATH narrower than the desk root: only hits under it
    res = run("--root", str(indexed), "pack", str(indexed / "sub"), "--query", "sentinel", "--json")
    _, files = _meta_and_files(res)
    assert [f["path"] for f in files] == ["sparse.txt"]


def test_query_zero_hits_header_and_fail_empty(indexed: Path):
    res = run("--root", str(indexed), "pack", str(indexed), "--query", "zzzqqq")
    assert res.exit_code == 0, res.output
    assert "no hits" in res.output
    res = run("--root", str(indexed), "pack", str(indexed), "--query", "zzzqqq", "--fail-empty")
    assert res.exit_code == 5, res.output
    assert "no files matched" in res.output


def test_query_without_index_exits_4(tmp_path: Path):
    (tmp_path / "a.txt").write_text("sentinel\n")
    res = run("--root", str(tmp_path), "pack", str(tmp_path), "--query", "sentinel")
    assert res.exit_code == 4, res.output
    assert "index --root" in res.output  # actionable hint


def test_query_stats_and_library_api(indexed: Path):
    res = run(
        "--root", str(indexed), "pack", str(indexed), "--query", "sentinel", "--stats", "--json"
    )
    assert res.exit_code == 0, res.output
    obj = json.loads(res.output)
    assert obj["totals"]["query"] == "sentinel" and obj["totals"]["hits"] == 3
    assert all("score" in row for row in obj["files"])
    # library: desk_root defaults to the pack root
    result = pack_paths([indexed], query="sentinel", fmt="json")
    assert result.files[0].path == "dense.txt"
    assert result.files[0].score is not None
    with pytest.raises(CarrelInputError):
        pack_paths([indexed], query="sentinel", top=0)


# ------------------------------------------------------- --since / --changed


def _sh_git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True
    )
    return proc.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Commit A: 4 files. Commit B: modifies one, adds one, deletes one."""
    if not adapters.have("git"):
        pytest.skip("requires 'git'")
    r = tmp_path / "repo"
    (r / "pkg").mkdir(parents=True)
    _sh_git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("alpha v1\n")
    (r / "b.txt").write_text("bravo\n")
    (r / "pkg" / "c.py").write_text("x = 1\n")
    (r / "gone.txt").write_text("to be deleted\n")
    _sh_git(r, "add", ".")
    _sh_git(r, "commit", "-q", "-m", "A")
    (r / "a.txt").write_text("alpha v2\n")
    (r / "pkg" / "d.py").write_text("y = 2\n")
    (r / "gone.txt").unlink()
    _sh_git(r, "add", "-A")
    _sh_git(r, "commit", "-q", "-m", "B")
    return r


def test_since_packs_exactly_the_changed_files(repo: Path):
    res = run("pack", str(repo), "--since", "HEAD~1", "--json")
    meta, files = _meta_and_files(res)
    assert {f["path"] for f in files} == {"a.txt", "pkg/d.py"}
    assert "alpha v2" in files[0]["content"] + files[1]["content"]
    assert meta["since"] == "HEAD~1" and meta["changed"] == 2
    assert meta["removed"] == ["gone.txt"]
    assert "untracked" not in meta
    md = run("pack", str(repo), "--since", "HEAD~1").output
    assert "since: HEAD~1 (2 changed, 1 removed)" in md
    assert "removed: gone.txt" in md
    assert "bravo" not in md


def test_since_no_changes_and_fail_empty(repo: Path):
    res = run("pack", str(repo), "--since", "HEAD", "--json")
    meta, files = _meta_and_files(res)
    assert files == [] and meta["changed"] == 0
    res = run("pack", str(repo), "--since", "HEAD", "--fail-empty")
    assert res.exit_code == 5


def test_changed_packs_uncommitted_and_untracked(repo: Path):
    (repo / "b.txt").write_text("bravo edited\n")  # uncommitted modification
    (repo / "pkg" / "new.py").write_text("z = 3\n")  # untracked
    res = run("pack", str(repo), "--changed", "--json")
    meta, files = _meta_and_files(res)
    assert {f["path"] for f in files} == {"b.txt", "pkg/new.py"}
    assert meta["untracked"] is True and meta["since"] == "HEAD" and meta["changed"] == 2
    md = run("pack", str(repo), "--changed").output
    assert "changed: 2 vs HEAD (+ untracked), 0 removed" in md
    # subdirectory PATH intersects with the walk
    res = run("pack", str(repo / "pkg"), "--changed", "--json")
    _, files = _meta_and_files(res)
    assert [f["path"] for f in files] == ["new.py"]


def test_since_and_changed_are_mutually_exclusive(repo: Path):
    res = run("pack", str(repo), "--since", "HEAD", "--changed")
    assert res.exit_code == 2
    assert "mutually exclusive" in res.output
    with pytest.raises(CarrelInputError):
        pack_paths([repo], since="HEAD", changed=True)


def test_since_bad_ref_exits_4_with_git_message(repo: Path):
    res = run("pack", str(repo), "--since", "no-such-ref-xyz")
    assert res.exit_code == 4, res.output
    assert "no-such-ref-xyz" in res.output  # git's own first stderr line


@needs("git")
def test_since_outside_a_repo_exits_4(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x\n")
    res = run("pack", str(tmp_path), "--since", "HEAD")
    assert res.exit_code == 4, res.output
    assert "not a git repository" in res.output.lower()


def test_since_without_git_exits_3(repo: Path, monkeypatch: pytest.MonkeyPatch):
    # the documented override: a set-but-missing CARREL_BIN_GIT counts as missing
    monkeypatch.setenv("CARREL_BIN_GIT", "/nonexistent/git")
    assert not adapters.have("git")
    res = run("pack", str(repo), "--since", "HEAD~1")
    assert res.exit_code == 3, res.output
    assert "'git' is required" in res.output and "apt install git" in res.output


def test_query_and_since_intersect(repo: Path):
    res = run("--root", str(repo), "index", str(repo))
    assert res.exit_code == 0, res.output
    # "alpha" is in a.txt (changed) only; "bravo" in b.txt (unchanged since HEAD~1)
    res = run(
        "--root", str(repo), "pack", str(repo), "--since", "HEAD~1", "--query", "alpha", "--json"
    )
    meta, files = _meta_and_files(res)
    assert [f["path"] for f in files] == ["a.txt"]
    res = run(
        "--root", str(repo), "pack", str(repo), "--since", "HEAD~1", "--query", "bravo", "--json"
    )
    meta, files = _meta_and_files(res)
    assert files == [] and meta["hits"] == 0


# ------------------------------------------------------- .gitignore negation


def test_gitignore_negation_reincludes(tmp_path: Path):
    root = tmp_path / "neg"
    root.mkdir()
    (root / ".gitignore").write_text("*.log\n!keep.log\n")
    (root / "keep.log").write_text("kept\n")
    (root / "other.log").write_text("dropped\n")
    res = run("pack", str(root), "--json")
    _, files = _meta_and_files(res)
    paths = {f["path"] for f in files}
    assert "keep.log" in paths and "other.log" not in paths


def test_gitignore_negation_order_matters(tmp_path: Path):
    root = tmp_path / "neg2"
    root.mkdir()
    (root / ".gitignore").write_text("!keep.log\n*.log\n")  # negation before its rule: no effect
    (root / "keep.log").write_text("kept?\n")
    res = run("pack", str(root), "--json")
    _, files = _meta_and_files(res)
    assert "keep.log" not in {f["path"] for f in files}


def test_gitignore_negation_dir_only_and_nested(tmp_path: Path):
    root = tmp_path / "neg3"
    (root / "build").mkdir(parents=True)
    (root / "sub").mkdir()
    (root / ".gitignore").write_text("build/\n*.tmp\n")
    (root / "build" / "x.txt").write_text("built\n")
    (root / "a.tmp").write_text("tmp a\n")
    (root / "sub" / ".gitignore").write_text("!*.tmp\n")  # inner file overrides the outer rule
    (root / "sub" / "b.tmp").write_text("tmp b\n")
    res = run("pack", str(root), "--json")
    _, files = _meta_and_files(res)
    paths = {f["path"] for f in files}
    assert "build/x.txt" not in paths and "a.tmp" not in paths
    assert "sub/b.tmp" in paths


def test_help_no_longer_claims_negation_unsupported():
    out = run("pack", "--help").output
    assert "not supported" not in out.lower()
    assert "!pattern" in out


# ---------------------------------------------------------- --dedupe-content


def test_dedupe_content_marks_duplicates(proj: Path):
    (proj / "copy.txt").write_text(A_TXT)  # identical to a.txt
    (proj / "sub" / "copy2.txt").write_text(A_TXT)
    res = run("pack", str(proj), "--dedupe-content", "--json")
    meta, files = _meta_and_files(res)
    assert meta["deduped"] == 2
    paths = [f["path"] for f in files]
    # walk order is dirs-first, so sub/copy2.txt is the first copy seen and wins
    assert "sub/copy2.txt" in paths and "a.txt" not in paths and "copy.txt" not in paths
    assert json.loads(res.output)["tree"].count("[same as sub/copy2.txt]") == 2
    md = run("pack", str(proj), "--dedupe-content").output
    assert md.count("hello world alpha beta") == 5  # inlined exactly once
    assert "deduped: 2 identical file(s) not inlined" in md
    # stats carry the same_as field
    st = json.loads(run("pack", str(proj), "--dedupe-content", "--stats", "--json").output)
    dup = next(r for r in st["files"] if r["path"] == "copy.txt")
    assert dup["same_as"] == "sub/copy2.txt" and dup["skipped"] == "same as sub/copy2.txt"
    assert st["totals"]["deduped"] == 2
    # duplicates are detected before the --max-bytes budget check, so they
    # neither consume budget nor get reported as budget omissions
    res = pack_paths([proj], dedupe_content=True, max_bytes=len(README_MD) + len(A_TXT) + 1)
    assert [e.path for e in res.files] == ["docs/readme.md", "sub/copy2.txt"]
    assert res.meta["deduped"] == 2
    assert not {"a.txt", "copy.txt"} & set(res.meta["omitted_budget"])


def test_dedupe_off_by_default(proj: Path):
    (proj / "copy.txt").write_text(A_TXT)
    meta, files = _meta_and_files(run("pack", str(proj), "--json"))
    assert "deduped" not in meta
    assert "copy.txt" in {f["path"] for f in files}


# ---------------------------------------------------------- --tokenizer exact


def test_tokenizer_exact_counts_and_labels(proj: Path):
    pytest.importorskip("tiktoken")
    res = run("pack", str(proj / "a.txt"), "--tokenizer", "exact", "--json")
    meta, files = _meta_and_files(res)
    assert meta["tokenizer"] == "exact (tiktoken o200k_base)"
    assert "tokens" in meta and "tokens_est" not in meta
    assert set(files[0]) >= {"path", "tokens", "content"} and "tokens_est" not in files[0]
    assert files[0]["tokens"] != estimate_tokens(A_TXT)  # a real count, not the heuristic
    assert files[0]["tokens"] == pack_mod.exact_token_counter()(A_TXT)
    md = run("pack", str(proj / "a.txt"), "--tokenizer", "exact").output
    assert "tokenizer: exact (tiktoken o200k_base)" in md and "- tokens:" in md
    assert "tokens_est" not in md
    xml = run("pack", str(proj / "a.txt"), "--tokenizer", "exact", "--format", "xml").output
    root = ET.fromstring(xml)
    assert root.get("tokens") == str(files[0]["tokens"]) and root.get("tokens-est") is None
    assert root.find("file").get("tokens") == str(files[0]["tokens"])
    st = json.loads(
        run("pack", str(proj / "a.txt"), "--tokenizer", "exact", "--stats", "--json").output
    )
    assert st["totals"]["tokens"] == files[0]["tokens"] and "tokens_est" not in st["totals"]


def test_tokenizer_heuristic_is_default_and_unchanged(proj: Path):
    a = run("pack", str(proj), "--json").output
    b = run("pack", str(proj), "--tokenizer", "heuristic", "--json").output
    assert a == b
    assert "tokenizer" not in json.loads(a)["meta"]


def test_tokenizer_exact_missing_exits_3(proj: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # makes `import tiktoken` raise ImportError
    res = run("pack", str(proj), "--tokenizer", "exact")
    assert res.exit_code == 3, res.output
    assert "tiktoken" in res.output
    assert "uv tool install 'carrel[tokens]'" in res.output
    with pytest.raises(adapters.MissingDependencyError):
        pack_paths([proj], tokenizer="exact")


def test_chunk_budget_uses_exact_tokenizer(proj: Path, tmp_path: Path):
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.get_encoding("o200k_base")
    big = proj / "big.txt"
    big.write_text(("lorem ipsum dolor sit amet " * 3 + "\n") * 120)
    out = tmp_path / "pack.md"
    budget = 400
    res = run("pack", str(proj), "-o", str(out), "--chunk", str(budget), "--tokenizer", "exact")
    assert res.exit_code == 0, res.output
    parts = sorted(tmp_path.glob("pack.md.part*"), key=lambda p: int(p.name.rsplit("part", 1)[1]))
    assert len(parts) >= 2
    for p in parts:
        assert len(enc.encode(p.read_text())) <= budget
        assert "tokenizer: exact" in p.read_text()


# ------------------------------------------------------------------ --outline


def test_outline_python_lists_defs_and_classes():
    cli_py = REPO_ROOT / "src" / "carrel" / "cli.py"
    res = run("pack", str(cli_py), "--outline", "--json")
    meta, files = _meta_and_files(res)
    assert meta["outline"] is True and meta["tree_only"] is True
    assert len(files) == 1 and files[0]["path"] == "cli.py"
    outline = files[0]["outline"]
    assert any(re.fullmatch(r"L\d+ class LazyGroup", item) for item in outline), outline
    assert any(re.fullmatch(r"L\d+ def main", item) for item in outline), outline
    assert "content" not in files[0]
    md = run("pack", str(cli_py), "--outline").output
    assert "class LazyGroup" in md and "def main" in md
    assert "outline: structure only" in md
    assert "import click" not in md  # no contents


def test_outline_markdown_headings_and_size_only(proj: Path):
    (proj / "docs" / "guide.md").write_text(
        "# Guide\n\n```md\n# not a heading (fenced)\n```\n\n## Install\n\ntext\n\n### Step 1\n"
    )
    (proj / "bad.py").write_text("def broken(:\n")
    res = run("pack", str(proj), "--outline", "--json")
    _, files = _meta_and_files(res)
    by = {f["path"]: f for f in files}
    assert by["docs/guide.md"]["outline"] == ["L1 # Guide", "L7 ## Install", "L11 ### Step 1"]
    assert by["bad.py"]["outline"] == ["[unparsable]"]
    assert by["a.txt"]["outline"] == [] and by["a.txt"]["bytes"] == len(A_TXT)
    md = run("pack", str(proj), "--outline").output
    assert "L1 # Guide" in md and "[unparsable]" in md
    assert re.search(r"a\.txt\s+\(\d+ B\)", md)  # other types: size only
    assert "hello world alpha beta" not in md
    xml = run("pack", str(proj), "--outline", "--format", "xml").output
    root = ET.fromstring(xml)
    assert root.get("outline") == "true" and "L1 # Guide" in root.find("tree").text
    assert root.findall("file") == []


def test_outline_incompatible_with_chunk(proj: Path, tmp_path: Path):
    res = run("pack", str(proj), "--outline", "--chunk", "100", "-o", str(tmp_path / "o.md"))
    assert res.exit_code == 2
    assert "--outline cannot be combined with --chunk" in res.output
    with pytest.raises(CarrelInputError):
        pack_paths([proj], outline=True, chunk=100)


# ------------------------------------------------ v1 compatibility guarantees


def test_pack_paths_defaults_keep_v1_signature_behavior(proj: Path):
    """New parameters are keyword-only with defaults; positional v1 calls are untouched."""
    sig = inspect.signature(pack_paths)
    new = (
        "query",
        "top",
        "desk_root",
        "since",
        "changed",
        "dedupe_content",
        "tokenizer",
        "outline",
    )
    for name in new:
        p = sig.parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is not inspect.Parameter.empty
    res = pack_paths([proj])
    assert set(res.meta) == {
        "generated_by",
        "root",
        "files_included",
        "files_skipped",
        "bytes",
        "tokens_est",
    }
    obj = json.loads(pack_paths([proj], fmt="json").document)
    assert all(set(f) == {"path", "tokens_est", "content"} for f in obj["files"])
