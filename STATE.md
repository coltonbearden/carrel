# STATE

> Live status of the project. A brand-new session should be able to resume from this file alone.
> Build history: docs/HOW_THIS_WAS_BUILT.md. Decisions: docs/DECISIONS.md. Release steps: docs/RELEASING.md.

## Now

- **Status:** published. Repo `coltonbearden/carrel` (moved from `FirstCastSolutions423/carrel`
  in August 2026), docs at https://coltonbearden.github.io/carrel/, PyPI package `carrel`
  (v0.1.1 live; v0.1.2 prepared — see Next).
- **Next:** cut v0.1.2. Requires the PyPI Trusted Publisher to be re-pointed at
  owner `coltonbearden` first (docs/RELEASING.md), then `gh release create v0.1.2`.

## Done

- Build phases 0–7 complete (2026-07-16); v0.1.0 tagged.
- v0.1.1 on PyPI via Trusted Publishing (2026-08-12).
- 2026-09-03 hardening: owner rename, version SoT fix, `--json` everywhere, timeouts,
  ruff/mypy CI gate, SHA-pinned workflows, Dependabot, branch/tag rulesets, secret
  scanning + push protection, CodeQL (docs/REPO_SETTINGS.md).

## Open issues

- PyPI Trusted Publisher still registered for the old owner until the user updates it
  (blocks the v0.1.2 publish job, nothing else).

## Key facts for a fresh session

- Stack: Python ≥3.12 + uv; click CLI; Textual TUI (`carrel desk`); hatchling build.
- Product identity: `product.json` is the SoT. Bump there, run `scripts/sync_product.py`,
  never edit `pyproject.toml` version / `_product.py` / manifest versions by hand.
- `main` is protected: changes land via PR with green `lint`, `test`, `test-minimal` checks.
  Repo admin can bypass in an emergency. Do not run `scripts/finalize.sh` — it relocates the
  tree and creates a new repo; it was for the original hand-off only.
- Marketplace: `claude plugin validate .` → `claude plugin marketplace add coltonbearden/carrel`
  → `claude plugin install <plugin>@carrel`.
