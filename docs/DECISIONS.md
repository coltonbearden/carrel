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
