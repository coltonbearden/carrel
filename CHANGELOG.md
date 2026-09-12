# Changelog

## Unreleased

- **Changed (behaviour):** a `carrel pack` that found **no files** now prints one line on stderr
  naming the reason, and **under `--json` it exits 5** instead of writing a valid, empty
  document. FTS5 AND-s the terms of a `--query`, so a natural-language question usually matches
  nothing — the failure a caller is least likely to notice, because an empty pack is
  indistinguishable from a successful one. "No files" means none reached the pack: a directory
  of images, a `--tree-only` run and a `--max-file-bytes` that skipped everything all still
  produce a useful listing and still exit 0, and a `--since` whose only change was a deletion
  reports the deletion rather than failing. The message names the filter that actually emptied
  the result. `--no-fail-empty` restores exit 0; human mode still exits 0 by default and
  `--fail-empty` opts in. Scripts that pipe `pack --json --query` should either fix the query or
  pass `--no-fail-empty`. `PackResult.empty_reason` carries the same sentence, so the MCP
  `carrel_pack` tool reports it too — an agent has no exit code to read (D-018).
- **Fixed:** `pack` now honours the worktree root's `.gitignore` when packing a subdirectory.
  `ancestor_ignores` returns nothing when its `top` equals its `stop_at`, and `pack` passed the
  packed arguments' *common path* as `stop_at` — which for a single directory argument *is* that
  directory. So `carrel pack src --stats --tree-only` listed 45 `__pycache__` entries from this
  repo while `carrel pack .` listed none: the README's own `pack.gif` command, packing build
  artefacts into a context window. `pack` passes the **desk root** now (`--root`, default the
  cwd), which is what `index` already passed. The v0.3.1 guard is untouched by design — nothing
  above the declared scope is consulted, so a `uv venv`'s `.gitignore` of `*` still cannot blank
  a desk, including the usual case where the venv sits inside a checkout (D-019).
  `assets/demo/pack.gif` is re-recorded from the fixed build.
- **Fixed (`watch --print-service`):** the generated systemd unit now sets
  `WorkingDirectory=` to the directory carrel was invoked from, so the unit reproduces the
  invocation. A systemd *user* unit starts in `$HOME`, so a `--run` action holding a relative
  path — `mv {path} "archive/$(date +%Y-%m)"`, the shape the v0.4.1 entry advertises — filed
  every processed document into `~/archive/` instead of where an interactive run would put it,
  silently and forever. `_abs()` only ever absolutised the *option* values; the action template
  was the one relative path left, and it has to resolve against the same root they do.
- **Fixed (`watch --print-service systemd`):** a watched directory whose name contains a newline
  can no longer inject directives into the unit. `Description=` was emitted bare, so everything
  after the newline became further unit settings in the file the user is told to save and
  `systemctl --user enable` — an attacker-chosen `[Service]` / `ExecStart=` among them. A name
  ending in a backslash was the quiet version: systemd's line continuation swallowed the
  `After=default.target` line that followed. Both are now refused with exit 2, because a unit
  file cannot represent either. Verified against systemd 259 rather than against a model of it:
  quoting these settings does **not** work — a quoted `WorkingDirectory=` is rejected as "path
  is not absolute", and a quoted `Description=` keeps its quotation marks verbatim.
- **Fixed (`watch --print-service`):** the unit file name, `Description=`, the systemctl hints
  and the schtasks `/TN` all read the product name from `product.json` instead of hardcoding it,
  as CLAUDE.md requires. `_launcher_path` compared `argv[0]` against a literal `"carrel"`, so
  after a rename it silently fell back to `python -m carrel.cli` — a module that no longer
  exists — and every generated unit died at boot.
