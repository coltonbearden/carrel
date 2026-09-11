"""Spec 29 — a bulk move refuses to rename files git is tracking.

On 2026-09-10 a `carrel rename --apply` aimed at carrel's own checkout renamed
21 tracked files after the "fields" it read out of their source. The command did
exactly what it was told and the outcome was still wrong, because in a work tree
tracked names are content: imports, test collection, CI config and the history
all address files by path.

The guard asks "would this move files git is tracking?", not "is this inside a
repository". The distinction matters: `~/Downloads` under a dotfiles repo is a
mainstream layout, and refusing there would leave the user no way out but
`--force` — the exact habit this guard exists to stop forming.

Repositories here are real (`git init` + `git add`) behind `@needs("git")`,
because the question the guard asks can only be answered by git. The one path
that does not need git — the conservative fallback when the binary is absent —
is exercised with a stale `CARREL_BIN_GIT`, which counts as missing (D-008).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.core import adapters
from carrel.core.fsops import repo_root, would_move_tracked

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


def git(root: Path, *args: str) -> None:
    proc = adapters.run("git", "-C", str(root), *args)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"


def make_repo(base: Path) -> Path:
    """A real repository with an identity, so `git commit` works unattended."""
    base.mkdir(parents=True, exist_ok=True)
    git(base, "init", "-q")
    git(base, "config", "user.email", "test@example.invalid")
    git(base, "config", "user.name", "carrel tests")
    return base


def fake_repo(base: Path) -> Path:
    """A directory that only *looks* like a work tree — for the no-git fallback."""
    (base / ".git").mkdir(parents=True, exist_ok=True)
    return base


def docs(directory: Path) -> Path:
    """Three organizable files of three different type categories."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "notes.txt").write_text("hello\n", encoding="utf-8")
    (directory / "report.md").write_text("# title\n", encoding="utf-8")
    (directory / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
    return directory


def commit_all(root: Path) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", "tracked")


# ------------------------------------------------------------------ repo_root


def test_repo_root_is_none_outside_any_work_tree(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo_root(plain) is None


@needs("git")
def test_repo_root_finds_the_top_from_a_nested_directory(tmp_path: Path) -> None:
    top = make_repo(tmp_path / "repo")
    nested = top / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert repo_root(nested) == top.resolve()


@needs("git")
def test_repo_root_judges_a_path_that_does_not_exist_yet(tmp_path: Path) -> None:
    """`intake --to repo/filed/2026` is judged by where it would be created."""
    top = make_repo(tmp_path / "repo")
    assert repo_root(top / "filed" / "2026" / "01") == top.resolve()


def test_repo_root_falls_back_to_the_ancestor_walk_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale CARREL_BIN_GIT counts as missing (D-008); the walk still finds the root."""
    monkeypatch.setenv("CARREL_BIN_GIT", str(tmp_path / "no-such-git"))
    top = fake_repo(tmp_path / "repo")
    nested = top / "deep"
    nested.mkdir()
    assert repo_root(nested) == top.resolve()

    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo_root(plain) is None


@needs("git")
def test_repo_root_honours_a_ceiling_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git's answer is trusted in both directions, not only when it says yes."""
    top = make_repo(tmp_path / "repo")
    nested = top / "deep"
    nested.mkdir()
    assert repo_root(nested) == top.resolve()

    # the walk refuses to enter a ceiling directory, so the repo is never found
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(top.resolve()))
    assert repo_root(nested) is None


@needs("git")
def test_repo_root_trusts_git_rejecting_a_malformed_dot_git(tmp_path: Path) -> None:
    """A `.git` file git calls invalid is git's call to make, not a lookalike to guard."""
    fake = tmp_path / "fake" / "sub"
    fake.mkdir(parents=True)
    (tmp_path / "fake" / ".git").write_text("not a real gitfile\n", encoding="utf-8")

    assert repo_root(fake) is None


@needs("git")
def test_repo_root_ignores_an_inherited_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run from a git hook or `git rebase -x`, GIT_DIR would override an explicit -C."""
    top = make_repo(tmp_path / "repo")
    elsewhere = tmp_path / "photos"
    elsewhere.mkdir()

    monkeypatch.setenv("GIT_DIR", str(top / ".git"))
    assert repo_root(elsewhere) is None, "an inherited GIT_DIR must not follow us around"


# --------------------------------------------------------- tracked vs present


@needs("git")
def test_untracked_files_inside_a_repository_are_not_guarded(tmp_path: Path) -> None:
    """The $HOME-is-a-dotfiles-repo case: `~/Downloads` holds nothing git tracks."""
    repo = make_repo(tmp_path / "home")
    (repo / "README.md").write_text("dotfiles\n", encoding="utf-8")
    commit_all(repo)
    downloads = docs(repo / "Downloads")

    assert would_move_tracked([downloads]) == {}
    run("organize", str(downloads), "--apply")
    assert (downloads / "docs" / "notes.txt").is_file()


@needs("git")
def test_tracked_files_are_guarded(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)

    offenders = would_move_tracked([tracked])
    assert list(offenders) == [repo.resolve()]
    assert sorted(offenders[repo.resolve()]) == ["src/data.json", "src/notes.txt", "src/report.md"]


# ------------------------------------------------------------------ organize


@needs("git")
def test_organize_apply_refuses_tracked_files_and_moves_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)
    before = listing(tracked)

    result = run("organize", str(tracked), "--apply", expect=2)

    assert "git is tracking" in result.output
    assert str(repo.resolve()) in result.output
    assert "--force" in result.output
    assert "notes.txt" in result.output, "the message should name what it found"
    assert listing(tracked) == before, "a refused run must leave the directory untouched"


@needs("git")
def test_the_refusal_has_no_usage_banner(tmp_path: Path) -> None:
    """It is a refusal, not a malformed command line — click's Usage: block misleads."""
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)

    result = run("organize", str(tracked), "--apply", expect=2)

    assert result.output.startswith("error: "), result.output
    assert "Usage:" not in result.output
    assert "--help" not in result.output


