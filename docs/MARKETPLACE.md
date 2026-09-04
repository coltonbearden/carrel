# MARKETPLACE — using the carrel plugins in Claude Code

This repo doubles as a Claude Code plugin marketplace: `.claude-plugin/marketplace.json`
at the root declares five plugins living under [`plugins/`](https://github.com/coltonbearden/carrel/tree/main/plugins/). Everything
below was executed on 2026-07-16 (see [TEST_REPORT.md](TEST_REPORT.md) for the original
proof runs).

## Prerequisite: the carrel CLI on PATH

Every plugin is a thin wrapper that has Claude run the `carrel` CLI, so install it first:

```bash
uv tool install /path/to/this/repo     # puts `carrel` on PATH
carrel doctor                          # shows which optional binaries you have
```

(`uv tool install` — like `pipx` — installs the package into its own venv and links the
`carrel` binary into `~/.local/bin`.) Without it, every command falls back to telling you
to install it or run `uv run carrel ...` from this repo.

## Install flow

```bash
claude plugin validate .                                   # optional sanity check
claude plugin marketplace add coltonbearden/carrel
# ✔ Successfully added marketplace: carrel

claude plugin install carrel-inspect@carrel
# ✔ Successfully installed plugin: carrel-inspect@carrel (scope: user)

claude plugin list
# ❯ carrel-inspect@carrel · Version 0.1.0 · Scope user · Status ✔ enabled
```

Install any subset — the five plugins are independent. In an interactive session the
commands autocomplete by their short name (`/inspect`, `/pack`, ...). **In headless
`claude -p` mode you must use the plugin-namespaced name:**

```bash
claude -p "/carrel-inspect:inspect report.pdf" --allowedTools "Bash(carrel:*)"
```

## The five plugins

| Plugin | Slash commands | Also ships |
|---|---|---|
| **carrel-convert** | `/convert`, `/ocr`, `/thumb`, `/audiobook` | `doc-converter` agent — batch conversions with per-file verification via `carrel inspect` |
| **carrel-inspect** | `/inspect`, `/diff`, `/search`, `/pack` | `context-packing` skill — format choice, token budgeting, chunking strategy for `carrel pack` |
| **carrel-organize** | `/organize`, `/dedupe`, `/tag`, `/note-file` | — |
| **carrel-watch** | `/watch-folder` | `watch-automation` skill — auto-thumb / auto-index / auto-convert drop-folder recipes |
| **carrel-agent** | — | `file-librarian` agent, `agent-workflows` skill, the carrel MCP server, and the reindex hook (both below) |

What the commands actually do: each command's markdown maps your request onto the real
CLI flags (verified against `--help`, never invented) and runs `carrel ... --json`,
then interprets the result conversationally. Safety conventions baked in:

- `/organize` and `/dedupe` **always dry-run/report first** — nothing moves or is
  deleted until you confirm (`--apply`, and for dedupe additionally `--delete <policy>`).
- Overwrites require an explicit ask (`--force` is never passed by default).
- Exit code 3 (missing optional binary) is relayed with its install hint; exit 4 means
  a missing/unsupported input.

## The PostToolUse reindex hook (carrel-agent)

`plugins/carrel-agent/hooks/hooks.json` registers a PostToolUse hook on `Write|Edit`
that runs [`scripts/reindex.sh`](https://github.com/coltonbearden/carrel/blob/main/plugins/carrel-agent/scripts/reindex.sh). Effect:
whenever Claude writes or edits a file in a project where you have already run
`carrel index` (i.e. a `.carrel/` desk db exists under the session cwd), the index row
for that file is refreshed — `carrel search` stays current without re-indexing.

It is deliberately inert everywhere else. Every path out of the script is `exit 0`,
under one second, and it does nothing unless **all** of these hold:

1. `carrel` is on PATH,
2. the hook payload names an existing file,
3. a `.carrel/` directory exists under the session's cwd.

It never creates an index (`--if-indexed`), never blocks the session, and swallows
degenerate payloads silently.

**To disable it** (without losing the librarian agent/skill), disable or uninstall the
plugin that ships it:

```bash
claude plugin disable carrel-agent      # keep it installed, hook + MCP server off
claude plugin enable carrel-agent       # turn it back on
```

There is no per-hook toggle — hooks load with their plugin.

## The MCP server (carrel-agent)

`plugins/carrel-agent/.mcp.json` registers a stdio MCP server:

```json
{"mcpServers": {"carrel": {"command": "carrel", "args": ["mcp"]}}}
```

Verified by a live JSON-RPC round trip (`initialize` → `tools/list` against
`carrel mcp`, 2026-07-16): the server identifies as `carrel 0.1.0` (protocol
`2025-06-18`) and exposes exactly three tools —

| Tool | Inputs | Does |
|---|---|---|
| `carrel_search` | `query`, `root`, `limit` | Full-text search of the desk index (`.carrel/carrel.db`) under `root`. Requires a prior `carrel index` run. |
| `carrel_pack` | `path`, `max_bytes`, `tree_only` | Pack a file/directory into LLM-ready context (tree + extracted text). |
| `carrel_inspect` | `path` | Metadata for one file: detected type, size, mtime, sha256, mime guess. |

When the server is connected, Claude prefers these structured tools over shelling out
for those three operations. The server searches the desk under the session's working
directory — run `carrel index` there first.

## Updating, uninstalling, removing

```bash
claude plugin update carrel-inspect          # re-pull from the marketplace source
claude plugin uninstall carrel-inspect       # alias: claude plugin remove
claude plugin marketplace update carrel      # refresh the marketplace itself
claude plugin marketplace remove carrel      # alias: rm — drops marketplace + its catalog
```

(Command names taken from `claude plugin --help` / `claude plugin marketplace --help`.)

## See also

- [PLUGIN_AUTHORING.md](PLUGIN_AUTHORING.md) — add your own plugin to this marketplace.
- [AGENTS.md](AGENTS.md) — the agents and agentic workflows in depth.
- [TEST_REPORT.md](TEST_REPORT.md) — the executed proof of this whole flow.
