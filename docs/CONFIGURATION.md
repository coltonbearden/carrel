# Configuring Carrel

Honest answer first: **carrel is config-free by design.** There is no config
file, no dotfile in your home directory, no environment variable the CLI
itself reads. Behavior is controlled by flags, and capability is controlled
by what's installed on your `PATH`. This page documents the few knobs that
*do* exist.

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

The CLI ignores environment variables, but every shell script in `snippets/`
and `examples/cookbook/` resolves the CLI through `CARREL`:

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
your `PATH`. Two adapters have multiple candidate names, tried in order:

| Adapter | Tries, in order | Why |
|---|---|---|
| `fd` | `fd`, then `fdfind` | Debian/Ubuntu package `fd-find` installs the binary as `fdfind` |
| `magick` | `magick`, then `convert` | ImageMagick 6 shipped `convert`; v7 ships `magick` |

There is no way (and no need) to configure tool paths: install the tool
anywhere on `PATH` and carrel finds it; `carrel doctor` shows the exact
resolved path and version for every adapter. A missing tool produces exit
code 3 with the install hint — see
[Troubleshooting](TROUBLESHOOTING.md#exit-code-3-a-tool-is-missing).

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