- **Fixed (`watch --print-service`):** an `argv[0]` with no final component (`/`, `.`, or any
  path ending in a separator) raised `ValueError` out of `pathlib` instead of a clean message;
  and the launcher path is normalised without being resolved, so an `argv[0]` carrying `..` no
  longer produces an `ExecStart=` systemd refuses ("Executable path contains special
  characters") while still naming the Homebrew/Nix symlink rather than the store path behind it.
- **Fixed (`watch --print-service schtasks`):** the printed line warns when the `/TR` value
  exceeds the ~261-character limit schtasks truncates or rejects at, and the cmd.exe
  metacharacter warning now names every part of the line — the watched path, `--done-dir`,
  `--error-dir` and `--log`, not only `--run`. `C:\R&D\inbox` is enough to split the paste.
- **Fixed (performance):** the `watch` tracked-file guard prunes `.git` and the
  `--done-dir`/`--error-dir` subtrees while walking instead of filtering afterwards. On a
  200-file repository with a 150-file archive the walk went from 425 paths to 200 — 52% of the
  old set was `.git/objects`, every one of them stat'd, resolved and sent through `git ls-files`
  for an answer git can never give — and it no longer grows without bound as the archive fills.
  Hidden *files* stay in the guarded set: `--existing` skips them, but a live event applies only
  `--glob`, so a committed `.gitkeep` really can be filed away. `--existing` shares that walker
  now, so it gets the same pruning — and a *relative* `--done-dir` prunes like an absolute one,
  which it did not when the two walkers were separate. `core.fsops` also stopped resolving every
  path twice (~850 realpath walks for 425 files).

## v0.4.1 — 2026-09-11

- **Changed (behaviour):** `rename --apply`, `organize --apply`, `intake --apply` and
  `watch --done-dir/--error-dir` now refuse to start when the move would touch a file **git is
  tracking**, exiting 2 with the repository and the offending paths named. Each gains `--force`
  to override. Untracked files inside a repository are fine — `~/Downloads` under a dotfiles
  repo keeps working — and the dry-run default is never guarded. `intake` checks INBOX and
  `--to` and refuses before creating `--to`, so a refused run leaves the disk untouched;
  `organize` also checks `--into` destinations, which can climb out of DIRECTORY. This exists
  because on 2026-09-10 a `rename --apply` aimed at carrel's own checkout renamed 21 tracked
  files after the "fields" it read out of their source; the command was correct and the outcome
  was still wrong, because a tracked file's name is content. Without the git binary carrel
  cannot tell what is tracked, so it exits 3 with git's install hint rather than guessing
  (spec 29, D-017). Only paths the command could really move count: `watch` skips files its
  `--glob` can never match, a tracked symlink counts as the link rather than its target, and
  file names containing `*`, `?` or `[` are matched literally. If you script one of these
  against tracked files, add `--force`.
- **Fixed (Windows):** every text read and write now names its encoding. `text=True` on
  `subprocess` and `Path.read_text()` both fall back to `locale.getencoding()`, which is
  cp1252 on a stock Windows box — so **every** external tool's output (`pdftotext`, `pandoc`,
  `tesseract`, `git`) was being decoded as cp1252, and a PDF containing `café` came back as
  `cafÃ©`. CI never noticed because it sets `PYTHONUTF8=1`. `ruff`'s `PLW1514` is the first
  gate and `tests/test_text_encoding.py` the second, because that rule only fires where it can
  infer a `Path` receiver; 10 of the sites were beyond its reach, including the write that
  recreates `product.json` and would have truncated it to 0 bytes on a non-UTF-8 locale.
- **Fixed:** `carrel mcp` now forces UTF-8 on its stdio. MCP frames are UTF-8 by
  specification, but Python wires stdio to the locale encoding with `errors="strict"`, so a
  document containing CJK or an em dash could kill the server mid-session on Windows.
- **Fixed:** reading a user's document goes through one place (`utf-8-sig`, `errors="replace"`),
  so Excel's "CSV UTF-8" export no longer names its first column `\ufeffname`, and its plain
  cp1252 export converts instead of raising. Four readers had drifted to three different
  error policies.
- **Fixed:** generated output that gets hashed — `pack`, `sign manifest`, `catalog export` —
  is written with `newline="\n"`. On Windows the same source tree produced CRLF and therefore
  a different sha256, which `diff --mode bytes`, catalog hashes and `sign manifest` all read
  as a changed file. The files carrel generates for itself (`_product.py`, the manifests) are
  pinned the same way, matching the other sync scripts.
- **Changed:** the `@handled` decorator (CarrelError → message + exit code) and the `root_of`
  desk-root resolver live once, in `carrel.core.output` (D-016). They had 25 and 12
  byte-identical copies across the command modules, four more root lookups open-coded, and
  three modules carrying the decorator's body inline; `color` imported `proof._handled` across
  modules. Behaviour is unchanged. `handled` is now generic in the wrapped signature, so mypy
  checks calls through it, and `debugging(ctx)` is the one place the global `--debug` is read.
