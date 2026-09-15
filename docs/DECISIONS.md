# DECISIONS

Format: `D-NNN (date) — decision — rationale — consequences`.

## D-001 (2026-07-16) — Marketplace schema locked to live docs

Fetched https://code.claude.com/docs/en/plugin-marketplaces and /plugins-reference during planning. Confirmed shape: `.claude-plugin/marketplace.json` at repo root (`name`, `owner`, `plugins[]` with `name` + `source: "./plugins/<n>"`, optional `metadata.pluginRoot`); each plugin has `plugins/<n>/.claude-plugin/plugin.json` (only `name` required) with default-scanned `commands/`, `skills/<skill>/SKILL.md`, `agents/`, `hooks/hooks.json`, `.mcp.json`; scripts use `${CLAUDE_PLUGIN_ROOT}`. Validation: `claude plugin validate`. Install: `claude plugin marketplace add` + `claude plugin install <p>@<m>`. Consequence: scaffold conforms to this; re-check cheaply at Phase 2.

## D-002 (2026-07-16) — Stack: Python ≥3.12 + uv

Dev box has Python 3.14.4 and uv 0.11. Python's file-format ecosystem (pypdf, Pillow, etc.) beats Node's for this capability set; uv makes installs fast and reproducible. External binaries only via one adapter layer with capability detection; `doctor` command re-probes. Consequence: `pyproject.toml` project, `uv run pytest`, entry points via `[project.scripts]`.

## D-003 (2026-07-16) — Flagship experience: Textual TUI

TUI dashboard (file browser + inspector + actions) sharing the core library with the CLI. Chosen over local web UI: finishable in one session, impressive in a terminal-first WSL environment, zero extra runtime surface. Fallback if it slips: cut to a rich-based interactive picker and document in FEATURES.md.

## D-004 (2026-07-16) — No forced installs of optional binaries

Phase 0 only inventories. Features degrade gracefully (exit 3 + install hint); `doctor` prints per-feature status. Bias from the directive honored.

## D-005 (2026-08-12) — Publish to PyPI via Trusted Publishing

Releases are built and uploaded by `.github/workflows/publish.yml` when a GitHub Release is published; PyPI authenticates the workflow with OIDC (no API token stored anywhere). Consequence: the PyPI project's trusted-publisher entry must name the exact owner/repo/workflow/environment — it had to be re-registered when the repo changed owner (D-006).

## D-006 (2026-09-03) — Repo lives at coltonbearden/carrel; versions bump only through product.json

The repository moved from `FirstCastSolutions423/carrel` to `coltonbearden/carrel`. The v0.1.1 release had bumped `pyproject.toml` directly, so the published wheel reported 0.1.0 and CI was red for three weeks. Rule: edit `product.json`, run `scripts/sync_product.py`; it regenerates `_product.py`, `pyproject.toml` (version, description, urls), plugin/marketplace manifests, and `CITATION.cff`, and `tests/test_product_sync.py` enforces agreement. `main` is protected by a ruleset requiring a PR with green CI (admin bypass only), so a drift like this cannot be merged again.

## D-007 (2026-09-04) — Optional extras; Textual becomes `carrel[tui]`

v0.2.0 introduces `[project.optional-dependencies]`: `tui` (textual), `office` (openpyxl), `tokens` (tiktoken), `all`. Textual leaves the core dependency list: agents and scripts that only run `pack`/`index`/`search`/`convert` should not pull a TUI framework, and future heavy dependencies (embeddings, PAdES) need the same mechanism. Consequence: `carrel desk` on a plain install exits 3 with the hint `uv tool install 'carrel[tui]'` (the guard already exists in `commands/desk.py`); README quickstart shows `carrel[all]`; every extra-gated feature degrades with exit 3 and the extra's name, exactly like a missing binary. Spec: `specs/19-install-ergonomics.md`.

## D-008 (2026-09-04) — `CARREL_BIN_<NAME>` is the single exception to config-free

carrel stays config-free (no config file, no dotfile). One environment-variable family is added: `CARREL_BIN_<ADAPTER>=/path` pins the exact binary an adapter uses, bypassing `PATH` search. Rationale: WSL users routinely have a Windows binary shadowing a Linux one via interop, and CI images sometimes ship several versions; there was no way to choose. A set-but-missing path counts as missing and the error names the override, so a stale variable cannot silently fall back. `doctor` shows `via CARREL_BIN_*`. Spec: `specs/19-install-ergonomics.md`; documented in `docs/CONFIGURATION.md`.

## D-009 (2026-09-04) — Desk DB schema is versioned; migrations are the only way to change it

