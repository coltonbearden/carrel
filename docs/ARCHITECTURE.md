# ARCHITECTURE

## Stack

Python ≥3.12 (dev: 3.14), **uv**-managed. CLI framework: **click** (groups, stable). Key libs: `pypdf`, `Pillow`, `reportlab` (stamp), `watchdog` (watch), `markdown-it-py` (md→html fallback), `rich`. External binaries only through the adapter layer.

Heavier Python dependencies are **optional extras** (D-007), declared in `pyproject.toml [project.optional-dependencies]`:

| Extra | Package | Gates | Missing → |
|---|---|---|---|
| `tui` | `textual` | `carrel desk` | exit 3: `textual is not installed (optional extra 'tui') — run: uv tool install 'carrel[tui]'  (from a checkout: uv sync --extra tui)` |
| `office` | `openpyxl` | xlsx reading in `convert`/`inspect`/`index`/`pack`/`diff` | exit 3 with `uv tool install 'carrel[office]'` |
| `tokens` | `tiktoken` | `pack --tokenizer exact` | exit 3 with `uv tool install 'carrel[tokens]'` |
| `all` | the union | — | — |

Textual is **not** a core dependency: a plain install runs every command except `desk`. Each gated import is lazy and fails the same way a missing binary does, so the CI `test-minimal` job (no extras, no optional binaries) stays green through skips, never crashes.

```
src/carrel/
├── __init__.py            # __version__ etc. from _product.py
├── _product.py            # GENERATED copy of /product.json (scripts/sync_product.py); never edit
├── cli.py                 # click root group; lazy-registers commands; global --json/--debug/--root
├── core/
│   ├── adapters.py        # binary registry + require()/have()/run(); CARREL_BIN_* override; MissingDependencyError
│   ├── output.py          # emit()/fail(); ExitCode enum; human tables via rich
│   ├── filetypes.py       # detect(path) -> FileType (ext + magic bytes + zip-container probe)
│   ├── textextract.py     # extract_text(path) for any supported type (uses adapters; openpyxl for xlsx)
│   └── db.py              # DeskDB: .carrel/carrel.db (files, FTS5, tags, notes) + MIGRATIONS
├── commands/<name>.py     # one module per subcommand; exports `cmd` (click.Command)
│                          #   incl. catalog.py (export/import/status), completion.py, mcp.py
└── desk/                  # textual app (flagship; `tui` extra)
```

## Global contracts (binding for every module)

### CLI shape

- Root: `carrel <command> [args]`. Every command: `--help` works, `--json` (where output is data) prints ONE JSON object/array to stdout and nothing else, human mode may use rich.
- Commands are registered in `cli.py` via a `COMMANDS: dict[str, str]` name→module map with lazy import (startup stays fast; a broken optional import breaks only its command). 26 commands as of v0.2.0.
- Global `--debug` (tracebacks), `--root PATH` (desk root for db-backed commands; default: cwd).
- `carrel completion bash|zsh|fish` prints click's completion script in-process (no subprocess); `--install-hint` appends the per-shell enable lines as a comment block; an unknown shell exits 2.

### Exit codes (`core.output.ExitCode`)

`0` OK · `1` error · `2` usage · `3` missing optional dependency (binary **or** extra) · `4` bad/unsupported input · `5` empty result with `--fail-empty`.

### Adapter layer (`core.adapters`)

```python
@dataclass(frozen=True)
class Adapter:
    name: str            # e.g. "pandoc"
    binaries: tuple[str, ...]   # candidates in order, e.g. ("magick", "convert")
    version_args: tuple[str, ...]
    install_hint: str    # "sudo apt install pandoc"
    purpose: str

ADAPTERS: dict[str, Adapter]                 # single registry, used by doctor
have(name) -> bool
require(name) -> str                         # resolved path | raises MissingDependencyError(hint)
run(name, *args, input=None, timeout=120) -> CompletedProcess  # check=False; caller checks rc
```

