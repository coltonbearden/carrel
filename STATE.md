# STATE

> Live status of the project. A brand-new session should be able to resume from this file alone.
> Build history: docs/HOW_THIS_WAS_BUILT.md. Decisions: docs/DECISIONS.md. Release steps: docs/RELEASING.md.

## Now

- **Status:** v0.5.0 "the first five minutes" is the current release (2026-09-12); its
  verification record is the v0.5.0 entry under Done. 33 commands, 14 MCP tools, 19 adapters,
  9 marketplace plugins, desk schema v2. Repo `coltonbearden/carrel`, docs at
  https://coltonbearden.github.io/carrel/, PyPI package `carrel`.
- **In flight:** no Dependabot PR is open. #57 (`setup-uv` 10.2.0) merged on 2026-10-09
  (Done), and Dependabot closed #61 and #62 itself once #58 had fixed their alerts. Its Monday
  run should propose pypdf 6.20.0 and `setup-uv` 10.3.0, both under Open issues. The ruleset's
  up-to-date rule makes every PR take `main`'s head before it merges, which reruns its checks.
  Two ways to update a Dependabot branch: `@dependabot rebase` keeps the PR Dependabot's own;
  `gh pr update-branch` adds a merge commit that is not Dependabot's, after which it stops
  rebasing that PR by itself (`@dependabot recreate` restores it).
  #48 (Context7) was the v0.5.0 wave's last PR. The two Dependabot PRs
  after it merged: #49 (`setup-uv` 10.1.0) as `d4619cf` and #50 (pypdf 6.18.1, ruff 0.16.7,
  pre-commit hooks run from `uv.lock`) as `fe0695a`. The owner items their reviews raised are
  decided and landed — CI's uv cache and uv pin, the pypdf floor (D-026) and the
  `.claude/settings.json` items (D-027); what is still open is below.
- **Next:** MCP v3 (`specs/30-mcp-v3.md`) as **v0.6.0**: 11 new tools, 14 → 25, with `rename`,
  `intake`, `organize` and `ocr` first. That ordering is this wave's brief, not spec 30, which
  states none: `rename`/`intake`/`organize` are what stop the accounting-inbox pipeline being
  CLI-only, and `ocr` rides along on their entry points. The Open-issue entry below still names
  the older headline set (`rename`, `batch`, `intake`). `batch` is cut from the wave — it is the
  single `shell=True` site (D-013) — and `audiobook`, `color` and `proof` are deferred; the spec
  says why. Every mutating tool is dry-run by
  default, and confinement is settled by **D-021** rather than re-opened.
  **Do this first, before any mutating tool lands:** replace the `confine_to` flag threaded
  through five walkers and two writers with one confined filesystem accessor (Open issues).
  Five review rounds on v0.5.0 each found one more caller that had been missed; the flag is
  the reason, and MCP v3 adds callers to the same surface.
