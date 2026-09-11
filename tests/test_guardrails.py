"""Spec 29 — `--apply` refuses to rewrite a git work tree.

On 2026-09-10 a `carrel rename --apply` aimed at carrel's own checkout renamed
21 tracked files after the "fields" it read out of their source. The command did
exactly what it was told and the outcome was still wrong, because in a work tree
the names *are* content: imports, test collection, CI config and the history all
address files by path.

`rename --apply`, `organize --apply` and `intake --apply` now refuse a
**directory** inside a work tree (exit 2) unless `--force` is given. Explicitly
named files and the dry-run default are deliberately untouched.

Work trees are made here by creating a plain `.git` directory, so the outcome
does not depend on the `git` binary being installed and is identical on Windows;
one test uses a real `git init` behind `@needs("git")` to prove the adapter path
agrees with the fallback walk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.core.fsops import repo_root

# ------------------------------------------------------------------ helpers


def run(*args: str, expect: int = 0):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == expect, (
        f"exit {result.exit_code} != {expect}\nstdout: {result.output}\nexc: {result.exception!r}"
    )
    return result


def listing(directory: Path) -> set[str]:
    """Every path under `directory`, relative and POSIX — a before/after fingerprint."""
    return {p.relative_to(directory).as_posix() for p in directory.rglob("*")}


def make_worktree(base: Path) -> Path:
    """A directory that is a git work tree as far as the guard is concerned."""
    (base / ".git").mkdir(parents=True, exist_ok=True)
    return base


def loose_files(directory: Path) -> Path:
    """Three organizable files of three different type categories."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "notes.txt").write_text("hello\n", encoding="utf-8")
    (directory / "report.md").write_text("# title\n", encoding="utf-8")
    (directory / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
    return directory


# ------------------------------------------------------------------ repo_root


def test_repo_root_is_none_outside_any_work_tree(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo_root(plain) is None


def test_repo_root_finds_the_top_from_a_nested_directory(tmp_path: Path) -> None:
    top = make_worktree(tmp_path / "repo")
    nested = top / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert repo_root(nested) == top.resolve()


def test_repo_root_judges_a_path_that_does_not_exist_yet(tmp_path: Path) -> None:
    """`intake --to repo/filed/2026` is judged by where it would be created."""
    top = make_worktree(tmp_path / "repo")
    assert repo_root(top / "filed" / "2026" / "01") == top.resolve()


def test_repo_root_falls_back_to_the_ancestor_walk_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale CARREL_BIN_GIT counts as missing (D-008); the walk still guards."""
    monkeypatch.setenv("CARREL_BIN_GIT", str(tmp_path / "no-such-git"))
    top = make_worktree(tmp_path / "repo")
    nested = top / "deep"
    nested.mkdir()
    assert repo_root(nested) == top.resolve()
    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo_root(plain) is None


@needs("git")
def test_repo_root_agrees_with_a_real_git_init(tmp_path: Path) -> None:
    from carrel.core import adapters

    top = tmp_path / "real"
    top.mkdir()
    assert adapters.run("git", "-C", str(top), "init", "-q").returncode == 0
    nested = top / "src"
    nested.mkdir()
    assert repo_root(nested) == top.resolve()


# ------------------------------------------------------------------ organize


def test_organize_apply_refuses_inside_a_work_tree_and_moves_nothing(tmp_path: Path) -> None:
    repo = make_worktree(tmp_path / "repo")
    before = listing(loose_files(repo))

    result = run("organize", str(repo), "--apply", expect=2)

    assert "git work tree" in result.output
    assert str(repo.resolve()) in result.output
    assert "--force" in result.output
    assert listing(repo) == before, "a refused run must leave the directory untouched"


def test_organize_apply_proceeds_with_force(tmp_path: Path) -> None:
    repo = make_worktree(tmp_path / "repo")
    loose_files(repo)

    run("organize", str(repo), "--apply", "--force")

    assert (repo / "docs" / "notes.txt").is_file()
    assert (repo / "data" / "data.json").is_file()
    assert not (repo / "notes.txt").exists()


def test_organize_apply_is_unaffected_outside_a_work_tree(tmp_path: Path) -> None:
    plain = loose_files(tmp_path / "plain")

    run("organize", str(plain), "--apply")

    assert (plain / "docs" / "report.md").is_file()


def test_organize_dry_run_still_prints_its_plan_inside_a_work_tree(tmp_path: Path) -> None:
    repo = make_worktree(tmp_path / "repo")
    before = listing(loose_files(repo))

    result = run("--json", "organize", str(repo))

    plan = json.loads(result.output)
    assert [e["action"] for e in plan].count("move") == 3
    assert listing(repo) == before


def test_organize_apply_is_guarded_from_a_nested_directory(tmp_path: Path) -> None:
    """The message names the repository root, not the directory that was passed."""
    repo = make_worktree(tmp_path / "repo")
    nested = loose_files(repo / "a" / "b")

    result = run("organize", str(nested), "--apply", expect=2)

    assert str(repo.resolve()) in result.output
    assert listing(nested) == {"notes.txt", "report.md", "data.json"}


# ------------------------------------------------------------------ rename


def test_rename_apply_refuses_a_directory_inside_a_work_tree(tmp_path: Path) -> None:
    repo = make_worktree(tmp_path / "repo")
    loose_files(repo)
    before = listing(repo)

    result = run("rename", str(repo), "--apply", "--template", "{sha8}{ext}", expect=2)

    assert "git work tree" in result.output
    assert listing(repo) == before


def test_rename_apply_allows_an_explicitly_named_file_inside_a_work_tree(tmp_path: Path) -> None:
    """Naming a file is already a decision at the granularity of the damage."""
    repo = make_worktree(tmp_path / "repo")
    loose_files(repo)

    result = run("--json", "rename", str(repo / "notes.txt"), "--apply", "--template", "x{ext}")

    plan = json.loads(result.output)
    assert [e["action"] for e in plan] == ["renamed"]
    assert (repo / "x.txt").is_file()
    assert not (repo / "notes.txt").exists()


def test_rename_dry_run_still_plans_inside_a_work_tree(tmp_path: Path) -> None:
    repo = make_worktree(tmp_path / "repo")
    before = listing(loose_files(repo))

    result = run("--json", "rename", str(repo), "--template", "{sha8}{ext}")

    assert [e["action"] for e in json.loads(result.output)] == ["rename"] * 3
    assert listing(repo) == before


def test_rename_apply_proceeds_with_force(tmp_path: Path) -> None:
    repo = make_worktree(tmp_path / "repo")
    loose_files(repo)

    result = run("--json", "rename", str(repo), "--apply", "--force", "--template", "r_{stem}{ext}")

    assert [e["action"] for e in json.loads(result.output)] == ["renamed"] * 3
    assert (repo / "r_notes.txt").is_file()


# ------------------------------------------------------------------ intake


def test_intake_apply_refuses_when_the_inbox_is_in_a_work_tree(tmp_path: Path) -> None:
    inbox = loose_files(make_worktree(tmp_path / "repo") / "inbox")
    dest = tmp_path / "filed"
    before = listing(inbox)

    result = run("intake", str(inbox), "--to", str(dest), "--apply", expect=2)

    assert "git work tree" in result.output
    assert listing(inbox) == before


def test_intake_apply_refuses_when_the_destination_is_in_a_work_tree(tmp_path: Path) -> None:
    inbox = loose_files(tmp_path / "inbox")
    dest = make_worktree(tmp_path / "repo") / "filed"
    before = listing(inbox)

    result = run("intake", str(inbox), "--to", str(dest), "--apply", expect=2)

    assert "git work tree" in result.output
    assert listing(inbox) == before
    assert not dest.exists(), "a refused run must not create --to"


def test_intake_apply_is_unaffected_outside_a_work_tree(tmp_path: Path) -> None:
    inbox = loose_files(tmp_path / "inbox")
    dest = tmp_path / "filed"

    result = run(
        "--json",
        "intake",
        str(inbox),
        "--to",
        str(dest),
        "--apply",
        "--no-refs",
        "--no-index",
        "--fallback",
        "unknown",
    )

    assert any(r["action"] == "filed" for r in json.loads(result.output))


def test_intake_apply_proceeds_with_force(tmp_path: Path) -> None:
    inbox = loose_files(make_worktree(tmp_path / "repo") / "inbox")
    dest = tmp_path / "filed"

    result = run(
        "--json",
        "intake",
        str(inbox),
        "--to",
        str(dest),
        "--apply",
        "--force",
        "--no-refs",
        "--no-index",
        "--fallback",
        "unknown",
    )

    assert any(r["action"] == "filed" for r in json.loads(result.output))


def test_intake_dry_run_still_plans_inside_a_work_tree(tmp_path: Path) -> None:
    inbox = loose_files(make_worktree(tmp_path / "repo") / "inbox")
    dest = tmp_path / "filed"
    before = listing(inbox)

    result = run(
        "--json",
        "intake",
        str(inbox),
        "--to",
        str(dest),
        "--no-refs",
        "--no-index",
        "--fallback",
        "unknown",
    )

    assert any(r["action"] == "plan" for r in json.loads(result.output))
    assert listing(inbox) == before
    assert not dest.exists()
