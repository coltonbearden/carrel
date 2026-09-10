# BUILD_PLAN

Waves of ≤4 parallel subagents. Owner types from `.claude/agents/`. Every task's acceptance = its spec's Acceptance section + CLAUDE.md command standards. Orchestrator verifies each wave by running smoke tests personally, then commits `wave(N)`.

**Constraint honored:** Wave 1 tasks must not depend on `tests/conftest.py`/fixtures (built concurrently) — they synthesize test inputs with pypdf/Pillow/stdlib in their own test files. Waves 2+ use shared fixtures.

## Wave 1 — foundations (no cross-deps)

- [x] W1.1 fixtures + conftest + core unit tests — **test-engineer** — specs/14, specs/00 acceptance — size M
- [x] W1.2 doctor + mcp — **module-builder** — specs/13 — size M
- [x] W1.3 pack — **module-builder** — specs/05 — size M
- [x] W1.4 edit — **module-builder** — specs/04 — size M

## Wave 2 — extraction & desk-db commands (need fixtures)

- [x] W2.1 convert — **module-builder** — specs/01 — size L
- [x] W2.2 ocr — **module-builder** — specs/02 — size S
- [x] W2.3 inspect + diff — **module-builder** — specs/03 — size M
- [x] W2.4 index + search + tag + note — **module-builder** — specs/06 — size M

## Wave 3 — media, automation, documents (need fixtures; marketplace independent)

- [x] W3.1 thumb + extract-images + proof + color — **module-builder** — specs/07 — size M
- [x] W3.2 watch + organize + dedupe — **module-builder** — specs/08 — size M
- [x] W3.3 redact + sign + form — **module-builder** — specs/10 — size L
- [x] W3.4 marketplace + 5 plugins — **module-builder** — specs/12 — size M

════════ **MVP LINE** — everything above must pass before anything below is attempted ════════

## Wave 4 — flagship & flourish

- [x] W4.1 audiobook — **module-builder** — specs/09 — size S
- [x] W4.2 desk TUI (flagship) — **module-builder** — specs/11 — size L
- [x] W4.3 snippets/ + examples/cookbook/ seed scripts — **doc-smith** — CLAUDE.md standards — size S
- [x] W4.4 integration review sweep — **integration-reviewer** — all specs — size M

## Phase 5+ (orchestrator-led, not waved)

- [x] fixtures for cookbook E2E runs executed for real → docs/TEST_REPORT.md
- [x] marketplace add + install + slash-command execution proof
- [x] Phase 6 wave: design-artist (assets/BRAND/README) ∥ doc-smith (docs package) ∥ CI workflow
- [x] Phase 7: finalize.sh + dry-run + temp-dir run + rename round-trip (suite green post-rename)

## Scope guards

- If a Wave 3 task slips badly: cut `proof`/`color` first, then `form build --pdf` (keep fill), then near-dupe. Log in FEATURES.md.
- If W4.2 TUI slips: reduce to two panes (tree + inspector w/ actions) before cutting.
- `recipes` runner and PAdES already cut (FEATURES.md).

---

# v0.2.0 — planned 2026-09-04

Same mechanism: waves of ≤3 parallel `module-builder` subagents on a feature branch `feat/v0.2.0`, one sub-branch per spec, merged into the feature branch only after the orchestrator has run that spec's Acceptance section by hand. Per-wave gates: `uv run pytest` · `uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy` · `uv run mkdocs build --strict` · `claude plugin validate .`. The release PR from `feat/v0.2.0` to `main` needs green `lint`/`test`/`test-minimal`; tagging and PyPI stay the user's step (docs/RELEASING.md).

**Ownership rule:** no file is owned by two specs in the same wave. Shared files are sequenced: `src/carrel/cli.py` (19 → 17), `src/carrel/commands/inspect.py` (18 → 15), `pyproject.toml` / `core/adapters.py` (19 only), `.github/workflows/test.yml` (21 only; orchestrator adds the spec-20 drift step in wave 3).

## Wave 1 — foundations (no cross-deps)

- [x] V1.1 office + ebook formats (docx/odt/epub/rtf/xlsx) — **module-builder** — specs/18 — size L
- [x] V1.2 install ergonomics: extras, `completion`, `git` adapter, `CARREL_BIN_*`, dead-adapter removal — **module-builder** — specs/19 — size M
- [x] V1.3 drift + gates: generated REFERENCE, COOKBOOK nav, CI matrix, coverage floor — **module-builder** — specs/21 — size M

## Wave 2 — agent surface (needs wave 1)

- [x] V2.1 mcp v2: 10 tools on impl functions, resources, stdio test — **module-builder** — specs/15 — size L
- [x] V2.2 pack v2: `--query`, `--since/--changed`, negation, dedupe, exact tokens, outline — **module-builder** — specs/16 — size L
- [x] V2.3 catalog: schema migrations, export/import, status — **module-builder** — specs/17 — size M

