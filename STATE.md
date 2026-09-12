# STATE

> Live status of the project. A brand-new session should be able to resume from this file alone.
> Build history: docs/HOW_THIS_WAS_BUILT.md. Decisions: docs/DECISIONS.md. Release steps: docs/RELEASING.md.

## Now

- **Status:** v0.4.1 "consolidation and guardrails" is the current release (2026-09-11); its
  verification record is the v0.4.1 entry under Done. 33 commands, 14 MCP tools, 19 adapters,
  9 marketplace plugins, desk schema v2. Repo `coltonbearden/carrel`, docs at
  https://coltonbearden.github.io/carrel/, PyPI package `carrel`.
- **In flight:** v0.5.0 "the first five minutes" — the defect/boundary/positioning wave.
  Landed: #38 (permissions), #39 (the gate), #40 (the owed review's findings), #41 (pack
  `.gitignore`, loud empty `--query`), #42 (guard honesty), #43 (MCP confinement,
  `--allow-tracked`), #44 (platform install hints, counts, PyPI metadata, JSON errors),
  #45 (README positioning), #46 (the release itself). The full record lands in the
  post-release `docs(state)` PR.
- **Next:** MCP v3 (`specs/30-mcp-v3.md`): 11 new tools, 14 → 25, with `rename` and `intake`
  first so the accounting-inbox pipeline stops being CLI-only. `batch` is cut from that wave —
  it is the single `shell=True` site (D-013) — and `audiobook`, `color` and `proof` are
  deferred; the spec says why. **First**, replace the `confine_to` flag threaded through five
  walkers with one confined filesystem accessor (see Open issues) — that wave adds mutating
  tools to the same surface.
