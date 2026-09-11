# spec: guardrails — a bulk move refuses to rename files git is tracking

**Owns:** `src/carrel/core/fsops.py` (`is_worktree_root`, `dot_git_ancestor`, `repo_root`, `tracked_paths`, `would_move_tracked`, `guard_worktree`), `src/carrel/core/output.py` (`CarrelUsageError`), `src/carrel/core/adapters.py` (`run(drop_env=…)`), `src/carrel/core/ignore.py` (shares the boundary predicate), `src/carrel/commands/rename.py`, `organize.py`, `intake.py`, `watch.py` (each gains `--force`), `pack.py` (`_git_root` delegates), `docs/REFERENCE.md` (regen), `docs/FEATURES.md`, `docs/TROUBLESHOOTING.md`, the `bookkeeper` agent and the plugin command docs, new `tests/test_guardrails.py`.
**Wave:** v0.4.1, PR 2.

## Why

On 2026-09-10, during the v0.4.0 build, a `carrel rename --apply` was aimed at the repository checkout itself. It did exactly what it was asked: it read each source file's "fields" and renamed **21 tracked files** after them, so `src/carrel/commands/refs.py` became `2026-09-10_carrel_refs_find_reference_numbers…py` and 20 siblings likewise. Nothing was lost, but only because the command prints its plan and that transcript could be replayed backwards.

The tool behaved correctly and the outcome was still wrong. A file git is tracking is a file whose *name is content*: imports, test collection, CI configuration and the history all address it by path. The plan-first default is a good guard against a *mistaken* run; it is no guard at all against a *deliberate* run aimed at the wrong place.

## Rule

`rename --apply`, `organize --apply`, `intake --apply` and `watch --done-dir/--error-dir` refuse to start when the move would touch a file **git is tracking**, unless `--force` is given. Exit **2** through `CarrelUsageError`, so the message reads `error: …` like every other carrel error.

### Tracked, not merely inside

The first draft of this guard asked "is this path inside a git work tree?". That is the wrong question, and the review said so: `~` under a dotfiles repository is a mainstream layout, and `carrel intake ~/Downloads --to ~/Documents/filed` would then refuse forever with no way out but `--force` — the exact reflex the guard exists to prevent. `~/Downloads` is untracked; `src/carrel/commands/` is tracked. Only the second is the incident.

So: `git -C <root> ls-files -z -- <paths>`. Non-empty ⇒ refuse and name what it found. Empty ⇒ proceed.

When the `git` binary is absent the question cannot be answered at all. carrel then exits **3** with git's install hint, the same as every other missing-binary path (CLAUDE.md's exit-code convention) — never a guess. `--force` skips the question entirely, so a git-less box is not stuck. The same applies to any git call that fails: "could not ask" and "nothing is tracked" are different answers and must never collapse into the safe-looking one.

### What is guarded

| Input | Guarded |
|---|---|
| A directory argument | yes — but only over what the command would actually move |
| Explicit file arguments | **yes** |
| `intake` INBOX and `--to` | yes, both |
| `organize --into CATEGORY=DIR` destinations | yes — a relative `--into` can climb out of DIRECTORY |
| A path that does not exist yet | no — creating a directory tracks nothing |
| `watch --done-dir` / `--error-dir` and the watched directory | yes |
| Anything without `--apply` (the dry-run default) | no |
| What a `watch --run` action does | no — that is the user's own command |

Explicit files are **not** exempt. The first draft exempted them on the theory that "naming a file is a decision at the granularity of the damage". A shell glob demolishes that: `carrel rename src/carrel/commands/*.py --apply` arrives as 21 file arguments and is the original incident, keystroke for keystroke. One word still selected a set the user never enumerated.

`organize` passes the top-level files it plans to move, not the directory: `ls-files -- DIR` matches recursively, so a tracked `sub/` would otherwise refuse a run that documented behaviour guarantees leaves it alone.

A path that does not exist yet is judged by *itself*, not by its nearest existing ancestor. Only the repository lookup climbs. Otherwise `intake --to ~/filed` on a first run (`--to` is "created if missing") would be judged by `~`, and in a dotfiles repo the guard would refuse and name every tracked dotfile — the false refusal this whole design exists to avoid.

### Ordering

