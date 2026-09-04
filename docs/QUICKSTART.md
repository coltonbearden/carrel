# Carrel in ten minutes

A guided tour of the desk. Every command and output below was actually run
against copies of this repo's test fixtures (and, for §6–7, a small scratch
docs folder); your hashes, timestamps and absolute paths will differ, the
shapes won't.

Prerequisite: carrel installed and on `PATH` ([INSTALL.md](INSTALL.md)) — the
tour assumes `uv tool install 'carrel[all]'`, so the TUI, xlsx reading and
exact token counts all work. Working from the repo instead? Substitute
`uv run carrel` everywhere.

Related docs: [Reference](REFERENCE.md) · [Configuration](CONFIGURATION.md) ·
[Troubleshooting](TROUBLESHOOTING.md) · [Cookbook](COOKBOOK.md) ·
[README](https://github.com/coltonbearden/carrel/blob/main/README.md)

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
│ git         │ found   │ git version 2.53.0        │
…
                command capabilities
│ catalog     │ ok      │ desk db export/import/status (stdlib sqlite)       │
│ convert     │ ok      │ built-in md→html fallback; pandoc widens formats… │
│ ocr         │ ok      │ tesseract for images, ocrmypdf for PDF text layers │
…
tesseract languages: eng, osd
```

Every `MISSING` row shows the exact install command. Missing tools never
crash carrel — a command that needs one exits with code 3 and that same hint.
The same goes for the optional Python extras: on a plain install `carrel desk`
exits 3 with `uv tool install 'carrel[tui]'`.

## 1. Set up a playground

From a clone of this repo, copy the committed test fixtures somewhere
disposable (the glob picks up `sample.docx`, `sample.xlsx`, `sample.epub`…
alongside the older ones):

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

Detail is per-type — a CSV reports its dialect and columns, a spreadsheet its
sheets:

```bash
carrel inspect sample.xlsx
```

```text
name       sample.xlsx
type       xlsx
mime       application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
size       5587
sha256     57a325efe344106367fb03df213a021e73e6a6543074b34a98b95d1e478f9d82
detail:
  sheets         [{"name": "Books", "rows": 4, "cols": 3}, {"name": "Loans", "rows": 4, "cols": 3}]
```

Add the global `--json` flag and you get one clean JSON object, ready for
`jq`:

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
carrel convert sample.docx --to md --force      # office/ebook formats read through pandoc
carrel convert sample.xlsx --to csv --sheet 2   # xlsx → csv/json (needs the office extra)
```

```text
sample.md -> sample.pdf  [pandoc+weasyprint]
sample.csv -> catalog.md  [builtin]
sample.docx -> sample.md  [pandoc]
sample.xlsx -> sample.csv  [openpyxl]
```

The bracket names the tool chain that did the work. Outputs are never
overwritten silently — repeat a conversion and you get
`error: refusing to overwrite sample.pdf (use --force)` (which is why the docx
line above, landing on an existing `sample.md`, passes `--force`). docx, odt,
epub and rtf read via pandoc; md/html/txt write to docx and odt; docx and epub
round-trip. Run `carrel convert --help` to see the full SRC → target matrix.

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
file — paste-ready context. It honors `.gitignore` (including `!` negation),
budgets with `--max-bytes`/`--chunk`, and emits `--format xml`
(Claude-friendly) or `json`. `tokens_est` is a chars/3.6 estimate;
`--tokenizer exact` counts with tiktoken and relabels the column `tokens`
(needs the `tokens` extra). `--outline` shows structure instead of contents
(`.py` defs/classes with line numbers, `.md` headings); `--dedupe-content`
inlines identical files once.

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
`carrel index --status` reports what has changed on disk since the last run
(see §7).

## 6. Pack what matters — `pack --query`

The index is also how `pack` decides what is *relevant*. Take a small docs
folder — two guides, two reference pages, a meeting note, a CSV, and a stray
`scratch.py`:

```bash
carrel --root docs index
carrel --root docs pack docs --query release --stats
```

```text
indexing guides/onboarding.md
indexing guides/release-checklist.md
indexing notes/meeting-2026-09-01.txt
indexing notes/topics.csv
indexing reference/exit-codes.md
indexing reference/glossary.md
│ indexed 6 │ skipped 0 │ pruned 0 │ errors 0 │

                                     pack stats
┃ path                         ┃ type          ┃ size  ┃ tokens_est ┃ score  ┃ note ┃
│ guides/release-checklist.md  │ md            │ 202 B │ 56         │ -0.000 │      │
│ notes/topics.csv             │ csv           │ 48 B  │ 15         │ -0.000 │      │
│ reference/glossary.md        │ md            │ 105 B │ 29         │ -0.000 │      │
│ notes/meeting-2026-09-01.txt │ txt           │ 154 B │ 43         │ -0.000 │      │
│ guides/onboarding.md         │ md            │ 152 B │ 43         │ -0.000 │      │
│ TOTAL                        │ 5 in / 0 skip │ 661 B │ 186        │        │      │
```

Five of six indexed files mention "release"; `exit-codes.md` does not and is
left out. Rows are in relevance order, not tree order, and the pack header
records the query:

```bash
carrel --root docs pack docs --query release --top 5 -o ctx.md
```

```text
wrote ctx.md (5 files, ~186 tokens_est)
```

```text
# carrel pack

- generated-by: carrel 0.1.2
- root: …/docs
- files: 5 included, 0 skipped
- tokens_est: 186
- query: 'release' (top 5, 5 hit(s))
```

Two honest notes. First, bm25 scores from FTS5 are tiny on small documents,
so the human table prints `-0.000`; `--json` carries the real value
(`-1.5e-06` here) along with `meta.query`, `meta.hits` and `meta.top`.
Second, `--query` only ranks files the index knows about, and `carrel index`
skips unsupported types such as `.py` and `.toml` — `scratch.py` contains
"release" too, yet it can never be a hit. Query-driven packing fits document
trees today; for source trees use `--include`/`--exclude`, `--since REF`, or
`--outline`.

In scripts, a query with no hits is exit 5 with `--fail-empty`:

```console
$ carrel --root docs pack docs --query xyzzyplugh --fail-empty --tree-only
error: no files matched --query 'xyzzyplugh'
$ echo $?
5
```

Inside a repository, `--since REF` and `--changed` pack what changed
instead (via the `git` adapter):

```bash
carrel pack . --since HEAD~1 --tree-only
```

```text
- files: 2 included, 0 skipped
- since: HEAD~1 (2 changed, 0 removed)
```

The whole §6 flow is [cookbook recipe 10](COOKBOOK.md); run
`bash examples/cookbook/10-pack-what-matters.sh` from a checkout.

## 7. Carry your tags and notes — `catalog`

Tags and notes are the one thing the desk cannot rebuild from your files, so
they export as a small JSON document. Working in the `docs` folder from §6:

```bash
carrel tag add guides/release-checklist.md release process
carrel tag add reference/glossary.md reference
carrel note add guides/release-checklist.md "Step 4 needs the PyPI trusted publisher set up first."
carrel catalog status
```

```text
guides/release-checklist.md: process, release
reference/glossary.md: reference
note 1 on guides/release-checklist.md @ 2026-09-04T07:51:19
…/docs/.carrel/carrel.db  (schema 1)
                         desk catalog
┃ files ┃ docs ┃ tags ┃ notes ┃ changed ┃ missing ┃ unindexed ┃
│     6 │    6 │    3 │     1 │       0 │       0 │         0 │
```

(Relative paths for `tag`/`note` resolve against your current directory, not
`--root`, so run them from inside the desk root or pass absolute paths.)

```bash
carrel catalog export -o desk.json
```

```text
wrote desk.json: 2 file(s), 3 tag(s), 1 note(s)
```

`desk.json` is deterministic (sorted by path; only `exported` changes between
runs), so it diffs cleanly and can live next to the files in version control:

```json
{
  "schema": 1,
  "product": "carrel",
  "version": "0.1.2",
  "exported": "2026-09-04T11:51:19+00:00",
  "root": "/home/you/docs",
  "files": [
    {
      "path": "guides/release-checklist.md",
      "tags": ["process", "release"],
      "notes": [{"created": 1788522679.0094275, "body": "Step 4 needs the PyPI trusted publisher set up first."}]
    },
    {"path": "reference/glossary.md", "tags": ["reference"], "notes": []}
  ]
}
```

Move the folder, rebuild the index, merge the catalog back in — importing the
same document twice adds nothing:

```console
$ rm -rf .carrel && carrel index --json
{"indexed": 6, "skipped": 0, "pruned": 0, "errors": []}
$ carrel catalog import desk.json
imported 3 tag(s), 1 note(s) across 2 file(s)
$ carrel --json catalog import desk.json
{"tags_added": 0, "notes_added": 0, "files_touched": 0, "skipped_missing": 0, "tags_removed": 0, "notes_removed": 0}
```

`catalog status` (or `index --status`) is also how you learn the index is
stale — edit one file, delete another, and:

```text
│     6 │    6 │    3 │     1 │       1 │       1 │         0 │
  changed   reference/exit-codes.md
  missing   notes/topics.csv
hint: `carrel index` refreshes changed/unindexed files; `carrel index --prune` drops missing ones
```

## 8. Make thumbnails — `thumb`

```bash
carrel thumb text+image.pdf sample.jpg --size 200
```

```text
text+image.pdf -> thumbs/text+image.png  (155x200)
sample.jpg -> thumbs/sample.png  (200x150)
```

PDFs are rasterized at page one; aspect ratio is always preserved.

## 9. Automate a folder — `watch`

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

## 10. Sit down at the desk — `desk`

Everything above, interactively:

```bash
carrel desk
```

A three-pane TUI: directory tree · inspector (metadata, text preview,
tags/notes) · actions (convert / OCR / thumbnail / pack / index / tag / note).
Action outputs land in `./carrel-out/`. Keys: `q` quit, `/` search, `t` tag,
`n` note. It needs the `tui` extra; without it:

```console
$ carrel desk
error: textual is not installed (optional extra 'tui') — run: uv tool install 'carrel[tui]'  (from a checkout: uv sync --extra tui)
```

## 11. Stop typing flags — `completion`

```bash
carrel completion bash --install-hint | tail -4
```

The script itself is generated in-process from the real command tree, so it
always matches the installed version. Enable it once per shell:

```bash
eval "$(carrel completion bash)"                                   # ~/.bashrc
eval "$(carrel completion zsh)"                                    # ~/.zshrc, after compinit
carrel completion fish > ~/.config/fish/completions/carrel.fish   # fish autoloads it
```

Any other shell name exits 2; `--json` gives `{"shell": …, "script": …}`.
Details per shell in [INSTALL.md](INSTALL.md#shell-completions).

## Where to next

- Full flag-by-flag docs for all 26 commands: [REFERENCE.md](REFERENCE.md) —
  including OCR, dedupe, organize, redact, sign, audiobook, and the MCP server
  (ten tools, two resource templates — see [AGENTS.md](AGENTS.md)).
- Runnable recipes: [COOKBOOK.md](COOKBOOK.md) (`examples/cookbook/` and
  `snippets/` in the repo).
- Claude Code integration: the repo doubles as a plugin marketplace
  (`/inspect`, `/pack`, `/watch-folder`, …) — see [MARKETPLACE.md](MARKETPLACE.md).
