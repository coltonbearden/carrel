# spec: guardrails — destructive `--apply` refuses to rewrite a git work tree

**Owns:** `src/carrel/core/fsops.py` (`repo_root`, `guard_worktree`), `src/carrel/commands/rename.py`, `src/carrel/commands/organize.py`, `src/carrel/commands/intake.py` (each gains `--force`), `src/carrel/commands/pack.py` (`_git_root` delegates), `docs/REFERENCE.md` (regen), `docs/FEATURES.md`, `docs/TROUBLESHOOTING.md`, the `bookkeeper` agent and the `rename`/`organize`/`intake` plugin command docs, new `tests/test_guardrails.py`.
**Wave:** v0.4.1, PR 2.

## Why

On 2026-09-10, during the v0.4.0 build, a `carrel rename --apply` was aimed at the repository checkout itself. It did exactly what it was asked: it read each source file's "fields" and renamed **21 tracked files** after them, so `src/carrel/commands/refs.py` became `2026-09-10_carrel_refs_find_reference_numbers_in_documents.py` and 20 siblings likewise. Nothing was lost, but only because the command prints its plan and that transcript could be replayed backwards.

The tool behaved correctly and the outcome was still wrong. A directory that is a git work tree is a directory whose names are content: imports, test collection, CI configuration and the history itself all address files by path. `rename`, `organize` and `intake` are the three commands that move files in bulk, and all three are one `--apply` away from rewriting a repository. The plan-first default is a good guard against a *mistaken* run; it is no guard at all against a *deliberate* run aimed at the wrong directory.

This is the cheapest possible fix: name the hazard, refuse it once, and make the escape hatch explicit.

## Rule

`rename --apply`, `organize --apply` and `intake --apply` refuse to start when a **directory** they would write into resolves inside a git work tree, unless `--force` is given. Exit **2** (usage), message names the repository root and `--force`.

Precisely:

| Input | Guarded? |
|---|---|
| A directory argument (`organize DIR`, `rename DIR`, `intake INBOX`) | yes |
| `intake --to DEST` | yes |
| An explicit file argument (`rename a.pdf b.pdf`) | **no** |
| Anything without `--apply` (the dry-run default) | **no** |
| `intake --watch` (implies `--apply`) | yes |

Explicit files are exempt because naming a file is already a deliberate act at the granularity of the damage: `carrel rename report.pdf --apply` inside a repo renames exactly the one file the user typed. The incident came from a directory argument, where one word selects an unbounded set.

The check happens **before** any plan is built, so a refused run costs nothing and touches nothing.

## `core/fsops.py`

```python
def repo_root(path: Path) -> Path | None:
    """The work tree `path` sits in, or None. Never raises."""

def guard_worktree(paths: Iterable[Path], *, force: bool, what: str) -> None:
    """Raise click.UsageError (exit 2) when any path is inside a work tree."""
```

`repo_root` asks git first — `git -C <dir> rev-parse --show-toplevel` through the adapter (D-008), which correctly handles a `.git` **file** (submodules, worktrees), `GIT_DIR`, and `$GIT_CEILING_DIRECTORIES`. When the `git` binary is absent, or the call fails for any reason, it falls back to walking ancestors for a `.git` entry — the same walk `core/ignore.py` already stops on. A `.git` that exists but git itself rejects still guards: refusing to touch a directory that merely looks like a repository is the safe direction, and `--force` is one word away.

`repo_root` is soft — it returns `None` rather than raising — because a guard that crashes on a broken repo is worse than no guard. `pack._git_root` keeps its raising behaviour by calling `repo_root` and raising when it is `None`, so the `rev-parse` call exists in exactly one place.

The guard resolves each path to its nearest existing ancestor before asking, so `intake --to ~/filed/new` (not yet created) is judged by where it would be created.

## Message

```
Error: rename --apply would rewrite files inside a git work tree:
  /home/you/projects/carrel
Moving tracked files breaks imports, tests and history. Run this somewhere
else, name the files explicitly, or pass --force if it is what you meant.
```

## Tests (`tests/test_guardrails.py`)

Work trees are made by creating a plain `.git` directory, so the outcome does not depend on the `git` binary being installed and is identical on Windows. One test additionally uses real `git init` behind `needs("git")`.

1. `organize DIR --apply` inside a work tree → exit 2, message names the root, **nothing moved** (the directory listing is byte-identical afterwards).
2. Same with `--force` → files move.
3. The same directory outside any work tree → files move, no `--force` needed.
4. `rename FILE --apply` inside a work tree → proceeds (explicit file exemption).
5. `rename DIR --apply` inside a work tree → exit 2.
6. Dry-run inside a work tree → exit 0 and the plan prints.
7. `intake INBOX --to DEST --apply` → exit 2 when **either** side is in a work tree; both cases separately.
8. A nested directory several levels below the root is guarded and the message still names the **root**, not the nested directory.
9. `repo_root` returns `None` for a plain directory and the root for a nested one.
10. With `CARREL_BIN_GIT` pointed at a nonexistent path (git "absent"), the ancestor-walk fallback still guards.

## Docs

`REFERENCE.md` regenerates from `--help`. `FEATURES.md` gains a line under the safety notes. `TROUBLESHOOTING.md` gains "`--apply` refuses to run: 'inside a git work tree'" explaining the incident and the three ways out. `scripts/sync_plugins.py` regenerates the usage blocks. The `bookkeeper` agent and the three command docs mention the guard so an agent does not try to work around it by escalating.

## Not in scope

Detecting other kinds of precious directory (`node_modules`, `$HOME` itself, a mounted share). Git is the one that is both unambiguous to detect and catastrophic to rewrite. Anything broader is a heuristic that trains users to reach for `--force` by reflex, which would cost more safety than it buys.
