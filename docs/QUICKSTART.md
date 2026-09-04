# Carrel in ten minutes

A guided tour of the desk. Every command and output below was actually run
against copies of this repo's test fixtures; your hashes and timestamps will
differ, the shapes won't.

Prerequisite: carrel installed and on `PATH` ([INSTALL.md](INSTALL.md)).
Working from the repo instead? Substitute `uv run carrel` everywhere.

Related docs: [Reference](REFERENCE.md) · [Configuration](CONFIGURATION.md) ·
[Troubleshooting](TROUBLESHOOTING.md) · [README](https://github.com/coltonbearden/carrel/blob/main/README.md)

## 0. Check the room — `doctor`

```bash
carrel doctor
```

```text
carrel 0.1.2 · python 3.12.13
                external tools
│ pandoc      │ found   │ pandoc 3.7.0.2            │
│ tesseract   │ found   │ tesseract 5.5.0           │
│ piper       │ MISSING │ pipx install piper-tts    │
…
                command capabilities
│ convert     │ ok      │ built-in md→html fallback; pandoc widens formats… │
│ ocr         │ ok      │ tesseract for images, ocrmypdf for PDF text layers │
…
tesseract languages: eng, osd
```

Every `MISSING` row shows the exact install command. Missing tools never
crash carrel — a command that needs one exits with code 3 and that same hint.

## 1. Set up a playground

From a clone of this repo, copy the committed test fixtures somewhere
disposable:

```bash
mkdir ~/carrel-tour && cp tests/fixtures/sample.* tests/fixtures/*.pdf ~/carrel-tour/
cd ~/carrel-tour
```

## 2. Look at a file — `inspect`

```bash
carrel inspect text+image.pdf
```

```text
name       text+image.pdf
path       text+image.pdf
type       pdf
mime       application/pdf
size       51379
sha256     cc62bbfc72b96e74c5434f42871ce226759fc5da321029720240c3fa2477f4fb
detail:
  encrypted      False
  pages          2
  producer       ReportLab PDF Library - (opensource)
  form_fields    0
  annotations    0
```

Detail is per-type — a CSV reports its dialect and columns instead. Add the
global `--json` flag and you get one clean JSON object, ready for `jq`:

```bash
carrel --json inspect sample.csv
```

```json
{
  "path": "sample.csv",
  "type": "csv",
  "sha256": "233467d1df2da52c66a8fc826ca26d65d03cc6b3ba654d9d49a8bfceb32294f8",
  "detail": {
    "delimiter": ",",
    "columns": ["id", "title", "shelf", "year", "checked_out"],
    "column_count": 5,
    "rows": 20
  }
}
```

(Trimmed — the real object also carries name, size, mtime, mime.)

## 3. Change a file's shape — `convert`

```bash
carrel convert sample.md --to pdf
carrel convert sample.csv --to md -o catalog.md
```

```text
sample.md -> sample.pdf  [pandoc+weasyprint]
sample.csv -> catalog.md  [builtin]
```

The bracket names the tool chain that did the work. Outputs are never
overwritten silently — repeat a conversion and you get
`error: refusing to overwrite sample.pdf (use --force)`. Run
`carrel convert --help` to see the full SRC → target matrix.

## 4. Bundle files for an LLM — `pack`

```bash
carrel pack . --include '*.md' --include '*.csv' -o context.md --stats
```

```text
                        pack stats
┃ path       ┃ type          ┃ size   ┃ tokens_est ┃
│ catalog.md │ md            │ 873 B  │ 243        │
│ sample.csv │ csv           │ 589 B  │ 187        │
│ sample.md  │ md            │ 656 B  │ 183        │
│ TOTAL      │ 3 in / 0 skip │ 2.1 KB │ 613        │
wrote context.md
```

`context.md` opens with a header and file tree, then one fenced section per
file — paste-ready context. It honors `.gitignore`, budgets with
`--max-bytes`/`--chunk`, and emits `--format xml` (Claude-friendly) or `json`.

## 5. Build a search index — `index` + `search`

```bash
carrel index
```

```text
indexing catalog.md
indexing sample.csv
…
│ indexed 15 │ skipped 0 │ pruned 0 │ errors 0 │
```

That creates `.carrel/carrel.db` in the current directory (the "desk root" —
control it with the global `--root`, see [CONFIGURATION.md](CONFIGURATION.md)).
Now full-text search it:

```bash
carrel search "shelf" --limit 3
```

```text
 1. catalog.md  (score -0.98)
    | id | title | [shelf] | year | checked_out | | 1 | Palimpsest Vol 1 | B2 …
 2. sample.csv  (score -0.98)
    id, title, [shelf], year, checked_out …
```

FTS5 syntax works (`"exact phrase"`, `term1 AND term2`), matches are
bracketed in the snippet, and `--json` gives `[{path, score, snippet}]`.
Images and scanned PDFs get searchable text too if you index with `--ocr`.

## 6. Make thumbnails — `thumb`

```bash
carrel thumb text+image.pdf sample.jpg --size 200
```

```text
text+image.pdf -> thumbs/text+image.png  (155x200)
sample.jpg -> thumbs/sample.png  (200x150)
```

PDFs are rasterized at page one; aspect ratio is always preserved.

## 7. Automate a folder — `watch`

`watch` runs shell actions on file events, with `{path}`, `{name}`, `{dir}`
substituted. Try a self-terminating example (`--once` exits after the first
action, `--timeout` is a safety net):

```bash
mkdir -p inbox
carrel watch inbox --glob '*.jpg' --run 'echo saw {name}' --once --timeout 60 &
cp sample.jpg inbox/drop.jpg
```

```text
watching /home/you/carrel-tour/inbox (on: created, modified, glob: *.jpg) — Ctrl-C to stop
[modified] …/inbox/drop.jpg :: echo saw drop.jpg -> rc=0
saw drop.jpg
```

Real-world version (thumbnail every PDF that lands in an inbox — note the
output goes *outside* the watched directory so it can't re-trigger):

```bash
carrel watch inbox --glob '*.pdf' --run 'carrel thumb {path} --out-dir thumbs'
```

WSL2 note: watch a directory under `~/…` (ext4), not `/mnt/c/…` — see
[Troubleshooting](TROUBLESHOOTING.md#watch-doesnt-fire-on-mntc).

## 8. Sit down at the desk — `desk`

Everything above, interactively:

```bash
carrel desk
```

A three-pane TUI: directory tree · inspector (metadata, text preview,
tags/notes) · actions (convert / OCR / thumbnail / pack / index / tag / note).
Action outputs land in `./carrel-out/`. Keys: `q` quit, `/` search, `t` tag,
`n` note.

## Where to next

- Full flag-by-flag docs for all 24 commands: [REFERENCE.md](REFERENCE.md) —
  including OCR, dedupe, organize, redact, sign, audiobook, and the MCP server.
- Runnable recipes: `examples/cookbook/` and `snippets/` in the repo.
- Claude Code integration: the repo doubles as a plugin marketplace
  (`/inspect`, `/pack`, `/watch-folder`, …) — see the repo
  [README](https://github.com/coltonbearden/carrel/blob/main/README.md).
