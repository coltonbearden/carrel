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
from collections.abc import Iterable
from pathlib import Path

from carrel.core import adapters
from carrel.core.output import CarrelUsageError


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
_GIT_ENV_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _nearest_existing(path: Path) -> Path:
    """The deepest existing ancestor of `path` (or `path` itself, resolved).

    `intake --to ~/filed/2026` may not exist yet; it is judged by the directory
    it would be created in.
    """
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def is_worktree_root(directory: Path) -> bool:
    """True when `directory` holds a `.git` entry (a directory, or a file for
    submodules and linked worktrees).

    The single definition of the repository boundary: `core.ignore` stops its
    `.gitignore` walk here, and `repo_root` falls back to it when git is absent.
    """
    return (directory / ".git").exists()


def dot_git_ancestor(start: Path) -> Path | None:
    """The nearest ancestor of `start` (inclusive) that `is_worktree_root`."""
    return next((d for d in (start, *start.parents) if is_worktree_root(d)), None)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run git under `root` with the environment's repo overrides dropped, or None."""
    try:
        if not adapters.have("git"):
            return None
        return adapters.run("git", "-C", str(root), *args, timeout=15, drop_env=_GIT_ENV_OVERRIDES)
    except Exception:  # noqa: BLE001 — a guard that crashes is worse than no guard
        return None


def repo_root(path: Path) -> Path | None:
    """The git work tree `path` sits in, or None. Never raises.

    Asks git first (`rev-parse --show-toplevel` through the adapter, D-008), so
    a `.git` *file* — submodules, linked worktrees — and `GIT_CEILING_DIRECTORIES`
    are honoured, including when git's answer is "no". Only when git cannot
    answer at all (not installed, or the call failed) does it fall back to
    looking for a `.git` entry in the parent directories.
    """
    try:
        start = _nearest_existing(path)
        if not start.is_dir():
            start = start.parent
        proc = _git(start, "rev-parse", "--show-toplevel")
        if proc is not None:
            # git ran: trust it in both directions, so a ceiling directory or a
            # refused `safe.directory` means "not ours to guard"
            if proc.returncode != 0:
                return None
            top = (proc.stdout or "").strip()
            return Path(top).resolve() if top else None
        return dot_git_ancestor(start)
    except Exception:  # noqa: BLE001 — `Never raises` is the contract, not an aspiration
        return None


def tracked_paths(root: Path, paths: Iterable[Path]) -> list[str]:
    """Repo-relative paths under `paths` that git is tracking in `root`.

    Empty when nothing is tracked — or when git cannot be asked, in which case
    the caller decides what to do with "unknown" (`would_move_tracked` treats it
    as "assume yes"). A directory argument matches everything beneath it, which
    is what `git ls-files -- DIR` already means.
    """
    args = [str(p) for p in paths]
    if not args:
        return []
    proc = _git(root, "ls-files", "-z", "--", *args)
    if proc is None or proc.returncode != 0:
        return []
    return [name for name in (proc.stdout or "").split("\0") if name]


def would_move_tracked(paths: Iterable[Path]) -> dict[Path, list[str]]:
    """{repo root: tracked paths} for every work tree `paths` would disturb.

    Empty when nothing tracked is involved. When git is absent the question
    cannot be answered, so being inside a work tree counts — the conservative
    direction, with `--force` one word away.
    """
    by_root: dict[Path, list[Path]] = {}
    for path in paths:
        root = repo_root(path)
        if root is not None:
            by_root.setdefault(root, []).append(_nearest_existing(path))
    if not by_root:
        return {}
    if not adapters.have("git"):
        return {root: [] for root in by_root}  # unknown: guard anyway
    hits = {root: tracked_paths(root, targets) for root, targets in by_root.items()}
    return {root: names for root, names in hits.items() if names}


def guard_worktree(paths: Iterable[Path], *, force: bool, what: str) -> None:
    """Refuse a bulk move that would rewrite files git is tracking.

    `paths` are everything the command would read from or write into — source
    directories, explicit file arguments and destinations alike. Raises
    `CarrelUsageError` (exit 2) naming each repository and the way out.
    """
    if force:
        return
    offenders = would_move_tracked(paths)
    if not offenders:
        return
    lines = []
    for root, names in sorted(offenders.items()):
        if names:
            shown = ", ".join(names[:3]) + (f", … ({len(names)} total)" if len(names) > 3 else "")
            lines.append(f"  {root}\n    tracked: {shown}")
        else:
            lines.append(
                f"  {root}\n    (git is not installed, so carrel cannot tell what is tracked)"
            )
    listed = "\n".join(lines)
    raise CarrelUsageError(
        f"{what} would move files that git is tracking:\n{listed}\n"
        "Renaming tracked files breaks imports, tests and history. Point this "
        "somewhere else, or pass --force if it is what you meant."
    )