## Wave 3 — surface completion & release

- [x] V3.1 plugins v2: `sync_plugins.py`, every command as a slash command, `carrel-documents`, `carrel-guard` — **module-builder** — specs/20 — size L
- [x] V3.2 integration review sweep of all commands (`--help`, fixture run, `--json`, missing-file/binary paths, adapter-layer grep) — **integration-reviewer** — all v0.2.0 specs — size M
- [x] V3.3 docs pass from real output (README type list + extras, MARKETPLACE, QUICKSTART, TEST_REPORT with the wave-3 proofs) — **doc-smith** — size M
- [x] V3.4 orchestrator: `sync_reference.py`, `sync_plugins.py`, bump `product.json` → 0.2.0, `sync_product.py`, CHANGELOG entry, release PR

## Scope guards (v0.2.0)

- If wave 2 slips: cut `pack --outline` and `--tokenizer exact` first (both isolated flags), then MCP resources (keep the 10 tools). Log in FEATURES.md.
- If `carrel-guard` cannot rewrite `Read` input reliably on the installed Claude Code, ship it as `deny` + reason naming the `carrel convert` command, and document.
- The Windows CI job `test-minimal (windows)` is advisory (`continue-on-error: true` in `.github/workflows/test.yml`). For v0.2.0 it ran only a CLI smoke test plus the two modules verified Windows-clean; since 2026-09-09 (D-f, PR #20) it runs the **whole suite** after the smoke test so every push records the current failure list — see [Windows suite](#windows-suite-failure-list) below. Promote the job to required (drop the flag, add the check name to the `main` ruleset) once the suite passes there and it has been green on `main` for two consecutive weeks. `test-minimal (macos)` is required from v0.2.0.
- Textual moves to the `tui` extra (D-007); if user feedback during the release cycle objects, revert to a core dependency in a patch release — the guard in `commands/desk.py` makes either choice safe.

## Windows suite — failure list

**Status (PR #22):** every row below is fixed. The run on #22's first head reported
`2 failed, 870 passed, 93 skipped` — `scripts/sync_plugins.py` wrote CRLF on Windows while
the checked-in command files are LF, and the read-guard hook treated `C:\…` paths as relative
— both fixed in the same PR. Next: two consecutive green weeks on `main`, then drop
`continue-on-error` and add `test-minimal (windows)` to the ruleset (owner step).

From the first full-suite run after PR #20 (run 34406425888, 2026-09-09, `windows-latest`,
`PYTHONUTF8=1`): **41 failed** across 7 modules. The 2026-09-04 run 33880114130 had 54 across
13; spec 22's POSIX `DeskDB.rel()` / sign-manifest paths and the job's `PYTHONUTF8=1` cleared
`test_redact_sign_form`, `test_product_sync`, `test_mcp_stdio`, `test_reference_sync`,
`test_mcp_doctor` and `test_desk_db_cmds`, and three `test_pack` chunking cases. Fix order:
test-side `bash` invocation and newline handling first (largest and cheapest), then the
`src/` defects, then platform-shaped test expectations.

| Module | Fails | Cause class | Fix side |
|---|---|---|---|
| `test_marketplace.py` | 25 | 21× `.sh` hook scripts executed directly (`WinError 193`: Windows does not honour shebangs); 3× executable-bit assertions; 1× capabilities summary via the same exec | tests: run scripts via `bash`; skip mode checks on `nt` |
| `test_pack.py` | 4 | CRLF from `write_text` in tests shifts byte budgets, content hashes and outline sizes (`max_file_bytes`, `max_bytes`, `dedupe_content`, `outline`) | tests: `newline="\n"`; add `.gitattributes` |
| `test_core_adapters.py` | 4 | `os.access(X_OK)` is plain existence on Windows; `~` override expansion; exec of a non-`.exe` file | src: `adapters.Adapter.resolve` |
| `test_core_cli.py` | 3 | `os.killpg` (Windows-absent, voids the action-timeout guarantee); `venv/bin/python` layout (`Scripts\` on Windows); non-UTF-8 adapter output | src: `watch`; tests |
| `test_watch_org_dedupe.py` | 2 | POSIX `shlex.quote` and `/tmp` path expectations in `_render` | tests |
| `test_core_db.py` | 2 | notes ordered by `created` alone (a coarse clock ties two inserts); `rel()` of a path outside the root is POSIX since spec 22 (`C:/…`) while the test expects `str(path)` | src: `ORDER BY created DESC, id DESC`; test |
| `test_completion.py` | 1 | `bash -n` on the generated script under Git Bash | tests |
