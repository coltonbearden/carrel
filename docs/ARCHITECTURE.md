# ARCHITECTURE

## Stack

Python ≥3.12 (dev: 3.14), **uv**-managed. CLI framework: **click** (groups, stable). TUI: **textual**. Key libs: `pypdf`, `Pillow`, `reportlab` (stamp), `watchdog` (watch), `markdown-it-py` (md→html fallback), `rich`. External binaries only through the adapter layer.

```
src/carrel/
├── __init__.py            # __version__ etc. from _product.py
├── _product.py            # GENERATED copy of /product.json (scripts/sync_product.py); never edit
├── cli.py                 # click root group; lazy-registers commands; global --json/--debug/--root
├── core/
│   ├── adapters.py        # binary registry + require()/have()/run(); MissingDependencyError
│   ├── output.py          # emit()/fail(); ExitCode enum; human tables via rich
│   ├── filetypes.py       # detect(path) -> FileType (ext + magic bytes)
│   ├── textextract.py     # extract_text(path) for any supported type (uses adapters)
│   └── db.py              # DeskDB: .carrel/carrel.db (files, FTS5, tags, notes)
├── commands/<name>.py     # one module per subcommand; exports `cmd` (click.Command)
└── desk/                  # textual app (flagship)
```

## Global contracts (binding for every module)

### CLI shape

- Root: `carrel <command> [args]`. Every command: `--help` works, `--json` (where output is data) prints ONE JSON object/array to stdout and nothing else, human mode may use rich.
- Commands are registered in `cli.py` via a `COMMANDS: dict[str, str]` name→module map with lazy import (startup stays fast; a broken optional import breaks only its command).
- Global `--debug` (tracebacks), `--root PATH` (desk root for db-backed commands; default: cwd).

### Exit codes (`core.output.ExitCode`)

`0` OK · `1` error · `2` usage · `3` missing optional dependency · `4` bad/unsupported input · `5` empty result with `--fail-empty`.

### Adapter layer (`core.adapters`)

```python
@dataclass(frozen=True)
class Adapter:
    name: str            # e.g. "pandoc"
    binaries: tuple[str, ...]   # candidates in order, e.g. ("fd", "fdfind")
    version_args: tuple[str, ...]
    install_hint: str    # "sudo apt install pandoc"
    purpose: str

ADAPTERS: dict[str, Adapter]                 # single registry, used by doctor
have(name) -> bool
require(name) -> str                         # resolved path | raises MissingDependencyError(hint)
run(name, *args, input=None, timeout=120) -> CompletedProcess  # check=False; caller checks rc
```

Command modules never call subprocess directly — with one documented exception: `commands/watch.py` runs user-authored `--run` shell actions itself (substitutions are shell-quoted, `--action-timeout` bounds each action). `MissingDependencyError` is caught centrally in `cli.py` → stderr message + hint, exit 3; a binary exceeding its timeout raises `ToolTimeoutError` → exit 1 with the binary named, never a traceback.

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

`DeskDB(root)` context manager; `ensure()` creates schema; all db-backed commands (index/search/tag/note/dedupe cache) share it.

### Product identity

`/product.json` is the single source of truth. `scripts/sync_product.py` regenerates `src/carrel/_product.py` (dict literal) and patches `pyproject.toml` `version`. A test asserts they match. `carrel --version` prints from `_product.py`.

### Type detection

`filetypes.detect(path)` → enum over the 11 supported types + `UNKNOWN`; extension first, magic-byte sniff (`%PDF`, PNG/JPEG/ICO signatures) to confirm/override. Unsupported input → exit 4.

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
                      # .mcp.json: carrel MCP server (search/pack/inspect as tools)
```

Slash commands are thin: they document flags and run `carrel …` via Bash, never duplicate logic. Plugins require carrel on PATH; each command's markdown says so and points to INSTALL.

### MCP server

`carrel mcp` = stdio JSON-RPC server (pure stdlib, no SDK): `initialize`, `tools/list`, `tools/call` exposing `search`, `pack`, `inspect`. Ships in `carrel-agent` plugin's `.mcp.json` via `${CLAUDE_PLUGIN_ROOT}`-independent command `carrel mcp`.

## Flagship: `carrel desk` (textual)

Three panes: DirectoryTree · Inspector (metadata + text preview + tags/notes from DeskDB) · Actions (convert/ocr/thumb/pack on selection, output to `./carrel-out/`). Read-only against core library APIs; no logic of its own.

## Testing

pytest; fixtures generated by `tests/fixtures/generate.py` (committed outputs). Binary-dependent tests use `@needs("pandoc")` skip-marker helper. Integration tests drive the CLI via `click.testing.CliRunner` or subprocess.

## Data flow notes

- `textextract.extract_text` is the shared spine: convert(pdf→txt), pack, index, diff(pdf), audiobook all reuse it.
- Long operations print progress to stderr (human mode only) so `--json` stdout stays clean.