- **Fixed:** `watch --print-service` wrote the *unresolved* `--root`, `--done-dir`,
  `--error-dir` and `--log` into the generated systemd unit and `schtasks` line. A service
  starts in the manager's working directory — `$HOME` for a systemd user unit — so a relative
  `--root` made the unit fail on every start (`--root` requires an existing directory), and a
  relative `--done-dir` would have filed documents into a directory under `$HOME`. Every path
  in a generated service is now absolute.
- **Fixed:** `watch --print-service` output now survives real actions. The systemd unit's
  `ExecStart` uses systemd's own quoting — backslashes and quotes C-escaped, `%` and `$`
  doubled — so `--run 'mv {path} "archive/$(date +%Y-%m)"'` reaches the service intact
  instead of `%Y` becoming the unit directory and `%m` the machine ID; verified by
  round-tripping argv through a real systemd unit. The `schtasks` line quotes the command
  once for carrel and again as the `/TR` argument, because Windows parses it twice, so
  embedded quotes and trailing backslashes survive. Paste it into cmd.exe, not PowerShell,
  and not when an action contains `&`, `|`, `<`, `>`, `^` or `%`. Both now name the carrel
  launcher that printed them rather than the first `carrel` on PATH — kept as the PATH
  symlink rather than resolved into a version directory an upgrade deletes, and found on
  Windows although the launcher hides its `.exe` — and carry the global `--json` as
  `--json-lines`.
- **Fixed:** `docs/index.md` claimed `carrel mcp` serves "ten MCP tools" — it has served 14
  since v0.4.0. `tests/test_docs_drift.py` now scans every live doc, and the plugin skills
  whose frontmatter states it, for a tool count in any spelling (numeral, word, hyphenated,
  emphasised) and checks it against the `TOOLS` table in `carrel.commands.mcp`; it also pins
  every tool name in `docs/AGENTS.md` and the inline lists in README and `docs/FEATURES.md`.
  Historical counts in the FEATURES release trail are left alone. `docs/REPO_SETTINGS.md` is
  pinned against `REQUIRED_CHECKS` in the hardening script the same way.

## v0.4.0 — 2026-09-10

The accounting inbox. carrel reads what a document says, links documents by the
numbers they share, files them where they belong, and answers questions about them —
and email is a first-class file type throughout.

- **Added:** `carrel meta` — typed key/value fields on desk files (`set/get/ls/rm/find/export`),
  stored in the new schema-v2 `meta` table. Kinds (str/num/date/bool) are inferred and values
  stored canonically, so `meta find total>1000` compares numerically and `due<2026-11-01`
  chronologically; `meta export` writes the desk as a CSV/JSON table; `search --meta COND`
  filters hits; `catalog export/import` carry fields with tags and notes (schema 2; schema-1
  documents still import). Existing desks migrate on open (D-009).
- **Added:** `carrel refs` — find reference numbers in any supported file: label-driven
  invoice/PO/order/check/account/tracking/ticket kinds and check-digit-verified IBAN, ABA
  routing, EIN, VAT, ISBN, GTIN, DOI, UPS and USPS identifiers, with page numbers for PDFs.
  `--tag` writes `ref:<kind>:<value>` tags so `tag find` / `search --tag` link the documents
  that share a reference; `--link` prints that grouping; `--pattern NAME=REGEX` adds house
  formats. The kinds live in the new `core/patterns.py`.
- **Changed:** `redact --builtin` accepts every kind of the shared registry (`iban`, `routing`,
  `invoice`, …); label-driven kinds replace only the value, so `Invoice # ████` keeps its label.
- **Added:** email as first-class files — `.eml` and `.mbox` (`.mbx`) are `FileType`s read by
  the standard library (`core/mail.py`), so `inspect`, `convert` (eml → md/txt/html/pdf,
  mbox → md/txt), `index`/`search --type eml`, `pack`, `diff`, `organize` (→ `mail/`), `refs`
  and the `carrel-guard` Read hook all handle them. Shape sniffing applies only to unmapped
  extensions (D-012). Outlook `.msg` is cut (D-011); `.pst` comes in through readpst.
