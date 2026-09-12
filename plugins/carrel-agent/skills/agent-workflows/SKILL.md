---
name: agent-workflows
description: Looping and pipeline patterns that combine carrel with Claude Code — watch + claude -p pipelines, index-then-ask loops, MCP-backed desk queries (14 tools, carrel:// resources). Use when the user wants recurring or automated agentic processing of local files rather than a one-off command.
---

# Agent workflows with carrel

Patterns for wiring `carrel` and Claude Code together into pipelines. Run `carrel doctor --json` first to see what the environment supports (or install the `carrel-guard` plugin, whose SessionStart hook reports it), and `--help` on any carrel command before scripting it.

## Pattern: watch + `claude -p` pipeline

React to new files with a headless Claude turn. Example — summarize every PDF dropped into a folder:

```bash
carrel watch ~/inbox --on created --glob '*.pdf' \
  --run 'sh -c "carrel convert {path} --to txt -o /tmp/drop.txt --force && claude -p \"Summarize /tmp/drop.txt in 5 bullets\" >> ~/inbox/summaries.md"'
```

Notes: keep the `claude -p` prompt self-contained; append results to a log/markdown file; test with `--once --timeout 60` before leaving it running; bound each action with `--action-timeout`.

## Pattern: index-then-ask loop

For question-answering over a collection, keep one desk index and reuse it:

```bash
carrel --json --root ~/papers index          # incremental, cheap to re-run
carrel --json --root ~/papers search 'transformer AND survey'
carrel --root ~/papers pack ~/papers --query 'transformer AND survey' --top 10 -o ctx.md
```

Feed the hit paths to Claude (or the `file-librarian` agent in this plugin) rather than packing the whole corpus — search first, read the top hits, cite paths. `pack --query` is the one-step version. Narrow a search with the desk's own facts: `--tag ref:invoice:inv-2026-0042` (written by `carrel refs --tag`) or `--meta 'total>1000'` (fields from `carrel meta set`). `carrel catalog status` tells you when the index is stale; `carrel catalog export` backs up tags and notes.

## Pattern: desk over MCP

This plugin ships a `carrel` MCP server (`carrel mcp`, stdio, pure stdlib) via `.mcp.json`. When it is connected, prefer its structured tools over shelling out for the same operations. The server works on the desk under the session's working directory (the `root` argument narrows it to a subdirectory); run `carrel index` there first for search-backed tools.

The server is **confined to that directory**: a `path`, a per-call `root` or a `carrel://` URI that resolves outside it — symlinks included — comes back as a tool error (exit code 2) or resource-not-found, never as a read. Use the CLI through Bash for a file elsewhere, or start the server with `carrel mcp --allow-outside-root` when the whole filesystem is genuinely in scope.

Tools (14):

| Tool | Does |
|---|---|
| `carrel_search` | FTS5 search of the desk index (`query`, `root`, `limit`) |
| `carrel_pack` | Pack a file/directory into LLM-ready context (`path`, budgets, `tree_only`) |
| `carrel_inspect` | Metadata for one file (type, size, mtime, sha256, per-type detail) |
| `carrel_tag` | Add / remove / list tags on desk files |
| `carrel_note` | Add / list sidecar notes on desk files |
| `carrel_index` | Build or refresh the desk index (incremental) |
| `carrel_convert` | Convert a file to another supported type |
| `carrel_diff` | Compare two files (text / struct / pdf / image modes) |
| `carrel_redact` | Redact builtin or custom patterns from a text file or PDF |
| `carrel_doctor` | Environment capability report |
| `carrel_meta` | Set / get / list / remove typed fields on a desk file, or find files by conditions (`total>1000`, `due<2026-11-01`, `paid?`) |
| `carrel_fields` | Vendor, invoice number, dates, subtotal/tax/total, currency and IBAN from a document with a confidence per field; `save` writes them as desk fields |
| `carrel_mail` | Save an email's attachments into a directory, or group eml/mbox messages into threads (Message-ID / In-Reply-To / References) |
| `carrel_refs` | Find reference numbers (invoice, PO, IBAN, routing, tracking, …) in a file or directory; `tag` writes `ref:<kind>:<value>` tags, `link` groups files by shared value |

Resource templates (2), for `resources/read`:

- `carrel://file/{path}` — the extracted text of a file (same spine `pack` and `index` use), so Claude can read a PDF or docx as text without a conversion step.
- `carrel://search/{query}` — the search hits for an FTS5 query as a resource.

`tools/list` and `resources/templates/list` return the live schemas — trust those over this table if they differ.

## Pattern: pack for a second opinion

Bundle context for another model/session: `carrel pack DIR --format xml --chunk 40000 -o ctx.xml` then feed `ctx.xml.part1..N` sequentially; add `--tokenizer exact` when the budget is tight. See the `context-packing` skill (carrel-inspect plugin) for budgeting guidance.

## Hygiene for all loops

- Idempotence: `carrel index` is incremental and `--if-indexed` makes hook-style reindexing a no-op until a desk exists — loops can run unconditionally. `catalog import` is idempotent too.
- Never delete in a loop: `carrel dedupe` stays report-only unless both `--delete` and `--apply` are passed; `catalog import --replace` wipes tags/notes — keep automation on the report side.
- Budget: bound every unattended loop with `--timeout`, log with `--json-lines`, and route long outputs to files, not the terminal.
