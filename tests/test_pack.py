"""Tests for `carrel pack` (spec 05).

Self-contained: builds its own tmp trees (no conftest helpers, no
tests/fixtures/ dependency — those are built concurrently in wave 1).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from carrel.cli import cli
from carrel.commands.pack import PackResult, estimate_tokens, pack_paths
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
