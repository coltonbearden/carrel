# spec: plugins v2 — the full CLI surface, generated from --help

**Owns:** `plugins/**`, `.claude-plugin/marketplace.json`, new `scripts/sync_plugins.py`, `tests/test_marketplace.py`, `docs/MARKETPLACE.md`, `docs/PLUGIN_AUTHORING.md`.
**Wave:** 3 (needs the final `--help` of every command from waves 1–2). The orchestrator wires `sync_plugins.py` into the CI lint job's drift step (`.github/workflows/test.yml` is spec 21's file).

## Why
24 CLI commands, 10 slash commands. The usage blocks inside `plugins/*/commands/*.md` are hand-copied and will drift the moment waves 1–2 add flags. Claude also cannot read PDFs, docx or images natively, yet the desk can turn any of them into text — nothing wires that in.

## `scripts/sync_plugins.py`
- For every `plugins/*/commands/*.md`, locate `<!-- usage:start -->` … `<!-- usage:end -->` and replace the enclosed fenced block with the current output of `carrel <command> [sub] --help` (command name from frontmatter key `carrel-command:`; for groups, one block per subcommand). Text outside the markers is preserved byte-for-byte. Exit 1 listing files that changed when run with `--check`.
- Invoked as `uv run python scripts/sync_plugins.py [--check]`; uses `carrel` from the current environment via `python -m carrel.cli` (not PATH).
- `tests/test_marketplace.py` gains a test that runs `--check` and fails on drift (same pattern as the `sync_product.py` CI step).

## Command coverage (every carrel command has a slash command)
Convert every existing `.md` to the marker format (frontmatter adds `carrel-command: <name>`), then add:
- `carrel-convert`: `edit.md` (all four `edit` subgroups), `extract-images.md`.
- **new plugin `carrel-documents`** (document craft): `redact.md`, `sign.md`, `form.md`, `proof.md`, `color.md`; agent `document-clerk.md` (redact → verify with `diff`/grep → sign manifest → report; refuses to overwrite without `--force`); skill `redaction-and-provenance/SKILL.md` (true-raster redaction caveat, re-OCR afterwards, manifest verify flow).
- `carrel-agent`: `index.md`, `doctor.md`, `catalog.md`, `completion.md`; `pack.md` (in carrel-inspect) documents `--query`/`--since`; `search.md` documents `--type/--tag`.
- `carrel-inspect/skills/context-packing/SKILL.md` rewritten around `--query` first, `--since` for PRs, `--tree-only`/`--outline` for orientation, `--tokenizer exact` when precision matters.
- `.mcp.json` in `carrel-agent` unchanged; its `agent-workflows` skill lists the 10 MCP tools and the two resource templates.
- `marketplace.json` lists 7 plugins (add `carrel-documents`, `carrel-guard`); versions come from `product.json` via `sync_product.py` (its glob already covers new plugins).

## New plugin `carrel-guard`
- `hooks/hooks.json`:
  - `PreToolUse` matcher `Read` → `scripts/read-guard.sh`. If `tool_input.file_path` has a pdf/docx/odt/epub/rtf/xlsx/png/jpg/ico extension (confirm by `carrel inspect --json` type when cheap; extension is enough for the decision), `carrel` is on PATH, and the file is under 64 MiB: convert to text (`carrel convert --to txt --out-dir "$CACHE"` where `CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/carrel-guard/<sha256-of-path>/`; images use `carrel ocr --to txt` and are skipped silently if OCR is unavailable) and emit `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": {"file_path": "<text path>"}, "additionalContext": "carrel-guard: <orig> was converted to text at <path> (<n> chars). Original left untouched."}}`. Schema verified against https://code.claude.com/docs/en/hooks on 2026-09-04 (`updatedInput` must match the Read tool's input schema — only `file_path` is rewritten; `offset`/`limit` pass through).
  - Anything else (not a binary, carrel missing, conversion failed, file too big): print nothing, exit 0 — the normal Read proceeds.
  - `SessionStart` → `scripts/capabilities.sh`: if `carrel` is on PATH, emit `additionalContext` with one paragraph: version, count of ok/degraded/unavailable commands from `carrel doctor --json`, and the three most useful missing binaries with their install hints. Otherwise exit 0 silently.
- Both scripts: bash, `set -u` (not `-e`), drain stdin, parse with `jq` else `python3` (same dual path as `carrel-agent/scripts/reindex.sh`), every exit path exits 0, no output on stderr in the happy path, finish under 5 s for a 20-page PDF (`timeout` guard on the carrel call).
- `README.md` inside the plugin explains the cache dir, how to clear it, and that the guard never modifies sources.

## Docs
- `MARKETPLACE.md`: plugin table for 7 plugins with what each gives Claude; guard section with a before/after transcript.
- `PLUGIN_AUTHORING.md`: the marker convention and `sync_plugins.py --check`.

## Acceptance
- `claude plugin validate .` passes (skip when `claude` absent); every `commands/*.md` has frontmatter with `description` and `carrel-command`, and both markers; `sync_plugins.py --check` exits 0 on a fresh checkout and 1 after a deliberate edit inside the markers (test does this in a tmp copy).
- Every name in `carrel.cli.COMMANDS` appears as a `carrel-command:` in exactly one plugin (test).
- `read-guard.sh` driven with a synthetic hook payload: for `tests/fixtures/sample.txt` → no output, exit 0; for `tests/fixtures/b.pdf` with `carrel` on PATH → JSON with `updatedInput.file_path` pointing at an existing `.txt` whose content matches `pdftotext` output (skip if pdftotext absent); with `PATH` stripped of `carrel` → no output, exit 0; for a nonexistent path → exit 0.
- `capabilities.sh` → valid JSON with `additionalContext` when carrel is present; silent exit 0 otherwise.
- Wave-3 orchestrator proof for `docs/TEST_REPORT.md`: `claude -p "/carrel-documents:redact tests/fixtures/sample.txt" --allowedTools "Bash(carrel:*)"` runs and reports hits; a headless session with `carrel-guard` installed reads `tests/fixtures/b.pdf` and the transcript shows the guard's `additionalContext`.
