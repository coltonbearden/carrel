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

## My pack is empty, or exits non-zero under `--json`

A pack that included **no files** always prints one line on stderr naming the
reason, and under `--json` it exits **5** (`ExitCode.EMPTY` — see the exit-code
table above) instead of writing a valid, empty document:

```console
$ carrel --json --root docs pack docs --query "how do I cut a release"
warning: packed no files: no document contains every term of --query 'how do I
cut a release' (FTS5 requires all of them; try fewer terms, or OR between them)
$ echo $?
5
```

That default exists because an agent reading an empty pack cannot tell it from
a successful one. Two ways out:

- **Fix the query.** FTS5 requires *every* term, so a natural-language question
  almost never matches. Use the two or three words that actually appear, or
  `OR` between them: `--query 'release OR changelog'`.
- **Keep exit 0.** `--no-fail-empty` restores the old behaviour; the stderr line
  stays either way. In human mode exit 0 is already the default, and
  `--fail-empty` opts in.

If the query looks right and still matches nothing, read on.

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
3. **The file is an indexed type.** `carrel index` walks the document types —
   pdf, md, txt, html, json, xml, csv, docx, odt, epub, rtf, xlsx, and images —
   plus plain-text source and config files (`.py`, `.toml`, `.yaml`, `.rs`, …,
   indexed as type `code`). It silently skips anything else, so a binary with
   no extractable text is never a hit. Two things also keep a file out:
   `--no-source` (documents only) and `.gitignore` — the walk honors it, so
   anything under an ignored `build/` or `node_modules/` is not indexed
   (`--no-gitignore` opts out). Hidden entries (`.git`, dotfiles) are never
   walked.

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

## `--apply` exits 2: "would move files that git is tracking"

`carrel rename --apply`, `organize --apply`, `intake --apply` and
`watch --done-dir/--error-dir` refuse to start when the move would touch a file
git is tracking. The message names the repository and what it found:

```console
$ carrel organize ~/projects/myapp/src --apply
error: organize --apply would move files that git is tracking:
  /home/you/projects/myapp
    tracked: src/a.py, src/b.py, src/c.py, … (21 total)
Renaming tracked files breaks imports, tests and history. Point this
somewhere else, or pass --force if it is what you meant.
```

This is a guard, not a bug. A tracked file's *name is content*: imports, test
collection, CI configuration and the history all address it by path, so a bulk
rename leaves a repository that no longer builds. carrel learned this the hard
way — a `rename --apply` aimed at its own checkout renamed 21 tracked files
after the "fields" it read out of their source.

Your options, best first:

1. **Point the command somewhere else.** Bulk renaming and filing are for
   document directories, not source trees.
2. **Preview first.** Drop `--apply`; the dry-run default prints the whole plan
   and is never guarded.
3. **`--force`**, when rewriting those files is genuinely what you want. Commit
   first, so `git status` can show you what happened.

**Untracked files inside a repository are fine.** If `~` is a dotfiles
repository, `carrel intake ~/Downloads --to ~/Documents/filed --apply` still
works, because nothing in `~/Downloads` is tracked. Only tracked paths refuse.
A shell glob is guarded like a directory: `carrel rename src/*.py --apply`
expands to a list of files that git tracks, which is the incident above.

`intake` refuses *before* creating `--to`, so a refused run leaves the disk
untouched, and `watch --print-service` refuses before printing a unit whose
command would fail at every start. A destination that does not exist yet is
never guarded — creating a directory tracks nothing — so the first
`intake ~/Downloads --to ~/filed --apply` works even when `~` is a repository.

**Without the git binary** carrel cannot tell what is tracked, so it exits 3
with git's install hint rather than guessing:

```console
$ carrel organize ~/projects/myapp/src --apply
error: 'git' is required for this operation but was not found.
  purpose: changed-file lists for pack --since/--changed
  install: sudo apt install git
```

Install git, or pass `--force` to skip the question. carrel never treats "could
not ask" as "nothing is tracked" — that would fail open on exactly the case the
guard exists for.

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
- `.gitignore`d paths and hidden entries are never indexed — see
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
(`PRAGMA user_version`) and migrated on open, data intact: a pre-v0.2.0 file
is stamped 1 and then carried to the current schema in the same open, so
`carrel catalog status` reports the current version (`(schema 2)` since
v0.4.0) — never an older one. If it does not, the file was not opened by this
carrel: check `--root` points at the desk you think it does.

**Audiobook voice sounds robotic.** That's espeak-ng, the baseline. Install
piper (`pipx install piper-tts`) and `--engine auto` picks it up next run.