- **Added:** `carrel mail` — `attachments` (saved with sha256, names sanitised, never
  overwritten without `--force`), `split` (mbox → dated `.eml` files), `threads`
  (Message-ID / In-Reply-To / References), `pst` (Outlook exports via the new `readpst`
  adapter, `sudo apt install pst-utils`).
- **Added:** `carrel fields` — vendor, invoice number, PO, dates, subtotal/tax/total, currency,
  IBAN and account last-4 out of invoices, receipts and statements (label heuristics over the
  text spine, `core/money.py` and `core/dates.py`), each with a confidence and its evidence
  line; `--set` overrides, `--save` writes them as desk fields.
- **Added:** `carrel rename --template '{date}_{vendor}_{ref}{ext}'` — names from the document's
  own fields (or desk fields / references), slugified, dry-run by default, never overwriting;
  the desk row follows the file. `organize --apply` moves through the same helper, so tags and
  notes no longer go missing after a move (pre-v0.4.0 bug).
- **Added:** `carrel batch` — run shell actions over many files with `watch`'s `{path}` language
  (`core/actions.py`, D-013): `--jobs`, `--dry-run`, `--manifest` + `--resume`, `--fail-fast`,
  `--json-lines`; exit 1 when any file failed.
- **Added:** `carrel watch` upgrades — `--recursive`, `--existing`, `--stable SECS` (wait for a
  file to stop growing), `--poll` (for `/mnt/c` and network shares), `--done-dir`/`--error-dir`,
  `--log FILE`, `--print-service systemd|schtasks`; `{stem}` and `{ext}` substitutions.
- **Fixed (email, found by review before release):** converting a message to PDF now renders its
  *text*, never the sender's HTML, so a conversion can no longer fetch a tracking pixel, reach an
  intranet URL, or embed a local `file://` into the output; `eml → html` re-declares the encoding
  it is actually written in (no more mojibake from a `windows-1252` header). A malformed `Date`,
  an address header containing a newline, an unknown charset, a 3000-message reply chain, a
  300-character attachment name and a Windows device name are all handled as data instead of
  crashing or silently dropping content. Attachments nested inside forwarded messages are found;
  two attachments with the same name in one run no longer overwrite each other; `mail split`
  plans every name before writing (so a collision cannot leave half a mailbox on disk) and writes
  the bytes as stored, keeping encodings and DKIM signatures intact. `mail pst --format mbox`
  passes readpst `-r` (one `mbox` per folder) rather than `-M` (MH format). The mail shape-sniff
  now applies only to files without a real extension (D-012), so `.patch`, `.diff` and log files
  are no longer reclassified as mail, while Maildir names still are; a mailbox saved as `.eml` is
  detected by its bytes instead of swallowing every message after the first.
- **Fixed (extraction and automation, found by review before release):** a negative amount on a
  labelled line kept its sign (`Total Due  -$1,234.56` was booked as a charge), a decoy label line
  no longer wins over the real one (`Total units 3.00` above `Total $1,234.56`, `Tax ID:` above
  `Tax`), `Net  500.00` is read as a subtotal rather than 500-day payment terms, a dotted date
  (`2026.03.04`) is no longer harvested as the amount 2026.03, and a currency tie resolves the same
  way on every run. `watch`/`batch` action templates are substituted in one pass, so a file named
  `{name}.txt` can no longer produce a command that acts on a different path; `--manifest` and
  `--log` create their directories instead of crashing on the first record; `watch`'s output-name
  guard only suppresses added segments (`report.pdf` → `report.txt`), so a new input that merely
  shares a prefix (`report-2026.pdf`) is no longer lost; `--existing` skips `--done-dir`/`--error-dir`,
  so a restart does not re-run every action over the archive; and `rename --apply` records a failed
  move instead of discarding the whole plan.
- **Added (MCP):** `carrel_meta`, `carrel_refs`, `carrel_fields` and `carrel_mail` tools (14 tools); `carrel_search` takes `meta`.
- **Added (marketplace):** `carrel-finance` plugin (`/refs`, `/fields`), `carrel-mail` plugin (`/mail` + a
  `mail-archive` skill); `/meta`, `/rename`, `/batch` in `carrel-organize`.

## v0.3.2 — 2026-09-10

