"""File moves that keep the desk in step, and the guard that stops them.

`organize --apply`, `rename --apply` and `intake --apply` all move files. A move
must (1) never overwrite (`uncollide`), (2) work across filesystems, and (3)
carry the desk row — tags, notes, fields, index text — with the file when a
desk exists under `desk_root`. Before v0.4.0 a move orphaned that row.

Those same three commands (and `watch --done-dir`) refuse to start when the move
would touch files git is tracking (`guard_worktree`, spec 29).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from carrel.core import adapters
from carrel.core.ignore import dot_git_ancestor
from carrel.core.output import CarrelError, CarrelUsageError, ExitCode


def uncollide(dest: Path, taken: Iterable[Path] = ()) -> Path:
    """First non-existing, not-yet-planned variant: name.ext, name-1.ext, …"""
    planned = set(taken)
    candidate, n = dest, 0
    while candidate.exists() or candidate in planned:
        n += 1
        candidate = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
    return candidate


def move_file(src: Path, dest: Path, *, desk_root: Path | None = None) -> Path:
    """Move `src` to `dest` (parents created); the desk row follows when a desk exists.

    `os.replace` first (atomic on one filesystem), `shutil.move` across
    filesystems. Never overwrites: callers pass an `uncollide`d destination.
    """
    from carrel.core.db import DeskDB

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite {dest}")
    try:
        os.replace(src, dest)
    except OSError:
        shutil.move(str(src), str(dest))
    if desk_root is not None and DeskDB.exists(desk_root):
        with DeskDB(desk_root) as db:
            db.rename_path(src, dest)
    return dest


# --------------------------------------------------------------------------
# git work-tree guard (spec 29)
#
# On 2026-09-10 a `rename --apply` aimed at carrel's own checkout renamed 21
# tracked files after the fields it read out of their source. The command was
# correct; the outcome was not. In a work tree, tracked names are content —
# imports, test collection, CI config and the history all address files by path.
#
# What matters is whether the move would touch files git is *tracking*, not
# whether it happens inside a repository. `~/Downloads` under a dotfiles repo is
# a mainstream layout, and refusing there would leave the user no way out but
# `--force`, which is the habit this guard exists to avoid forming.

#: variables that let the environment override an explicit `git -C`. carrel run
#: from a git hook or `git rebase -x` would otherwise be told about the hook's
#: repository no matter which directory it asked about.
GIT_ENV_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _nearest_existing(path: Path, *, resolved: bool = False) -> Path:
    """The deepest existing ancestor of `path` (or `path` itself, resolved).

    Only ever used to decide *which repository to ask*. It is deliberately not
    used as the thing asked about: `intake --to ~/filed` on a first run would
    otherwise climb to `~`, and in a dotfiles repo the guard would refuse and
    name every tracked dotfile — the false refusal D-017 exists to avoid.

    `resolved=True` says the caller already did the `expanduser().resolve()`.
    `resolve()` is a full realpath walk — one `lstat` per component — and
    `would_move_tracked` resolves every path before calling this, so a
    recursive `watch` over 425 files was doing 850 of them for 425 answers.
    """
    candidate = path if resolved else path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run git under `root` with the environment's repo overrides dropped, or None."""
    try:
        if not adapters.have("git"):
            return None
        return adapters.run("git", "-C", str(root), *args, timeout=15, drop_env=GIT_ENV_OVERRIDES)
    except Exception:  # noqa: BLE001 — a guard that crashes is worse than no guard
        return None