@needs("git")
def test_organize_apply_proceeds_with_force(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)

    run("organize", str(tracked), "--apply", "--force")

    assert (tracked / "docs" / "notes.txt").is_file()
    assert not (tracked / "notes.txt").exists()


def test_organize_apply_is_unaffected_outside_a_work_tree(tmp_path: Path) -> None:
    plain = docs(tmp_path / "plain")
    run("organize", str(plain), "--apply")
    assert (plain / "docs" / "report.md").is_file()


@needs("git")
def test_organize_dry_run_still_prints_its_plan(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)
    before = listing(tracked)

    result = run("--json", "organize", str(tracked))

    assert [e["action"] for e in json.loads(result.output)].count("move") == 3
    assert listing(tracked) == before


@needs("git")
def test_organize_guards_an_into_destination_that_escapes_the_directory(tmp_path: Path) -> None:
    """`--into docs=../repo/src` writes outside DIRECTORY, so the source alone is not enough."""
    repo = make_repo(tmp_path / "repo")
    docs(repo / "src")
    commit_all(repo)
    loose = docs(tmp_path / "loose")
    before = listing(repo / "src")

    result = run("organize", str(loose), "--apply", "--into", "docs=../repo/src/sorted", expect=2)

    assert "git is tracking" in result.output
    assert listing(repo / "src") == before
    assert listing(loose) == {"notes.txt", "report.md", "data.json"}


@needs("git")
def test_a_bad_into_reports_itself_rather_than_the_guard(tmp_path: Path) -> None:
    """Validation comes first: otherwise the user fixes the wrong thing."""
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)

    result = run("organize", str(tracked), "--apply", "--into", "bogus=x", expect=2)

    assert "--into expects CATEGORY=DIR" in result.output
    assert "git is tracking" not in result.output


# ------------------------------------------------------------------ rename


@needs("git")
def test_rename_apply_refuses_a_directory_of_tracked_files(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)
    before = listing(tracked)

    result = run("rename", str(tracked), "--apply", "--template", "{sha8}{ext}", expect=2)

    assert "git is tracking" in result.output
    assert listing(tracked) == before


@needs("git")
def test_rename_apply_refuses_an_expanded_glob_of_tracked_files(tmp_path: Path) -> None:
    """The 2026-09-10 incident: a shell glob arrives as a list of FILES, not a directory.

    Exempting every explicitly named file would let `carrel rename src/*.py
    --apply` through — one word that selects a set the user never enumerated.
    """
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)
    before = listing(tracked)

    result = run(
        "rename",
        str(tracked / "notes.txt"),
        str(tracked / "report.md"),
        str(tracked / "data.json"),
        "--apply",
        "--template",
        "{sha8}{ext}",
        expect=2,
    )

    assert "git is tracking" in result.output
    assert listing(tracked) == before


