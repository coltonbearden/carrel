# Configuring Carrel

Honest answer first: **carrel is config-free by design.** There is no config
file, no dotfile in your home directory, and — with exactly one exception,
[`CARREL_BIN_<NAME>`](#pinning-a-binary-carrel_bin_name) — no environment
variable the CLI itself reads. Behavior is controlled by flags, and capability
is controlled by what's installed on your `PATH`. This page documents the few
knobs that *do* exist.

Related docs: [Install](INSTALL.md) · [Quickstart](QUICKSTART.md) ·
[Reference](REFERENCE.md) · [Troubleshooting](TROUBLESHOOTING.md) ·
[README](https://github.com/coltonbearden/carrel/blob/main/README.md)

## The desk root: `--root` and `.carrel/`

Db-backed commands (`index`, `search`, `tag`, `note`, `desk`) operate on a
"desk root" — by default the current directory, overridable with the global
flag:

```bash
carrel --root ~/documents index
carrel --root ~/documents search "invoice 2026"
```

The first db-backed command creates `.carrel/carrel.db` (SQLite) directly
under the root:

```text
<root>/
└── .carrel/
    └── carrel.db     # files, FTS5 text index, tags, notes
```

Inside the db: a `files` table (path, size, mtime, hash, type), a contentless
FTS5 `docs` table for full-text search, and `tags`/`notes` tables. One root =
one self-contained index — delete the `.carrel/` directory and you've cleanly
un-indexed that tree (tags and notes go with it). `.carrel` is always skipped
by `index`, `pack`, and `dedupe`, so it never pollutes its own results.

## The `CARREL` environment variable (scripts only)

The CLI itself does not read `CARREL`, but every shell script in `snippets/`
and `examples/cookbook/` resolves the CLI through it:

```bash
CARREL="${CARREL:-carrel}"
```

So to run the recipes against a development checkout instead of an installed
binary:

```bash
CARREL="uv run carrel" ./snippets/pdf-to-searchable.sh ~/scans
```

## External tools: adapter PATH resolution

Every external binary goes through one adapter registry
(`src/carrel/core/adapters.py`), which resolves the first matching name on
your `PATH`. One adapter has multiple candidate names, tried in order:

| Adapter | Tries, in order | Why |
|---|---|---|
| `magick` | `magick`, then `convert` | ImageMagick 6 shipped `convert`; v7 ships `magick` |

Normally there is no need to configure tool paths: install the tool anywhere
on `PATH` and carrel finds it; `carrel doctor` shows the exact resolved path
and version for every adapter. A missing tool produces exit code 3 with the
install hint — see
[Troubleshooting](TROUBLESHOOTING.md#exit-code-3-a-tool-is-missing).

## Pinning a binary: `CARREL_BIN_<NAME>`

This is the single exception to config-free (decision D-008 in
[DECISIONS.md](DECISIONS.md)). When several versions of a tool are installed,
or `PATH` finds the wrong one, set `CARREL_BIN_<NAME>` to the exact binary
the adapter should use. `<NAME>` is the adapter name from `carrel doctor`,
upper-cased with `-` replaced by `_`:

| Adapter | Variable |
|---|---|
| `pandoc` | `CARREL_BIN_PANDOC` |
| `pdftotext` | `CARREL_BIN_PDFTOTEXT` |
| `espeak-ng` | `CARREL_BIN_ESPEAK_NG` |
| `edge-tts` | `CARREL_BIN_EDGE_TTS` |
| `magick` | `CARREL_BIN_MAGICK` (also bypasses the `magick`/`convert` candidate search) |

Rules, so a stale variable can never surprise you:

- When set, `PATH` is **not** searched for that adapter — the value is used
  as-is (`~` is expanded). It must be an existing, executable file.
- A set-but-missing path counts as **missing**: the command exits 3 and the
  message names the override, e.g.
  `'pandoc' is required for this operation but was not found (override CARREL_BIN_PANDOC=/opt/pandoc/bin/pandoc not found).`
  There is no silent fallback to whatever `PATH` would have found.
- An empty value is the same as unset.
- `carrel doctor` shows `found via CARREL_BIN_PANDOC` next to an overridden
  adapter (and `MISSING via CARREL_BIN_PANDOC` with the stale path in the hint
  column); in `--json`, each adapter row carries
  `"override": {"var": "CARREL_BIN_PANDOC", "path": "…"}` (or `null`).

**WSL example.** Windows interop puts every `*.exe` on your Windows `PATH`
onto the Linux `PATH` too, so a Windows `pandoc.exe` can shadow — or be found
instead of — the Linux one. Pin the Linux build:

```bash
export CARREL_BIN_PANDOC=/usr/bin/pandoc     # ~/.bashrc; `command -v pandoc` shows what PATH picks
carrel doctor | grep pandoc                  # → found via CARREL_BIN_PANDOC
```

The variable is read per invocation, so a one-off works too:
`CARREL_BIN_PDFTOTEXT=/opt/poppler-26/bin/pdftotext carrel convert scan.pdf --to txt`.

## TTS engine preference

`carrel audiobook --engine auto` (the default) probes the adapter registry
and picks the best voice available, in this order:

1. `piper` (natural, local — `pipx install piper-tts`)
2. `edge-tts` (natural, cloud — `pipx install edge-tts`)
3. `espeak-ng` (robotic but dependable — the only engine assumed to exist)

Installing a better engine upgrades every future audiobook with no flag
changes; force a specific one with `--engine espeak|piper|edge-tts`.

## ICC profiles (`proof`, `color convert`)

Profiles are discovered from the standard system directories rather than
configured. On this dev box `carrel doctor` reports:

```text
ICC profile dirs: /usr/share/color/icc (91 profiles),
/mnt/c/Windows/System32/spool/drivers/color (138 profiles)
```

(That second entry is a WSL2 nicety — Windows' installed profiles are picked
up automatically.) You can always bypass discovery by passing an explicit
file: `carrel proof photo.jpg --profile ./MyPrinter.icc`.

## Everything else is a flag

Debug tracebacks (`--debug`), machine output (`--json`), OCR language
(`ocr --lang`), watch debounce (`watch --debounce`) — all per-invocation
flags, all documented in [REFERENCE.md](REFERENCE.md).