- **Also pending:**
  - ~~**A review is owed.**~~ **Done 2026-09-12.** The v0.4.1 second-review fixes
    (`refs/pull/36/head`, `5b88c7a`) were reviewed; the eleven confirmed findings shipped as
    #40. Do not re-run it.
  - **Owner's step, on or after 2026-09-24:** promote `test-minimal (windows)` to required once
    it has been green on `main` for two consecutive weeks. That changes branch protection, so it
    needs the owner's go-ahead in that session: drop `continue-on-error` in
    `.github/workflows/test.yml`, add the check to `REQUIRED_CHECKS`, then run
    `scripts/github-harden.sh`. (`test-minimal (macos)` was added on 2026-09-11 under the
    owner's authorisation in the v0.4.1 brief.)

## Done

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

- 19 of 33 commands have no MCP tool, so an agent can read a desk but not act on it. Four are
  excluded by design (`watch` is a long-running loop, `desk` is a TUI, `completion` prints a
  shell script, `mcp` is the server). The other 15 are the gap: `audiobook`, `batch`,
  `catalog`, `color`, `dedupe`, `edit`, `extract-images`, `form`, `intake`, `ocr`, `organize`,
  `proof`, `rename`, `sign`, `thumb`. The headline three are `rename`, `batch` and `intake` —
  the whole v0.4.0 accounting-inbox pipeline is CLI-only, so the `bookkeeper` agent shells out
  for exactly the steps that move files. Most already have `_file()`/`_paths()` entry points
  the tool layer can call, and six headline `pack` flags remain agent-invisible. Its own spec
  (30), scoped as MCP v3: 14 → 25 tools (`batch` is cut — it is the single `shell=True` site).


- v0.4.1 ships a documented behaviour change (`--apply` refuses tracked files, exit 2) as a
  **patch** bump. The release review argued for 0.5.0: a `carrel~=0.4.0` pin or a routine
  `uv tool upgrade` pulls it in, and a cron `intake --apply` whose `--to` sits under a
  dotfiles repo could start exiting 2. Kept at 0.4.1 because the session brief named that
  version; the guard only bites on *tracked* files, and `--allow-tracked` is the documented
  way through (spelled `--force` before v0.5.0 — D-022; the alias is kept, with no
  removal date). **Decided in v0.5.0 (D-023):** a previously-successful invocation
  that can newly exit non-zero is a minor bump, so this wave is 0.5.0. Still open:
  whether `publish.yml` should refuse a patch tag when the CHANGELOG entry says
  "Changed (behaviour)".

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

- ~~`--force` carries two unrelated meanings.~~ **Decided in v0.5.0 (D-022):** the
  tracked-files guard on `rename`, `organize`, `intake` and `watch` is overridden by
  `--allow-tracked`, which is not reachable by reflex from the "overwrite existing output"
  meaning `--force` keeps on `mail`, `edit`, `sign`, `form`, `catalog`, `meta` and
  `audiobook`. `--force` stays on all four as a deprecated alias that warns once when the
  guard is actually consulted; it is not removed and no removal date is set.

- **`docs/QUICKSTART.md` §6's captured output cannot be re-captured.** The block shows a
  tutorial `docs/` tree (5 files, 661 B, 186 tokens) that nothing in the repo builds, so a
  release can only update its `generated-by:` version line by hand — which
  `docs/RELEASING.md` explicitly forbids ("never hand-edit the numbers in real output"). At
  v0.5.0 that one line was changed after verifying by execution that the header renders
  `generated-by: carrel 0.5.0`; the counts were left untouched and are still that tree's.
  Reconstructing the tree from the documented byte sizes gets within a token (187 vs 186) but
  is a fabrication, which is worse. Fix: commit the tutorial tree as a fixture with a capture
  script, so §6 is regenerated like `docs/REFERENCE.md` rather than transcribed.

- **`pack --json --no-fail-empty` prints a plain-text `warning:` on stderr**, the one `--json`
  path that does not emit JSON there — and the v0.5.0 CHANGELOG points script authors straight
  at that flag. In spec as written (the stderr contract covers *errors*, and this is a warning)
  but inconsistent in practice. Not changed in the release PR: altering the stderr shape again
  inside the release that introduces the contract is worse than documenting it. Fix: route
  warnings through `core/output.error_line`'s sibling, or say in the contract that warnings stay
  plain.

- **Deferred from PR #43:** the MCP boundary is threaded as a `confine_to` flag into
  five separate walkers (`index._walk`, `pack._walk_dir`, `refs._candidates`,
  `mail._mail_files`, `fields.fields_for`) plus `confined_dest` at two writers,
  rather than fixed once in a confined filesystem accessor. Four review rounds
  each found "one more caller also does this" — four walkers, then `mail`, then
  the write side and the stored index rows, then `<root>/.carrel` itself — which
  is the argument for one
  `iter_files(top, confine_to=...)` every walker uses. Not done here: it is a
  cross-module refactor of five walkers with different ignore-stack shapes, in a
  PR that is already 37 files, and the regression risk lands on `pack` and
  `index`, the two most-used commands. The registry-driven tests
  (`test_no_tool_reads_through_a_symlink_planted_in_the_desk`,
  `test_every_tool_refuses_a_root_outside_the_server_root`, and their write-side
  twin) drive every (tool, action) pair from `mcp.TOOLS` — but they only see
  surfaces that walk or write a *named* path, which is exactly why the `.carrel`
  hole survived them. The shape to aim at is `Desk` owning the primitives
  (`desk.open`, `desk.db`, `desk.walk`) so a new surface is confined by
  construction. **Do this first in the MCP v3 wave (v0.6.0)**, before its
  mutating tools land on the same surface.

- **Considered and declined in PR #43:** a per-call MCP `root` bounds the ancestor
  `.gitignore` walk at that root, not at the server's launch root, so
  `carrel_refs {"path": ".", "root": "sub"}` does not apply `<desk>/.gitignore`.
  A review argued the same file should give the same answer whichever way the
  client addresses it. Left as is because the tool schema documents `root` as
  "Desk root (default: server --root / cwd)" — a client naming `sub` is naming a
  desk, and D-019 fixes the bound at the desk root, so this is the documented
  semantics rather than a defect. The CLI behaves identically
  (`carrel --root sub refs .` versus `carrel --root desk refs sub`). Revisit if
  MCP v3 makes the per-call `root` mean "subtree of the desk" instead.

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
- `carrel index` indexes source/config files as type `code` (`--no-source` opts out) and
  honours `.gitignore` (`--no-gitignore` opts out). `files.type` must stay a `FileType` value:
  `desk/app.py` calls `FileType(info["type"])` on it (D-010).