def repo_root(path: Path) -> Path | None:
    """The git work tree `path` sits in, or None. Never raises.

    Asks git first (`rev-parse --show-toplevel` through the adapter, D-008), so
    a `.git` *file* — submodules, linked worktrees — and `GIT_CEILING_DIRECTORIES`
    are honoured.

    git saying "not a git repository" is believed: that is how a ceiling
    directory reports itself, and it is the one negative that means "there is
    nothing here to protect". **Every other git failure falls back to the `.git`
    walk**, because those mean "git could not read this repository", not "there
    is none" — `detected dubious ownership` (the default for a /mnt/c checkout
    under WSL) and a `safe.directory` refusal both land here, and both must
    still guard.
    """
    try:
        start = _nearest_existing(path)
        if not start.is_dir():
            start = start.parent
        proc = _git(start, "rev-parse", "--show-toplevel")
        if proc is not None and proc.returncode == 0:
            top = (proc.stdout or "").strip()
            return Path(top).resolve() if top else None
        if proc is not None and "not a git repository" in (proc.stderr or "").lower():
            return None
        return dot_git_ancestor(start)
    except Exception:  # noqa: BLE001 — `Never raises` is the contract, not an aspiration
        return None


class TrackedUnknownError(CarrelError):
    """git could not be asked what it tracks — the guard must not assume "nothing"."""

    exit_code = ExitCode.MISSING_DEP


#: Budget for one `git ls-files -- <paths>` command line, in characters.
#: Windows' CreateProcess caps the whole line at 32,767; Linux ARG_MAX is ~2 MB.
#: Chunking by path *count* is not enough — 400 long absolute paths already
#: overflow on Windows, which is how CI caught this — so the budget is measured
#: in characters. An overflow raises, and before the "could not ask" distinction
#: that read as "nothing is tracked": the guard failing open on the largest
#: glob, which is the case it exists for.
_ARGV_BUDGET = 24_000


def _chunked(paths: Sequence[Path]) -> Iterator[list[str]]:
    """`paths` as argv batches that fit one command line (at least one each)."""
    batch: list[str] = []
    size = 0
    for path in paths:
        text = str(path)
        if batch and size + len(text) + 1 > _ARGV_BUDGET:
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += len(text) + 1
    if batch:
        yield batch


def tracked_paths(root: Path, paths: Sequence[Path]) -> list[str]:
    """Repo-relative paths under `paths` that git is tracking in `root`.

    Raises `TrackedUnknownError` when git cannot answer. "git could not be
    asked" and "git says nothing is tracked" must never collapse into the same
    value: one of them means it is safe to proceed and the other does not.
    """
    found: list[str] = []
    for chunk in _chunked(paths):
        # --literal-pathspecs: an inbox file named `sub*` or `Scan [1].pdf` is a
        # name, not a pattern. As a glob, `sub*` matched a tracked `sub/keep.txt`
        # and `Scan [1].pdf` matched `Scan 1.pdf`, refusing moves of files the
        # command never touches. Directory arguments still match everything
        # beneath them, so the recursive cases are unaffected.
        proc = _git(root, "--literal-pathspecs", "ls-files", "-z", "--", *chunk)
        if proc is None or proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()[:1] if proc else []
            raise TrackedUnknownError(
                f"could not ask git what it tracks in {root}" + (f": {detail[0]}" if detail else "")
            )
        found += [name for name in (proc.stdout or "").split("\0") if name]
    return found


def _asked_about(path: Path) -> Path:
    """The absolute path to ask git about.

    A symlink leaf is kept, not followed. A tracked `incoming/link.pdf` is
    tracked *as the link*; resolving it asked git about the target, usually
    outside the work tree, found nothing, and let the move through. Parent
    directories are still resolved, so a symlinked route into a repository is
    not an escape, and a symlink to a directory is resolved because what moves
    is what is inside it.
    """
    p = path.expanduser()
    if p.is_symlink() and not p.is_dir():
        return p.parent.resolve() / p.name
    return p.resolve()