- **Also pending:**
  - **Owner's step, not before 2026-10-23:** promote `test-minimal (windows)` to required once
    it has been green on `main` for two consecutive weeks (D-028). The count starts at
    2026-10-09T01:10Z, the first `main` run after a gap with none since 2026-09-24 (#60's
    merge; dates here are UTC, as `gh` prints them): on 2026-10-09 the owner chose to wait for
    the rule as written rather than promote on the runs of one evening. The job has been green
    in all six `main` runs since, the run cancelled on #64's merge included, and
    `tests (weekly)` adds a run on 2026-10-12 and 2026-10-19 even if nothing merges. Count by
    the job, not by the run: `continue-on-error` keeps a run green when this job fails, and a
    re-run hides the first attempt, so `gh run list` cannot show either.
    `scripts/windows-promotion-evidence.sh` (read-only) prints the job's result for every
    attempt of every `main` run of both workflows since the count started, leaves out pull
    requests, and exits 0 only when the window is 14 days old and nothing failed. A `failure`
    restarts the count (pass `--since` the next green run); `cancelled` or `absent` is no
    evidence either way. Settle the `kill_tree` flake first (Open issues): it failed this job
    once on a pull request on 2026-10-09, and a required job that fails at random blocks
    merges at random. Promotion changes branch protection, so it needs the owner's go-ahead
    in that session: drop `continue-on-error` in `.github/workflows/test.yml`, add the check
    to `REQUIRED_CHECKS`, then run `scripts/github-harden.sh`. (`test-minimal (macos)` was
    added on 2026-09-11 under the owner's authorisation in the v0.4.1 brief.)
  - **Dated check, 2026-10-12:** the first scheduled run. GitHub fires a schedule only from
    the default branch, so no pull request could exercise the timer; the call from
    `weekly.yml` into `test.yml` was run once on #65 through a temporary `pull_request`
    trigger, removed before the merge. Confirm a scheduled run exists:
    `gh run list --workflow weekly.yml --event schedule`.

## Done

- 2026-10-09: the two things D-027 left open were taken up (#66, D-029). The `github-pages`
  environment deploys only from `main`: the policy was already set on GitHub, and
  `scripts/github-harden.sh` now converges both environments to one pattern each, naming
  any pattern it removes, and verifies them, mode included (`--verify-only` read every
  setting back green;
  `tests/test_github_harden.py` runs the script against a stand-in `gh`). `gh workflow run`
  and `gh repo edit` are `ask` rules in `.claude/settings.json`, which hold against the
  owner's user-level `Bash(gh:*)` allow where D-027's "not allowed" did not; checked live,
  the one matching command stopped for approval. Every plain dispatch asks now, so the two
  exact dispatch allows are gone. Neither is a boundary; what still gets past is under Open
  issues.
- 2026-10-09: `main` is tested every Monday at 06:17 UTC as well as on push (#65, D-028), so
  a failure that arrives with the calendar shows up there within a week, as a red
  `tests (weekly)` run. The schedule is in a workflow of its own,
  `weekly.yml` (`tests (weekly)`), which calls `test.yml`: GitHub can disable a scheduled
  workflow in a quiet repository, and `test.yml` reports the required checks.
  `tests/test_workflows.py` lists every workflow's triggers exactly, so none gains a timer
  directly or by being chained to this one. The rule that no test depends on the day it runs
  is in `CLAUDE.md`'s Testing section as well as `docs/CONTRIBUTING.md`, and the one test
  that still dated a file by an unpinned mtime (`rename`'s plan-and-apply test) is pinned.
  The first scheduled run is 2026-10-12 (Also pending).
- 2026-10-09: #57 (`setup-uv` 10.1.0 to 10.2.0, all seven steps in `test.yml`, `docs.yml` and
  `publish.yml`) merged. `/code-review 57 high` found no defect in the bump. The pin is
  upstream's signed `v10.2.0` tag commit; the built bundle differs from 10.1.0's in a
  `save-cache: auto` default that skips saving on `merge_group` events only (no workflow here
  has one), in built-in checksums for uv 0.12.13 to 0.12.17, and in `smol-toml` 1.8.0, which
  reads `uv.lock`; and every job installed uv 0.12.22 from `uv.lock` on Linux, macOS and
  Windows. Fixed with the PR: `tests/test_workflows.py` now fails when the `setup-uv` steps
  are not all on one pin, and the `ci` label that `.github/dependabot.yml` names but the
  repository lacked exists, so Dependabot stops posting a label error on every Actions PR.
  Two findings are deferred under Open issues: a Windows process-tree flake that this PR's
  CI surfaced, and the checksum table that trails `uv.lock`.
- 2026-10-09: #58 (Dependabot's `python-deps` group) merged as `ff9debc`, and the pypdf floor
  followed it in #64. `uv.lock` moved to pypdf 6.19.0, ruff 0.16.10, mypy 2.4.0 and uv
  0.12.22, and two compiled packages mypy already depended on moved with it: ast-serialize
  from 0.9.0 to 0.12.1 and librt from 0.15.0 to 0.16.0. The merge closed Dependabot alerts 9
  to 12: three high ones on pypdf below 6.19.0 and a medium one on uv 0.12.7 to 0.12.17
  (GHSA-2cv4-cqwr-gwf7, path traversal on Windows when a wheel is extracted; uv is CI's own
  tool here, installed by every `setup-uv` step at the version `uv.lock` pins).
  `/code-review 58 high` found no defect in the lock: every changed entry matches PyPI's
  hashes, and `form fill` writes the same appearance streams for the form fixture on both
  pypdf versions. One finding was fixed in the PR: the
  `uv-pin` group's floor sat inside the uv advisory's range and is `>=0.12.18` now, so a
  relock cannot take CI's uv back into it. #64 then raised the runtime floor to
  `pypdf>=6.19.0` (D-026; unreleased, see Open issues). Two findings are deferred under Open
  issues: pypdf 6.20.0 and Dependabot's missing cooldown. `main`'s `tests` run on #58's merge
  commit was green in all seven jobs.
- 2026-10-08: #59 (urllib3 from 2.7.0 to 2.8.0, `uv.lock` only) merged as `1a15026`. Its
  `/code-review 59 high` completed with no findings: the lock entry matches PyPI's record for
  2.8.0, nothing in carrel imports urllib3 directly (it arrives through `requests`, for
  `tiktoken` and `mkdocs-material`), and CI installed 2.8.0 with the same pass and skip counts
  as `main`. The merge closed Dependabot alert GHSA-gh4c-6fx4-qh6g, and `main`'s `tests` run
  on the merge commit was green in all seven jobs.
- 2026-10-08: `tests/test_intake.py::test_layout_and_fallback_options` no longer depends on the
  day it runs. The `inbox` fixture's `note.md` has no date of its own, so `intake` dates it by
  mtime, and the test expected the quarter that was current when it was written (`FY2027/Q1`
  with `--fiscal-start 7`, true only from July to September 2026). From 2026-10-01 it failed on
  every branch, while `main` still showed its last run, a green one from 2026-09-24. The code
  was right: October is Q2 of a July fiscal year. The fixture now pins the note's mtime, and
  the rule is written down in `docs/CONTRIBUTING.md` (How to add a command, step 4): a file
  that a test dates by mtime gets `os.utime`, as the `organize` date tests already do. Two
  findings of #60's review are deferred under Open issues.
- 2026-09-12 (v0.5.0): released in seven PRs (#40–#46) plus the two Step-0 PRs (#38, #39).
  The GitHub Release is pinned to the release PR's merge commit `cda1aa8`; PyPI via Trusted
  Publishing. **Verified from PyPI in a clean `/tmp` venv:** `carrel 0.5.0`; `doctor --json`
  33 commands (31 ok, `mail` degraded without readpst, `desk` unavailable without the `tui`
  extra) and 19 adapters; in a fresh clone with `src` compiled,
  `carrel pack src --stats --tree-only | grep -c __pycache__` → **0** (45 before the fix); an
  MCP server started in a scratch desk answered `resources/read` for a path outside it with
  `resource not found` and `carrel_inspect` with `isError: true, exit_code 2`, and the file's
  contents appeared nowhere in the output; a `.png` `Read` payload through `read-guard.sh`
  produced no output and exit 0. The wheel **and** the sdist each carry a PEP 740 attestation
  naming `coltonbearden/carrel`, `publish.yml`, environment `pypi`. The global install went
  0.4.1 → 0.5.0 (`uv tool upgrade carrel --reinstall`; note `--refresh` is not a flag of that
  subcommand). The GitHub repository description was set to the functional line.

  What the wave fixed: `pack` ignored the worktree root's `.gitignore` when packing a
  subdirectory (#41); an empty `--query` pack exited 0 (#41); `carrel-guard`'s README was wrong
  about `Read` and images were OCR'd unconditionally (#42); the MCP server was not confined
  though `SECURITY.md` said it was (#43); install hints were Debian-only on every platform,
  prose counts were stale by hundreds, PyPI had no classifiers, `--json` errors were English,
  and `redact --builtin` was last-one-wins (#44); the README led with the TUI (#45).

  **The owed v0.4.1 review is discharged.** `refs/pull/36/head` (`5b88c7a`) — the systemd and
  schtasks quoting in `commands/watch.py`, and the guard's symlink handling,
  `--literal-pathspecs` and per-repository lookup in `core/fsops.py` — was reviewed on
  2026-09-12 and its eleven confirmed findings shipped as **#40**. Do not re-run it. The local
  `pr36` and `review/pr36-owed` branches were deleted once #40 landed.

  **The MCP boundary took five review rounds**, each finding one more way a path reached the
  filesystem: named by the client, found by a walk (symlinked *files* were read even though
  symlinked directories were skipped), a fifth walker nobody had listed (`carrel_mail threads`),
  derived by a writer (`convert` and `mail attachments` wrote *through* planted symlinks, and a
  dangling one created the file outside), read back from the desk index (rows an unconfined CLI
  had stored), and the index's own location (`<root>/.carrel` as a symlink moved the whole
  database out of the desk). All closed, each with a test that fails when the fix is reverted,
  plus two registry-driven tests that drive every (tool, action) pair from `mcp.TOOLS`. Those
  two cover the *read* side; the write-side twin is hand-listed over `carrel_convert` and
  `carrel_mail attachments`, the only two tools that write today — so v0.6.0's mutating tools
  are not covered by it automatically and must be added. The threading approach is what let
  each round find one more caller — hence the v0.6.0 item above.

  Process notes worth keeping: the release PR's first push reddened **every** CI job in seconds
  because `uv.lock` pins carrel's own version and CI syncs under `UV_LOCKED=1`. The lock was
  correct on disk the whole time — `uv run` had relocked it silently during the gate — and was
  simply never staged. It now has a `uv-lock-current` pre-commit hook (`uv lock --check`), and
  the reason it needs a *hook* rather than a test is that anything reached through `uv run`
  relocks first and repairs the very staleness it is asked to detect. CLAUDE.md's gate invokes
  pre-commit through `uv run`, so CI is the real backstop for this class.

- 2026-09-11 the gate could not be run (#39). `pre-commit run --all-files` is a step in
  CLAUDE.md's gate and had never been executed: `pre-commit` is not a project dependency and
  no git hook was installed. It rewrote five tracked files. `ruff-format` reformats Python
  fences **inside Markdown** (its upstream `types_or` has included `markdown` since
  ruff-pre-commit v0.14), which turned `docs/COOKBOOK.md`'s `--8<-- "snippets/…"` directive
  into `--8 < --"…"` and silently dropped a 40-line example from the published page — while
  `mkdocs build --strict` still exited 0, because the mangled text is no longer a directive
  for `pymdownx.snippets` to check. The root-cause guard is `extend-exclude = ["**/*.md"]`
  in `pyproject.toml`, so it holds for an editor's format-on-save and a bare `ruff format .`
  too, not only for the hook; `tests/test_precommit_config.py` asserts the outcome
  (`ruff format --check .` clean, the directive still intact) rather than the config shape.
  Also: `end-of-file-fixer` was rewriting the generated fixture `tests/fixtures/thread.mbox`
  in a loop with `generate.py` (1058 → 1057 → 1058 bytes), and `check-yaml` could not read
  `mkdocs.yml`'s `!relative` tag at all — `--unsafe` is now scoped to that one file, since
  repo-wide it would stop catching the duplicate keys a bad merge leaves in a workflow.
  Separately, `test_watcher_settle_waits_for_a_growing_file` slept 0.1 s inside a 0.2 s
  settle window and asserted the file had *not* settled — an assertion about how fast the
  runner gets back. It failed `test-minimal (macos)` (a required check) on #38 and passed on
  re-run; it now drives `watch`'s own clock through an injected `time`.
- 2026-09-11 (v0.4.1): released in five PRs (#32–#36). The GitHub Release is pinned to the
  release PR's merge commit `5aaed7b`, whose tree is byte-identical to the one CI tested; PyPI via
  Trusted Publishing. Verified from PyPI in a clean venv with no extras: `carrel 0.4.1`,
  `doctor --json` 33 commands (31 ok; `mail` degraded without readpst and `desk` unavailable
  without the `tui` extra, both by design) and 19 adapters, and the spec-29 guard refusing
  (exit 2) to move a tracked file in a real repository. The wheel and the sdist each carry a
  PEP 740 attestation naming `coltonbearden/carrel`, `publish.yml` and environment `pypi`. The
  global `carrel[all]` install went 0.4.0 → 0.4.1 (32 ok, `mail` degraded).
  The release PR had two completed reviews. The first found the `watch` guard over-reaching
  into subdirectories, generated service units pinning whichever `carrel` was first on PATH, an
  unescaped schtasks line, `publish.yml` free to re-lock the environment its test step runs in,
  and QUICKSTART §7 catalog samples rotted since v0.4.0 (re-run for real); the second review
  covered those fixes. The second found a tracked symlink slipping past the guard, glob
  characters in file names over-matching, `--glob` ignored, one `git rev-parse` per directory
  (1,500 directories: 2.52 s, now 0.10 s) and systemd `%`, `$` and backslash quoting wrong in
  every generated unit. Those fixes were verified — a real systemd unit re-printing its argv,
  real repositories, the suite — but **not reviewed** (Also pending). Before tagging,
  `publish.yml`'s build job was replayed at the release head under `UV_LOCKED=1` and passed;
  that lock covers `uv run` only, and the `hatchling` build backend is still unpinned (Open issues).
- 2026-09-11 process + settings: `.claude/settings.json` is committed, so an unattended agent
  run never stalls on a permission prompt for the release loop (`uv`, `git switch`/`fetch`/
  `rebase`/`worktree`, `git add`/`commit`/`push`, `git branch -d`/`-D`, the read-only and
  PR-management halves of `gh`, `claude plugin`, `mkdocs`,
  and `scripts/github-harden.sh`). `gh api` is deliberately not
  allow-listed — no prefix can express read-only. The deny list names destructive shapes:
  specific `rm -rf` roots, every force-push spelling plus the `+refspec`, `--mirror`,
  `--delete`, `--receive-pack=`/`--exec=` and `git -C … push` forms, any push that lands on
  `main`, `git reset --hard`, `git clean`, the
  work-destroying `git checkout`/`stash drop` forms, `gh run delete` and
  `gh release delete`. `tests/test_settings_permissions.py` implements the documented
  wildcard matcher and asserts on real command strings, so the file is verified by execution.
  The repo's
  own `.gitignore` now excludes `.claude/settings.local.json` — it was only ever excluded by
  this machine's *global* gitignore, so a fresh clone could have committed someone's local
  permissions. CLAUDE.md gains two rules: a PR merges only after its review completes, and
  mutating smoke tests run in `/tmp`. `docs/index.md` said "ten MCP tools" two releases after
  it became 14; `tests/test_docs_drift.py` now scans **every live doc** (plus the plugin
  skills, whose frontmatter states it) for a stated tool count and checks it against
  `mcp.TOOLS`, and pins every tool name in `docs/AGENTS.md` plus the inline lists in README
  and `docs/FEATURES.md`. The first attempt hand-listed three files and matched the literal
  "MCP tools", which only ever existed in `docs/index.md` — six live statements of the count
  sat outside it, including a shipped plugin skill. The name check scanned whole documents,
  where `search`/`pack`/`diff` appear for unrelated reasons, so it could not fail; it reads
  only the lines describing MCP now, and a meta-test strips the list out to prove it bites.
  GitHub: `test-minimal (macos)` is a required check on the `main` ruleset, and
  `docs/REPO_SETTINGS.md` is pinned against `REQUIRED_CHECKS` so that pair cannot drift.
- 2026-09-11 (spec 29, D-017): `rename --apply`, `organize --apply`, `intake --apply` and
  `watch --done-dir/--error-dir` refuse (exit 2) when the move would touch a file **git is
  tracking**, naming the repository and the paths; each gains `--force`. Motivated by the
  2026-09-10 incident in which a `rename --apply` aimed at this checkout renamed 21 tracked
  files. The first draft asked "is this inside a work tree?" and the review killed it twice
  over: it refused forever on the `$HOME`-is-a-dotfiles-repo layout (no way out but `--force`,
  the reflex the guard exists to prevent) while still letting `rename src/*.py --apply` —
  the incident itself, arriving as file arguments — straight through. `git ls-files` answers
  the right question. Also from that review: `pack --since` without git regressed to exit 4
  "not a git repository" instead of exit 3 with the install hint; `organize --into ../escape`
  wrote outside the guarded directory; the guard masked genuine argument errors by running
  before validation; and `click.UsageError` printed a `Usage:` banner implying the command
  line was malformed (now `CarrelUsageError`, which also keeps click out of `core/`).
  A **second** review then found the guard failing open twice over: a glob too long for one
  `git ls-files` command line raised, and "git could not be asked" was being read as "nothing
  is tracked" (argv is chunked by character budget now — Windows caps a command line at
  32,767 — and "could not ask" is its own answer); and a repository git refuses to read,
  including `detected dubious ownership`, the default for a `/mnt/c` checkout under WSL, was
  left unguarded, because "git ran and failed" was treated as "not a repository". Only git's
  literal "not a git repository" is believed now. It also found the guard refusing what it
  had promised to allow: a `--to` that does not exist yet was judged by its nearest existing
  ancestor, so a first `intake ~/Downloads --to ~/filed` in a dotfiles repo refused and named
  every tracked dotfile. With git absent the command exits **3** with the install hint rather
  than guessing, and `--force` still skips the question.
- 2026-09-11: the latent Windows text-IO gap is closed and gated. `ruff`'s `PLW1514` is on
  (via `lint.preview` + `lint.explicit-preview-rules`, so only that preview rule turns on —
  a blanket `preview = true` would surface 324 findings) and it found 43 sites across
  `src`, `tests` and `scripts`. Hand-auditing found 9 more the rule could not see, because
  it only fires where it can infer the receiver is a `Path`: four in `core/textextract.py`
  (the JSON/HTML/XML/CSV readers), two in `commands/pack.py`, one in `commands/audiobook.py`
  and two in `scripts/rename_product.py` — plus one more the *review* caught, the write that
  recreates `product.json`, which on a non-UTF-8 locale truncated the single source of truth
  to 0 bytes before raising. `PLW1514` fires only on an inferable `Path` receiver, so it is
  the first gate, not the only one: `tests/test_text_encoding.py` scans shipped code by AST
  for what ruff cannot see. Worse, `text=True` on `subprocess` decodes with
  `locale.getencoding()`, so **every** adapter's output — `pdftotext`, `pandoc`, `tesseract`,
  `git` — came back cp1252-decoded on Windows; `café` in a PDF arrived as `cafÃ©`. Both
  `adapters.run` says `encoding="utf-8"` now; the two `Popen` calls in `core/actions.py`
  deliberately do **not** — a `--run` action is the user's own command line, and on Windows it
  emits the OEM code page, so forcing UTF-8 there would destroy recoverable text. They gained
  `errors="replace"`, which is what was actually missing. `carrel mcp` reconfigures its stdio
  to UTF-8: MCP frames are UTF-8 by specification, and fixing the adapters made real non-ASCII
  reach stdout where a strict cp1252 encode would have killed the server mid-session. Reading
  a user's document goes through one `textextract.read_text_file` now (`utf-8-sig`, so Excel's
  "CSV UTF-8" BOM stops naming the first column `\ufeffname`, plus `errors="replace"` so a
  cp1252 export still converts). Generated output that gets hashed — `pack`, `sign manifest`,
  `catalog export` — is written LF, so one tree no longer hashes two ways across platforms.
  CI passed throughout only because it sets `PYTHONUTF8=1`.
- 2026-09-11 (D-016): `handled` and `root_of` live once, in `core/output.py`. The decorator
  had 25 byte-identical copies and the desk-root resolver 12, plus four open-coded root
  lookups and three inlined copies of the decorator's body; `color.py` was importing
  `proof._handled` across modules. `audiobook` became a plain `@handled`; `convert` and
  `thumb` keep their per-file loops and share only `debugging(ctx)`. `handled` is now generic
  in the wrapped signature, so mypy checks calls through it. Found on the way: `watch
  --print-service` baked the *unresolved* `--root` and `--done-dir`/`--error-dir`/`--log`
  into the generated systemd unit, which runs from `$HOME` — a relative `--root` made the
  unit die on every start. `tests/test_command_conventions.py` is the drift gate and the
  first cover the `--debug` re-raise branch has ever had.
- 2026-09-10 (v0.4.0): released (GitHub Release + PyPI via Trusted Publishing, with a PEP 740
  attestation) and verified from PyPI in a clean venv: `carrel 0.4.0`, `doctor` 33 commands
  (31 ok, `mail` degraded without readpst, `desk` unavailable without the `tui` extra — both by
  design), and an end-to-end `intake` → `meta find` → `mail threads` against a fresh desk. The
  global `carrel[all]` install was upgraded.
- 2026-09-10 (v0.4.0, specs 23–28): the accounting-inbox release, in five PRs (#25, #26, #28, #29, #30).
  `meta` + `refs` (#25), email as a file type + `mail` (#26), `fields` + `rename` +
  `batch` + watch v2 (#28), the email review fixes (#29), and `intake`. Schema v2 adds
  the `meta` table (D-015); `core/patterns.py` is one registry for `redact --builtin` and
  `refs`; `core/actions.py` is the single `shell=True` site shared by `watch` and `batch`
  (D-013); `core/fsops.py` makes every move carry the desk row, which also fixed
  `organize --apply` orphaning tags and notes. `.msg` is cut (D-011), mail shape-sniffing
  is gated to extension-less files (D-012), and `intake` never destroys its input (D-014).
- 2026-09-10 three adversarial reviews ran before the release and found 42 verified defects
  between them (email 15, fields/rename/batch/watch 12, intake 15). Every one was fixed with
  a regression test. The ones worth remembering: `convert msg.eml --to pdf` rendered the
  sender's HTML, so a conversion fetched tracking pixels and could embed local files into the
  PDF (it renders the message text now); a negative amount on a labelled line was reported
  positive, booking a credit note as a charge; `core/actions.render` substituted placeholders
  in sequence, so a file named `{name}.txt` produced a shell command aimed at a different
  file; and `watch` silently dropped any new file whose name shared a prefix with one it was
  already processing.
- Build phases 0–7 complete (2026-07-16); v0.1.0 tagged.
- v0.1.1 on PyPI via Trusted Publishing (2026-08-12).
- 2026-09-03 hardening: owner rename, version SoT fix, `--json` everywhere, timeouts,
  ruff/mypy CI gate, SHA-pinned workflows, Dependabot, branch/tag rulesets, secret
  scanning + push protection, CodeQL (docs/REPO_SETTINGS.md).
- 2026-09-04: v0.1.2 released; PyPI Trusted Publisher re-pointed at owner `coltonbearden`.
- v0.2.0 wave 1 (specs/21): `docs/REFERENCE.md` is generated by `scripts/sync_reference.py`
  (CI fails on drift), `docs/COOKBOOK.md` renders every recipe and snippet on the docs site,
  CI runs `test-minimal` on macOS (required) and Windows (advisory) with an 80% coverage
  floor on the Linux matrix.
- 2026-09-09 (specs/22, v0.3.0): `carrel index` covers source and config files as
  `FileType.CODE`, the walk honours `.gitignore` (shared with `pack` via `core/ignore.py`),
  and `DeskDB.rel()` / PDF manifest entries emit POSIX separators (D-010).
- 2026-09-09 (v0.3.1): the ancestor `.gitignore` walk is bounded at the repo root or the
  caller's root; an unbounded walk contributes nothing (found verifying v0.3.0 from PyPI:
  `uv venv` writes a `*` gitignore that blanked a desk created inside it).
- 2026-09-09 Windows (PR #22): the full suite passes on `windows-latest`. Real defects fixed:
  `watch` crashed on action timeout (`os.killpg`), `CARREL_BIN_*` overrides counted any file
  as executable (`os.access(X_OK)`), notes tied on a coarse clock, the read-guard hook treated
  `C:\…` paths as relative, and the sync scripts wrote CRLF. Tests run hook scripts through
  Git for Windows' bash (the `bash` on PATH there is the WSL stub) and write fixtures as LF.
- 2026-09-10: v0.3.2 released (Windows fixes, note order, `search` score format) and
  verified from PyPI; global install upgraded to `carrel[all]` 0.3.2.
- 2026-09-09 doc-drift gate (D-g): `tests/test_docs_drift.py` fails when README or
  docs/MARKETPLACE.md lack a marketplace plugin, when docs/FEATURES.md grows an "In flight"
  section, or when any doc sample prints a version other than `product.json`'s; the `lint`
  job also runs `mkdocs build --strict`. `test-minimal (windows)` now runs the whole suite,
  still advisory (D-f).

## Open issues

- **The MCP boundary is a flag, not a mechanism.** `confine_to` is threaded to five walkers
  (`index._walk`, `pack._walk_dir`, `refs._candidates`, `mail._mail_files`, `fields.fields_for`),
  `confined_dest` to two writers, `_inside` to three result readers, and `_root` guards the desk
  directory. Five review rounds on #43 each found one more caller that had been missed, and the
  last — `<root>/.carrel`, the database's own location — was invisible to the registry-driven
  tests because it is neither a walk nor a path any schema names. The shape to aim at is `Desk`
  owning the primitives (`desk.open`, `desk.db`, `desk.walk`) so a new surface is confined by
  construction. **First item of v0.6.0**, before its mutating tools land on the same surface.

  The callers that *do not* pass it are the ones to watch, because none is reachable over MCP
  today and that is the only reason they are not holes: `rename.py:195` and `catalog.py:190`
  call the shared `candidate_files`/`_walk` without a boundary, as do `dedupe.py:39`/`:179`,
  `batch.py:42`, `edit.py:453`/`:474` and `desk/app.py:405`. **`rename` is first on v0.6.0's
  list.** Wiring `confine_to` tool-by-tool from the confined-caller list would miss it — which
  is the sixth round this entry exists to prevent.

- **Should `publish.yml` refuse a patch tag whose CHANGELOG entry says "Changed (behaviour)"?**
  D-023 settles the *rule* (a previously-successful invocation that can newly exit non-zero is a
  minor bump) and explicitly leaves the *enforcement* here. Enforcing it needs a CHANGELOG
  convention stricter than the one in use — today the bullet prefixes are a habit, not a schema.

- **`inspect` opens a CSV twice.** `src/carrel/commands/inspect.py::_csv_detail` reads a
  64 KiB sample for the dialect sniff, then re-opens and reads to EOF for the row/column count.
  Deferred in `84fc6db` and never logged until now. The cost is 64 KiB plus one full pass, not
  two full passes — worth fixing on large files, not urgent.

- **`docs/QUICKSTART.md` §6's captured output cannot be re-captured.** The block shows a
  tutorial `docs/` tree (5 files, 661 B, 186 tokens) that nothing in the repo builds, so a
  release can only update its `generated-by:` line by hand — which `docs/RELEASING.md`
  explicitly forbids. At v0.5.0 that line was changed after verifying by execution that the
  header renders `generated-by: carrel 0.5.0`; the counts are untouched and are still that
  tree's. Reconstructing the tree from the documented byte sizes lands within one token but is
  a fabrication, which is worse. Fix: commit the tree as a fixture with a capture script.

- **`pack --json --no-fail-empty` prints a plain-text `warning:` on stderr** — the one `--json`
  path that does not emit JSON there, and the flag the v0.5.0 CHANGELOG points script authors
  at. In spec as written (the contract covers *errors*; this is a warning) but inconsistent.
  Not changed inside the release that introduced the contract. Fix: route warnings through a
  sibling of `core/output.error_line`, or state in the contract that warnings stay plain.

- **Considered and declined in #43:** a per-call MCP `root` bounds the ancestor `.gitignore`
  walk at that root rather than at the server's launch root, so
  `carrel_refs {"path": ".", "root": "sub"}` does not apply `<desk>/.gitignore`. Left as is:
  the tool schema documents `root` as "Desk root", D-019 fixes the bound at the desk root, and
  the CLI behaves identically (`carrel --root sub refs .` vs `carrel --root desk refs sub`).
  Revisit if MCP v3 redefines the per-call `root` as "a subtree of the desk".

- 19 of 33 commands have no MCP tool, so an agent can read a desk but not act on it. Four are
  excluded by design (`watch` is a long-running loop, `desk` is a TUI, `completion` prints a
  shell script, `mcp` is the server). The other 15 are the gap: `audiobook`, `batch`,
  `catalog`, `color`, `dedupe`, `edit`, `extract-images`, `form`, `intake`, `ocr`, `organize`,
  `proof`, `rename`, `sign`, `thumb`. The headline three are `rename`, `batch` and `intake` —
  the whole v0.4.0 accounting-inbox pipeline is CLI-only, so the `bookkeeper` agent shells out
  for exactly the steps that move files. Most already have `_file()`/`_paths()` entry points
  the tool layer can call, and six headline `pack` flags remain agent-invisible. Its own spec
  (30), scoped as MCP v3: 14 → 25 tools (`batch` is cut — it is the single `shell=True` site).

- `watch --print-service schtasks` prints a one-line `schtasks /Create … /TR …` for pasting.
  The `/TR` value is now quoted correctly for both of Windows' own parsing passes (a parser
  model on every run; the real `CreateProcess` in the `test-minimal (windows)` job), but a
  paste goes through cmd.exe first, which toggles quoting at every `"` regardless of
  backslashes. An action containing `&`, `|`, `<`, `>`, `^` or a `%VAR%` reference is
  therefore split or expanded before schtasks sees it, and PowerShell does not treat `\"`
  as an escape at all; the printed REM lines now say so. The real fix is Task Scheduler XML
  (`schtasks /Create /XML FILE`), where the command and its arguments are separate elements
  and no shell is involved. That changes what `--print-service schtasks` prints and needs
  the accepted file encoding verified on Windows, so it is its own change rather than another
  fix round inside the v0.4.1 release PR.

- `watch` filters hidden paths only at start: `--existing` skips hidden entries and the
  `--done-dir`/`--error-dir` subtrees (`_existing_files`), but live events go through
  `_Watcher.seed`, which applies only `--glob`. So a `--recursive` watch with `--done-dir`
  queues `.git/` internals (or any dotfile) the moment something writes them, and files them
  away after the actions run. The spec-29 guard covers the usual case at start — a tree with
  tracked files refuses unless `--allow-tracked` — leaving a repository with nothing tracked
  yet, or an explicit override, as the exposure. Found probing the v0.4.1 guard; pre-existing since
  watch v2 (v0.4.0). Fix: apply the same hidden-component and skip-subtree test in `seed`,
  with a regression test that writes into `.git/` under a recursive watch.

- The build backend is unpinned. `pyproject.toml` asks for `hatchling` with no version and uv
  has no build constraint, and `uv build` has no locked mode, so every build — CI's and
  `publish.yml`'s — installs the newest hatchling at that moment. A release's PyPI files can be
  built by a backend no PR check ran. `publish.yml`'s `UV_LOCKED=1` covers only its `uv run`
  test step. Fix: pin `hatchling` exactly (in `[build-system] requires`, or through uv's build
  constraints — `uv build --build-constraint`), keep it bumped by Dependabot, and let CI's build
  job prove each bump.

- The suite cannot run under a non-UTF-8 locale: `LC_ALL=C PYTHONUTF8=0 uv run pytest -q`
  fails 45 tests across 9 files with `UnicodeDecodeError`. Every one is *test-side* —
  `subprocess.run(..., text=True)` and `Path.read_text()` in the harness, not in shipped code,
  which `tests/test_text_encoding.py::test_no_unencoded_text_io_in_shipped_code` now gates by
  AST (ruff's PLW1514 only fires on an inferable `Path` receiver, so it sees roughly an eighth
  of the sites and cannot see `(tmp_path / "a.txt").write_text(...)` at all). Fixing the
  harness is ~123 mechanical call sites across 30 files and would let CI add one
  `PYTHONUTF8=0` job, which is the only way to catch this class end to end. Deliberately not
  bundled into the encoding PR: the risky part of that PR is the product change, and a
  30-file test rewrite riding alongside it would obscure the diff.

- `tests/test_guardrails.py` adds a ninth near-verbatim copy of the `run()` CliRunner helper
  (also in `test_refs.py`, `test_desk_db_cmds.py`, `test_watch_org_dedupe.py`,
  `test_redact_sign_form.py` and others). `tests/conftest.py` is the shared-plumbing home;
  hoisting it is a whole-suite edit, deliberately not bundled into a behaviour PR.

- **No released carrel carries a pypdf security floor.** carrel 0.5.0 on PyPI still declares
  `pypdf>=5.0`: the raise to a security floor (D-026; #52 to 6.18.1, #64 to 6.19.0) is under
  Unreleased in `CHANGELOG.md`, so until the next release `pip install carrel` keeps whatever
  pypdf an environment already holds. 6.19.0 fixes three high advisories published on
  2026-10-01: GHSA-v247-6f48-mgcj (long runtimes reading embedded files), GHSA-php9-fj8v-98fj
  (long runtimes generating appearance streams when form fields are updated with flattening
  on) and GHSA-w23x-9jrw-r45c (large memory use reading alphabetical page labels). carrel
  reads neither embedded files nor page labels through pypdf, but `form fill` does reach the
  second. It calls `update_page_form_field_values` without `flatten`, and pypdf builds the
  appearance stream of every text and choice field either way: filling a list box that offers
  40,000 options took about 2.6 s on 6.18.1 and 0.3 s on 6.19.0, and about 145 s against
  1.2 s at 160,000 (a 1.5 MB PDF, timed twice), so an install of 0.5.0 beside an older pypdf
  can be stalled by a form someone else wrote. The owner decided on 2026-10-09 that the raise
  ships with v0.6.0, not in a release of its own. It crosses a hardening release (6.18.1),
  which D-026 reads as a minor bump, so that release is a minor either way.

- **Pillow's floor is `>=10.0`, below its ImageCms fix.** Found reviewing the pypdf floor
  (D-026). `color` and `proof` pass untrusted images to `ImageCms`, and Pillow 10.3.0 fixed a
  buffer overflow there (CVE-2024-28219); `pip install carrel` keeps an older Pillow. Deferred
  to the next release under the D-026 rule rather than raised here, because the rule wants each
  parser's advisories reviewed together (`pillow`, `openpyxl`, `markdown-it-py`) and the lock
  is already at Pillow 12.3.0, so the floor choice has room to be deliberate.

- **pypdf 6.20.0 came out the day #58 was reviewed, and `uv.lock` pins 6.19.0.** Published on
  2026-10-09, its one security item limits the work a single stream may cost (filter count
  and accumulated decoding work, pypdf #4173); 6.19.0 has no such limit. No advisory is
  published for it, so no alert is open. Not taken in #58: that PR was reviewed at 6.19.0 and
  closes four open alerts as it stands, it carries hand-made merge commits so Dependabot no
  longer refreshes it, and 6.20.0 also flattens the page tree differently and drops a null
  `/Kids` entry instead of raising, which wants a review of its own. Dependabot's weekly run
  (Mondays) should propose it; the floor follows the lock again when it lands (D-026). A
  raise touches `pyproject.toml`, the specifier in `uv.lock` (relock), the Unreleased
  `CHANGELOG.md` bullet that names the floor and `SECURITY_FLOORS` in
  `tests/test_dependency_floors.py`, which fails if the first is lowered or the changelog
  disagrees with it. Nothing checks any other document, so refer to the floor there rather
  than restate it: #64's review found two stale copies.

- **Dependabot proposes a release as soon as it is published.** `.github/dependabot.yml` sets
  no `cooldown`, and #58 locked ast-serialize 0.12.1 two days after its upload to PyPI
  (2026-10-03). #58's review compared every changed lock entry with PyPI's hashes and found
  nothing wrong; the gap is that a bad release would be proposed, and run in CI on the PR,
  before anyone had time to notice it. Fix: a `cooldown` block with `default-days` for both
  ecosystems, which delays version updates only, never security updates. Deferred from #58's
  review because how long to wait is the owner's call.

- **On Windows a timed-out `--run` action can outlive `kill_tree`.**
  `tests/test_core_cli.py::test_watch_timeout_orphan_check` failed once in #57's
  `test-minimal (windows)` job and passed on the re-run of the same commit: the watcher
  reported exit 124, and the worker still wrote its marker 4.5 s later. `core/actions.py`
  runs `taskkill /F /T` on the shell's pid and discards its exit code and output, so nothing
  says why the tree survived; the runner was slow (148 s for the suite against about 100 s),
  and a child created after taskkill's snapshot of the tree is the likely cause, unverified.
  A Windows user of `watch` or `batch --run --action-timeout` can get a worker that keeps
  writing after carrel reports it killed. It also bears on promoting `test-minimal (windows)`
  (Now): #57's review counted this as one failure in roughly the last sixty Windows jobs, and
  a required job that fails that often blocks merges at random. Fix: put the action in a
  Windows job object so the kill cannot miss a child, and report what taskkill said when it
  fails. Deferred from #57, a pin bump: the fix is Windows-only process code that can be
  tested only in CI.

- **A `watch` test with a four-second budget failed once on macOS, in a required job.**
  `tests/test_fields_rename_batch.py::test_watch_existing_stable_done_error_dirs_and_log`
  runs `watch --existing --timeout 4 --stable 0.2` and expects both files handled before the
  timeout. In #57's `test-minimal (macos)` job on 2026-10-09 the watcher printed its
  `watching` line and nothing else; the re-run of the same commit passed. With the Windows
  failure above that is two `watch` tests in one day that depend on how fast a runner is.
  `test-minimal (macos)` is required, so each such failure costs a manual re-run before a
  merge. Fix: give the test a budget that a slow runner meets, or wait on the event instead
  of the clock. Deferred from #65, which changes when CI runs, not what the tests assume.

- **The full-capability jobs depend on the runner's package mirror.** Each `test (py3.x)` job
  installs about 160 packages with `apt-get` before any test runs, usually in about a
  minute. In three runs on 2026-10-09 a job was still in that step ten minutes in; the one
  log read showed the Azure Ubuntu mirror serving packages slowly, not a hang. Two were
  cancelled and re-run by hand and the third was cancelled by the next push to `main`, which
  is why `main`'s `tests` run on #64's merge commit reads cancelled with six of seven jobs
  green. Left alone such a job ends at its 30-minute timeout as a red run that says nothing
  about carrel, and the weekly scheduled run has nobody watching it. Fix: a short timeout on
  the install step with one retry, or a cached package set. Deferred from #65: it needs its
  own look at what the allowed-actions list permits.

- **`context7-refresh` got HTTP 400 on 2026-10-09.** The run for #64's merge commit and its
  re-run both failed at `Request a refresh`; the run for #60's merge the night before
  returned 200. The request is the one Context7 documents (`POST /api/v1/refresh` with
  `{"libraryName": "/<owner>/<repo>"}`), and its docs give 400 as "invalid parameters". The
  workflow prints the status code only, by design, because the log is public, so the reason
  is not visible from here. Nothing depends on it: the check is not required and Context7
  re-indexes on its own schedule. It repeated on #65's merge, so three 400s on 2026-10-09,
  all within a day of the 200 at 01:10Z, which would fit a once-a-day refresh limit
  (unverified); Context7 still serves `/coltonbearden/carrel`. Next: see whether a run more
  than a day after the last 200 succeeds, and if not, read the response body in a session
  that holds the key.

- **A red weekly run does not show on the README.** The `tests` badge reads `test.yml` on
  `main`, which is the last push's result, and `gh run list --workflow test.yml` says the
  same; only the Actions tab and `gh run list --workflow weekly.yml` show `tests (weekly)`.
  Fix: a second badge for `weekly.yml`. Deferred from #65's review: until the first
  scheduled run exists (2026-10-12) the badge would read "no status", and the header is
  brand surface (D-024).

- **The weekly run cannot use the push runs' caches.** Called through `weekly.yml`,
  `github.workflow` is the caller's name, so every `setup-uv` step in `test.yml` gets a
  `tests (weekly)-<job>` cache key: each Monday's run starts mostly cold and saves about
  300 MB of caches that only the next weekly run could restore, if GitHub has not evicted
  them (the repository held 97 caches, 4.4 GB, on 2026-10-09). Nothing breaks. Fix: skip the
  cache save on `schedule`, or key by a literal name. Deferred from #65's review because the
  key shape is one of the rules #49's review set (`tests/test_workflows.py`), and changing it
  wants its own look.

- **`setup-uv`'s built-in checksums trail the uv that `uv.lock` pins.** The action checks the
  uv it downloads against a table compiled into it, and for a version the table lacks it
  takes both the download URL and the sha256 from a manifest fetched at run time
  (`astral-sh/versions`). 10.2.0's table ends at uv 0.12.17 and the lock pins 0.12.22, so
  every job, the release build in `publish.yml` included, trusts that manifest; the action's
  SHA pin does not cover it. Nothing is wrong today: 10.3.0 (published 2026-10-09) carries
  0.12.22, and #57's review found its three hashes equal to what the manifest serves.
  Dependabot's next run should propose 10.3.0, but uv moves weekly and the table moves only
  with the action, so the gap reopens unless the two are bumped together. Deferred from
  #57's review: 10.3.0 came out after the branch was reviewed and wants its own review.

- **No CI job installs the declared floors.** CI tests `uv.lock`, and every declared floor
  but one sits well below it: pillow 10.0 against 12.3.0, click 8.1 against 8.5.0, rich 13.0
  against 15.0.0, reportlab 4.0 against 5.0.1, watchdog 4.0 against 6.0.0, markdown-it-py 3.0
  against 4.2.0, textual 1.0 against 8.2.8. Code that uses a newer API of any of them passes
  CI and fails for a user at the floor. pypdf is level with its floor since #64, until the
  next Dependabot bump (6.20.0 is already out, above). Fix: a job running the suite after
  `uv pip install --resolution lowest-direct`. Deferred because other floors will need raises
  before it can be green — `pillow>=10.0` publishes no wheels past CPython 3.12, the oldest in
  carrel's matrix — which makes it a PR of its own.

- **pypdf's log is silenced wholesale.** `main` sets the `pypdf` logger to `CRITICAL` so a
  hostile file cannot flood stderr (D-026). That also hides the occasional useful warning on an
  honest file; `--debug` restores them. A counted summary ("pypdf: 50,000 warnings suppressed")
  would keep the signal. Not done yet.

- **carrel has no shared PDF-opening helper, so hostile-PDF handling stops at pypdf's own
  errors.** `core.output.pdf_refusal` maps pypdf's `PyPdfError`s to exit 4 by type. Three gaps
  remain, all found reviewing the pypdf-floor PR: (1) a malformed structure that makes pypdf
  raise a plain `ValueError` (`/MediaBox [ 0 ]` in `sign stamp`) or carrel's own loops raise a
  `TypeError` (`/Annots 9` in `note pdf`) is still exit 1 "unexpected error"; (2) the message
  does not say which file — `edit pdf a.pdf --merge b.pdf` on a hostile `b.pdf` leaves the user
  to guess (only `note` names it); (3) a pypdf error on a PDF carrel generated itself (`sign`'s
  reportlab overlay, `note pdf-add`'s read-back) is reported as the user's bad input. The fix
  for all three is one helper that opens *user input*, touches `.pages`, and converts pypdf's
  refusals and structural `ValueError`/`TypeError`s into `CarrelInputError(path, …)` where the
  path is known. Deferred because it touches every pypdf call site in seven commands — the same
  surface v0.6.0's confined accessor rewrites.

- **`main` reads `--json` and `--debug` from raw argv.** Its last-resort error handler and the
  pypdf log switch run where click's context is gone, so a literal `--json` or `--debug` passed as
  a positional after `--` is mistaken for the flag: JSON formatting of a last-resort error, or
  pypdf's log left on. `--debug` already worked this way; `--json` joined it with the
  pypdf-floor PR. Fix: invoke through `cli.make_context` so `main` can read `ctx.obj`.

- **At the next release, confirm `publish.yml`'s build ran uncached on the locked uv.** The
  `ci:` PR that took the release build off the shared uv cache and pinned uv through `uv.lock`
  could not exercise `publish.yml` — it only runs on a published release. In that run's `build`
  job, the setup-uv step should report the uv version `uv.lock` pins and restore no cache.
  `tests/test_workflows.py` holds the configuration; only a release proves the behaviour.

- **The setup-uv step is copied seven times across three workflows.** Folding it into a local
  composite action was the last item of the #49 review's cache finding and was not done: the
  parametrized `tests/test_workflows.py` now fails on any copy that drifts from the pin or
  cache rules, which was the risk the duplication posed, and a composite action would also
  need Dependabot's `github-actions` entry to list `.github/actions/*` so its pinned SHA keeps
  moving. Worth doing when a fourth rule arrives.

- **The `gh` ask rules are a prompt on two spellings, not a boundary, and the Pages policy
  covers one environment.** `tests/test_settings_permissions.py` lists what gets past
  `Bash(gh workflow run:*)` and `Bash(gh repo edit:*)`: under this file's own allows, a
  runner or a git option in front (`uv run gh workflow run ...`, `git rebase --exec '...'`);
  under the owner's user-level `Bash(gh:*)` and `Bash(gh api:*)`, the same command with a
  flag in the middle (`gh workflow -R <repo> run`) and `gh api`, which can dispatch a
  workflow, edit the repository or delete a deployment policy. `scripts/github-harden.sh` is
  allowed whole, and its apply mode writes repository settings. On the GitHub side the
  deploy-from-`main` policy applies to jobs that name the `github-pages` environment;
  `actions/deploy-pages` accepts another name, so a pushed branch with its own workflow file
  could still publish. Found by #66's review, which replaced "an unattended run cannot" with
  what the rules actually do. Fix: the PreToolUse hook of the next entry, extended to `gh`;
  narrower `uv run` allows; and for the script, allowing only `--verify-only`. Deferred
  because each changes what the release loop may do without a prompt, which the owner
  decides (he chose the two ask rules on 2026-10-09 and nothing wider).

- **`.claude/settings.json`'s deny list matches text, and git has more spellings than rules.**
  Under `Bash(git push:*)`, `git add:*` and `git commit:*` these still run unprompted: bundled
  short options with the flag after the first letter (`git push -uf`, `git commit -anm`),
  `git add -f .` and other stage-everything spellings (`git add -- .`, `git add pyproject.toml .`),
  quoted refspecs (`git push origin '+feature'`), colon-refspec deletion
  (`git push origin :feature`), and arguments split by a newline or tab. Each of D-027's two
  review rounds found more. The fix is the one the permissions docs recommend: a PreToolUse hook
  that parses `git push`/`add`/`commit` arguments (git's own option parser rules: bundles,
  unique prefixes, `+` and `:` refspecs) and refuses the destructive forms, with the deny list
  kept as the readable first line. `main` itself stays protected by the ruleset. Deferred as
  its own change: it is code with tests, not configuration.

- **pypdf 6.18 changed what `form fill` writes, and no test looks at appearance streams.**
  Found reviewing #50 and confirmed by filling `tests/fixtures/form.pdf` (`name` = "Hello")
  under both versions: 6.16.2's rebuilt `/AP /N` clips text to `4 2 212.0 16.0 re` and paints
  nothing else; 6.18.1 first paints the field's own `/MK` background (`0.8 0.843 1 rg f`) and
  border (`0.1 0.1 0.1 RG s`), then clips to `4 2 208.0 14.0 re`. So filled fields gain the
  background their form declared, and a value that exactly fit before can now be clipped at
  the right edge. `NeedAppearances` stays true, so viewers that regenerate appearances are
  unaffected. Deferred rather than pinned because the change is upstream, honours the form's
  own `/MK`, and reaches every install through the raised pypdf floor once that ships (D-026) — a
  documented, upstream behaviour change; a byte-level assertion on pypdf's stream would break on its next
  cosmetic change. Fix: a test that fills a field to its width and asserts the value's glyphs
  are inside the clip box, not the stream's bytes.

- **Nothing pins what `note pdf-add` writes beyond `/Subtype` and `/Contents`.** #50's review
  predicted pypdf 6.18.1 (#4051) would change the FreeText `/DA` colour; run against both
  versions, the annotation is byte-identical (`/DA '0.0 0.0 0.0 rg'`, `/C [1,1,1]`, the same
  `/DS`, no `/AP`), so that part was wrong. What stands: the `/DA` pypdf writes has no `Tf`
  font operator, which the PDF spec requires in a default appearance string, and no test would
  notice a regression in colour or font. Fix: assert `/DA` and `/DS` in
  `tests/test_desk_db_cmds.py`, and set the font in `/DA` ourselves if a viewer is found that
  mis-renders it.

- **`test_ocr_requested_without_the_binary_exits_3` cannot fail** (#60's review; it predates
  #60). It runs `intake --ocr` without `--apply` and asserts `not (dest / "2026").exists()`. A
  dry run creates nothing under `dest` whether or not the `ocrmypdf` pre-flight fires, so
  deleting `adapters.require("ocrmypdf")` leaves it green, and from 2027 the year no longer
  names the folder the scan would land in. The guard its comment claims ("exits before
  anything moved") needs `--apply`, the inbox asserted intact and `dest` asserted to hold no
  files (`dest` itself is created before the pre-flight), revert-checked against the
  pre-flight. Deferred from #60: that PR repaired a red `main` and changed only what the
  clock decided.

## Key facts for a fresh session

- Stack: Python ≥3.12 + uv; click CLI; Textual TUI (`carrel desk`); hatchling build.
- Product identity: `product.json` is the SoT. Bump there, run `scripts/sync_product.py`,
  never edit `pyproject.toml` version / `_product.py` / manifest versions by hand.
- Generated docs: `docs/REFERENCE.md` comes from `uv run python scripts/sync_reference.py`
  (`--check` in tests and the lint job). Never edit it by hand; add a command to
  `carrel.cli.COMMANDS` and regenerate.
- Doc samples: `tests/test_docs_drift.py` lists every doc line whose sample output shows a
  version other than `product.json`'s. After a bump, re-run the command in that block and
  paste its output (docs/RELEASING.md step 1) — never hand-edit the numbers.
- Extras (v0.2.0, specs/19, D-007): `tui` (textual, for `carrel desk`), `office`
  (openpyxl), `tokens` (tiktoken), `all`. A checkout uses `uv sync --all-extras`;
  the `test-minimal` CI jobs install none and must stay green via skips.
- `main` is protected: changes land via PR with green `lint`, `test (py3.12)`, `test (py3.13)`,
  `test (py3.14)`, `test-minimal` and `test-minimal (macos)` (the list is `REQUIRED_CHECKS` in
  `scripts/github-harden.sh`, mirrored in docs/REPO_SETTINGS.md; macOS was added 2026-09-11).
  `test-minimal (windows)` runs the full suite and has passed since PR #22, but stays advisory
  (`continue-on-error`) until it has been green on `main` for two consecutive weeks. The
  failure-by-module list in docs/BUILD_PLAN.md is a 2026-09-09 snapshot, kept as history.
  Repo admin can bypass in an emergency. Do not run `scripts/finalize.sh` — it relocates the
  tree and creates a new repo; it was for the original hand-off only.
- Marketplace: `claude plugin validate .` → `claude plugin marketplace add coltonbearden/carrel`
  → `claude plugin install <plugin>@carrel`.
- `HANDOFF.md` at the repo root is session-local (regenerated by the handoff skill) and
  git-ignored.
- `gh workflow run` and `gh repo edit` prompt in an interactive session, whatever else is
  allowed (ask rules, D-029). A headless run (`claude -p`) has nobody to ask: the command is
  refused and the run carries on. The weekly run needs no dispatch. The rules match those two
  spellings only (Open issues).
- `weekly.yml` (`tests (weekly)`) runs `test.yml` on `main` every Monday at 06:17 UTC (D-028).
  In a public repository GitHub disables a scheduled workflow after 60 days without
  repository activity: if `gh run list --workflow weekly.yml --event schedule` goes quiet,
  `gh workflow enable weekly.yml`. The schedule is kept out of `test.yml` so that rule can
  never reach the required checks.
- `uv.lock`'s `revision` line may flip between 3 and 5: the uv this lock pins (0.12.22) writes
  5 on any relock, Dependabot's updater wrote 3. uv documents a revision as a
  backwards-compatible addition that older versions read without error; only `version` is a
  breaking change.
- `carrel index` indexes source/config files as type `code` (`--no-source` opts out) and
  honours `.gitignore` (`--no-gitignore` opts out). `files.type` must stay a `FileType` value:
  `desk/app.py` calls `FileType(info["type"])` on it (D-010).