- **Fixed (Windows):** `carrel watch --action-timeout` crashed with `module 'os' has no
  attribute 'killpg'` when an action timed out; a timed-out action is now killed as a
  process tree (`taskkill /T`) there. `CARREL_BIN_<NAME>` overrides counted any existing
  file as executable on Windows (`os.access(X_OK)` is plain existence there); executability
  now follows `PATHEXT`, so a stale override never silently resolves (D-008). Substitutions
  in `watch --run` templates are quoted for cmd.exe rather than `sh`.
- **Fixed:** notes on a file come back newest-first by insertion order as well as
  timestamp, so two notes added within one clock tick keep their order.
- **Changed:** `carrel search` prints bm25 scores with three significant digits
  (`score -0.0412`), matching `pack --stats`, instead of rounding them all to `-0.00`.

## v0.3.1 — 2026-09-09

- **Fixed:** an unrelated `.gitignore` in a distant ancestor directory could
  silently exclude an entire desk. The ancestor walk had no stopping point
  outside a git repository, so it collected rules all the way to `/`. It now
  stops at the repo root (`.git`) or the caller's root — the desk root for
  `index`, the common root for `pack` — and an unbounded walk contributes
  nothing. Found while verifying v0.3.0 from PyPI: `uv venv` writes a
  `.gitignore` containing `*` into the venv directory, and a desk created inside
  one reported `indexed: 0, skipped: 0, errors: []` with nothing to explain it.
  `pack` was affected the same way and is fixed by the same change.

## v0.3.0 — 2026-09-09

The desk reads code. `carrel index` covers source trees, so the agent-facing
half of v0.2.0 — `pack --query`, `search`, and the plugin reindex hook — finally
works on the repositories agents actually point it at.

- **Added:** `carrel index` covers plain-text source and config files (`.py`, `.rs`, `.toml`,
  `.yaml`, `Makefile`, …) as the new type `code`, so `search`, `pack --query`, `tag`, `note`
  and the MCP `carrel_search` / `carrel_pack` tools reach source trees — closing the "planned
  follow-up" left open in v0.2.0. `search --type code` filters to them; `--no-source` opts out.
- **Added:** the `index` walk honours `.gitignore` (`--no-gitignore` opts out), sharing
  `pack`'s matcher via the new `carrel.core.ignore`. Without it, indexing a repo would pull in
  `node_modules/`, `build/` and `dist/`.
- **Changed:** source files are indexed **by default**. An existing desk will
  grow on its next `carrel index` run; pass `--no-source` to keep it to
  documents. `.gitignore` is honored by the same walk, so ignored build output
  stays out.
- **Changed:** `carrel diff a.py b.py` picks `text` mode automatically instead of
  exiting 4; `carrel inspect` reports source files as `type: code` with a
  line/word/char detail block.
- **Fixed:** `DeskDB.rel()` and PDF-manifest entries now use POSIX separators. `files.path` is
  written verbatim into `carrel catalog export`, so a catalog produced on Windows could not be
  imported on Linux — the exact portability D-009 exists to provide.
- **Fixed:** the `carrel-agent` `PostToolUse(Write|Edit)` reindex hook was a silent no-op on
  source repositories, because the files Claude writes were never an indexable type.

## v0.2.0 — 2026-09-04

The desk grows up for agents: the whole CLI is reachable over MCP, `pack` can
select by relevance or by git history, the index is versioned and portable,
and Office/ebook documents join the supported types.

- **Added:** docx, odt, epub, rtf (via pandoc) and xlsx (via `carrel[office]`)
  across `convert`, `inspect`, `index`/`search`, `pack`, `diff`; `convert --sheet`
  for workbooks; md/html/txt → docx/odt.
- **Added:** `carrel pack --query TEXT [--top N]` (index-ranked packing),
  `--since REF` / `--changed` (git-aware), `--dedupe-content`,
  `--tokenizer exact` (tiktoken via `carrel[tokens]`), `--outline`;
  `.gitignore` negation (`!pattern`) is honored.
- **Added:** `carrel catalog export|import|status` and `carrel index --status`;
  the desk database carries `PRAGMA user_version` and migrations (D-009), so
  tags and notes can move between machines and schemas can evolve safely.
- **Added:** MCP server v2 — 10 tools (`carrel_search`, `carrel_pack`,
  `carrel_inspect`, `carrel_tag`, `carrel_note`, `carrel_index`,
  `carrel_convert`, `carrel_diff`, `carrel_redact`, `carrel_doctor`) built on
  the same implementation functions as the CLI, plus `carrel://file/{path}`
  and `carrel://search/{query}` resources.
