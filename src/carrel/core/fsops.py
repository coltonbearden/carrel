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
from collections.abc import Iterable, Sequence
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


def _nearest_existing(path: Path) -> Path:
    """The deepest existing ancestor of `path` (or `path` itself, resolved).

    Only ever used to decide *which repository to ask*. It is deliberately not
    used as the thing asked about: `intake --to ~/filed` on a first run would
    otherwise climb to `~`, and in a dotfiles repo the guard would refuse and
    name every tracked dotfile — the false refusal D-017 exists to avoid.
    """
    candidate = path.expanduser().resolve()
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


#: `git ls-files -- <paths>` is passed absolute paths; ARG_MAX is ~2 MB on Linux
#: and far smaller on Windows, and a glob of a few thousand files blows past it.
#: An E2BIG would surface as "git failed" and, before this cap, as "nothing is
#: tracked" — the guard failing open on exactly the case it exists for.
_LS_FILES_CHUNK = 400


def tracked_paths(root: Path, paths: Sequence[Path]) -> list[str]:
    """Repo-relative paths under `paths` that git is tracking in `root`.

    Raises `TrackedUnknownError` when git cannot answer. "git could not be
    asked" and "git says nothing is tracked" must never collapse into the same
    value: one of them means it is safe to proceed and the other does not.
    """
    found: list[str] = []
    for i in range(0, len(paths), _LS_FILES_CHUNK):
        chunk = [str(p) for p in paths[i : i + _LS_FILES_CHUNK]]
        proc = _git(root, "ls-files", "-z", "--", *chunk)
        if proc is None or proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()[:1] if proc else []
            raise TrackedUnknownError(
                f"could not ask git what it tracks in {root}" + (f": {detail[0]}" if detail else "")
            )
        found += [name for name in (proc.stdout or "").split("\0") if name]
    return found


def would_move_tracked(paths: Iterable[Path]) -> dict[Path, list[str]]:
    """{repo root: tracked paths} for every work tree `paths` would disturb.

    Empty when nothing tracked is involved. Raises `TrackedUnknownError` when a
    repository is in play but git cannot say what it tracks — the caller turns
    that into an exit-3 "install git", never into permission to proceed.
    """
    by_root: dict[Path, list[Path]] = {}
    # one `git rev-parse` per *directory*, not per path: a glob arrives as
    # hundreds of siblings and each spawn costs a process (300 files took 0.46s
    # before this, and it scales linearly; Windows spawns are far dearer)
    seen: dict[Path, Path | None] = {}
    for path in paths:
        resolved = path.expanduser().resolve()
        probe = _nearest_existing(resolved)
        key = probe if probe.is_dir() else probe.parent
        if key not in seen:
            seen[key] = repo_root(key)
        root = seen[key]
        if root is not None:
            # the *asked-about* path is the caller's, not its nearest existing
            # ancestor: a destination that does not exist yet tracks nothing
            by_root.setdefault(root, []).append(resolved)
    if not by_root:
        return {}
    if not adapters.have("git"):
        which = "these repositories track" if len(by_root) > 1 else "this repository tracks"
        raise TrackedUnknownError(f"git is not installed, so carrel cannot tell what {which}")
    hits = {root: tracked_paths(root, targets) for root, targets in by_root.items()}
    return {root: names for root, names in hits.items() if names}


def guard_worktree(paths: Iterable[Path], *, force: bool, what: str) -> None:
    """Refuse a bulk move that would rewrite files git is tracking.

    `paths` are exactly what the command would move or write into. Raises
    `CarrelUsageError` (exit 2) naming each repository and the way out, or
    `TrackedUnknownError` (exit 3, with git's install hint) when the question
    cannot be answered — never silence.
    """
    if force:
        return
    try:
        offenders = would_move_tracked(paths)
    except TrackedUnknownError as e:
        adapters.require("git")  # the usual exit-3 message, binary + install hint
        raise CarrelUsageError(f"{what}: {e} — pass --force to proceed anyway") from e
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
        "somewhere else, or pass --force if it is what you meant."
    )
