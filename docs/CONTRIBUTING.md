# CONTRIBUTING

## Dev setup

```bash
git clone https://github.com/coltonbearden/carrel.git ~/projects/carrel && cd ~/projects/carrel
uv sync                 # creates .venv from pyproject.toml + uv.lock
uv run carrel doctor    # which optional binaries you have + apt install hints
uv run pytest           # 501 tests; binary-gated tests skip (with reason) when a binary is absent
```

Python ≥3.12, managed by [uv](https://docs.astral.sh/uv/). Optional external binaries
(pandoc, tesseract, ocrmypdf, weasyprint, pdftotext, pdftoppm, espeak-ng, ffmpeg, gpg,
exiftool) unlock more tests and commands — `carrel doctor` lists them all; nothing is
required to run the core suite.

## Coding standards

The binding rules live in [`CLAUDE.md`](https://github.com/coltonbearden/carrel/blob/main/CLAUDE.md) (repo root) and
[ARCHITECTURE.md](ARCHITECTURE.md) §Global contracts. The short version:

- Type hints on public functions, `pathlib.Path` over strings, f-strings, no global
  state. CLI framework is **click** — not argparse.
- Every command: working `--help`, `--json` when output is data (one JSON object/array
  on stdout, nothing else), ≥1 test, graceful degradation when an optional binary is
  missing.
- **No stubs, no TODOs** in shipped commands. Can't finish it? Cut it and document the
  cut in [FEATURES.md](FEATURES.md).
- Product name comes from `/product.json` — never hardcode "carrel" in code or
  generated output (docs prose is fine).

### The adapter-layer rule (most-enforced rule in review)

External binaries are called **only** through `src/carrel/core/adapters.py`
(`have()` / `require()` / `run()`, one `ADAPTERS` registry that `doctor` reads).
Command modules never import `subprocess`. `MissingDependencyError` is caught centrally
in `cli.py` and becomes an actionable stderr message + install hint, exit 3. The
integration reviewer greps for violations; the one documented exception is `watch`
running user-supplied shell actions.

### Exit codes (memorize these)

| code | meaning |
|---|---|
| 0 | success |
| 1 | general/unexpected error (stderr message; traceback only with `--debug`) |
| 2 | bad usage/arguments |
| 3 | missing optional dependency (message names the binary + install hint) |
| 4 | input file missing / unreadable / unsupported type |
| 5 | empty result with `--fail-empty` |

## How to add a command

1. **Spec first.** Add/extend a spec in `specs/` with an **Owns** line (your exact write
   boundary) and an **Acceptance** section.
2. **Module.** Create `src/carrel/commands/<name>.py` exporting a click command named
   `cmd`. Use the core library: `core.adapters` (binaries), `core.output.emit`/`fail`/
   `ExitCode` (output + errors), `core.filetypes`, `core.textextract`, `core.db`.
3. **Register it.** Add `"<cli-name>": "<module_name>"` to the `COMMANDS` dict at the
   top of `src/carrel/cli.py`. Commands are lazy-imported — a broken import must only
   break its own command, so keep import-time work at zero.
4. **Tests.** `tests/test_<name>.py`, driving the real CLI on fixtures from
   `tests/fixtures/` (regenerate via `tests/fixtures/generate.py`; the docx/odt/
   epub/rtf/xlsx fixtures come from pandoc and openpyxl, whose bytes differ
   between tool versions, so they are written once and kept unless you pass
   `--force`; never hand-edit
   binaries). Tests needing an optional binary use the `needs()` skip helper from
   conftest. Run them: `uv run pytest tests/test_<name>.py -q`.
5. **Verify by hand** before claiming done: `uv run carrel <name> --help`, one real
   fixture invocation, `--json` piped through `python -m json.tool`, and the failure
   paths (missing file → 4; missing binary → 3).
6. Optionally wrap it in a plugin command — see
   [PLUGIN_AUTHORING.md](PLUGIN_AUTHORING.md).

## Commit convention

Branch `main`. History is checkpointed, not noisy:

- `phase(N): ...` — phase-gate commits (plan, test report, finalize).
- `wave(N): ...` — a verified wave of parallel module work (see
  [AGENTS.md](AGENTS.md) for how waves ran).

For ordinary contributions a plain imperative subject is fine; group your work into
one coherent commit per logical change. Never commit generated junk (`.gitignore`);
generated fixtures **are** committed.

## PR expectations

- `uv run pytest` fully green — including `tests/test_marketplace.py` if you touched
  `plugins/` (and `claude plugin validate .` passing when you have the CLI).
- No stubs/TODO/placeholder code; cut-and-document instead.
- Exit codes and `--json` shapes match the contracts above.
- New/changed flags reflected in any plugin command markdown that wraps them (doc
  drift is a review finding — it has happened).
- Claims verified by execution: paste real command output in the PR description, the
  way the builder agents do in their reports.

## Permissions for an unattended agent run

`.claude/settings.json` is committed so an unattended agent run does not stall
waiting for a human to approve the commands this repository's release loop
actually uses: `uv run`/`sync`/`build`, `git switch`/`fetch`/`rebase`/`worktree`,
`git add`/`git commit`/`git push` (the loop has to be able to land a branch),
`git branch -d`/`-D`, the read-only and PR-management halves of `gh`,
`claude plugin`, `mkdocs build`, and `scripts/github-harden.sh`.

**A rule is a match against the whole command, with `*` standing in for any
text** ([permissions reference](https://code.claude.com/docs/en/permissions)).
Three properties of that matcher decide how this file has to be written, and
each of them has caught us out:

- A trailing ` *` **also matches the bare command**, but only when it is the
  rule's only wildcard — and `:*` is just another spelling of that trailing
  wildcard. So `Bash(git push --force:*)` already denied a plain
  `git push --force`; the entries worth adding were the ones naming a
  *different* shape, such as `Bash(git push * --force)`.
- A `*` with no space before it keeps matching inside the word. That is why
  `Bash(git push --force*)` (in a user-level file) also blocks
  `git push --force-with-lease`.
- The `:*` form is recognised **only at the end of a pattern**, which means no
  rule can end in a literal colon followed by a wildcard. `Bash(git push * :*)`
  reads as `git push *  *`, not as "a refspec beginning with a colon".

`tests/test_settings_permissions.py` implements that matcher and asserts on real
command strings, so the file is checked by execution rather than by reading.
Three further consequences are easy to get wrong:

- **`gh api` is not allow-listed at all.** No endpoint prefix is safe: `gh api
  repos/owner/repo` also matches `gh api repos/owner/repo/... -X DELETE`, and
  `-X` can appear anywhere in the line. The narrow "read-only GET" grant this
  file originally tried to express cannot be expressed. `scripts/github-harden.sh`
  is allow-listed instead — it is the audited wrapper that performs the ruleset
  work, and it has a `--verify-only` mode. Ad-hoc `gh api` still prompts, which
  is correct.
- **`gh pr merge` is allowed, and the merge gate is not enforced here.** A
  prefix matcher cannot tell "merged after the review completed and its findings
  were fixed" from "merged the instant CI went green" — it only sees the command
  string. Denying it outright makes the documented workflow impossible and a
  `deny` cannot be overridden, so the gate lives in CLAUDE.md as a rule the
  agent follows, and this file does not pretend otherwise. `gh run delete` and
  `gh release delete` *are* denied: those destroy CI evidence and unpublish a
  release, and nothing in this workflow needs them.
- **The deny list cannot stop `carrel … --apply`.** The flag comes after the
  path (`carrel organize DIR --apply`), so no prefix rule reaches it, and
  `uv run` — this repo's canonical runner — would cover it anyway. What actually
  guards that is the product itself (spec 29: a bulk move refuses to rename
  files git tracks) plus CLAUDE.md's rule that mutating smoke tests run in a
  `/tmp` scratch directory. Do not read an absence here as a guarantee.

Destructive verbs that discard uncommitted work are denied alongside the
obvious ones: `git checkout .`, `git checkout -f` and `git stash drop`/`clear`
destroy exactly what `git reset --hard` and `git clean` do. `git switch` is
allowed and covers branch changes safely.

`git branch -D` is **allowed**, unlike those: it deletes a ref, not a working
tree, and pruning branches whose commits are already on `main` is ordinary
housekeeping in this repo. Note that it also deletes that branch's own reflog,
so confirm the commits are upstream first — `git cherry -v main <branch>`, or
a tree comparison against the squash-merge commit for a squashed branch.

Because `Bash(git push:*)` pre-approves *every* push, the deny list has to name
everything that must not happen anyway: any push that lands on `main`, a `+`
refspec (a force push spelled without the flag), `--mirror`, `--delete`,
`--receive-pack=`/`--exec=` (arbitrary execution against a local remote), the
bundled `-fu` spelling, and git's own `git -C …`/`git -c … push` prefix forms,
which no rule anchored on the literal text `git push` can see.

The same reasoning applies to the other broad grants, so the deny list also
names `git worktree remove --force` (it discards uncommitted work, exactly like
`git reset --hard`), `git commit --no-verify`/`-n` (it skips the hooks, which is
how unformatted or fixture-corrupting work lands), and `git add -A`/`--all`/`.`
(they stage whatever `.gitignore` happens to miss, against CLAUDE.md's rule
about generated junk). Naming a path to `git add` still works, which is what the
release loop does.

Your own `.claude/settings.local.json` is git-ignored and takes precedence, so a
local `ask` entry still overrides an `allow` here. This file sets the floor for
a fresh clone, not a ceiling on your machine — but note that a `deny` cannot be
overridden locally or at the prompt, which is why the deny list is short and
specific.