- **Added:** `carrel completion bash|zsh|fish`; `CARREL_BIN_<NAME>=/path` pins a
  specific binary for an adapter (D-008, the one exception to config-free).
- **Added:** plugins `carrel-documents` (redact/sign/form/proof/color) and
  `carrel-guard` (a `PreToolUse` hook that hands Claude the text of PDFs,
  Office files and images instead of the binary; a `SessionStart` capability
  summary); every CLI command now has a slash command, with usage blocks
  generated from `--help` by `scripts/sync_plugins.py --check`.
- **Changed (breaking):** Textual is an optional extra — install
  `carrel[tui]` or `carrel[all]` for `carrel desk` (D-007). A plain install
  exits 3 with that hint.
- **Changed:** nine adapter entries that no command used (`gs`, `pngquant`,
  `jq`, `mlr`, `rg`, `fd`, `sqlite3`, `inotifywait`, `claude`) were removed
  from `doctor`; `git` was added.
- **Changed:** `docs/REFERENCE.md` is generated from `--help`
  (`scripts/sync_reference.py --check` gates drift); cookbook and snippets
  have a docs page; CI adds macOS (required after this release) and Windows
  (advisory) `test-minimal` jobs and an 80% coverage floor.
- **Known limitation:** `pack --query` ranks only files the index knows;
  `carrel index` skips unknown types such as `.py`, so query-driven packing
  fits document trees, not source trees yet.

## v0.1.2 — 2026-09-04

Housekeeping release after the repository moved to `coltonbearden/carrel`.

- **Fixed:** the v0.1.1 wheel reported `carrel 0.1.0` — the release bumped
  `pyproject.toml` without bumping `product.json` (the source of truth). Version
  bumps now go through `product.json` + `scripts/sync_product.py`, which also
  syncs the marketplace/plugin manifests, `CITATION.cff`, and `[project.urls]`;
  `tests/test_product_sync.py` fails if any copy drifts.
- **Fixed:** `--json` is now accepted after the subcommand for every data
  command (`carrel pack --json …`), not only before it. `carrel watch --json`
  implies `--json-lines`.
- **Fixed:** external-tool timeouts surface as a clean error (exit 1 with the
  binary name) instead of a traceback; `watch` actions get `--action-timeout`
  (default 300 s) so a hung action can no longer wedge the watcher.
- **Fixed:** `index` exits 3 (not 0) when every file was skipped for a missing
  binary; `redact --fail-empty` prints why it exited 5.
- **Changed:** all links, badges, and `claude plugin marketplace add` targets
  point at `coltonbearden/carrel`; install hints use `uv tool install carrel`.
- **Changed:** dependencies bumped for security advisories (pypdf ≥ 6.16.1,
  mkdocs-material ≥ 9.7.7).
- **Fixed (review follow-ups):** `--json` also works after nested subcommands
  (`carrel tag ls … --json`); an unchanged `index` re-run stays exit 0 and
  `--update` hook mode never fails; per-file tool timeouts are recorded instead
  of aborting the walk; a timed-out `watch` action is killed as a whole process
  group; undecodable tool output can no longer crash `doctor`;
  `sync_product.py` escapes TOML strings and touches only plugin versions;
  the publish workflow requires the release commit to be on `main` and diffs
  every generated file.
- **Internal:** ruff + mypy gate in CI, SHA-pinned actions, split build/publish
  release workflow with tag↔version check and attestations, Dependabot config,
  `SECURITY.md`, `CODEOWNERS`, `py.typed`, pre-commit.

## v0.1.1 — 2026-08-12

First PyPI release: `pip install carrel`, published from CI via PyPI Trusted
Publishing (.github/workflows/publish.yml, OIDC — no token). Repo-side
discoverability round: CODE_OF_CONDUCT, issue forms + PR template,
CITATION.cff, FUNDING.yml, Related-projects README section, repo homepage +
Discussions + social preview. No CLI behavior changes.

## v0.1.0 — 2026-07-16

Initial release: carrel CLI (24 commands), desk TUI, Claude Code plugin
marketplace (5 plugins), MCP server, docs package. Built 2026-07-16.