`.carrel/carrel.db` gains `PRAGMA user_version` and an ordered `MIGRATIONS` list in `core/db.py`; version 1 is the v0.1.x schema, and pre-v0.2.0 databases (user_version 0) are stamped 1 on open. Tags and notes — the only data the desk cannot regenerate — become portable through `carrel catalog export/import`. Rationale: later features (page-aware chunks, stored text, embeddings) all need schema changes, and without a version there is no safe path. Consequence: any spec that changes the schema appends a migration and a test that opens the previous version. Spec: `specs/17-catalog.md`.

## D-010 (2026-09-09) — Source files are one `FileType.CODE`, not one type per language

`carrel index` skipped every path `detect()` typed `UNKNOWN`, i.e. every source file, so
`pack --query`, `search`, and the `carrel-agent` reindex hook were all blind to source trees
(spec 22). Source files become `FileType.CODE`, with the per-language label kept outside the
database in `SOURCE_EXTENSIONS`.

One enum member rather than `python`/`rust`/… as stored types, because `desk/app.py` does
`FileType(info["type"])` on the value `index` wrote: anything that is not an enum member
crashes the TUI preview. Keeping it a member also makes `search --type code` work for free
(`_valid_types()` derives from the enum) and leaves `convert`'s `supported_targets` — derived
from the `CONVERTERS` pair list — correctly empty, so `convert foo.py --to pdf` still exits 4.

