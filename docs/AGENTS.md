# AGENTS — the agents that built carrel, and the agents carrel ships

Two distinct casts:

1. **Builder agents** in [`.claude/agents/`](https://github.com/coltonbearden/carrel/tree/main/.claude/agents/) — Claude Code subagents
   that built this repo, wave by wave. They stay useful for maintenance.
2. **Shipped agents & skills** in [`plugins/`](https://github.com/coltonbearden/carrel/tree/main/plugins/) — what users get when they
   install the marketplace plugins ([MARKETPLACE.md](MARKETPLACE.md)).

## The five builder agents

| Agent | Role | Ground rule that keeps it honest |
|---|---|---|
| [`module-builder`](https://github.com/coltonbearden/carrel/blob/main/.claude/agents/module-builder.md) | Implements exactly one spec from `specs/` — command module + its tests | Touches only the paths its spec's **Owns** line lists; must paste real pytest output; no stubs/TODOs |
| [`test-engineer`](https://github.com/coltonbearden/carrel/blob/main/.claude/agents/test-engineer.md) | Fixtures, integration tests, cookbook validation | Fixtures generated programmatically (`tests/fixtures/generate.py`), never hand-crafted binaries; drives the real CLI, no fs mocking |
| [`integration-reviewer`](https://github.com/coltonbearden/carrel/blob/main/.claude/agents/integration-reviewer.md) | Adversarial cross-module review | Verifies by **execution**, not by reading reports — runs `--help`, fixture invocations, `--json | python -m json.tool`, failure paths; reports, never fixes |
| [`doc-smith`](https://github.com/coltonbearden/carrel/blob/main/.claude/agents/doc-smith.md) | Reference docs, guides, cookbook recipes | Never documents a flag it didn't see in real `--help` output; runs every recipe before writing it down |
| [`design-artist`](https://github.com/coltonbearden/carrel/blob/main/.claude/agents/design-artist.md) | Visual identity: SVG logo/banner, palette, README/TUI theming | Original hand-authored SVG only; palette defined once in `docs/BRAND.md` |

### How they actually built carrel: waves

The orchestrator session dispatched ≤4 builder agents in parallel per wave
([BUILD_PLAN.md](BUILD_PLAN.md)), verified each wave personally by running smoke tests,
then committed `wave(N): ...`:

- **Wave 1** — test-engineer (fixtures + core tests) ∥ module-builders (doctor+mcp,
  pack, edit). No cross-deps: Wave 1 tests synthesized their own inputs because the
  shared fixtures were being built concurrently.
- **Wave 2** — module-builders: convert, ocr, inspect+diff, index/search/tag/note (now
  against shared fixtures).
- **Wave 3** — module-builders: thumb/extract-images/proof/color, watch/organize/dedupe,
  redact/sign/form, and the marketplace + 5 plugins. MVP line.
- **Wave 4** — audiobook, the desk TUI, snippets+cookbook seeds (doc-smith), and an
  integration-reviewer sweep whose findings (flag drift in a plugin doc, a wrong exit
  code, a silent overwrite) were all fixed and re-verified — see
  [TEST_REPORT.md](TEST_REPORT.md).

The enforcement pattern that made this work: every agent's completion report must
contain *executed* output (pytest tails, real invocations), and the reviewer re-runs
everything anyway. Claims are verified by execution, never trusted.

## The shipped agents (what plugin users get)

### `doc-converter` (carrel-convert)

Batch conversion specialist. Invoke it when many files need converting/OCR-ing/
thumbnailing at once. Its method: Glob the exact inputs → check support
(`carrel convert --help` matrix, `carrel doctor --json`) → one multi-source
`carrel --json convert SRC... --to EXT --out-dir DIR` → **verify every output** with
`carrel inspect --json` → report a converted/failed/skipped scoreboard. Never
overwrites without an explicit `--force` ask.

### `file-librarian` (carrel-agent)

Question-answering over a local document collection, with citations. Its method:
locate the desk root → `carrel --json --root DIR index` (incremental, always safe) →
`carrel --json --root DIR search "QUERY"` with 2-3 FTS5 formulations → open the top
hits to verify (snippets are leads, not answers) → answer with a `Sources:` list of
file paths. Persists findings on request via `carrel tag add` / `carrel note add`.

## Driving carrel from Claude Code in practice

Day-to-day, you combine three layers:

- **Slash commands** for one-offs: `/inspect report.pdf`, `/pack ./papers as xml`.
- **Agents** for batches and Q&A: "convert everything in ~/scans to searchable PDFs"
  (doc-converter), "which of my papers mention distillation?" (file-librarian).
- **The `agent-workflows` skill** (carrel-agent) for recurring pipelines. It teaches
  four patterns: watch + `claude -p`, index-then-ask, desk-over-MCP, and
  pack-for-a-second-opinion.

### Worked example: the watch + `claude -p` loop

The pipeline from the skill — auto-summarize every PDF dropped into a folder — with
every flag verified against the installed `carrel watch --help` / `carrel convert --help`:

```bash
carrel watch ~/inbox --on created --glob '*.pdf' \
  --run 'sh -c "carrel convert {path} --to txt -o /tmp/drop.txt --force && claude -p \"Summarize /tmp/drop.txt in 5 bullets\" >> ~/inbox/summaries.md"'
```

How it works, piece by piece:

- `carrel watch DIR` is **non-recursive** and watchdog-based; `--on created` fires on
  new files only; `--glob '*.pdf'` narrows matches.
- `--run CMD` runs per event; `{path}` (also `{name}`, `{dir}`) is substituted with the
  triggering file, already shell-quoted. Repeatable — multiple `--run` flags execute
  in order.
- Inside the action: convert the PDF to text, then a headless Claude turn (`claude -p`)
  appends a 5-bullet summary to a running markdown log. Keep the prompt self-contained
  and route output to a file, never the terminal.
- **Test before trusting**: add `--once --timeout 60` for a bounded dry run, drop a
  fixture PDF in from another shell, check `summaries.md`. `--debounce 500` (default)
  absorbs editor save-storms; `--json-lines` gives machine-readable logs.

Loop hygiene (from the skill, enforced by the CLI's own design): indexing is
incremental and `--if-indexed` makes hook-style reindexing a no-op until a desk exists,
so loops can run unconditionally; `carrel dedupe` cannot delete anything without both
`--delete <policy>` and `--apply`, so keep automation on the report side; bound every
unattended loop with `--timeout`.

### The MCP alternative

With the carrel-agent plugin enabled, a `carrel mcp` stdio server exposes
`carrel_search`, `carrel_pack`, and `carrel_inspect` as structured tools — Claude uses
those instead of Bash for search/pack/inspect. Details in
[MARKETPLACE.md](MARKETPLACE.md#the-mcp-server-carrel-agent).

## See also

- [PLUGIN_AUTHORING.md](PLUGIN_AUTHORING.md) — ship your own agent/skill in a plugin.
- [`examples/cookbook/`](https://github.com/coltonbearden/carrel/tree/main/examples/cookbook/) — executable versions of these
  pipelines (02 = watch loop, 08 = pack-for-Claude).
