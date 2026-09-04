# TEST_REPORT — 2026-07-16

Everything below was executed for real on the dev machine (Ubuntu 26.04 / WSL2). Commands are copy-pasteable from the repo root.

## Suite

```
$ uv run pytest
501 passed in 49.24s
```

20 test files; fixtures for **all 11 supported types** in `tests/fixtures/` (18 files), generated idempotently by `tests/fixtures/generate.py`, including: a PDF with text + embedded image (`text+image.pdf`), an AcroForm PDF (`form.pdf`: text field + checkbox), a scanned-style image (`scanned.png`, tesseract-verified) and an image-only PDF (`scanned.pdf`). Binary-gated tests use a `needs()` skip helper; on this machine all binaries exist so nothing skips.

## Cookbook end-to-end runs (all executed, all "RECIPE OK")

| # | Recipe | Proof observed |
|---|---|---|
| 01 | scan → OCR → md → index → search | search snippet returns `CARREL OCR [FIXTURE] 42` |
| 02 | watch-folder → auto-thumbnail | watch event rc=0; 128×96 png produced |
| 03 | dedupe sweep (exact + near) | 5 files → 2 survivors, newest kept |
| 04 | redaction (txt + true pdf raster redaction) | pdf `verified: true`; leak-check: no text layer PII |
| 05 | conversion relay md→html→pdf→txt + inspect summary (4+ types) | sentinel "melodious cartography" survives the relay |
| 06 | form build + fill roundtrip | fill read-back `Ada Lovelace` / `/Yes` |
| 07 | audiobook from markdown (chapters) | 2 chapter mp3s, engine espeak-ng, 40.23s total |

Run any of them: `bash examples/cookbook/07-audiobook-from-markdown.sh`

## Marketplace validation (the hard requirement) — documented flow, executed

(Local paths in this transcript are generalized to `~/projects/...`.)

```
$ claude plugin validate .
✔ Validation passed                       # marketplace + all 5 plugin manifests

$ claude plugin marketplace add ~/projects/carrel
✔ Successfully added marketplace: carrel (declared in user settings)

$ claude plugin install carrel-inspect@carrel
✔ Successfully installed plugin: carrel-inspect@carrel (scope: user)

$ claude plugin list
❯ carrel-inspect@carrel · Version 0.1.0 · Scope user · Status ✔ enabled

$ uv tool install .                        # puts `carrel` on PATH for the plugins
$ claude -p "/carrel-inspect:inspect text+image.pdf" --allowedTools "Bash(carrel:*)"
# → Claude ran `carrel inspect --json`, summarized: 2 pages, 50 KB, ReportLab
#   producer, sha256 … (real headless run, 2026-07-16)
```

Notes: in headless `-p` mode the command needs its plugin-namespaced name (`/carrel-inspect:inspect`); in the interactive `/plugin`-managed session, `/inspect` autocompletes. The PostToolUse reindex hook was validated end-to-end in the integration review (synthetic payload → index refreshed → search finds new content; degenerate payloads exit 0).

## Integration review (adversarial, execution-based)

Full sweep of all 24 commands: `--help` exit 0, real fixture invocation, parseable `--json`, missing-file → exit 4, exit 3 verified live with a crippled adapter, no direct `subprocess` outside the adapter layer (one documented exception: `watch` runs user-supplied shell actions). Findings — all fixed and re-verified:

- **M1** `organize.md` plugin doc drifted from the real `--into CATEGORY=DIR` flag → corrected.
- **m1** `pack`/missing path exited 2 instead of 4 (click `exists=True` pre-empted the convention) → now 4.
- **m2** `audiobook` silently overwrote outputs → `--force` guard added (refusal → exit 1).
- also fixed: `sign manifest` no longer hashes its own output file; `watch-folder.md` event list completed.

## MCP server

`carrel mcp` handshake validated by pytest subprocess tests (initialize / tools/list = 3 tools / tools/call inspect / error paths) and re-checked in the review sweep with a live JSON-RPC round-trip.

