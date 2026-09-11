# Changelog

## Unreleased

- **Changed (behaviour):** `rename --apply`, `organize --apply` and `intake --apply` now refuse
  to start when a *directory* they would rewrite is inside a git work tree, exiting 2 with the
  repository root named. `intake` checks both `INBOX` and `--to`, and refuses before creating
  `--to`, so a refused run leaves the disk untouched. The new `--force` on each command
  overrides it. **Not** guarded: the dry-run default, and explicitly named file arguments —
  naming a file is already a decision at the granularity of the damage, while one directory
  name selects an unbounded set. This exists because on 2026-09-10 a `rename --apply` aimed at
  carrel's own checkout renamed 21 tracked files after the "fields" it read out of their
  source; the command was correct and the outcome was still wrong, because in a work tree the
  file names are content. Detection asks git (`rev-parse --show-toplevel`) and falls back to a
  `.git` ancestor walk when git is absent (spec 29). If you script one of these against a
  directory inside a repository, add `--force`.
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
