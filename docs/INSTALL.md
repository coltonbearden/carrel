# Installing Carrel

Carrel is a Python CLI managed with [uv](https://docs.astral.sh/uv/). The core
always works with nothing but Python; external binaries unlock extra
capability and are detected at runtime — nothing breaks when one is missing
(you get a one-line message with the install hint and exit code 3).

Related docs: [Quickstart](QUICKSTART.md) · [Reference](REFERENCE.md) ·
[Configuration](CONFIGURATION.md) · [Troubleshooting](TROUBLESHOOTING.md) ·
[README](https://github.com/coltonbearden/carrel/blob/main/README.md)

## Prerequisites

- **Python ≥ 3.12** (`requires-python = ">=3.12"`; developed on 3.12–3.14)
- **uv** — install per <https://docs.astral.sh/uv/getting-started/installation/>
  if `uv --version` says nothing

## Install the CLI (recommended)

From PyPI (recommended):

```bash
uv tool install carrel      # or: pipx install carrel
```

Or from a clone of this repository (to hack on it):

```bash
git clone https://github.com/coltonbearden/carrel.git ~/projects/carrel
cd ~/projects/carrel
uv tool install .
```

`uv tool install` builds the package into an isolated environment and drops a
`carrel` launcher into `~/.local/bin` (make sure that's on your `PATH`; `uv
tool update-shell` fixes it if not). Verify:

```console
$ carrel --version
carrel 0.1.2 — A library desk for your files — and your agents.
```

Having `carrel` on `PATH` matters beyond convenience: the Claude Code plugins
in this repo's marketplace and the `carrel-agent` re-index hook all invoke
`carrel` directly (see [Troubleshooting](TROUBLESHOOTING.md#plugins-cant-find-carrel)).

Upgrade after pulling changes with `uv tool install . --force` (or
`uv tool upgrade carrel` when installed from an index); remove with
`uv tool uninstall carrel`.

## Development mode

To hack on carrel itself, skip the install and run from the repo:

```bash
cd ~/projects/carrel
uv sync            # create .venv and install dependencies from uv.lock
uv run carrel doctor
uv run pytest      # the test suite; binary-dependent tests skip when a tool is absent
```

`uv run carrel …` behaves identically to the installed CLI. Shell snippets in
`snippets/` and `examples/cookbook/` honor a `CARREL` environment variable so
you can point them at dev mode: `CARREL="uv run carrel" ./snippets/inbox-triage.sh`
(see [Configuration](CONFIGURATION.md#the-carrel-environment-variable-scripts-only)).

## Optional binaries, by capability

Carrel calls every external tool through one adapter registry, and
`carrel doctor` renders that registry as a live report — which tools it found,
their versions, and the exact install hint for each missing one. Run it first:

```console
$ carrel doctor
carrel 0.1.2 · python 3.12.13
                external tools
┃ adapter     ┃ status  ┃ version / install hint ┃
│ pandoc      │ found   │ pandoc 3.7.0.2         │
│ pdftotext   │ found   │ pdftotext version 26.01.0 │
│ …           │         │                        │
│ piper       │ MISSING │ pipx install piper-tts │
│ edge-tts    │ MISSING │ pipx install edge-tts  │
                command capabilities
│ audiobook   │ ok      │ piper/edge-tts upgrade the voice when present │
│ convert     │ ok      │ built-in md→html fallback; pandoc widens formats… │
│ …           │         │                        │
ICC profile dirs: /usr/share/color/icc (91 profiles), …
tesseract languages: eng, osd
```

(Trimmed; `carrel doctor --json` gives the same data machine-readably.)

The groups below mirror the doctor's install hints exactly.

### PDF handling

```bash
sudo apt install poppler-utils   # pdftotext, pdftoppm, pdfimages — text extraction, thumbnails, embedded images
sudo apt install qpdf            # PDF surgery (edit pdf: linearize/decrypt)
sudo apt install ghostscript     # PDF render/compress, ICC profiles
```

### Document conversion

```bash
sudo apt install pandoc          # conversion hub (md/html/txt…)
sudo apt install weasyprint      # HTML/CSS → PDF rendering
```

Without pandoc, `convert` still covers a useful core (a built-in md→html
fallback, csv/json/xml transforms); pandoc widens the format matrix and
weasyprint renders html→pdf.

### OCR

```bash
sudo apt install tesseract-ocr   # OCR engine (images)
sudo apt install ocrmypdf        # adds OCR text layers to PDFs
sudo apt install tesseract-ocr-deu   # extra languages, one package per language
```

Only English (`eng`) ships by default — `carrel doctor` lists installed
languages; see [Troubleshooting](TROUBLESHOOTING.md#ocr-in-languages-other-than-english).

### Images

```bash
sudo apt install imagemagick               # image operations (magick, or legacy convert)
sudo apt install pngquant                  # PNG optimization
sudo apt install icoutils                  # .ico build/extract (icotool)
sudo apt install libimage-exiftool-perl    # deep metadata (inspect --deep)
```

### Audio / text-to-speech (audiobook)

```bash
sudo apt install espeak-ng       # baseline voice
sudo apt install ffmpeg          # mp3/ogg encoding, durations (ffprobe)
pipx install piper-tts           # optional: natural local voice, preferred automatically
pipx install edge-tts            # optional: cloud voice, preferred over espeak
```

`--engine auto` prefers piper > edge-tts > espeak-ng — installing a better
engine upgrades the voice with no flag changes
([Configuration](CONFIGURATION.md#tts-engine-preference)).

### Search, find, watch

```bash
sudo apt install ripgrep         # rg — fast content search
sudo apt install fd-find         # fd/fdfind — fast file finding
sudo apt install sqlite3         # SQLite CLI (the index db itself uses Python's stdlib)
sudo apt install inotify-tools   # inotifywait — filesystem event tap (watch fallback)
```

### Data processing

```bash
sudo apt install jq              # JSON processing
sudo apt install miller          # mlr — CSV/TSV/JSON transforms
```

### Signing

```bash
sudo apt install gnupg           # gpg — detached signatures for manifests
```

### Everything at once

```bash
sudo apt install poppler-utils qpdf ghostscript pandoc weasyprint \
  tesseract-ocr ocrmypdf imagemagick pngquant icoutils \
  libimage-exiftool-perl espeak-ng ffmpeg ripgrep fd-find sqlite3 \
  inotify-tools jq miller gnupg
```

Then re-run `carrel doctor` — every row in the *command capabilities* table
should read `ok`.

## WSL2 notes

- **Work under the Linux filesystem** (`~/projects/…`, ext4), not under
  `/mnt/c/…`. Two reasons: file I/O across the Windows boundary is 10–50×
  slower, and `carrel watch` relies on inotify events, which are reliable on
  ext4 but do **not** arrive for changes made by Windows applications on
  `/mnt/c` paths (details in
  [Troubleshooting](TROUBLESHOOTING.md#watch-doesnt-fire-on-mntc)).
- `/mnt/c` is fine for copying files in and out — e.g.
  `cp /mnt/c/Users/you/Downloads/scan.pdf ~/inbox/` — just don't point
  `watch`, `index --root`, or heavy batch jobs at it.
- A nice WSL bonus: `carrel doctor` also picks up Windows ICC profiles from
  `/mnt/c/Windows/System32/spool/drivers/color` for `proof`/`color convert`.

## Next steps

Take the ten-minute tour in [QUICKSTART.md](QUICKSTART.md), or jump straight
to the full [command reference](REFERENCE.md).
