# spec: source index — `carrel index` covers source trees

**Owns:** `src/carrel/core/filetypes.py`, `src/carrel/core/textextract.py`, new `src/carrel/core/ignore.py`, `src/carrel/commands/index.py`, `src/carrel/commands/pack.py` (extraction of the `.gitignore` matcher only), `src/carrel/core/db.py` + `src/carrel/commands/sign.py` (path-separator fix), new `tests/test_source_index.py`, `tests/fixtures/generate.py` (one new fixture), `examples/cookbook/10-pack-what-matters.sh`.
**Wave:** post-v0.2.0.

## Why
`docs/FEATURES.md` closed v0.2.0 with "Indexing source types is a planned follow-up". `carrel index` skipped every path `detect()` typed `UNKNOWN`, which was every source file, while `pack` packed the same files happily (`pack.py`: `if ftype is FileType.UNKNOWN:  # plain-text source file`). The consequences went well past `pack --query`:

- `search`, `tag`, `note` and the MCP `carrel_search` / `carrel_pack` tools were blind to code.
- `plugins/carrel-agent/hooks/hooks.json` runs `scripts/reindex.sh` on `PostToolUse(Write|Edit)` to re-index what Claude just writes. Claude writes `.py`/`.ts`/`.go`, so that hook was a silent no-op on the repos it exists for.

## filetypes.py
- New `FileType.CODE = "code"` with an `is_code` predicate. One member, not one per language: `desk/app.py` does `FileType(info["type"])` on the stored value, so `files.type` must be an enum member (D-010).
- `SOURCE_EXTENSIONS: dict[str, str]` (extension → language label) and `SOURCE_FILENAMES` for extensionless build files (`Makefile`, `Dockerfile`, `justfile`, …). `source_language(path) -> str | None` is the accessor.
- Kept **separate** from `_EXT_MAP` / `SUPPORTED_EXTENSIONS` so `detect_or_die`'s "supported:" message stays the list of types with real extractors rather than growing to ~80 entries.
- `detect()` order is unchanged for everything that already worked: magic bytes, then `_EXT_MAP`, and only then `SOURCE_EXTENSIONS`. A `.json`/`.xml`/`.csv`/`.md` file keeps its richer type. Extension-driven only — no new IO.

## textextract.py
One branch: `CODE` joins `TXT`/`MD` and is read verbatim with `encoding="utf-8", errors="replace"`. This is the single spine behind `index`, `search`, `pack`, `diff` and the MCP `carrel://file/{path}` resource, so one branch serves all of them.

## core/ignore.py (new)
`pack`'s `.gitignore` matcher moves out of `pack.py` unchanged (`IgnoreRule`, `IgnoreFile`, `load_ignore`, `ancestor_ignores`, `ignored`) and `pack` imports it. A prerequisite, not a nicety: `index._walk` had no ignore support, so admitting source files without it would index `node_modules/`, `build/` and `dist/`.

Git semantics are preserved, including the one that surprises: a file under an excluded directory **cannot** be re-included by `!pattern`, because the directory is pruned before descent. Verified against `git check-ignore -v`.

## index.py
- `_walk` honours `.gitignore`, seeded from `ancestor_ignores(top)` and extended per directory.
- The `UNKNOWN → skip` short-circuit now falls out naturally: source files are typed `CODE`, so they are candidates.
- `index_paths(..., source: bool = True, gitignore: bool = True)`; both are keyword-only and default on. CLI: `--no-source`, `--no-gitignore`.
- `--update` (hook mode) picks up source files too — this is what makes the `carrel-agent` reindex hook real.

## Path-separator fix (folded in)
`DeskDB.rel()` and `sign._manifest_entry_path()` returned `str(...)`, i.e. native separators. `files.path` is read straight back out by `export_catalog`, so a catalog written on Windows could not import on Linux — defeating the reason D-009 exists. Both now return `.as_posix()`, matching what `pack.py` already did.

## Acceptance
- `carrel index` on a source tree indexes `.py`/`.rs`/`.toml`; `search` finds a term inside a `.py`; `pack --query` ranks it.
- `.gitignore`d and hidden paths are never walked; `--no-gitignore` and `--no-source` opt out.
- `search --type code` filters to source files (free: `_valid_types()` derives from the enum).
- `FileType(row["type"])` round-trips for an indexed source file.
- `convert foo.py --to pdf` still exits 4 cleanly (`supported_targets` derives from `CONVERTERS`, which has no `CODE` pair).
- `tests/fixtures/sample.py` exists so `test_support_matrix_covered` still holds.
- `examples/cookbook/10-pack-what-matters.sh` demonstrates source ranking and ends `RECIPE OK`.
- No schema migration: `files.type` is free-form `TEXT`, `MIGRATIONS` is untouched.