`SOURCE_EXTENSIONS` stays separate from `_EXT_MAP` so `.json`/`.xml`/`.csv`/`.md` keep their
richer types and `detect_or_die`'s "supported:" message does not grow to ~80 entries. No
schema migration: `files.type` is free-form `TEXT` (D-009's `MIGRATIONS` is untouched).

Consequence: the `.gitignore` matcher moved from `pack.py` to `core/ignore.py` so `index`
shares it — without it a source tree would drag in `node_modules/` and `build/`. Also folded
in: `DeskDB.rel()` and `sign._manifest_entry_path()` now return `.as_posix()`, since
`files.path` is what `export_catalog` writes and a native separator made a catalog written on
Windows unimportable on Linux.

## D-011 (2026-09-10) — Outlook `.msg` is cut; Outlook comes in through `.pst`

`tests/test_core_filetypes.py::test_support_matrix_covered` requires a generated fixture for every `FileType`, and `tests/fixtures/generate.py` may only produce fixtures programmatically (never hand-edited binaries). No pure-Python writer exists for Outlook's OLE `.msg` container, so a `FileType.MSG` could not be tested honestly. Consequence: `.eml` and `.mbox` ship (stdlib), `carrel mail pst` converts Outlook exports through `readpst` (`pst-utils`), and `.msg` is logged in the FEATURES cuts. Revisit if a maintained pure-Python MSG writer appears.

## D-012 (2026-09-10) — Text-format sniffing never overrides a mapped extension

`detect()` keeps "bytes beat names" for binary signatures (`%PDF`, PNG, zip containers). Email has no signature, only a shape (an RFC 5322 header block; an mbox `From ` separator line), and a shape sniff that outranked extensions would turn any `.txt` beginning with `From:` into a message. Rule: shape sniffs run only for files whose extension is not in `_EXT_MAP` (after the source-file check). Consequence: `.eml`/`.mbox`/`.mbx` by name, extension-less exports by shape, everything else unchanged.

## D-013 (2026-09-10) — `batch` shares `watch`'s direct-subprocess exception

User-authored shell actions cannot go through the adapter registry. Rather than a second ad-hoc `subprocess` site, `watch`'s quoting, rendering and process-group killing move to `core/actions.py`, and `batch` (spec 26) is the second and last command that runs them; CLAUDE.md and ARCHITECTURE name both. Consequence: one place owns Windows quoting (`list2cmdline`) and tree kills (`taskkill /T`).

## D-014 (2026-09-10) — `intake` never destroys its input

When `intake` OCRs a scanned PDF, the OCRed copy is what gets filed and the original moves to `DEST/_originals/<filed name>`; without `ocrmypdf` the file is filed un-OCRed with `ocr: "unavailable"` in its record (never exit 3 mid-batch; `--ocr` requested explicitly with the binary absent exits 3 before any move). Every move is collision-safe and dry-run is the default. Consequence: an intake run can always be undone by moving files back.

## D-015 (2026-09-10) — Schema v2 adds `meta`; values are canonical and typed

`.carrel/carrel.db` gains a `meta(file_id, key, value, kind, source, updated)` table through the migration mechanism of D-009. Kinds (`str|num|date|bool`) are inferred unless forced, values are stored canonically (`1,234.50` → `1234.5`, ISO dates, `true`/`false`; digit strings with a leading zero stay `str`), and every write path — CLI, MCP, `catalog import` — goes through the same `coerce_meta`, so a comparison such as `total>1000` or `due<2026-11` is meaningful. Catalog documents are `schema: 2`; schema-1 documents still import. Consequence: any automation that fills fields names itself in `source`.


## D-016 (2026-09-10) — One `handled`, one `root_of`, in `core/output.py`

The `@_handled` decorator that turns a `CarrelError` into a clean message plus its exit code was copy-pasted into 25 command modules, and the `_root_of(ctx)` desk-root resolver into 12 — byte-identical every time, so the exit-code convention in CLAUDE.md depended on 25 copies never drifting, and `color.py` had already resorted to importing `proof._handled` across modules. Both are now public helpers in `carrel.core.output`, beside `emit` and `fail` which they call, and `handled` is generic in the wrapped signature so mypy still checks calls through it.

Four more root lookups were open-coded rather than named (`organize`, `watch`, `pack`, `desk`) and three modules inlined the decorator's body as a `try/except CarrelError`. `audiobook` was a straight drop-in for `@handled`; `convert` and `thumb` deliberately are not — they record an error per source and keep going — so the part they do share, the `--debug` re-raise decision, is now `debugging(ctx)` in the same module.

Consequence: a command module imports `handled`, `root_of` and `debugging` and never redefines them. `tests/test_command_conventions.py` fails the build if a private copy comes back, if the root lookup is open-coded again, or if the set of modules that skip `@handled` changes without a stated reason; it also covers the `--debug` re-raise branch, which nothing else in the suite did.

## D-017 (2026-09-11) — The bulk-move guard asks "is it tracked?", not "is it in a repo?"

`rename --apply`, `organize --apply`, `intake --apply` and `watch --done-dir/--error-dir` refuse when the move would touch a file git is tracking (spec 29; the motivating incident renamed 21 tracked files in this checkout). Three scope decisions, each a deliberate narrowing:

1. **Tracked, not merely inside a work tree.** `~` under a dotfiles repository is a mainstream layout, so "inside a repo" would make `intake ~/Downloads --to ~/Documents/filed` refuse forever with `--force` the only way out — the reflex the guard exists to prevent. `git ls-files -- <paths>` separates `~/Downloads` (untracked, fine) from `src/carrel/commands/` (tracked, the incident). Without the git binary the question is unanswerable, so being inside a work tree counts and the message says so.
2. **Explicit file arguments are guarded too.** The first draft exempted them ("naming a file is a decision at the granularity of the damage"). A shell glob refutes that: `rename src/carrel/commands/*.py --apply` arrives as 21 file arguments and is the original incident keystroke for keystroke.
3. **`--apply` only, and after argument validation.** Dry-run is never guarded, and a bad `--into` or template reports itself rather than being masked by a refusal.

Consequence: `git` becomes load-bearing for a safety property, so `repo_root` never raises and trusts git's answer in both directions (a ceiling directory or a malformed `.git` means "not ours"), and every git call drops `GIT_DIR`/`GIT_WORK_TREE` so a run from inside a git hook is not told about the hook's repository. The refusal is a `CarrelUsageError` (exit 2) rather than `click.UsageError`, which would print a `Usage:` banner implying the arguments were malformed, and which would put the CLI framework inside `core/`.

## D-018 (2026-09-12) — An empty `pack` is an error under `--json`, and the reason travels with the result

`carrel pack --query` that matched nothing exited 0 with a valid, empty document. FTS5 AND-s the terms of a query, so a natural-language question ("how do I cut a release") matches nothing far more often than users expect — and an empty pack is indistinguishable from a successful one, which makes it the failure a caller is least likely to notice.

A pack that found no files now names the reason on stderr in every mode, and exits **5** by default under `--json`. `--no-fail-empty` restores exit 0; human mode still exits 0 by default and `--fail-empty` opts in. This is a behaviour change for scripts that pipe `pack --json --query`.

Three scope decisions, each from the review that followed:

1. **"Empty" means no file reached the pack, not "nothing was inlined."** A directory of images packs a complete, useful tree with `files_included == 0`, and so does `--tree-only`; `--max-file-bytes` can skip every file and still leave a correct listing. Failing those would break good packs. A `--since` whose only change was a deletion is likewise not empty — `removed` is the answer the caller asked for.
2. **The reason names the filter that actually emptied the result**, in pipeline order (`--since`/`--changed`, then `--query`, then paths and globs). Blaming `--query` whenever one was present told users to loosen a query that had matched when `--since` was the cause.
3. **The signal lives on `PackResult.empty_reason`, not in the click layer.** The MCP `carrel_pack` tool and the desk TUI call `pack_paths` directly; putting the check in the command would have left an agent — the caller the change exists for — reading a valid-looking empty payload with no diagnostic. The tool has no exit code, so it carries the sentence instead.

Consequence: the exit-code tables in `docs/ARCHITECTURE.md`, `docs/CONTRIBUTING.md` and the generated `docs/REFERENCE.md` no longer condition 5 on the flag, and `specs/16-pack-query.md` records the new contract.

## D-019 (2026-09-12) — The ancestor `.gitignore` walk is bounded by the **desk root**, for `pack` as well as `index`

`carrel pack src --stats --tree-only` listed 45 `__pycache__` entries from this repo while `carrel pack .` listed none — the README's own `pack.gif` command, packing build artefacts into a context window. `ancestor_ignores` returns nothing when its `top` equals its `stop_at`, and `pack` passed the packed arguments' **common path** as `stop_at`, which for a single directory argument *is* that directory. So the walk stopped before reading anything.

`pack` passes the desk root now — `--root`, default the cwd — which is what `index` already passed. One call site; the walker is unchanged.

**The alternative was tried and reverted.** Making the walk run to the *worktree root* regardless of `stop_at` is what git itself does (`git check-ignore` consults every `.gitignore` up to the repository root), and it fixes `pack src` too. It also reinstates the v0.3.1 incident: `uv venv` writes a `.gitignore` containing `*`, venvs normally live inside a checkout, and a desk under one then indexed zero files again with nothing to explain it. The v0.3.1 rule — never consult anything above the scope the user declared — outranks matching git's semantics, because the user naming a directory is a stronger signal than an ancestor's ignore file.

One narrowing came with it: when `top` is **outside** `stop_at` entirely, the walk now returns nothing rather than falling back to the repository root, for the same reason. There is no declared scope covering that path, and an unbounded walk contributes nothing (the existing rule).

Consequence: `tests/test_pack.py` pins all three — the subdirectory case, a desk inside a `.venv` inside a repository, and a `$HOME` dotfiles work tree whose `.gitignore` is `*`.

## D-020 (2026-09-12) — The guard converts what `Read` cannot open; images stay pictures

`carrel-guard`'s README said Claude's `Read` "cannot parse PDFs, Word/OpenDocument/EPUB/RTF files, spreadsheets, email files **or images**". Per the [tools reference](https://code.claude.com/docs/en/tools-reference) it returns images as visual content Claude can see and reads PDFs natively (in `pages` ranges past ten pages), so the claim holds only for `.docx .odt .epub .rtf .xlsx .eml .mbox .mbx`. The guard behaved as if the README were true, and OCR'd every image Read with no way to turn it off — replacing a picture Claude could already see with a worse transcription of a screenshot, a chart or a photo.

Three defaults follow from what `Read` actually does:

1. **Formats `Read` cannot open are converted.** Pure gain, no decision to make.
2. **PDFs are converted, but the conversion is a *token* saving, not a capability.** Page images cost far more than the text, so text stays the default; `CARREL_GUARD_PDF_TEXT=0` returns them to the visual `Read` when layout or diagrams carry the meaning.
3. **Images are left alone.** `CARREL_GUARD_OCR_IMAGES=1` opts in. `.ico` sits behind the same switch for consistency rather than for the same reason — `Read` cannot render an ICO container either, so OCR is the only text carrel can offer for one.

Timeouts became visible with it. The budget was 5 s, which measurement showed kills ordinary documents: `carrel convert --to txt` takes 2.4 s on a 33 KB pandoc-written docx, 6.7 s on 68 KB and 13.9 s on 127 KB, against 0.28 s for a 600-page PDF. It is 15 s now, and a timeout reports itself rather than exiting 0 in silence — `additionalContext` with no `updatedInput`, which the [hooks reference](https://code.claude.com/docs/en/hooks) allows, the decision fields being independent. The note differs by format, because "reading the original instead" is only true where `Read` can open it; for a docx it says the following Read will fail and names the manual conversion.

Consequence: a killed conversion's partial output is deleted rather than served — `carrel convert` writes the text in one call, so SIGTERM mid-write truncates it, and the truncated file is newer than its source, so the freshness check would have cached it forever. And `hooks/hooks.json` caps the hook at 60 s, so a budget above that cannot be reached; the note and the tunables table say so.

## D-021 (2026-09-12) — `carrel mcp` is confined to the directory it was started in

`SECURITY.md` listed "the MCP server reading or writing outside its root" among the reports it cares about most, and the server did exactly that: `_resolve` accepted any absolute path, `_root` accepted any client-supplied `root`, and no confinement code existed in the module. A server started in `docs/` returned `carrel_inspect` metadata for `/etc/hostname` and served the contents of `/tmp/…/secret.txt` through `resources/read carrel://file/…`. The documented property was false, which is worse than an undocumented gap: it is what a reader relies on when deciding what to point the server at.

The root is `Path(default_root).resolve()` — `--root` when given, otherwise the working directory the server was started in — recorded once at startup on a frozen `Desk`. Every path a client can name goes through `Desk.resolve()`: the `path`/`paths`/`out_dir` arguments of all fourteen tools, the per-call `root`, and the `carrel://file/` and `carrel://search/` handlers. There is no second way in, which is the point — a rule applied at twenty-seven call sites is a rule that gets forgotten at the twenty-eighth.

Symlinks resolve **before** the test, so a link inside the root pointing out of it is refused rather than followed. Outside → a tool result with `isError: true` and exit code 2 naming the root; for resources, the server's existing resource-not-found shape, because the resource protocol has one failure shape and a distinct refusal there would turn `resources/read` into an existence oracle for the disk.

`--allow-outside-root` lifts it for the session. Two consequences worth stating: a per-call `root` can now only narrow the desk, never leave it (the old override is gone); and `carrel --root / mcp` is unconfined by construction, because `/` is then the desk the user named.

The rule has three halves, and review found each of the second two only after the first looked finished. **Paths the client names** go through `Desk.resolve`. **Paths a walk finds** need `confine_to` threaded to the walkers, because skipping symlinked *directories* still reads symlinked *files*. **Paths a tool derives** need `confined_dest`, because a write follows a symlink and the client never named the destination — a link planted where a conversion or an attachment lands carried the write out of the root, and a dangling one created the outside file with nothing to overwrite. Reads and writes are different problems and the same boundary; missing either makes the SECURITY.md sentence false again.

The desk *database* is the fourth derived path and the one that survived four review rounds: `DeskDB` opens `<root>/.carrel/carrel.db`, so a symlink at `<root>/.carrel` sent the index — the extracted full text of every file in the desk — and every tag, note and field wherever it pointed, and `carrel_search` read it back. Every tool that opens a `DeskDB` does so under a root established in one place, so the check sits there rather than at each call site.

Stored rows are the fifth case and are not a path at all. The desk index is written by whoever ran `carrel index`, and the CLI follows links by design, so a desk indexed from the shell holds rows pointing anywhere; `--prune` keeps them because the target still exists. Confining the walk stops the server *writing* such rows and cannot unwrite them, so `carrel_search`, `carrel_tag find` and `carrel_meta find` filter what they return.

Consequence: `plugins/carrel-agent/.mcp.json` is unchanged — Claude Code starts the server in the project directory, which is the desk. `specs/30-mcp-v3.md`'s re-opened confinement question is answered by this record, so the mutating tools of v0.6.0 inherit the boundary rather than each solving it.

## D-022 (2026-09-12) — The tracked-files guard is overridden by `--allow-tracked`; `--force` stays as a deprecated alias

`--force` means "overwrite existing output" on `mail`, `edit`, `sign`, `form`, `catalog`, `meta` and `audiobook`. On `rename`, `organize`, `intake` and `watch` it meant "bypass the tracked-files guard" (spec 29) — and those four never overwrite anything, so the habitual meaning does not apply to them at all. Someone who learned `--force` from `mail attachments` and adds it to `intake --apply` expecting overwrite semantics silently disables the guard that exists because a `rename --apply` once renamed 21 tracked files in this checkout.

The guard's override is `--allow-tracked` on all four. It cannot be reached by reflex from the other meaning, and it names what it does. `core/fsops.py::guard_worktree` takes `allow_tracked=`, and both refusal messages say "pass `--allow-tracked` to proceed".

`--force` is **not removed**. Scripts and the `bookkeeper` agent's documented flow use it, and breaking them to make a naming point is the wrong trade. It stays as an alias whose help says it is deprecated, and one line on stderr **when it actually bypasses the guard**: `warning: --force here means --allow-tracked (bypass the tracked-files guard); the --force spelling is deprecated`. A dry run is never guarded, and a `watch` without `--done-dir`/`--error-dir` never asks the question, so the warning stays silent there — claiming a bypass that did not happen would be false, and it would add stderr noise to scripted dry runs that were quiet before. No removal date is set; removing it is a separate decision, recorded when it is made.

Consequence: `tests/test_guardrails.py` runs every override assertion under both spellings (`OVERRIDES`), asserts the warning fires exactly once on each of the four commands when the guard is consulted, and asserts silence both for `--allow-tracked` and for a `--force` run that reaches no guard.

Consequence: `watch --print-service` writes `--allow-tracked` into the unit whichever spelling was typed. The unit is installed once and started forever; a deprecated alias baked into it would warn into `journalctl` on every boot and break outright the day the alias goes. `commands/_guard_flags.py::normalise_guard_flags` rewrites `ctx.params`, which `_watch_command_line` re-serialises, and its name says so.

## D-023 (2026-09-12) — A previously-successful invocation that can newly exit non-zero is a minor bump

v0.4.1 shipped a documented behaviour change — `--apply` refuses tracked files, exit 2 — as a **patch**. Its release review argued that was wrong and `STATE.md` has carried the question as an open owner call ever since: a `carrel~=0.4.0` pin or a routine `uv tool upgrade` pulls a patch in without anyone reading a changelog, and a cron `intake --apply` whose `--to` sits under a dotfiles repo starts exiting 2 at 3 a.m. The v0.4.1 session kept the patch number only because its brief named that version.

The rule from here: **if an invocation that succeeded before can now exit non-zero, it is a minor bump.** Not "is the new behaviour better", not "is the escape hatch documented" — both were true of v0.4.1 — but "can an unchanged command line that worked yesterday fail today". A new flag, a new output field, a faster path, a fixed crash: patch. A refusal, a new exit code on an existing path, a default that flips from permissive to strict: minor.

This wave has four such changes — MCP confinement, the `--json` empty-pack exit, image `Read`s passing through, and the JSON error shape on stderr — so it is **0.5.0**, and MCP v3 (`specs/30-mcp-v3.md`) moves from that number to v0.6.0.

Consequence: `docs/RELEASING.md` states the rule where the version is bumped. Still undecided, and left in `STATE.md`: whether `publish.yml` should *refuse* a patch tag whose CHANGELOG entry contains a "Changed (behaviour)" bullet. The rule is worth having before the enforcement, and enforcing it needs a CHANGELOG convention stricter than the one in use.

## D-024 (2026-09-12) — The README leads with the document workflow; the TUI is a companion

The first screen answered "what is this?" with a TUI tour and a paragraph about a study carrel. The people arriving are Claude Code users with a folder of PDFs, and what they needed to see was that carrel reads documents their agent cannot, packs the relevant few out of hundreds, and files an inbox by what the invoices say. The desk TUI is a fine thing and is nobody's reason to install a CLI.

The order is now: the functional line — **Read, index, pack and file your documents — from the terminal, for you and your agents** — then `pack.gif` and `redact-proof.gif`, then one paragraph, then install, then **three things to try**, each with a command block that has actually been run and one honest limitation. `desk-tour.gif` moves to "The desk TUI" and "the flagship" becomes "a companion to the CLI".

Nothing was removed — but the first attempt at proving that was too narrow, and a reviewer found two things the check could not see. Set-diffing rows, links and command mentions caught neither the `assets/logo.svg` mark dropped from the body nor a link whose *text* had been gutted, because the diff compared targets, not the whole link, and never looked at images at all. Both are restored; the check now covers images (`src="…"`), full link text, and headings. The honest result: images identical, `[Quickstart](#quickstart)` → `[Install](#install)` (the rename, followed), `[SECURITY.md]` added, and the heading set changed as intended. A count that matches is not evidence that content survived.

Three layers, and the next README edit should keep them apart:

1. **The motto** — *A library desk for your files — and your agents.* Identity. It is in `product.json` and does not move.
2. **The functional line** — what the tool does, in verbs, for someone who has never heard of it. It leads the README and `docs/index.md`, it is the GitHub description, and it leads the PyPI summary.
3. **The three use cases** — context for an agent, reading what an agent cannot, an inbox into an archive. In that order: the first is why most readers arrive, the third is the most impressive and the least believed on sight.

A "Status and support" section states what is stable, what is experimental, which platforms CI actually covers, the security response window, and two things carrel is not. Every claim there is one somebody could hold the project to.

Consequence: `docs/BRAND.md` carries this layering so it survives the next rewrite, and `product.json`'s `description` starts with the functional line, so `sync_product.py` carries it into `pyproject.toml` — and from there the PyPI summary, as motto + line + description. It does **not** reach `CITATION.cff` or the plugin manifests: `sync_product.py` propagates only the *version* to those, and `CITATION.cff` has no description field at all. The line drops its "for you and your agents" clause in `product.json` alone, because the motto sits immediately before it in the composed summary and already says so.

The GitHub repository description is **not** set by anything in this repo — `scripts/github-harden.sh` does not touch it and no test asserts it. Setting it is an owner-facing step recorded in `STATE.md`; until it is run, the repository still shows the old text.

## D-025 (2026-09-12) — Context7 indexes `docs/` and `plugins/`; freshness is a workflow, not a habit

Context7 serves carrel's documentation to other people's coding agents, and it was doing so with no configuration: whatever its crawler made of the repository, including files that are records rather than documentation. `context7.json` at the root now states the scope.

**The library is `/coltonbearden/carrel`.** `/firstcastsolutions423/carrel` redirects to it from the pre-transfer name.

**Scope is `folders: ["docs", "plugins"]`** — the reference pages and the plugin commands, agents and skills. The root `README.md` is indexed regardless of `folders`.

**Both exclusion lists replace Context7's defaults rather than adding to them** ([library-owners](https://context7.com/docs/library-owners.md), "Default Exclusions": *"If you don't specify `excludeFiles` or `excludeFolders` … Context7 uses these default patterns"*). So the three default file names are re-listed with the case and `.mdx` variants the docs give, alongside carrel's own non-documentation: `STATE.md`, `CLAUDE.md`, `BUILD_PLAN.md`, `TEST_REPORT.md`, `REPO_SETTINGS.md`, `HOW_THIS_WAS_BUILT.md`, `BRAND.md` and `DECISIONS.md`. Those are true records of a moment, and an agent that reads them as current advice gets stale advice — `DECISIONS.md` most of all, being an append-only log whose early entries later ones overturn (it was indexed in the first draft; review caught it). `VISION.md` stays indexed: it states principles, not a dated position.

Dropping the default `excludeFolders` is the deliberate half. Its `*archive*` pattern matches `plugins/carrel-mail/skills/mail-archive` — a shipped skill, and exactly the kind of thing an agent should find. carrel has no `i18n/`, `deprecated/` or `legacy/` trees for the rest of the defaults to protect, so the whole list costs one real page and buys nothing.

**`rules` are five checkable sentences**, not slogans: `--json` plus the exit-code table and its one exception (`carrel diff` exits 1 when the inputs differ), `carrel doctor` before relying on a capability, `pack --query` for bounded context and its non-zero empty, `carrel mcp`'s confinement (D-021), and which commands dry-run and which carry the tracked-files guard (D-022). Each is something an agent can be wrong about in a way a user notices — and the first draft was wrong in exactly that way: it told agents `dedupe` refuses tracked files and takes `--allow-tracked`. It has neither, and an agent trusting it would delete tracked duplicates inside a checkout. So the rules are now tested like every other CLI-behaviour surface: each `carrel <cmd>` and `--flag` a rule names must appear in that command's real `--help`, and a rule may only claim the guard for a command that calls `guard_worktree`.

**`projectTitle` and `description` come from `product.json`** via `scripts/sync_product.py`, asserted by `tests/test_product_sync.py` and watched by the `product-sync` pre-commit hook — the same treatment every other derived copy gets, so a rename reaches the page other people's agents read. The sync rewrites those two keys only, and the test that pins this *runs* `sync_context7` against a stale copy — the first draft only read the committed file, so it could not observe the sync at all. The hand-maintained `rules` name the CLI, so `scripts/rename_product.py` covers `context7.json` as well.

**No `url` or `public_key`** (owner's answer). Both are in the schema; neither is needed for a public GitHub repository, and `public_key` is a claim credential that belongs in the dashboard rather than in git.

**Freshness is `.github/workflows/context7-refresh.yml`.** The plan for this work assumed the refresh endpoint was undocumented and provided for shipping the config alone — it is documented, in the published OpenAPI spec (<https://context7.com/openapi.json>, "Context7 Public API" 2.0.0): `POST https://context7.com/api/v1/refresh`, bearer auth, body `{"libraryName": "/owner/repo"}`, `200 → {"message": …}`. The workflow was written from that spec rather than from guesswork. It derives `libraryName` from `github.repository` — the repository has moved once already, and a hardcoded name would 404 forever after the next move — and it logs the HTTP status and `message`, the one documented field, only. The first draft also echoed an `error` field, which is precisely where an authenticated endpoint puts a credential or an internal path; GitHub masks only the registered secret, and the log is public. Retries are bounded (`--retry-max-time 120`, `timeout-minutes: 5`) so a long `Retry-After` cannot park a runner for hours. Until `CONTEXT7_API_KEY` exists the job is green and skipped, so there is nothing to disable and no red history in a repository that never asked for it.

## D-026 (2026-09-15) — Runtime floors for parsers of untrusted input track security releases

carrel reads files it did not write, so the dependencies that parse them are its attack surface. `pypdf>=5.0` let `pip install carrel` keep whatever pypdf an environment already held, which meant the 6.18.1 hardening release that Dependabot moved into `uv.lock` (#50) reached CI and not users: carrel 0.5.0 installed into an environment holding pypdf 6.16.2 left it there.

**The floor is raised to the newest security release**, not held at the oldest API that works — `pypdf>=6.18.1` now. The alternative the owner was offered, a tested minimum with a CI job that installs the floors, answers a different question (does the floor still work?) and leaves the security one open; it is still worth having and is tracked in `STATE.md`.

**The rule has three limits**, in `docs/RELEASING.md` step 1: the release must support carrel's `requires-python` and classified platforms; the floor may not exceed what `uv.lock` pins, because CI tests the lock; and the raise is classified under D-023 by its effect. Hardening adds limits that refuse files older versions read, so crossing a hardening release is a minor bump.

**The parsers carrel ships are `pypdf`, `pillow`, `openpyxl` and `markdown-it-py`.** Only pypdf was raised in this change; the others are checked at the next release under the same rule.

**A PDF pypdf's parser refuses is bad input.** `core.output.pdf_refusal` classifies pypdf's own errors by type, for `handled`, `main`'s last-resort handler and the MCP server alike: every `pypdf.errors.PyPdfError` — `LimitReachedError` included, a sibling of `PdfReadError` rather than a subclass — is exit 4; an encrypted file names `edit pdf --decrypt`; pypdf's `DependencyError` is exit 3 with pypdf's own message; and `PageSizeNotDefinedError`/`XmpDocumentError`, raised for API misuse, stay unexpected. Classification by type cannot tell a hostile file from a carrel-generated one, and plain `ValueError`/`TypeError` from malformed structures are not covered; both wait for a shared PDF-opening helper (STATE.md). `main` silences pypdf's logger unless `--debug` is given, because a 156-byte PDF with no `/Root` made pypdf log 50,000 warnings before its exception.

## D-027 (2026-09-15) — `.claude/settings.json` grants only what the release loop runs, and every rule does work

Four owner items from #38's review, deferred at the time because the file landed byte-for-byte, decided together. The file is not a security boundary — the permissions docs say a Bash rule matches the command text Claude writes, not the program — so the aim is that the commands an unattended run ordinarily writes are the intended ones, and that every rule in the file does something.

**`gh workflow run` is two exact commands: `test.yml` and `context7-refresh.yml`.** `docs.yml` deploys GitHub Pages on any event but `pull_request`, dispatch included, so the blanket grant let an unattended run publish the site. Exact, not prefixes: `--ref <branch>` runs that branch's copy of the workflow, which the same run could push first. The control that would hold — a deployment-branch policy restricting the `github-pages` environment to `main` — is a repository setting and the owner's step (`STATE.md`).

**`gh repo edit` is no longer allowed at all; it asks.** Narrowing it to `--description` cannot be written: the allow rule's trailing wildcard carries any flag or a positional repository after the description, and a deny rule for "anything after it" also refuses descriptions containing ` -`. It runs about once per positioning change, so a prompt costs nothing.

**No force push or remote-ref deletion in the spellings an agent writes, as the owner ruled.** The dead `git push --force-with-lease` allow is dropped rather than revived. Git accepts any unique prefix of a long option (gitcli, "Abbreviating long options"), so the deny rules are those prefixes, leading and after any argument: `--for` (`--force`, `--force-with-lease`, `--force-if-includes`), `--de` (`--delete`), `--mi` (`--mirror`), `--pru` (`--prune`, which deletes remote branches with no local counterpart), `--e` (`--exec`) and `--rece` (`--receive-pack`), plus `-d` and `-f` leading any bundle. Each prefix is the shortest that no other `git push` option shares — `--fo` would also refuse `--follow-tags`, `--pr` `--progress` — and tests hold both halves. `gh pr update-branch` is allowed for merging the base in; its `--rebase`, a server-side rewrite, is denied.

**Commit hooks and stage-everything:** `git commit --no-veri` (the unique prefix; `--no-v` would catch `--no-verbose`), a trailing `-n`, `git add ./` and `git add :/` are denied alongside the existing shapes.

**Deny rules another deny rule already covers are removed**, as is `git push * :*`, which reads as `git push *  *` and matched nothing. `tests/test_settings_permissions.py` rejects a rule that needs a double space to match, a deny rule another covers (duplicates included), and an allow rule the deny list kills entirely.

**What a text-matching deny list cannot do, and what would.** Bundled short options with the flag after the first letter (`git push -uf`, `git commit -anm`), `git add -f .` and other stage-everything spellings, quoted refspecs (`'+feature'`), colon-refspec deletion (`git push origin :feature`), and arguments separated by a newline or tab all run unprompted under `Bash(git push:*)`/`git add:*`/`git commit:*`. Each review of this file found more of them. The permissions docs' answer is a PreToolUse hook that parses the command's arguments; that is the fix, recorded in `STATE.md`. In the owner's own sessions a user-level `Bash(gh:*)` allow also re-grants every `gh` command narrowed here.
