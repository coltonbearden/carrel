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

The `@_handled` decorator that turns a `CarrelError` into a clean message plus its exit code was copy-pasted into 25 command modules, and the `_root_of(ctx)` desk-root resolver into 12 — byte-identical every time, so the exit-code convention in CLAUDE.md depended on 25 copies never drifting, and `color.py` had already resorted to importing `proof._handled` across modules. Both are now public helpers in `carrel.core.output`, beside `emit` and `fail` which they call. Consequence: a command module imports `handled` and `root_of` and never defines them; `tests/test_command_conventions.py` fails the build if one comes back.
