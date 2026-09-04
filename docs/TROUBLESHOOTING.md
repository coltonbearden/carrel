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
full exit-code table is in [REFERENCE.md](REFERENCE.md#exit-codes).

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
  the *same* `--root` to both commands.
- Scanned PDFs and images have no text until you index with `--ocr`.
- In scripts, `--fail-empty` makes an empty result exit 5 instead of 0, so
  pipelines can distinguish "no hits" from success.

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

The repo doubles as a plugin marketplace (five plugins: carrel-convert,
carrel-inspect, carrel-organize, carrel-watch, carrel-agent). Two gotchas:

- **Namespacing in headless mode.** When two plugins could claim a name — or
  always, in headless/`-p` runs — address commands by plugin:
  `/carrel-inspect:inspect`, `/carrel-inspect:pack`,
  `/carrel-convert:ocr`, `/carrel-watch:watch-folder`. Interactively, plain
  `/inspect` works when unambiguous.
- <a id="plugins-cant-find-carrel"></a>**Plugins can't find carrel.** Slash
  commands are thin wrappers that run `carrel …` via Bash, and the
  carrel-agent plugin's PostToolUse hook runs
  `carrel index --update --if-indexed` on files Claude writes. All of it
  requires `carrel` on `PATH`: install with `uv tool install .` from the repo
  ([INSTALL.md](INSTALL.md#install-the-cli-recommended)) and check with
  `command -v carrel`. (The hook is deliberately quiet: `--if-indexed` exits
  0 silently unless you've already created a desk index in that root.)

## FAQ

**Exit code 4?** Input problem — missing file, unreadable, or unsupported
type: `error: no such file: missing.pdf`. Carrel handles pdf, md, txt, html,
json, xml, csv, png, jpg, ico.

**Why won't convert overwrite my file?** By design — every output-producing
command refuses to clobber existing files without `--force`.

**Where did my index/tags/notes go?** They live in `.carrel/carrel.db` under
whatever `--root` you used (default: the directory you ran `index` in). See
[CONFIGURATION.md](CONFIGURATION.md#the-desk-root-root-and-carrel).

**`fd` vs `fdfind`, `magick` vs `convert`?** Carrel tries both names
automatically — see
[CONFIGURATION.md](CONFIGURATION.md#external-tools-adapter-path-resolution).

**Audiobook voice sounds robotic.** That's espeak-ng, the baseline. Install
piper (`pipx install piper-tts`) and `--engine auto` picks it up next run.