@needs("git")
def test_rename_apply_allows_an_untracked_file_inside_a_repository(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    commit_all(repo)
    loose = repo / "scan.txt"
    loose.write_text("hello\n", encoding="utf-8")

    result = run("--json", "rename", str(loose), "--apply", "--template", "x{ext}")

    assert [e["action"] for e in json.loads(result.output)] == ["renamed"]
    assert (repo / "x.txt").is_file()


@needs("git")
def test_rename_dry_run_still_plans(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)
    before = listing(tracked)

    result = run("--json", "rename", str(tracked), "--template", "{sha8}{ext}")

    assert [e["action"] for e in json.loads(result.output)] == ["rename"] * 3
    assert listing(tracked) == before


@needs("git")
def test_rename_apply_proceeds_with_force(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)

    result = run(
        "--json", "rename", str(tracked), "--apply", "--force", "--template", "r_{stem}{ext}"
    )

    assert [e["action"] for e in json.loads(result.output)] == ["renamed"] * 3
    assert (tracked / "r_notes.txt").is_file()


@needs("git")
def test_a_bad_template_reports_itself_rather_than_the_guard(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    tracked = docs(repo / "src")
    commit_all(repo)

    result = run("rename", str(tracked), "--apply", "--template", "no-placeholders", expect=2)

    assert "no placeholders" in result.output
    assert "git is tracking" not in result.output


# ------------------------------------------------------------------ intake


@needs("git")
def test_intake_apply_refuses_a_tracked_inbox(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    inbox = docs(repo / "inbox")
    commit_all(repo)
    dest = tmp_path / "filed"
    before = listing(inbox)

    result = run("intake", str(inbox), "--to", str(dest), "--apply", expect=2)

    assert "git is tracking" in result.output
    assert listing(inbox) == before


@needs("git")
def test_intake_apply_refuses_a_tracked_destination(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    dest = docs(repo / "filed")
    commit_all(repo)
    inbox = docs(tmp_path / "inbox")
    before = listing(inbox)

    result = run("intake", str(inbox), "--to", str(dest), "--apply", expect=2)

    assert "git is tracking" in result.output
    assert listing(inbox) == before


@needs("git")
def test_intake_does_not_create_its_destination_when_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    inbox = docs(repo / "inbox")
    commit_all(repo)
    dest = tmp_path / "filed"

    run("intake", str(inbox), "--to", str(dest), "--apply", expect=2)

    assert not dest.exists(), "a refused run must leave the disk untouched"


def test_intake_apply_is_unaffected_outside_a_work_tree(tmp_path: Path) -> None:
    inbox = docs(tmp_path / "inbox")
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


@needs("git")
def test_intake_apply_proceeds_with_force(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    inbox = docs(repo / "inbox")
    commit_all(repo)
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


@needs("git")
def test_intake_dry_run_still_plans(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    inbox = docs(repo / "inbox")
    commit_all(repo)
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


# ------------------------------------------------------------------ watch


@needs("git")
def test_watch_done_dir_refuses_a_tracked_directory(tmp_path: Path) -> None:
    """The fourth bulk mover, and the only one with no dry-run to fall back on."""
    repo = make_repo(tmp_path / "repo")
    watched = docs(repo / "src")
    commit_all(repo)
    done = tmp_path / "done"

    result = run(
        "watch", str(watched), "--run", "true", "--done-dir", str(done), "--once", expect=2
    )

    assert "git is tracking" in result.output
    assert not done.exists()


@needs("git")
def test_watch_without_done_dir_is_not_guarded(tmp_path: Path) -> None:
    """A watch that only runs actions moves nothing, so it has nothing to refuse."""
    repo = make_repo(tmp_path / "repo")
    watched = docs(repo / "src")
    commit_all(repo)

    run("watch", str(watched), "--run", "true", "--timeout", "0.3")


# ------------------------------------------------- the no-git conservative path


def test_without_git_being_inside_a_work_tree_is_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """carrel cannot ask what is tracked, so it assumes the worst and says so."""
    monkeypatch.setenv("CARREL_BIN_GIT", str(tmp_path / "no-such-git"))
    repo = fake_repo(tmp_path / "repo")
    inside = docs(repo / "src")
    before = listing(inside)

    result = run("organize", str(inside), "--apply", expect=2)

    assert "not installed" in result.output
    assert str(repo.resolve()) in result.output
    assert listing(inside) == before


def test_without_git_a_plain_directory_is_still_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARREL_BIN_GIT", str(tmp_path / "no-such-git"))
    plain = docs(tmp_path / "plain")

    run("organize", str(plain), "--apply")

    assert (plain / "docs" / "notes.txt").is_file()