## finalize.sh

Tested in Phase 7 — see the "finalize.sh test runs" section appended below.

## finalize.sh test runs (Phase 7, executed 2026-07-16)

**Dry run:** `bash scripts/finalize.sh --dry-run --dest <tmp>/final-dry --name carrel` → exit 0; prints every step ([dry-run] prefixed), changes nothing.

**Real run into a temp dir:** `bash scripts/finalize.sh --dest <tmp>/carrel-final --keep-source` → copy relocated (tar-pipe, venv/caches excluded), full dev history preserved, release commit `release: carrel v0.1.0` created, tag `v0.1.0` set, clean tree; in the copy: `uv sync` → `carrel --version` boots, tests pass.

**Centralized rename in the copy:** `python3 scripts/rename_product.py lectern` → 99 text files patched, 5 plugin dirs renamed, pyproject name + console-script renamed, `_product.py` regenerated. Verified in the renamed copy: **entire 501-test suite green**, `claude plugin validate .` ✔, `lectern --help` / `lectern doctor --json` correct. Guarantees enforced by design: the Python import package stays `carrel`; core-owned literals (`.carrel/`, `carrel.db`, `carrel.*` module paths) are protected from renaming; fixture content is name-neutral (nothing product-named is baked into committed binaries).


# v0.2.0 — 2026-09-04

Executed on the dev machine (Ubuntu 26.04 / WSL2, Python 3.12.13) against `feat/v0.2.0` at commit `7ee57f3` (waves 1–2 merged: specs 15–19 and 21). Commands are copy-pasteable from the repo root with `uv run` in front. The wave-3 results (spec 20 plugins, the integration review fixes, and the final suite) are appended below.

## Suite

```
$ uv run pytest -p no:cacheprovider -o addopts="" -q
........................................................................ [  8%]
.........s.............................................................. [ 16%]
…
......................s....s............................................ [ 75%]
…
..................................................................           [100%]
855 passed, 3 skipped in 84.12s (0:01:24)
```

28 test files (new this release: `test_office.py`, `test_catalog.py`, `test_completion.py`, `test_mcp_stdio.py`, `test_reference_sync.py`). Fixtures now cover **all 15 supported types** (23 files in `tests/fixtures/`, incl. `sample.docx/odt/epub/rtf/xlsx` generated by pandoc and openpyxl). The three skips are environment-dependent, e.g. `tests/test_completion.py:165: zsh not installed`. Coverage floor in CI: `--cov-fail-under=80` (measured 86% when set). `uv run python scripts/sync_reference.py --check` → `docs/REFERENCE.md: up to date`.

## Proof 1 — office round trip (spec 18)

The fixture sentinel *melodious cartography* survives `sample.md → docx → md`:

```console
$ uv run carrel convert tests/fixtures/sample.md --to docx -o /tmp/office/sample.docx
tests/fixtures/sample.md -> /tmp/office/sample.docx  [pandoc]
$ uv run carrel convert /tmp/office/sample.docx --to md -o /tmp/office/roundtrip.md
/tmp/office/sample.docx -> /tmp/office/roundtrip.md  [pandoc]
$ grep -n "melodious cartography" /tmp/office/roundtrip.md
4:phrase is *melodious cartography*, planted here for extraction tests.
28:Final paragraph mentioning melodious cartography once more, then
```

Also observed in the same run: `inspect sample.docx` → `paragraphs 14 · words 92 · created 2026-09-04T11:49:34Z`; `convert tests/fixtures/sample.xlsx --to csv` → `[openpyxl]`, header `title,shelf,year`; `--sheet 2` → the `Loans` sheet (`member,title,days_out`); `inspect sample.xlsx --json` → `sheets: [{Books, 4×3}, {Loans, 4×3}]`; a docx copied to `mystery.bin` inspects as `type: docx` (byte sniffing).

Degradation, in a fresh venv built with `uv pip install .` (no extras):

