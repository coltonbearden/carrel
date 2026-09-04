# Troubleshooting & FAQ

First move for almost anything: `carrel doctor`. It lists every external tool
carrel can use, whether it was found, and the exact install command when it
wasn't. Add the global `--debug` flag to any failing command to see a full
traceback instead of the one-line error.

Related docs: [Install](INSTALL.md) · [Quickstart](QUICKSTART.md) ·
[Reference](REFERENCE.md) · [Configuration](CONFIGURATION.md) ·
[README](https://github.com/coltonbearden/carrel/blob/main/README.md)

## Exit code 3: a tool is missing

Commands that need an external binary degrade gracefully — no traceback, no
silent no-op. Real example:

```console
$ carrel audiobook notes.txt --engine piper
error: 'piper' is required for this operation but was not found.
  purpose: text-to-speech (natural voice, preferred if present)
  install: pipx install piper-tts
$ echo $?
3
```

Fix: run the printed install line (they're all collected in
[INSTALL.md](INSTALL.md#optional-binaries-by-capability)), then re-run.
Exit code 3 always means exactly this — scripts can branch on it safely. The
same code and shape cover a missing optional *Python extra* (next three
entries). The full exit-code table is in [REFERENCE.md](REFERENCE.md#exit-codes).

## `carrel desk` says textual is not installed

Since v0.2.0 the TUI framework is an optional extra, so a plain install has
every command except `desk`:

```console
$ carrel desk
error: textual is not installed (optional extra 'tui') — run: uv tool install 'carrel[tui]'  (from a checkout: uv sync --extra tui)
$ echo $?
3
```

Fix: add the extra to your existing install — `uv tool install --force
'carrel[tui]'` (or `pipx install --force 'carrel[tui]'`), or take everything
with `'carrel[all]'`. The quotes matter: most shells treat `[` specially.
Rationale is decision D-007 in [DECISIONS.md](DECISIONS.md); the extras table
is in [INSTALL.md](INSTALL.md#optional-extras).

## xlsx exits 3 (`openpyxl` is required)

Word-processor and ebook formats (docx, odt, epub, rtf) go through the
`pandoc` binary, but spreadsheets are read by a Python package that lives in
the `office` extra:

```console
$ carrel convert sample.xlsx --to csv
error: 'openpyxl' is required for this operation but was not found.
  purpose: read .xlsx workbooks (xlsx → text/csv/json, inspect)
  install: uv tool install 'carrel[office]'  (from a checkout: uv sync --extra office)
$ echo $?
3
```

The same message appears from `inspect`, `index`, `pack` and `diff` when they
meet an `.xlsx`. Fix: `uv tool install --force 'carrel[office]'`. If instead
you see `'pandoc' is required …` for a `.docx`, that is the binary:
`sudo apt install pandoc`. `pack --tokenizer exact` behaves the same way for
`tiktoken` and the `tokens` extra.

## `pack --query` finds nothing (or misses a file you know matches)

`--query` does not grep your files — it asks the desk index under `--root`,
so three things have to line up:

1. **There is an index.** Without one the command exits 4 and tells you what
   to run:

   ```console
   $ carrel --root docs pack docs --query release --tree-only
   error: --query needs a desk index but none exists under /home/you/docs — run `carrel index --root /home/you/docs` first
   ```

   Pass the *same* `--root` to `index` and to `pack`.
2. **The index is fresh.** `carrel index --status` (alias of
   `carrel catalog status`) lists `changed`, `missing` and `unindexed` files;
   `carrel index` refreshes them, `--prune` drops the missing ones.
3. **The file is an indexed type.** `carrel index` walks the supported types —
   pdf, md, txt, html, json, xml, csv, docx, odt, epub, rtf, xlsx, and images —
   and silently skips everything else (`.py`, `.toml`, `.yaml`, `.rs`, …).
   A source file that contains your term can therefore never be a hit. This
   is a known limitation of v0.2.0, not a bug in your setup: query-driven
   packing fits document trees; for source trees use `--include`/`--exclude`,
   `--since REF`/`--changed`, or `--outline` (see the scope note in
   [FEATURES.md](FEATURES.md#explicit-scope-notes)).

With an index and no hits, the header says so and the pack is empty; add
`--fail-empty` to turn that into exit 5 for scripts:

```console
$ carrel --root docs pack docs --query xyzzyplugh --fail-empty --tree-only
error: no files matched --query 'xyzzyplugh'
$ echo $?
5
```

Also note the `score` column: FTS5 bm25 scores are tiny for small documents,
so `-0.000` in the human table is normal — `--json` carries the real value.

## Which pandoc (or any tool) is carrel using?

`carrel doctor` prints the version of each tool it resolved; `carrel doctor
--json` adds the exact `path`. Normally that is the first match on `PATH`
(`command -v pandoc`). If several copies are installed — on WSL2 a Windows
`pandoc.exe` can be reached through interop — pin the one you want with the
`CARREL_BIN_<NAME>` environment variable (adapter name upper-cased, `-` → `_`).
`doctor` then labels the row:

```console
$ CARREL_BIN_PANDOC=/usr/bin/pandoc carrel doctor | grep pandoc
│ pandoc     │ found via CARREL_BIN_PANDOC │ pandoc 3.7.0.2                                        │
```

A stale override never falls back silently — the tool counts as missing and
the message names the variable:

```console
$ CARREL_BIN_PANDOC=/opt/nowhere/pandoc carrel convert sample.docx --to md
error: 'pandoc' is required for this operation but was not found (override CARREL_BIN_PANDOC=/opt/nowhere/pandoc not found).
  purpose: document conversion hub (md/html/txt…)
  install: sudo apt install pandoc
$ echo $?
3
```

So if a tool you *know* is installed shows as `MISSING via CARREL_BIN_…`,
check your shell profile for a leftover export. Details and the full variable
list: [CONFIGURATION.md](CONFIGURATION.md#pinning-a-binary-carrel_bin_name).

## OCR says nothing changed / "page already has text"

`carrel ocr file.pdf --to pdf` runs ocrmypdf with `--skip-text`: born-digital
pages pass through untouched, and only image-only pages get a text layer. If
you want to re-OCR pages that already have (perhaps garbage) text — common
with PDFs that carry a broken text layer from a previous bad OCR pass:

```bash
carrel ocr file.pdf --to pdf --redo     # maps to ocrmypdf --force-ocr
```

## OCR in languages other than English

Only `eng` ships with tesseract by default. `carrel doctor` shows what you
have (`tesseract languages: eng, osd`). Install more, one apt package per
language, then pass tesseract codes to `--lang`:

```bash
sudo apt install tesseract-ocr-deu tesseract-ocr-fra
carrel ocr brief.pdf --to pdf --lang eng+deu
```

## html → pdf output has wrong or missing glyphs (weasyprint)

`convert --to pdf` from html/md renders through weasyprint, which uses the
fonts installed on *this* machine via fontconfig — a font named in your CSS
but not installed gets silently substituted, and characters outside the
substitute's coverage render as boxes. Fresh WSL images are minimal, so:

```bash
sudo apt install fonts-dejavu fonts-liberation fonts-noto-core
fc-cache -f                    # refresh the font cache
fc-list | grep -i "dejavu"     # confirm the font is visible to fontconfig
```

For CJK or emoji coverage add `fonts-noto-cjk` / `fonts-noto-color-emoji`.

## Watch doesn't fire on /mnt/c

`carrel watch` uses native inotify events (via the watchdog library). On the
WSL2 Linux filesystem (`~/…`, ext4) these are reliable. On `/mnt/c/…` the
Windows drive is mounted through a network-style filesystem, and **changes
made by Windows applications do not generate inotify events** — the watch
just sits there. There is no polling mode.

Do this instead:

- Watch a directory on the Linux side (`~/inbox`), and copy/save files into
  it — the project convention of working under `~/projects` exists for
  exactly this reason (plus 10–50× faster I/O).
- If files *must* arrive on the Windows side, sweep them across on a schedule
  rather than watching: `cp /mnt/c/Users/you/Downloads/*.pdf ~/inbox/` in a
  cron job, and watch `~/inbox`.

## search returns nothing

- No index yet? `search` reads `.carrel/carrel.db` under `--root` (default:
  current directory) — run `carrel index` there first, and make sure you pass
  the *same* `--root` to both commands. `carrel index --status` shows whether
  the index exists and what is stale.
- Scanned PDFs and images have no text until you index with `--ocr`.
- Source files (`.py`, `.toml`, …) are not indexed types — see
  [`pack --query` finds nothing](#pack-query-finds-nothing-or-misses-a-file-you-know-matches).
- In scripts, `--fail-empty` makes an empty result exit 5 instead of 0, so
  pipelines can distinguish "no hits" from success.

## Tags or notes vanished after I deleted `.carrel/`

They lived in that database. Since v0.2.0 you can keep them portable:
`carrel catalog export -o desk.json` before you delete or move a desk, and
`carrel catalog import desk.json` after re-indexing (merge by default,
`--replace` to reset). Importing the same document twice adds nothing. See
[Quickstart §7](QUICKSTART.md#7-carry-your-tags-and-notes-catalog).

## gpg signing fails or hangs (WSL / scripts)

`carrel sign manifest --gpg` invokes gpg with `--batch`, so gpg cannot pop up
an interactive passphrase prompt. On a desktop Linux box a pinentry dialog
covers this; in WSL or headless shells there's often nowhere to prompt, and
signing fails with a "No pinentry"/"Inappropriate ioctl" style error from gpg
(carrel surfaces it as `gpg signing failed (rc=2): …`).

Options, best first:

1. **Cache the passphrase in gpg-agent first** — sign anything interactively
   once (`echo test | gpg --clearsign > /dev/null`), then run carrel within
   the agent's cache window.
2. **Enable loopback pinentry** so the passphrase can be supplied without a
   GUI (this is the `--pinentry-mode loopback` approach from the cookbook
   work):

   ```bash
   echo "pinentry-mode loopback" >> ~/.gnupg/gpg.conf
   echo "allow-loopback-pinentry" >> ~/.gnupg/gpg-agent.conf
   gpgconf --kill gpg-agent
   ```

3. **Use a signing subkey without a passphrase** for automation.

Note `sign manifest` without `--gpg` needs no gpg at all — sha256 manifests
and `sign verify` always work.

## Claude Code marketplace: slash command not found

The repo doubles as a plugin marketplace ([MARKETPLACE.md](MARKETPLACE.md)
lists the current plugins). Two gotchas:

- **Namespacing in headless mode.** When two plugins could claim a name — or
  always, in headless/`-p` runs — address commands by plugin:
  `/carrel-inspect:inspect`, `/carrel-inspect:pack`,
  `/carrel-convert:ocr`, `/carrel-watch:watch-folder`. Interactively, plain
  `/inspect` works when unambiguous.
- <a id="plugins-cant-find-carrel"></a>**Plugins can't find carrel.** Slash
  commands are thin wrappers that run `carrel …` via Bash, and the
  carrel-agent plugin's PostToolUse hook runs
  `carrel index --update --if-indexed` on files Claude writes. All of it
  requires `carrel` on `PATH`: install with `uv tool install 'carrel[all]'`
  ([INSTALL.md](INSTALL.md#install-the-cli-recommended)) and check with
  `command -v carrel`. (The hook is deliberately quiet: `--if-indexed` exits
  0 silently unless you've already created a desk index in that root.)

## FAQ

**Exit code 4?** Input problem — missing file, unreadable, or unsupported
type: `error: no such file: missing.pdf`. Carrel handles pdf, md, txt, html,
json, xml, csv, docx, odt, epub, rtf, xlsx (xlsm), png, jpg, ico. Detection is
by bytes, so a docx renamed to `.bin` still inspects as `docx`.

**Why won't convert overwrite my file?** By design — every output-producing
command refuses to clobber existing files without `--force`.

**Where did my index/tags/notes go?** They live in `.carrel/carrel.db` under
whatever `--root` you used (default: the directory you ran `index` in). See
[CONFIGURATION.md](CONFIGURATION.md#the-desk-root-root-and-carrel). Export
them with `carrel catalog export` before moving a desk.

**`tag add` says "no such file" although the file exists under `--root`.**
`tag` and `note` resolve relative paths against your current directory, not
against `--root`. Run them from inside the desk root or pass absolute paths.

**`magick` vs `convert`?** Carrel tries both names automatically — see
[CONFIGURATION.md](CONFIGURATION.md#external-tools-adapter-path-resolution).
To force one binary, use `CARREL_BIN_MAGICK`.

**Old desk database after upgrading?** `.carrel/carrel.db` is versioned
(`PRAGMA user_version`); a pre-v0.2.0 database is recognised and stamped
version 1 on first open, data intact. `carrel catalog status` shows
`(schema 1)`.

**Audiobook voice sounds robotic.** That's espeak-ng, the baseline. Install
piper (`pipx install piper-tts`) and `--engine auto` picks it up next run.
