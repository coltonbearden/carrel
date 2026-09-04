# Changelog

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
