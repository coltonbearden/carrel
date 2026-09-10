# spec: meta — typed key/value fields on desk files (schema v2)

**Owns:** `src/carrel/core/db.py` (migration 2, meta API, catalog v2), new `src/carrel/commands/meta.py`, `src/carrel/commands/search.py` (`--meta`), `src/carrel/commands/catalog.py` (meta in export/import/status output), `src/carrel/commands/mcp.py` (`carrel_meta`, `carrel_search.meta`), `src/carrel/desk/app.py` (fields line in the inspector), new `tests/test_meta.py`, `tests/test_catalog.py` (schema 2 assertions), `plugins/carrel-organize/commands/meta.md`.
**Wave:** v0.4.0, PR A (with spec 23).

## Why
Tags say *that* a file belongs to a set; notes are prose. Nothing could hold `vendor=Acme`, `total=1234.50`, `due=2026-10-01`, `paid=true` in a way a query can use — which is what an accounting inbox needs (`which invoices over 1000 are due before November?`) and what `fields --save` and `intake` (specs 25, 27) will write.

## Schema (D-009: append a migration, never edit)
```sql
CREATE TABLE meta (file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                   key TEXT NOT NULL, value TEXT NOT NULL,
                   kind TEXT NOT NULL DEFAULT 'str', source TEXT NOT NULL DEFAULT 'user',
                   updated REAL NOT NULL, UNIQUE(file_id, key));
CREATE INDEX meta_key_value ON meta(key, value);
```
`MIGRATIONS = [(1, _SCHEMA), (2, _META_SQL)]`; `SCHEMA_VERSION == 2`. A v1 desk (or a v0 one stamped 1) migrates on open with tags/notes intact (tested).

## Values
- Keys: `[a-z0-9][a-z0-9_.-]{0,63}` after lower-casing (`normalize_meta_key`).
- Kinds `str|num|date|bool`, inferred by `coerce_meta(value, None)`: `true/false` → bool; `[-+]?\d+(,\d{3})*(\.\d+)?` → num stored as plain decimal text without separators or trailing zeros (`1,234.50` → `1234.5`) **unless the digits carry a leading zero** (`02134`, `0042` stay str — they are identifiers); `YYYY-MM-DD` (a real date) → date; else str. Explicit `--kind` is strict (`yes/no/1/0/on/off` for bool; `Decimal` for num; ISO date) and raises `CarrelInputError` (exit 4) otherwise.
- `source` is free text: `user` (CLI default), `agent` (MCP default), `fields`, `intake`.

## DeskDB API
`set_meta(path, key, value, *, kind=None, source="user") -> row`, `meta_of(path) -> [rows]`, `get_meta(path, key)`, `rm_meta(path, keys) -> n`, `meta_keys() -> {key: n}`, `find_by_meta(conditions) -> [paths]`, `meta_table(keys=None) -> (columns, rows)`, `counts()["meta"]`.
Conditions (`parse_meta_condition`): `key OP value` with OP `= != > >= < <= ~` or bare `key?`; a value may not start with an operator character (`vendor>>x` is a usage error, not a comparison against `>x`). A numeric literal compares as `CAST(value AS REAL)` against `num` fields *and* as text against every other kind (so `zip=02134` finds a str field); `=`/`!=` on text are `COLLATE NOCASE` and accept bool spellings (`paid=yes`); ordering on non-num kinds is lexical, which is chronological for ISO dates and lets a `due<2027` prefix work; `~` is an escaped `LIKE '%…%'`; `?` is existence. Conditions AND together. `!=` matches only files that *have* the key with another value.

## Catalog (schema 2)
Export selects files with tags OR notes OR meta; each entry gains `"meta": [{key, value, kind, source}]` sorted by key (no `updated`, so exports stay byte-identical). Import: `_validate_catalog` accepts an optional `meta` list (shape-checked, keys normalised, every value canonicalised through `coerce_meta(value, kind)` so a document cannot smuggle `abc` under `num`); rows are upserted and counted under `meta_set` only when the stored triple changed; `--replace` clears meta too (`meta_removed`). Schema-1 documents import unchanged.

## CLI (`carrel meta`, a click group)
- `set PATH KEY=VALUE... [--kind K] [--source S]` → `{path, set: [keys], meta: {k: v}}`; registers the file (exit 4 if missing); bad pair / key → exit 2; bad value for an explicit kind → exit 4.
- `get PATH KEY [--fail-empty]` → `{path, key, value|null, kind, source}`; human prints the bare value (nothing when absent); exit 5 with `--fail-empty`.
- `ls [PATH]` → `{path, meta: [{key, value, kind, source, updated(iso)}]}` or `{keys: {key: n}}`.
- `rm PATH KEY...` → `{path, removed, meta}`.
- `find COND...` → `[{path, meta: {k: v}}]`; bad condition → exit 2 even without a desk.
- `export [--key K]* [-o FILE] [--force]` → CSV to stdout (JSON rows with `--json`); `-o` writes CSV (or JSON when the name ends `.json`) and prints `{out, format, files, keys}`; refuses to overwrite without `--force`; exit 4 without a desk.
- Read-only subcommands never create `.carrel/`.

## Integration
- `search --meta COND` (repeatable) → `search_index(meta=[...])` post-filters through `find_by_meta`; a bad condition is a usage error (exit 2).
- `catalog status` counts and human table show `meta`; `catalog export -o` summary and `import` output count fields.
- Desk TUI inspector: a `fields` line under tags.
- MCP `carrel_meta {action, path?, fields?, key?, keys?, conditions?, source?, root?}`; `carrel_search` gains `meta: string[]`.

## Acceptance
- Fresh desk → `PRAGMA user_version = 2`; a v1 desk opens as v2 with its tags; `catalog status` prints `schema 2`.
- `meta set f vendor="Acme Corp" total=1,234.50 due=2026-10-01` → `find total>1000`, `find due<2026-11-01`, `find vendor~cme`, `find vendor="acme corp"` all return `f`; `find total>1e9` returns nothing.
- `meta export` CSV has `path` + sorted keys, empty cells for missing fields; `--key` picks columns in order.
- `search QUERY --meta total>100` narrows hits; `catalog export` → wipe → `import` restores fields (`meta_set` counted once, idempotent on re-import).
- `tests/test_catalog.py`, `tests/test_desk_db_cmds.py`, MCP suites stay green with the new counts.
