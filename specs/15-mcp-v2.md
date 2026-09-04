# spec: mcp v2 — the whole desk over MCP

**Owns:** `src/carrel/commands/mcp.py`, `tests/test_mcp_doctor.py` (mcp classes only — doctor tests untouched), new `tests/test_mcp_stdio.py`.
**Additive-only edits allowed:** `src/carrel/commands/inspect.py` gains a public `inspect_path(path: Path, *, deep: bool = False) -> dict[str, Any]` wrapping the existing per-type detail functions; `src/carrel/commands/search.py` gains a public `search_index(root: Path, query: str, *, limit: int = 20, types: set[str] | None = None, tags: list[str] | None = None) -> list[dict[str, Any]]`. Both are pure refactors of code already inside the click callbacks — CLI behavior and `--json` shape must not change (existing tests are the guard).
**Wave:** 2 (after spec 18 has finished its `inspect.py` edits).

## Why
`mcp.py` exposes 3 tools out of 24 commands and carries private copies of the walk and token estimate that `pack.py` already owns (`mcp.py:6-9` defers exactly this refactor). Agents that install `carrel-agent` get search/pack/inspect and nothing else — no tags, no notes, no conversions, no way to learn what the desk can do.

## Wire surface (unchanged transport)
Newline-delimited JSON-RPC 2.0 on stdio, pure stdlib, no MCP SDK (as today). `initialize` now returns `capabilities: {"tools": {}, "resources": {}}`.

### Tools (`tools/list` → 10)
Every existing tool keeps its name and input schema. Bodies delegate:
- `carrel_search` → `search.search_index` (adds optional `types: string[]`, `tags: string[]` inputs).
- `carrel_pack` → `pack.pack_paths` (`pack.py:458`); `_walk`/`_tokens_est` in `mcp.py` are deleted. Adds optional `format: "json"|"md"|"xml"` (default json object as today), `include`/`exclude` globs, `query` (relevance-ranked packing, see spec 16 — pass through only if `pack_paths` accepts it; otherwise omit the field and note it).
- `carrel_inspect` → `inspect.inspect_path`; adds `deep: boolean`.
- **new** `carrel_tag` `{action: "add"|"rm"|"ls"|"find", path?, tags?: string[], root?}` → `DeskDB.add_tags/rm_tags/tags_of/find_by_tags`. `find` requires `tags`; `add`/`rm`/`ls` require `path`.
- **new** `carrel_note` `{action: "add"|"ls", path, body?, root?}` → `DeskDB.add_note/notes_of`.
- **new** `carrel_index` `{paths?: string[], update?: boolean, prune?: boolean, ocr?: boolean, root?}` → the index command's impl (reuse its `_index_file`/walk; make a public `index_paths(...)` in `index.py` **only if** spec 17 has not already done so — coordinate through the orchestrator; otherwise call the one spec 17 created). Returns `{indexed, skipped, pruned}` counts.
- **new** `carrel_convert` `{path, to, out_dir?, force?: boolean}` → convert's dispatch; returns `{output, type}` and, when `to` is a text type, `content` (capped at 1 MiB with `truncated: true`).
- **new** `carrel_diff` `{a, b, mode?: "auto"|"text"|"struct"|"pdf"|"image"}` → diff's `--json` payload; `differ: boolean` is part of the result, never an error.
- **new** `carrel_redact` `{path, builtin?: string[], pattern?: string[], replacement?}` → redact's text-type engine on the file **contents**; returns `{content, hits}`; **never writes**; PDFs are rejected with an `isError` message pointing at the CLI (`carrel redact file.pdf -o …`).
- **new** `carrel_doctor` `{}` → `doctor`'s `--json` payload (adapters + `CAPABILITIES` table, `doctor.py:27`) so an agent can decide what to call.

Every tool: relative paths resolve against `--root` (server cwd default) as today; `root` overrides per call; failures are `isError: true` with the same message the CLI would print (CarrelError text), never a crash; missing-binary failures include the install hint.

### Resources
- `resources/templates/list` → `[{uriTemplate: "carrel://file/{path}", name: "file text", mimeType: "text/plain"}, {uriTemplate: "carrel://search/{query}", name: "desk search", mimeType: "application/json"}]`.
- `resources/list` → `[]` (templates only; enumerating a desk is `carrel_pack --tree-only`'s job).
- `resources/read {uri}` → `carrel://file/<rel-or-abs path>` returns `contents: [{uri, mimeType: "text/plain", text}]` via `textextract.extract_text` (URL-decoded path, resolved against root, must exist); `carrel://search/<url-encoded query>` returns the `carrel_search` payload as JSON text. Unknown scheme/shape → JSON-RPC error `-32002` "resource not found".

## Acceptance
- `tools/list` returns exactly 10 tools; each `inputSchema` is a valid JSON Schema object with `type: object` and `required` listing only declared properties (tested generically over the list).
- Per-tool happy path on fixtures: tag add→ls→find round-trip; note add→ls; index a tmp dir then search hits; convert `sample.md` → txt returns content containing a known sentinel; diff `sample.csv` vs itself → `differ: false`; redact a tmp file with an email → `hits ≥ 1`, original file unchanged (hash equal); doctor payload has `adapters` and `capabilities` keys.
- Failure paths as `isError: true`: search without index, inspect missing file, convert to an unsupported target, redact a PDF, tool call with a missing required arg.
- `resources/read` on `carrel://file/sample.txt` returns the fixture text; unknown URI → `-32002`.
- `tests/test_mcp_stdio.py` spawns `sys.executable -m carrel.cli mcp` with pipes (the existing handshake test at `tests/test_mcp_doctor.py:318` moves here and grows): initialize → initialized → tools/list → `carrel_inspect` → `resources/templates/list` → `resources/read` → EOF; asserts exit 0 and one JSON object per stdout line.
- `mcp.py` contains no walk/token-estimate implementation of its own (`grep -c "def _walk\|def _tokens_est" mcp.py == 0`).
- Existing `inspect`/`search` CLI tests pass unchanged after the additive refactor.
