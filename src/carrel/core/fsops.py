"""File moves that keep the desk in step, and the guard that stops them.

`organize --apply`, `rename --apply` and `intake --apply` all move files. A move
must (1) never overwrite (`uncollide`), (2) work across filesystems, and (3)
carry the desk row — tags, notes, fields, index text — with the file when a
desk exists under `desk_root`. Before v0.4.0 a move orphaned that row.

Those same three commands also refuse to start when the directory they would
rewrite is inside a git work tree (`repo_root` / `guard_worktree`, spec 29).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

import click

from carrel.core.output import CarrelError


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
# correct; the outcome was not. In a work tree the names are content — imports,
# test collection, CI config and the history all address files by path.


def _nearest_existing(path: Path) -> Path:
    """The deepest existing ancestor of `path` (or `path` itself, resolved).

    `intake --to ~/filed/2026` may not exist yet; it is judged by the directory
    it would be created in.
    """
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _walk_for_dot_git(start: Path) -> Path | None:
    """Ancestor walk for a `.git` entry — the fallback when git is not installed."""
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return directory
    return None


def repo_root(path: Path) -> Path | None:
    """The git work tree `path` sits in, or None. Never raises.

    Asks git first (`rev-parse --show-toplevel` through the adapter, D-008), so
    a `.git` *file* — submodules, linked worktrees — and `GIT_CEILING_DIRECTORIES`
    are honoured. Falls back to an ancestor walk for a `.git` entry whenever git
    is unavailable or unhelpful: a directory that merely looks like a repository
    still guards, which is the safe direction when the cost of being wrong is a
    rewritten checkout and the cost of being cautious is typing `--force`.
    """
    from carrel.core import adapters

    start = _nearest_existing(path)
    if not start.is_dir():
        start = start.parent
    if adapters.have("git"):
        try:
            proc = adapters.run("git", "-C", str(start), "rev-parse", "--show-toplevel", timeout=15)
        except (CarrelError, OSError, ValueError):
            proc = None
        if proc is not None and proc.returncode == 0:
            top = (proc.stdout or "").strip()
            return Path(top).resolve() if top else None
    return _walk_for_dot_git(start)


def guard_worktree(paths: Iterable[Path], *, force: bool, what: str) -> None:
    """Refuse a bulk move that would rewrite files inside a git work tree.

    `paths` are the *directories* the command would write into. Explicit file
    arguments are deliberately not passed here: naming a file is already a
    decision at the granularity of the damage, while one directory name selects
    an unbounded set. Raises `click.UsageError` (exit 2) naming every distinct
    repository root involved, plus the way out.
    """
    if force:
        return
    roots: list[Path] = []
    for path in paths:
        root = repo_root(path)
        if root is not None and root not in roots:
            roots.append(root)
    if not roots:
        return
    listed = "\n".join(f"  {root}" for root in roots)
    raise click.UsageError(
        f"{what} would rewrite files inside a git work tree:\n{listed}\n"
        "Moving tracked files breaks imports, tests and history. Run this "
        "somewhere else, name the files explicitly, or pass --force if it is "
        "what you meant."
    )
