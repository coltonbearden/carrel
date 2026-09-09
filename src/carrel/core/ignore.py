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


def ancestor_ignores(top: Path) -> tuple[IgnoreFile, ...]:
    """.gitignore files above `top`, stopping at the repo root (dir with .git)."""
    found: list[IgnoreFile] = []
    for d in top.parents:
        ig = load_ignore(d)
        if ig:
            found.append(ig)
        if (d / ".git").exists():
            break
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
