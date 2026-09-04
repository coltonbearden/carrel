# Installing Carrel

Carrel is a Python CLI managed with [uv](https://docs.astral.sh/uv/). The core
always works with nothing but Python; [optional extras](#optional-extras)
(pip-installable) and external binaries unlock extra capability and are
detected at runtime — nothing breaks when one is missing (you get a one-line
message with the install hint and exit code 3).

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

## Optional extras

A plain install pulls only what the file toolkit needs (click, rich, pypdf,
Pillow, reportlab, watchdog, markdown-it-py). Heavier Python dependencies are
**extras** you opt into (decision D-007 in [DECISIONS.md](DECISIONS.md)):

| Extra | Installs | Enables |
|---|---|---|
| `tui` | `textual` | `carrel desk`, the interactive three-pane TUI |
| `office` | `openpyxl` | `.xlsx` text extraction for `convert`/`pack`/`index`/`inspect` (the other office formats — `.docx`, `.odt`, `.epub`, `.rtf` — need no extra) |
| `tokens` | `tiktoken` | exact token counts in `carrel pack` (without it, counts are estimated) |
| `all` | the union of the above | everything |

Install with the extras you want in square brackets (quote them — most shells
treat `[` specially):

```bash
uv tool install 'carrel[all]'           # everything
uv tool install 'carrel[tui,tokens]'    # pick and choose
pipx install 'carrel[all]'              # pipx works the same way
uv tool install --force 'carrel[tui]'   # add an extra to an existing install
```

From a checkout:

```bash
uv sync --extra tui                     # one extra
uv sync --all-extras                    # all of them (what CI's full test job uses)
```

A command whose extra is missing exits 3 and names it, exactly like a missing
binary — for example `carrel desk` on a plain install prints
`textual is not installed (optional extra 'tui') — run: uv tool install 'carrel[tui]'  (from a checkout: uv sync --extra tui)`.
`carrel doctor` lists `desk` as `unavailable` with the same hint until the
extra is present.

## Development mode

To hack on carrel itself, skip the install and run from the repo:

```bash
cd ~/projects/carrel
uv sync --all-extras   # create .venv and install dependencies (+ every extra) from uv.lock
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

### Git-aware packing

```bash
sudo apt install git             # changed-file lists for pack --since / --changed
```

`index`, `search`, and `watch` need no external tools: the index db is
Python's stdlib SQLite (FTS5), and folder watching uses the bundled
`watchdog` library.

### Signing

```bash
sudo apt install gnupg           # gpg — detached signatures for manifests
```

### Everything at once

```bash
sudo apt install poppler-utils qpdf pandoc weasyprint \
  tesseract-ocr ocrmypdf imagemagick icoutils \
  libimage-exiftool-perl espeak-ng ffmpeg gnupg git
```

Then re-run `carrel doctor` — every row in the *command capabilities* table
should read `ok`.

If `PATH` finds the wrong copy of a tool (several versions installed, or a
Windows `.exe` reached through WSL interop), pin the one carrel should use
with `CARREL_BIN_<NAME>` — see
[Configuration](CONFIGURATION.md#pinning-a-binary-carrel_bin_name).

## Shell completions

`carrel completion <shell>` prints a tab-completion script for bash, zsh, or
fish (generated in-process from the real command tree, so it always matches
the installed version). Add `--install-hint` to have the same instructions
appended as a comment block; `--json` gives `{"shell": …, "script": …}`.

**bash** — append to `~/.bashrc` (needs bash ≥ 4.4 with `bash-completion`):

```bash
eval "$(carrel completion bash)"
```

**zsh** — append to `~/.zshrc`, *after* the line that runs `compinit`
(`autoload -Uz compinit && compinit`):

```zsh
eval "$(carrel completion zsh)"
```

**fish** — fish autoloads from `~/.config/fish/completions/`:

```fish
carrel completion fish > ~/.config/fish/completions/carrel.fish
```

`eval "$(…)"` regenerates the script on every shell start (a few
milliseconds); to skip that, redirect once into a file and `source` it
instead — `carrel completion bash --install-hint` shows the exact lines. Any
other shell name exits 2.

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
