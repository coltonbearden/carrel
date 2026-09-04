# Changelog

## v0.1.2 — unreleased

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
