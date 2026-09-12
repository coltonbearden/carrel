# carrel

*A library desk for your files — and your agents.*

**Read, index, pack and file your documents — from the terminal, for you and your agents.**

carrel turns the documents on your disk — PDFs, Word and OpenDocument files, ebooks, spreadsheets, email, scans — into text you can search, fields you can query, and context you can hand to an LLM. One CLI; every data command speaks `--json` with stable exit codes; dry-run by default; nothing overwritten without `--force`. It ships an MCP server and a [Claude Code plugin marketplace](MARKETPLACE.md) that drive the same commands, so Claude can read your `.docx`, pack the five relevant files out of five hundred, and file an invoice inbox by what the invoices say. Missing pandoc or tesseract? `carrel doctor` tells you what works today and how to unlock the rest.

A **carrel** is a private study desk in a library: your materials close at hand, organized your way. carrel is that desk for your local files — pdf, docx, odt, epub, rtf, xlsx, md, html, txt, json, xml, csv, eml/mbox email, and png/jpg/ico images — with 33 commands to convert, OCR, inspect, diff, index, search, pack, watch, file an inbox, and more. `carrel mcp` serves the whole desk as fourteen MCP tools.

## Three things to try

- **Give Claude the right context** — `carrel index ~/papers`, then `carrel pack ~/papers --query "…" --stats` packs what the desk's own ranking picks; `--since HEAD~5` does it from git history instead. Query terms must appear in the text (FTS5 AND-s them), and an empty pack exits non-zero under `--json`.
- **Read what the agent can't** — the `carrel-guard` plugin turns Office, ebook, email and spreadsheet files into text before Claude's `Read` sees them, and PDFs into cheap text; images stay pictures. Layout-heavy PDFs still want the visual `Read`, and the guard's note says so.
- **Turn an inbox into an archive** — `carrel fields` reads vendor, dates and totals with a confidence column; `carrel intake ~/inbox --to ~/archive` shows every planned move and files nothing until `--apply`. Extraction is English-label heuristics; originals are always kept.

## Start here

```sh
uv tool install 'carrel[all]'   # or: pipx install 'carrel[all]'
carrel doctor    # what can your desk do today? (+ install hints for the rest)
```

Plain `carrel` (no extras) skips the TUI, xlsx reading, and exact token counts; each of those exits 3 with the extra to add. The extras are listed in [Installing](INSTALL.md#optional-extras).

- **[Carrel in ten minutes](QUICKSTART.md)** — a guided tour of the CLI and the desk TUI.
- **[Installing](INSTALL.md)** — the CLI, its optional extras, the optional binaries that unlock each capability, and shell completions.
- **[Command reference](REFERENCE.md)** — every flag of all 33 commands, generated from real `--help` output.
- **[Cookbook & snippets](COOKBOOK.md)** — runnable, end-to-end recipes.

## Three things worth trying first

**Pack what matters.** Index a docs tree once, then pack only the files the index ranks for a query — in relevance order, with a score per file:

```sh
carrel --root docs index
carrel --root docs pack docs --query release --stats
```

```text
┃ path                         ┃ type          ┃ size  ┃ tokens_est ┃ score  ┃ note ┃
│ guides/release-checklist.md  │ md            │ 202 B │ 56         │ -0.000 │      │
│ notes/topics.csv             │ csv           │ 48 B  │ 15         │ -0.000 │      │
│ reference/glossary.md        │ md            │ 105 B │ 29         │ -0.000 │      │
│ notes/meeting-2026-09-01.txt │ txt           │ 154 B │ 43         │ -0.000 │      │
│ guides/onboarding.md         │ md            │ 152 B │ 43         │ -0.000 │      │
│ TOTAL                        │ 5 in / 0 skip │ 661 B │ 186        │        │      │
```

`--query` only sees what the index knows — and `carrel index` covers source and config files (`.py`, `.toml`, `.yaml`, …) as type `code` alongside documents, honoring `.gitignore`, so this works on source trees too ([Quickstart §6](QUICKSTART.md#6-pack-what-matters-pack-query)).

**Carry your tags and notes.** They are the one thing the desk cannot regenerate, so they export as plain JSON and merge back in:

```sh
carrel catalog export -o desk.json     # wrote desk.json: 2 file(s), 3 tag(s), 1 note(s)
carrel catalog import desk.json        # imported 3 tag(s), 1 note(s) across 2 file(s)
carrel catalog status                  # schema version, row counts, stale index rows
```

**Complete on Tab.** `carrel completion bash|zsh|fish` prints a completion script generated from the real command tree:

```sh
eval "$(carrel completion bash)"       # ~/.bashrc; see INSTALL for zsh and fish
```

## For agents and their operators

- **[The marketplace](MARKETPLACE.md)** — the Claude Code plugins: slash commands, agents, skills, hooks, and the MCP server.
- **[Agents](AGENTS.md)** — the shipped agents, the fourteen MCP tools and two resource templates, and the watch + `claude -p` loop.
- **[Authoring a plugin](PLUGIN_AUTHORING.md)** — add your own to this marketplace.

## Inside the build

carrel v0.1.0 was designed, built, tested, and shipped in a single day by an autonomous multi-agent build; v0.2.0 followed the same wave mechanism ([Build plan](BUILD_PLAN.md)). **[How this was built](HOW_THIS_WAS_BUILT.md)** tells that story from the primary sources; [Architecture](ARCHITECTURE.md), [Decisions](DECISIONS.md), and the [Test report](TEST_REPORT.md) hold the details.