```console
$ carrel desk
error: textual is not installed (optional extra 'tui') — run: uv tool install 'carrel[tui]'  (from a checkout: uv sync --extra tui)   # exit 3
$ carrel convert tests/fixtures/sample.xlsx --to csv
error: 'openpyxl' is required for this operation but was not found.
  install: uv tool install 'carrel[office]'  (from a checkout: uv sync --extra office)   # exit 3
$ carrel pack tests/fixtures/sample.md --tokenizer exact --stats
error: 'tiktoken' is required for this operation but was not found.
  install: uv tool install 'carrel[tokens]' (or `uv sync --extra tokens` from a checkout)   # exit 3
$ carrel convert tests/fixtures/sample.docx --to txt -o s.txt     # pandoc is a binary, no extra needed
tests/fixtures/sample.docx -> s.txt  [pandoc]
```

## Proof 2 — `pack --query` on a scratch docs tree (spec 16)

Seven files (two guides, two reference pages, a meeting note, a CSV, a `scratch.py`) in a scratch folder outside the repo; the desk root is that folder, never the repo root.

```console
$ carrel --root DOCS pack DOCS --query release --tree-only
error: --query needs a desk index but none exists under DOCS — run `carrel index --root DOCS` first     # exit 4
$ carrel --root DOCS index
│ indexed 6 │ skipped 0 │ pruned 0 │ errors 0 │                                                            # scratch.py not an indexed type
$ carrel --root DOCS pack DOCS --query release --stats
┃ path                         ┃ type          ┃ size  ┃ tokens_est ┃ score  ┃ note ┃
│ guides/release-checklist.md  │ md            │ 202 B │ 56         │ -0.000 │      │
│ notes/topics.csv             │ csv           │ 48 B  │ 15         │ -0.000 │      │
│ reference/glossary.md        │ md            │ 142 B │ 38         │ -0.000 │      │
│ notes/meeting-2026-09-01.txt │ txt           │ 154 B │ 43         │ -0.000 │      │
│ guides/onboarding.md         │ md            │ 152 B │ 43         │ -0.000 │      │
│ TOTAL                        │ 5 in / 0 skip │ 698 B │ 195        │        │      │
$ carrel --root DOCS pack DOCS --query release --json --top 3     # meta + per-file score
{"tokens_est": 109, "query": "release", "top": 3}
guides/release-checklist.md -1.5123523093447907e-06
notes/topics.csv -1.309767441860465e-06
reference/glossary.md -1.090627420604183e-06
$ carrel --root DOCS pack DOCS --query xyzzyplugh --tree-only --fail-empty
error: no files matched --query 'xyzzyplugh'                                                                # exit 5
```

`exit-codes.md` (no "release") is absent; `scratch.py` contains "release" but is not indexed and can never be ranked — the documented limitation. Also in that run: `--outline` listed `L2 def release` under `scratch.py` and the `L1` heading of each `.md`; in a throwaway git repo `--since HEAD~1` packed exactly the two files commit B touched (`since: HEAD~1 (2 changed, 0 removed)`), `--changed` packed the one uncommitted edit, `--since` outside a repo exited 4 with git's message, and `--dedupe-content` marked `dup.md  [same as a.md]` with `deduped: 1` in the header.

## Catalog round trip (spec 17)

Same scratch tree, run from inside it: 2 tags + 1 note on `guides/release-checklist.md`, 1 tag on `reference/glossary.md`.

```console
$ carrel catalog export -o desk.json
wrote desk.json: 2 file(s), 3 tag(s), 1 note(s)
$ rm -rf .carrel && carrel --json index          # {"indexed": 6, …}
$ carrel catalog import desk.json
imported 3 tag(s), 1 note(s) across 2 file(s)
$ carrel tag ls guides/release-checklist.md
guides/release-checklist.md: process, release
$ carrel --json catalog import desk.json
{"tags_added": 0, "notes_added": 0, "files_touched": 0, "skipped_missing": 0, "tags_removed": 0, "notes_removed": 0}
$ echo x >> reference/exit-codes.md && rm notes/topics.csv && carrel --json index --status
… "stale": {"changed": 1, "missing": 1, "unindexed": 0}, "examples": {"changed": ["reference/exit-codes.md"], "missing": ["notes/topics.csv"], …}
```

