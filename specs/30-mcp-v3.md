# spec: MCP v3 — the whole desk over MCP, not just the reading half

**Owns:** `src/carrel/commands/mcp.py` (the `TOOLS` table and its dispatch map), whichever command modules still lack a callable entry point, `docs/AGENTS.md`, `docs/FEATURES.md`, `README.md`, `docs/index.md`, `tests/test_mcp_stdio.py`, `tests/test_docs_drift.py` (the pin already exists).
**Wave:** v0.6.0.

## Why

`carrel mcp` serves 14 tools. 19 of the 33 commands have none, and four of those
are excluded by design: `watch` is a long-running loop, `desk` is a TUI,
`completion` prints a shell script, `mcp` is the server itself.

That leaves 15 commands an agent cannot reach — and the three that matter most
are `rename`, `batch` and `intake`, which is to say the entire v0.4.0
accounting-inbox pipeline. The `bookkeeper` agent ships with carrel and has to
shell out through Bash for exactly the steps that move files, which is the one
place where an agent most needs structured arguments, a dry-run it can inspect,
and a typed result it can check. Reading a desk is solved; acting on one is not.

## Scope: 14 → 25 tools

| Tool | Wraps | Notes |
|---|---|---|
| `carrel_ocr` | `ocr` | `--redo`, `--lang`; exit 3 surfaces as a tool error |
| `carrel_edit` | `edit` | the pdf/image/text verb set |
| `carrel_rename` | `rename` | **dry-run default**, `apply: true` to execute |
| ~~`carrel_batch`~~ | — | **cut, see below** |
| `carrel_intake` | `intake` | **dry-run default**; `apply: true` executes |
| `carrel_organize` | `organize` | dry-run default |
| `carrel_catalog` | `catalog` | export/import/status |
| `carrel_dedupe` | `dedupe` | `--near` included |
| `carrel_thumb` | `thumb` | |
| `carrel_extract_images` | `extract-images` | |
| `carrel_sign` | `sign` | manifest + verify; gpg optional |
| `carrel_form` | `form` | build/fill/list-fields |

Deferred with reasons: `audiobook` (minutes-long, needs progress streaming),
`color` and `proof` (narrow, no agent demand yet).

### `batch` is cut from this wave

`carrel batch` requires `--run CMD` — there is no invocation without a shell
command — and `core/actions.py` is the single `shell=True` site in the codebase
(D-013). A `carrel_batch` tool is therefore arbitrary shell execution with the
user's privileges, reachable by any MCP client, over any path on the machine.

That is a different kind of decision from "expose `ocr` over MCP", and it does
not follow from the read-only tools' precedent: the existing 14 read, convert
or report, and `carrel_redact` explicitly never writes. Exposing it needs its
own answer to the confinement question below, and probably a per-call
allow-list of commands rather than a free-form string. Out of scope here; the
CLI keeps it.

## The three rules this spec exists to get right

1. **Mutating tools are dry-run by default — in the tool, not by inheritance.**
   `rename`, `intake` and `organize` default `apply` to `false` and the result
   carries the same plan the CLI prints, so an agent that forgets the flag gets
   a plan rather than a filesystem change. Note the flags differ per command and
   the tool layer must normalise them: `rename`/`intake`/`organize` take
   `--apply` (default off), while `batch` — were it ever added — takes
   `--dry-run` (default **off**, i.e. it runs). Forwarding arguments verbatim
   would invert the rule for exactly the command where it matters most.
2. **The spec-29 guard applies unchanged.** A tool call that would move files
   git is tracking fails with the same message and exit code the CLI gives;
   `allow_tracked` is a distinct parameter an agent must set deliberately
   (the flag was renamed from `--force` in v0.5.0, D-022). MCP is not a way
   around it — and every path the tool names is confined to the server's root
   (D-021), so a mutating tool cannot reach outside the desk either.
3. **Every tool delegates to the command's impl function**, never to the click
   callback — the existing 14 already do, and that is why they are testable.

## Tests

`tests/test_mcp_stdio.py` already drives the server over real stdio. Extend it
with: `tools/list` returns 25; every name in `TOOLS` dispatches; each mutating
tool is a no-op without `apply`; a guarded path fails with exit 2's message; a
missing binary surfaces as exit 3's text rather than a traceback.
`tests/test_docs_drift.py` already pins the count and the names in README,
`docs/index.md`, `docs/FEATURES.md` and `docs/AGENTS.md`, so those four update
or the build fails.

## The confinement question — answered in v0.5.0 (D-021)

`docs/TEST_REPORT.md` recorded "MCP tools are not confined to the desk root" as
accepted behaviour, decided when every tool read, converted or reported. It was
re-opened for this wave, which adds tools that **move and rename files**, and
answered before it: **v0.5.0 confines the server to the directory it was started
in** — every tool path, every client-supplied `root` and both `carrel://`
resource URIs, symlinks resolved first, refused when they land outside;
`--allow-outside-root` lifts it for the whole session (`docs/DECISIONS.md`
D-021, `docs/AGENTS.md`, `SECURITY.md`).

What that leaves for this wave: the boundary is already enforced in the one
helper every tool argument goes through, so a mutating tool inherits it at no
cost and needs no confinement code of its own. Its remaining safety questions
are the dry-run default and the spec-29 guard (below), not the root.

## Not in scope

Resources beyond the two that exist (`carrel://file/{path}`,
`carrel://search/{query}`).