def would_move_tracked(paths: Iterable[Path]) -> dict[Path, list[str]]:
    """{repo root: tracked paths} for every work tree `paths` would disturb.

    Empty when nothing tracked is involved. Raises `TrackedUnknownError` when a
    repository is in play but git cannot say what it tracks — the caller turns
    that into an exit-3 "install git", never into permission to proceed.

    Costs one `git rev-parse` per *repository*, not per directory: a recursive
    `watch` over 1,500 directories spawned 1,500 of them (2.5 s measured). The
    candidate root is found by walking up for a `.git` entry, which is stat
    calls only, and git is asked about that candidate once. Where git would
    answer differently for a deeper directory — a ceiling directory or a
    filesystem boundary below the root — this guards anyway, the safe direction.
    """
    by_root: dict[Path, list[Path]] = {}
    candidate_of: dict[Path, Path | None] = {}  # directory -> nearest .git ancestor
    root_of_candidate: dict[Path, Path | None] = {}  # that ancestor -> git's answer
    for path in paths:
        asked = _asked_about(path)
        if asked.is_symlink():
            key = asked.parent  # never follow the leaf, even to find the repository
        else:
            probe = _nearest_existing(asked, resolved=True)  # _asked_about resolved it
            key = probe if probe.is_dir() else probe.parent
        if key not in candidate_of:
            candidate_of[key] = dot_git_ancestor(key)
        candidate = candidate_of[key]
        if candidate is None:
            continue  # no .git entry anywhere above, so git would find no repository either
        if candidate not in root_of_candidate:
            root_of_candidate[candidate] = repo_root(candidate)
        root = root_of_candidate[candidate]
        if root is not None:
            # the *asked-about* path is the caller's, not its nearest existing
            # ancestor: a destination that does not exist yet tracks nothing
            by_root.setdefault(root, []).append(asked)
    if not by_root:
        return {}
    if not adapters.have("git"):
        which = "these repositories track" if len(by_root) > 1 else "this repository tracks"
        raise TrackedUnknownError(f"git is not installed, so carrel cannot tell what {which}")
    hits = {root: tracked_paths(root, targets) for root, targets in by_root.items()}
    return {root: names for root, names in hits.items() if names}


def within(path: Path, root: Path | None) -> bool:
    """True when `path`, symlinks resolved, is inside `root`. `root=None` confines nothing.

    A directory walk that skips symlinked *directories* still reads symlinked
    *files*, so a link inside a confined tree is a way out of it. Callers that
    declare a boundary — `carrel mcp`, which is confined to the directory it was
    started in (D-021) — pass it here; the CLI passes `None` and keeps following
    links, because a desk that symlinks documents in from elsewhere is a
    legitimate layout.

    **Both sides are resolved.** Comparing a resolved path against a raw `root`
    is false for every entry when the root is relative, or reached through a
    symlinked parent — `/tmp` on macOS, `/home` under some WSL layouts — and the
    walk would then yield nothing with no error at all. `ancestor_ignores`
    resolves its own `stop_at` for the same reason.
    """
    if root is None:
        return True
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        # Not symlink loops — `resolve()` is non-strict and returns those
        # unchanged. `os.getcwd()` behind a relative path when the cwd has been
        # removed, and Windows' `_getfinalpathname` on a reserved name or an
        # over-long path, both raise here. Outside a boundary we cannot evaluate
        # is the safe answer, and a walk must not die on one bad entry.
        return False


def guard_worktree(paths: Iterable[Path], *, what: str, allow_tracked: bool = False) -> None:
    """Refuse a bulk move that would rewrite files git is tracking.

    `paths` are exactly what the command would move or write into. Raises
    `CarrelUsageError` (exit 2) naming each repository and the way out, or
    `TrackedUnknownError` (exit 3, with git's install hint) when the question
    cannot be answered — never silence.
    """
    if allow_tracked:
        return
    try:
        offenders = would_move_tracked(paths)
    except TrackedUnknownError as e:
        adapters.require("git")  # the usual exit-3 message, binary + install hint
        raise CarrelUsageError(f"{what}: {e} — pass --allow-tracked to proceed anyway") from e
    if not offenders:
        return
    lines = []
    for root, names in sorted(offenders.items()):
        shown = ", ".join(names[:3]) + (f", … ({len(names)} total)" if len(names) > 3 else "")
        lines.append(f"  {root}\n    tracked: {shown}")
    listed = "\n".join(lines)
    raise CarrelUsageError(
        f"{what} would move files that git is tracking:\n{listed}\n"
        "Renaming tracked files breaks imports, tests and history. Point this "
        "somewhere else, or pass --allow-tracked if it is what you meant."
    )
