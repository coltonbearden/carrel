# carrel

*A library desk for your files — and your agents.*

A **carrel** is a private study desk in a library: your materials close at hand, organized your way. carrel is that desk for your local files — pdf, docx, odt, epub, rtf, xlsx, md, html, txt, json, xml, csv, and png/jpg/ico images — with 26 commands to convert, OCR, inspect, diff, index, search, pack, watch, and more.

It treats AI agents as first-class users of the desk: every data-producing command speaks `--json` on stable exit codes, `carrel pack` turns file trees into LLM-ready context, `carrel mcp` serves the whole desk as ten MCP tools, and the [repository doubles as a Claude Code plugin marketplace](MARKETPLACE.md) whose plugins drive the same CLI.

## Start here

```sh
uv tool install 'carrel[all]'   # or: pipx install 'carrel[all]'
carrel doctor    # what can your desk do today? (+ install hints for the rest)
```

Plain `carrel` (no extras) skips the TUI, xlsx reading, and exact token counts; each of those exits 3 with the extra to add. The extras are listed in [Installing](INSTALL.md#optional-extras).

- **[Carrel in ten minutes](QUICKSTART.md)** — a guided tour of the CLI and the desk TUI.
- **[Installing](INSTALL.md)** — the CLI, its optional extras, the optional binaries that unlock each capability, and shell completions.
- **[Command reference](REFERENCE.md)** — every flag of all 26 commands, generated from real `--help` output.
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

`--query` only sees what the index knows, and `carrel index` skips unsupported types such as `.py` and `.toml` — so this fits document trees; for source trees use `--include`/`--exclude`, `--since REF`, or `--outline` ([Quickstart §6](QUICKSTART.md#6-pack-what-matters-pack-query)).

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
- **[Agents](AGENTS.md)** — the shipped agents, the ten MCP tools and two resource templates, and the watch + `claude -p` loop.
- **[Authoring a plugin](PLUGIN_AUTHORING.md)** — add your own to this marketplace.

## Inside the build

carrel v0.1.0 was designed, built, tested, and shipped in a single day by an autonomous multi-agent build; v0.2.0 followed the same wave mechanism ([Build plan](BUILD_PLAN.md)). **[How this was built](HOW_THIS_WAS_BUILT.md)** tells that story from the primary sources; [Architecture](ARCHITECTURE.md), [Decisions](DECISIONS.md), and the [Test report](TEST_REPORT.md) hold the details.
