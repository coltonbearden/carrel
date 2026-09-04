# CONTRIBUTING

## Dev setup

```bash
git clone https://github.com/coltonbearden/carrel.git ~/projects/carrel && cd ~/projects/carrel
uv sync                 # creates .venv from pyproject.toml + uv.lock
uv run carrel doctor    # which optional binaries you have + apt install hints
uv run pytest           # 501 tests; binary-gated tests skip (with reason) when a binary is absent
```

Python ≥3.12, managed by [uv](https://docs.astral.sh/uv/). Optional external binaries
(pandoc, tesseract, ocrmypdf, weasyprint, pdftotext, pdftoppm, espeak-ng, ffmpeg, gpg,
exiftool) unlock more tests and commands — `carrel doctor` lists them all; nothing is
required to run the core suite.

## Coding standards

The binding rules live in [`CLAUDE.md`](https://github.com/coltonbearden/carrel/blob/main/CLAUDE.md) (repo root) and
[ARCHITECTURE.md](ARCHITECTURE.md) §Global contracts. The short version:

- Type hints on public functions, `pathlib.Path` over strings, f-strings, no global
  state. CLI framework is **click** — not argparse.
- Every command: working `--help`, `--json` when output is data (one JSON object/array
  on stdout, nothing else), ≥1 test, graceful degradation when an optional binary is
  missing.
- **No stubs, no TODOs** in shipped commands. Can't finish it? Cut it and document the
  cut in [FEATURES.md](FEATURES.md).
- Product name comes from `/product.json` — never hardcode "carrel" in code or
  generated output (docs prose is fine).

### The adapter-layer rule (most-enforced rule in review)

External binaries are called **only** through `src/carrel/core/adapters.py`
(`have()` / `require()` / `run()`, one `ADAPTERS` registry that `doctor` reads).
Command modules never import `subprocess`. `MissingDependencyError` is caught centrally
in `cli.py` and becomes an actionable stderr message + install hint, exit 3. The
integration reviewer greps for violations; the one documented exception is `watch`
running user-supplied shell actions.

### Exit codes (memorize these)

| code | meaning |
|---|---|
| 0 | success |
| 1 | general/unexpected error (stderr message; traceback only with `--debug`) |
| 2 | bad usage/arguments |
| 3 | missing optional dependency (message names the binary + install hint) |
| 4 | input file missing / unreadable / unsupported type |
| 5 | empty result with `--fail-empty` |

## How to add a command

1. **Spec first.** Add/extend a spec in `specs/` with an **Owns** line (your exact write
   boundary) and an **Acceptance** section.
2. **Module.** Create `src/carrel/commands/<name>.py` exporting a click command named
   `cmd`. Use the core library: `core.adapters` (binaries), `core.output.emit`/`fail`/
   `ExitCode` (output + errors), `core.filetypes`, `core.textextract`, `core.db`.
3. **Register it.** Add `"<cli-name>": "<module_name>"` to the `COMMANDS` dict at the
   top of `src/carrel/cli.py`. Commands are lazy-imported — a broken import must only
   break its own command, so keep import-time work at zero.
4. **Tests.** `tests/test_<name>.py`, driving the real CLI on fixtures from
   `tests/fixtures/` (regenerate via `tests/fixtures/generate.py`; the docx/odt/
   epub/rtf/xlsx fixtures come from pandoc and openpyxl, whose bytes differ
   between tool versions, so they are written once and kept unless you pass
   `--force`; never hand-edit
   binaries). Tests needing an optional binary use the `needs()` skip helper from
   conftest. Run them: `uv run pytest tests/test_<name>.py -q`.
5. **Verify by hand** before claiming done: `uv run carrel <name> --help`, one real
   fixture invocation, `--json` piped through `python -m json.tool`, and the failure
   paths (missing file → 4; missing binary → 3).
6. Optionally wrap it in a plugin command — see
   [PLUGIN_AUTHORING.md](PLUGIN_AUTHORING.md).

## Commit convention

Branch `main`. History is checkpointed, not noisy:

- `phase(N): ...` — phase-gate commits (plan, test report, finalize).
- `wave(N): ...` — a verified wave of parallel module work (see
  [AGENTS.md](AGENTS.md) for how waves ran).

For ordinary contributions a plain imperative subject is fine; group your work into
one coherent commit per logical change. Never commit generated junk (`.gitignore`);
generated fixtures **are** committed.

## PR expectations

- `uv run pytest` fully green — including `tests/test_marketplace.py` if you touched
  `plugins/` (and `claude plugin validate .` passing when you have the CLI).
- No stubs/TODO/placeholder code; cut-and-document instead.
- Exit codes and `--json` shapes match the contracts above.
- New/changed flags reflected in any plugin command markdown that wraps them (doc
  drift is a review finding — it has happened).
- Claims verified by execution: paste real command output in the PR description, the
  way the builder agents do in their reports.