`catalog status` prints `(schema 1)` and the hint line `` `carrel index` refreshes changed/unindexed files; `carrel index --prune` drops missing ones ``.

## MCP v2 (spec 15)

Live stdio round trip (`initialize → notifications/initialized → tools/list → resources/templates/list → resources/read`), one JSON object per stdout line, exit 0:

- `initialize` → `capabilities: {"tools": {}, "resources": {}}`, `serverInfo: {"name": "carrel", "version": "0.1.2"}`.
- `tools/list` → exactly 10 tools: `carrel_search`, `carrel_pack`, `carrel_inspect`, `carrel_tag`, `carrel_note`, `carrel_index`, `carrel_convert`, `carrel_diff`, `carrel_redact`, `carrel_doctor` (arguments in [AGENTS.md](AGENTS.md#the-mcp-server-ten-tools-two-resources)).
- `resources/templates/list` → `carrel://file/{path}` (`text/plain`) and `carrel://search/{query}` (`application/json`).
- `resources/read carrel://file/tests/fixtures/sample.txt` → the fixture text (`Carrel sample text fixture. …`).

`grep -c "def _walk\|def _tokens_est" src/carrel/commands/mcp.py` → 0 (the private copies are gone).

## Install ergonomics (spec 19)

- `carrel completion bash` → 28-line script containing `_CARREL_COMPLETE=bash_complete`; `zsh --json` → `{"shell": "zsh", "script": …}` (1165 chars, contains `_CARREL_COMPLETE`); `fish --install-hint` ends with the `~/.config/fish/completions/carrel.fish` comment block; `completion powershell` → click usage error, exit 2.
- `CARREL_BIN_PANDOC=/opt/nowhere/pandoc carrel convert sample.docx --to md` → exit 3, `… not found (override CARREL_BIN_PANDOC=/opt/nowhere/pandoc not found).`; `doctor` row reads `MISSING via CARREL_BIN_PANDOC` and `convert` drops to `degraded`. `CARREL_BIN_PANDOC=/usr/bin/pandoc carrel doctor` → `found via CARREL_BIN_PANDOC`; `--json` row carries `"override": {"var": "CARREL_BIN_PANDOC", "path": "/usr/bin/pandoc"}`.
- `carrel doctor --json` lists 18 adapters (`git` present; none of the nine removed names).

## Cookbook

Recipe 10 (`examples/cookbook/10-pack-what-matters.sh`) executed with `CARREL="uv run carrel"`: index summary of 6, `--stats` with the `score` column, `wrote …/ctx.md (5 files, ~186 tokens_est)` with `- query: 'release' (top 5, 5 hit(s))` in the header, `--json` `hits: 3` for `--top 3`, exit 5 on `--fail-empty`, then `RECIPE OK`. Note: without the `CARREL` override the recipe picks up whatever `carrel` is on `PATH` — on this machine the released v0.1.2, which predates `--query` (`Error: No such option '--query'`, exit 2). That is the convention working as intended.

## Observed by the docs pass (status after the review fixes)

- ~~`carrel doctor`'s **human** table drops the `[tui]`/`[office]` bracket text~~ — **fixed** in the review-fix commit (rich markup escaped; `tests/test_review_v020.py::test_doctor_human_output_keeps_extra_brackets`).
- ~~`pack --query` human `score` column reads `-0.000`~~ — **fixed**: scores print with three significant digits.
- `tag`/`note` resolve relative paths against the cwd rather than `--root` (exit 4 `no such file: <cwd>/guides/…` when run from elsewhere with `--root DOCS`); `index`, `search`, `catalog` and `pack --query` use `--root`. Documented in Quickstart §7 and the FAQ.
- `pack --tree-only --json` returns `"files": []` (the listing is under `tree`), so scripts asserting on `files` must drop `--tree-only`.

## Wave 3 — plugins v2 (spec 20), executed 2026-09-04

Run at commit `7686ca9` + the review-fix commit, with a throwaway local marketplace (`claude plugin marketplace add <checkout>`) and a PATH shim that resolves `carrel` to `uv run --project <checkout> carrel`, so the plugins drove the v0.2.0 code under test rather than the released 0.1.2 on PATH. Both plugins and the marketplace were removed afterwards (`claude plugin marketplace list` shows no `carrel`).

**`claude plugin validate .`** → `✔ Validation passed` (7 plugins). **`scripts/sync_plugins.py --check`** → `24 command files: up to date`.

**Proof 1 — `/carrel-documents:redact`** (headless):

```text
$ claude -p "/carrel-documents:redact $S/pii.txt --builtin email,phone -o $S/pii.redacted.txt" \
    --allowedTools "Bash(carrel:*)" "Bash(grep:*)"
Redaction complete and verified. The output is at …/pii.redacted.txt, and the original was not modified.
| Pattern | Count |   email | 3   phone | 2
Verification of the output file found zero email patterns and zero phone patterns.
One thing to flag: the file still contains an SSN-style string … rerun with `--builtin email,phone,ssn` …
$ tail -1 $S/pii.redacted.txt
Contact: █ or █
```

**Proof 2 — `carrel-guard` PreToolUse hook on a PDF read** (headless, `--allowedTools Read`):

```text
$ claude -p "Read the file tests/fixtures/b.pdf and quote its first line verbatim. Also say whether a hook told you the file was converted."
The first line of the file is:  Fixture B
Yes, a hook reported the conversion. A PreToolUse hook from carrel-guard said the PDF was converted to text at a
cached path …, with the original left untouched. The extracted text is short, at 135 characters, and its
distinguishing phrase is "second fiddle harbor."
$ ls $XDG_CACHE_HOME/carrel-guard   → one sha256-named directory holding b.txt
```

## Integration review (V3.2) — 12 findings, 9 fixed

The `integration-reviewer` sweep (26 commands × `--help` / fixture run / `--json` / exit 4 / exit 3 via `CARREL_BIN_*=/nonexistent`, MCP over real stdio with 68 requests, an extras-free venv, adapter-layer grep, docs-vs-`--help` scan) confirmed zero blockers and 12 findings. Fixed in `fix(review): address v0.2.0 integration review findings` with regression tests in `tests/test_review_v020.py`: nonexistent `--root` (exit 2, and exit 4 from DeskDB/MCP instead of a traceback); `diff`/`audiobook` accept documents; `search` without index exits 4 and `pack --query` bad FTS syntax exits 2 (aligned); `catalog import` skips out-of-root paths; mis-named xlsx converts; `ocr` type check precedes overwrite check; MCP `carrel_redact` type check precedes rule compilation; doctor markup escaping; `pack --since` help wording. Left as documented behavior: MCP tools are not confined to the desk root (a local stdio server with the caller's privileges; the per-call `root` argument already points anywhere), `tag`/`note` resolve relative paths against the cwd, `convert --sheet` is ignored for non-workbooks, `inspect` on a docx without pandoc reports `words: null` without a hint.

## Final suite on the release branch

```text
$ uv run pytest -p no:cacheprovider -o addopts="" -q
935 passed, 3 skipped in 96.93s (0:01:36)
$ uv run ruff check src tests scripts && uv run ruff format --check src tests scripts && uv run mypy
All checks passed! · 71 files already formatted · Success: no issues found in 38 source files
$ uv run python scripts/sync_reference.py --check && uv run python scripts/sync_plugins.py --check
docs/REFERENCE.md: up to date · 24 command files: up to date
$ uv run --group docs mkdocs build --strict → Documentation built · claude plugin validate . → ✔ Validation passed
```