Command modules never call subprocess directly — with one documented exception: `commands/watch.py` runs user-authored `--run` shell actions itself (substitutions are shell-quoted, `--action-timeout` bounds each action). `MissingDependencyError` is caught centrally in `cli.py` → stderr message + hint, exit 3; a binary exceeding its timeout raises `ToolTimeoutError` → exit 1 with the binary named, never a traceback.

**Override (D-008).** `CARREL_BIN_<NAME>` (adapter name upper-cased, `-` → `_`, e.g. `CARREL_BIN_ESPEAK_NG`) pins the exact binary; when set, `PATH` is not searched for that adapter. A set-but-missing path counts as missing and the message names it:

```text
error: 'pandoc' is required for this operation but was not found (override CARREL_BIN_PANDOC=/opt/nowhere/pandoc not found).
  purpose: document conversion hub (md/html/txt…)
  install: sudo apt install pandoc
```

`doctor` shows `found via CARREL_BIN_PANDOC` / `MISSING via CARREL_BIN_PANDOC`, and its `--json` adapter rows carry `"override": {"var", "path"}` or `null`. This is the single exception to config-free; details in [CONFIGURATION.md](CONFIGURATION.md#pinning-a-binary-carrel_bin_name).

**Registry hygiene.** Every entry is wired to at least one command. v0.2.0 added `git` (for `pack --since`/`--changed`) and removed nine entries no command referenced (`gs`, `pngquant`, `jq`, `mlr`, `rg`, `fd`, `sqlite3`, `inotifywait`, `claude`) — see the Cuts log in [FEATURES.md](FEATURES.md#cuts-running-log-updated-through-the-build). `carrel doctor --json` lists 18 adapters.

### Output (`core.output`)

```python
emit(ctx, data, human=None)   # --json → json.dumps(data); else human(data) or rich pretty-print
fail(msg, code=ExitCode.ERROR)
```

### Desk DB (`core.db`) — `.carrel/carrel.db` under `--root`

```sql
files(id INTEGER PK, path TEXT UNIQUE, size INT, mtime REAL, hash TEXT, type TEXT, indexed_at REAL)
docs  (FTS5: content, path UNINDEXED)     -- contentless-delete FTS5 table keyed by files.id
tags  (file_id INT, tag TEXT, UNIQUE(file_id, tag))
notes (id INTEGER PK, file_id INT, created REAL, body TEXT)
```

`DeskDB(root)` context manager; opening applies `MIGRATIONS` (tracked by `PRAGMA user_version`, v1 = the layout above) and adding a migration is the only way to change the schema (D-009); all db-backed commands (index/search/tag/note/catalog, plus `pack --query`) share it.

**Migrations.** A fresh DB is created at version 1. A pre-v0.2.0 DB (`user_version` 0) is recognised as the version-1 layout and stamped 1 on open, data intact. `carrel catalog status` (alias `carrel index --status`) reports `schema_version`, `db_path`, row counts and stale rows (`changed` = size/mtime differ, `missing` = file gone, `unindexed` = on disk but not in the DB), always exit 0 — exit 4 only when no `.carrel/` exists under the root.

**Catalog export/import.** Tags and notes are the only data the desk cannot regenerate, so `carrel catalog export` writes them as one deterministic JSON document (sorted by path, byte-identical apart from `exported`):

```json
{"schema": 1, "product": "carrel", "version": "0.1.2", "exported": "…", "root": "/abs/root",
 "files": [{"path": "guides/release-checklist.md", "tags": ["process", "release"],
            "notes": [{"created": 1788522679.0094275, "body": "Step 4 needs …"}]}]}
```

`catalog import FILE` merges (tags `INSERT OR IGNORE`, notes deduplicated on `(file, created, body)`, so a second import adds nothing); `--replace` deletes all tags and notes first and prints what it removed; entries whose file is missing on disk count as `skipped_missing`. Exit 4 for invalid JSON or a `schema` newer than the build supports.

### Product identity

`/product.json` is the single source of truth. `scripts/sync_product.py` regenerates `src/carrel/_product.py` (dict literal) and patches `pyproject.toml` `version`, the plugin/marketplace manifests and `CITATION.cff`. A test asserts they match. `carrel --version` prints from `_product.py`.

### Type detection

`filetypes.detect(path)` → `FileType` enum over 15 supported types (`pdf md jpg png ico txt html json xml csv docx odt epub rtf xlsx`) + `UNKNOWN`; `.jpeg` maps to `jpg`, `.xlsm` to `xlsx`. Bytes beat names: extension first, then a magic-byte sniff (`%PDF`, PNG/JPEG/ICO signatures, `{\rtf`) confirms or overrides. A `PK\x03\x04` zip container is probed read-only (first 64 entries): a `mimetype` entry of `application/epub+zip` → epub, `application/vnd.oasis.opendocument.text` → odt; otherwise `[Content_Types].xml` plus a `word/` entry → docx, `xl/` → xlsx. The probe never raises (a broken zip falls back to the extension; a plain zip of text files stays `UNKNOWN`). Unsupported input → exit 4.

`FileType.is_document` is true for docx/odt/epub/rtf (pandoc reads them; PDF keeps its own paths); `textextract.extract_text` dispatches on the new types, so `index`, `search`, `pack`, `diff` and `audiobook` light up for all of them from one branch. xlsx text is `# <sheet>` headings followed by CSV-flattened rows, via openpyxl (`office` extra).

## Marketplace layout (schema per D-001, verified against live docs)

```
.claude-plugin/marketplace.json      # name "carrel", metadata.pluginRoot "./plugins"
plugins/
├── carrel-convert/   # /convert /ocr /thumb /audiobook           (+ doc-converter agent)
├── carrel-inspect/   # /inspect /diff /search /pack              (+ context-packing skill)
├── carrel-organize/  # /organize /dedupe /tag /note-file
├── carrel-watch/     # /watch-folder + watch-loop skill
└── carrel-agent/     # file-librarian agent, agent-workflows skill,
                      # PostToolUse hook: re-index files Claude writes (if .carrel exists),
                      # .mcp.json: the carrel MCP server (10 tools + resources, below)
```

The plugin set is growing in v0.2.0 (spec 20 adds `carrel-documents` and `carrel-guard` and generates every usage block from `--help`); [MARKETPLACE.md](MARKETPLACE.md) is authoritative for the current list. Slash commands are thin: they document flags and run `carrel …` via Bash, never duplicate logic. Plugins require carrel on PATH; each command's markdown says so and points to INSTALL.

### MCP server

`carrel mcp` = newline-delimited JSON-RPC 2.0 over stdio, pure stdlib, no SDK. `initialize` returns `capabilities: {"tools": {}, "resources": {}}` and `serverInfo: {"name": "carrel", "version": …}`. `tools/list` returns exactly ten tools whose bodies delegate to the same implementation functions the CLI uses (`search.search_index`, `pack.pack_paths`, `inspect.inspect_path`, the `DeskDB` tag/note methods, …) — `mcp.py` owns no walk or token-estimate of its own.

| Tool | Required | Optional |
|---|---|---|
| `carrel_search` | `query` | `root`, `limit`, `types`, `tags` |
| `carrel_pack` | `path` | `max_bytes`, `tree_only`, `format`, `include`, `exclude`, `root`, `query`, `top` |
| `carrel_inspect` | `path` | `deep`, `root` |
| `carrel_tag` | `action` (`add`/`rm`/`ls`/`find`) | `path`, `tags`, `root` |
| `carrel_note` | `action` (`add`/`ls`), `path` | `body`, `root` |
| `carrel_index` | — | `paths`, `update`, `prune`, `ocr`, `root` |
| `carrel_convert` | `path`, `to` | `out_dir`, `force`, `root` |
| `carrel_diff` | `a`, `b` | `mode`, `root` |
| `carrel_redact` | `path` | `builtin`, `pattern`, `replacement`, `root` |
| `carrel_doctor` | — | — |

Relative paths resolve against the server's `--root` (cwd by default); `root` overrides per call. Failures come back as `isError: true` with the CLI's message (install hint included for missing binaries), never a crash. `carrel_redact` never writes and rejects PDFs (the CLI's raster redaction is the path for those); `carrel_diff` reports `differ` as data, never as an error.

Resources: `resources/templates/list` returns `carrel://file/{path}` (`text/plain`, extracted text of one file) and `carrel://search/{query}` (`application/json`, the `carrel_search` payload); `resources/list` is empty by design (enumerating a desk is `carrel_pack --tree-only`'s job); an unknown URI is JSON-RPC error `-32002`. Ships in the `carrel-agent` plugin's `.mcp.json` as the plain command `carrel mcp`. The one-line purpose of each tool is in [AGENTS.md](AGENTS.md#the-mcp-server-ten-tools-two-resources).

## Flagship: `carrel desk` (textual, `tui` extra)

Three panes: DirectoryTree · Inspector (metadata + text preview + tags/notes from DeskDB) · Actions (convert/ocr/thumb/pack on selection, output to `./carrel-out/`). Read-only against core library APIs; no logic of its own. The guard in `commands/desk.py` turns a missing `textual` into exit 3 with the `carrel[tui]` hint.

## Testing and drift gates

pytest; fixtures generated by `tests/fixtures/generate.py` (committed outputs, including `sample.docx/odt/epub/rtf/xlsx`). Binary-dependent tests use the `needs("pandoc")` skip helper; extra-dependent tests use `pytest.importorskip`. Integration tests drive the CLI via `click.testing.CliRunner` or subprocess (`tests/test_mcp_stdio.py` spawns `python -m carrel.cli mcp` with pipes).

Generated artifacts are gated in CI's `lint` job so they cannot drift from the code:

- `scripts/sync_product.py` → `_product.py`, `pyproject.toml`, plugin/marketplace manifests, `CITATION.cff`.
- `scripts/sync_reference.py` → `docs/REFERENCE.md`, one section per `COMMANDS` entry and per subcommand, captured from `--help` in-process with `COLUMNS=100`; `--check` exits 1 on drift (`tests/test_reference_sync.py` runs it too).

CI matrix (`.github/workflows/test.yml`): `test` on Linux for Python 3.12/3.13/3.14 with every apt tool and `--all-extras`, enforcing a coverage floor (`--cov-fail-under=80`, measured 86% when set); `test-minimal` (Linux) and `test-minimal (macos)` with no extras and no optional binaries — both required checks; `test-minimal (windows)` runs advisory (`continue-on-error: true`) until it has been green on `main` for two weeks (BUILD_PLAN scope guard). Docs build with `mkdocs build --strict`.

## Data flow notes

- `textextract.extract_text` is the shared spine: convert(pdf→txt), pack, index, diff(pdf), audiobook all reuse it — the office/ebook branch made every one of them handle docx/odt/epub/rtf/xlsx at once.
- `pack --query` is search-then-pack: `DeskDB.fts_search(query, limit=top)` ranks, the normal PATH/include/exclude/ignore filters intersect, and files are emitted in relevance order with a per-file `score`. Only indexed files can be ranked; `index` skips unsupported types (`.py`, `.toml`, …), so query-driven packing fits document trees today ([FEATURES.md](FEATURES.md#explicit-scope-notes)).
- `pack --since REF` / `--changed` run `git diff --name-only` (plus `git ls-files --others --exclude-standard` for `--changed`) through the `git` adapter with cwd = the PATH's repository root; the result is intersected with the walk, and deleted files are listed in the header as `removed`.
- Long operations print progress to stderr (human mode only) so `--json` stdout stays clean.
