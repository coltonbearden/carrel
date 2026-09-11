"""`.gitignore` matching shared by the tree-walking commands (`pack`, `index`).

A deliberately simple per-directory matcher, not a full git implementation:
plain names and `*` globs match anywhere below their `.gitignore`; a pattern
containing `/` matches relative to its `.gitignore`'s directory; a trailing `/`
makes a rule directory-only; `!pattern` re-includes. Rules apply in order
(outer `.gitignore` first, then file order) and the last matching rule wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


def is_worktree_root(directory: Path) -> bool:
    """True when `directory` holds a `.git` entry (a directory, or a file for
    submodules and linked worktrees).

    The single definition of the repository boundary, used both by the
    `.gitignore` walk below and by `core.fsops`'s guard. It lives here because
    this module is a leaf: `fsops` pulls in the adapter layer and click, and
    `batch`/`refs`/`mail` import `ignore` lazily to keep that cost off the
    import path.
    """
    return (directory / ".git").exists()


def dot_git_ancestor(start: Path) -> Path | None:
    """The nearest ancestor of `start` (inclusive) that `is_worktree_root`."""
    return next((d for d in (start, *start.parents) if is_worktree_root(d)), None)


@dataclass(frozen=True)
class IgnoreRule:
    pattern: str
    dir_only: bool
    negate: bool


@dataclass(frozen=True)
class IgnoreFile:
    base: Path
    rules: tuple[IgnoreRule, ...]  # in file order; the last matching rule wins


def load_ignore(directory: Path) -> IgnoreFile | None:
    gi = directory / ".gitignore"
    if not gi.is_file():
        return None
    rules: list[IgnoreRule] = []
    try:
        # not the shared reader: this module is a leaf by design, and a
        # .gitignore is git's file, not a user document
        lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:].strip()
        elif line.startswith("\\!"):
            line = line[1:]  # escaped literal "!"
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if line:
            rules.append(IgnoreRule(line, dir_only, negate))
    return IgnoreFile(directory, tuple(rules)) if rules else None


def ancestor_ignores(top: Path, stop_at: Path | None = None) -> tuple[IgnoreFile, ...]:
    """`.gitignore` files above `top`, up to the nearest bounding directory.

    The walk stops at the first ancestor containing `.git` (the repo root) or at
    `stop_at`, whichever comes first; the stopping directory's own `.gitignore`
    still counts. `stop_at` is the caller's known boundary — the desk root for
    `index`, the common root for `pack`.

    An **unbounded** walk returns nothing. Without that rule a directory outside
    any git repo collects `.gitignore` files all the way to `/`, where something
    unrelated can silently exclude the entire tree — a `uv venv` writes a
    `.gitignore` containing `*` into the venv directory, so a desk created inside
    one indexed zero files with no error to explain it.
    """
    top = top.resolve()
    boundary: Path | None = None
    if stop_at is not None:
        stop_at = stop_at.resolve()
        if top == stop_at:
            return ()  # top's own .gitignore is loaded by the walk itself
        if top.is_relative_to(stop_at):
            boundary = stop_at

    found: list[IgnoreFile] = []
    bounded = False
    for d in top.parents:
        ig = load_ignore(d)
        if ig:
            found.append(ig)
        if is_worktree_root(d) or d == boundary:
            bounded = True
            break
    if not bounded:
        return ()
    return tuple(reversed(found))


def _rule_matches(rule: IgnoreRule, rel: str, name: str, is_dir: bool) -> bool:
    if rule.dir_only and not is_dir:
        return False
    if "/" in rule.pattern:
        return fnmatch(rel, rule.pattern.lstrip("/"))
    return fnmatch(name, rule.pattern)


def ignored(path: Path, is_dir: bool, ignores: tuple[IgnoreFile, ...]) -> bool:
    """Git semantics: rules apply in order (outer .gitignore first, then file
    order); the last matching rule decides, `!pattern` re-includes."""
    result = False
    for ig in ignores:
        try:
            rel = path.relative_to(ig.base).as_posix()
        except ValueError:
            continue
        for rule in ig.rules:
            if _rule_matches(rule, rel, path.name, is_dir):
                result = not rule.negate
    return result
