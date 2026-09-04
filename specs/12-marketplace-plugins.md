# spec: marketplace + plugins

**Owns:** `.claude-plugin/marketplace.json`, `plugins/**`, `tests/test_marketplace.py`.

## marketplace.json (schema per D-001)
`{"name":"carrel","owner":{"name": from product.json author},"metadata":{"description":..., "pluginRoot":"./plugins"},"plugins":[5 entries: name, source "./plugins/<name>" or bare name via pluginRoot, description, version (from product.json), keywords]}`
Use explicit `"./plugins/<name>"` sources (belt over pluginRoot cleverness).

## Plugins (each: `.claude-plugin/plugin.json` with name/description/version/author + components)

1. **carrel-convert** — commands: `convert.md`, `ocr.md`, `thumb.md`, `audiobook.md`; agent `doc-converter.md` (converts/OCRs batches, verifies outputs by running carrel inspect).
2. **carrel-inspect** — commands: `inspect.md`, `diff.md`, `search.md`, `pack.md`; skill `context-packing/SKILL.md` (when+how to pack folders for LLM context, chunking guidance, examples).
3. **carrel-organize** — commands: `organize.md`, `dedupe.md`, `tag.md`, `note-file.md`.
4. **carrel-watch** — command `watch-folder.md`; skill `watch-automation/SKILL.md` (recipes: auto-thumb, auto-index, auto-convert drop folder).
5. **carrel-agent** — agent `file-librarian.md` (indexes, searches, answers questions about a doc collection with citations to paths); skill `agent-workflows/SKILL.md` (looping patterns: watch+claude -p pipelines); hook `hooks/hooks.json`: PostToolUse on Write|Edit → `carrel index --update "$FILE" --if-indexed` via `${CLAUDE_PLUGIN_ROOT}/scripts/reindex.sh` (script guards: carrel on PATH + .carrel exists, always exit 0, <1s); `.mcp.json`: `{"mcpServers":{"carrel":{"command":"carrel","args":["mcp"]}}}`.

## Command markdown conventions
Frontmatter: `description`, `allowed-tools: ["Bash(carrel *)"]`(verify field names against docs excerpt in tool-results before writing), body: what it does, then instruct Claude to run `carrel <cmd> ... --json` with user's request mapped to flags, interpret results for user. Every command notes: requires carrel CLI (`uv tool install carrel` — see INSTALL).

## Acceptance
`claude plugin validate .` passes (run in tests via subprocess, skip if claude absent). JSON files all parse; every commands/*.md has frontmatter description; hook script is executable and exits 0 without carrel index present.