The guard runs **after** the command's own argument validation — `--into bogus=x`, a template with no placeholders, and `intake`'s "INBOX and --to must be separate" all report themselves instead of being masked by a refusal. It runs **before** anything is created or moved: `intake` refuses before `mkdir`-ing `--to`, and `watch` refuses before `--print-service` returns, so carrel never hands back a systemd unit whose command would fail with exit 2 at every start (with `Restart=on-failure` looping it until the start limit trips).

## `core/fsops.py`

```python
is_worktree_root(directory) -> bool        # a `.git` entry lives here
dot_git_ancestor(start) -> Path | None     # nearest such ancestor
repo_root(path) -> Path | None             # git's answer, or the walk. Never raises.
tracked_paths(root, paths) -> list[str]    # repo-relative paths git tracks
would_move_tracked(paths) -> {root: [paths]}
guard_worktree(paths, *, force, what)      # CarrelUsageError (exit 2)
```

`repo_root` asks git first — `rev-parse --show-toplevel` through the adapter (D-008), which handles a `.git` **file** (submodules, linked worktrees) and `GIT_CEILING_DIRECTORIES`. git saying literally **"not a git repository"** is believed, because that is how a ceiling directory reports itself and it is the one negative meaning "there is nothing here to protect". **Every other git failure falls back to the `.git` walk**: `detected dubious ownership` — the default for a `/mnt/c` checkout under WSL — and a `safe.directory` refusal mean "git could not read this repository", not "there is none", and both must still guard.

`ls-files` argv is chunked by **character budget** (24,000), not by path count. Windows' `CreateProcess` caps a whole command line at 32,767 characters and Linux ARG_MAX is about 2 MB; a count-based chunk of 400 long absolute paths still overflowed on Windows, which is how CI caught it. An overflow raises, and a naive reading turns that into "nothing is tracked" — the guard failing open on the largest glob, which is the case it exists for. The repository lookup is memoised per directory, so a glob of siblings costs one `rev-parse` rather than one per file (300 files: 0.46s → 0.011s).

Every git call drops `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and `GIT_COMMON_DIR` from the child environment (`adapters.run(drop_env=…)`). Those override an explicit `-C`, so carrel invoked from a git hook or `git rebase -x` would otherwise be told about the hook's repository no matter which directory it asked about, and would refuse to organize an unrelated photo folder.

`repo_root` returns `None` rather than raising, and means it: the whole body is guarded, because a safety check that crashes is worse than no safety check. `pack._git_root` keeps its raising behaviour by calling `adapters.require("git")` first — so a missing binary is still exit 3 with the install hint, never a misleading "not a git repository" — then `repo_root`.

`is_worktree_root` is the single definition of the repository boundary; `core/ignore.py` stops its `.gitignore` walk on the same predicate instead of its own copy.

## Message

```
error: organize --apply would move files that git is tracking:
  /home/you/projects/myapp
    tracked: src/a.py, src/b.py, src/c.py, … (21 total)
Renaming tracked files breaks imports, tests and history. Point this
somewhere else, or pass --force if it is what you meant.
```

`CarrelUsageError`, not `click.UsageError`: click prefixes the latter with a `Usage:` / `Try --help` banner, which tells the user their arguments were malformed when in fact they were understood and refused. It also keeps `core/` free of the CLI framework.

## Tests (`tests/test_guardrails.py`)

Repositories are real (`git init` + `git add`) behind `@needs("git")`, because the question the guard asks can only be answered by git. The no-git fallback is exercised with a stale `CARREL_BIN_GIT`, which counts as missing (D-008). 32 tests, covering: tracked refused and nothing moved; untracked-inside-a-repo allowed (the dotfiles case); an expanded glob of tracked files refused; `--force` through; dry-run unaffected; `--to` not created on refusal; `--into` escaping DIRECTORY; argument validation reported ahead of the guard; no `Usage:` banner; a ceiling directory and a malformed `.git` both trusted as "no"; an inherited `GIT_DIR` ignored; `watch --done-dir` refused and a plain `watch` not.

## Not in scope

Detecting other kinds of precious directory (`node_modules`, `$HOME` itself, a mounted share). Git tracking is both unambiguous to detect and catastrophic to break. Anything broader is a heuristic that trains users to reach for `--force` by reflex, which would cost more safety than it buys.
