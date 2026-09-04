---
description: Turn a text, markdown, or PDF document into a spoken audiobook (mp3/ogg/wav) using the carrel CLI
argument-hint: <txt|md|pdf file> [voice/engine/format wishes]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: audiobook
---

Create an audiobook from: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel audiobook --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel audiobook [OPTIONS] SRC

  Narrate SRC (txt, md, pdf) into an audiobook.

  Markdown is stripped for speech: headings become spoken chapter announcements, code blocks become
  "[code omitted]", links read their text. mp3/ogg need ffmpeg; --format wav works with espeak-ng
  alone. Existing outputs are never overwritten without --force. With --json, prints {src, outputs,
  engine, duration_s, chars}.

Options:
  -o, --output FILE               Output audio file (default: SRC with audio extension).
  --voice TEXT                    Voice: espeak voice name, piper model path, or edge-tts voice.
  --rate INTEGER RANGE            Speech rate in words per minute.  [default: 170; 80<=x<=450]
  --engine [auto|espeak|piper|edge-tts]
                                  TTS engine; auto prefers piper > edge-tts > espeak-ng.  [default:
                                  auto]
  --split-chapters                One file per chapter (markdown H1/H2, or the PDF outline).
  --force                         Overwrite existing output files.
  --format [mp3|ogg|wav]          Audio format (default: from -o extension, else mp3).
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```
<!-- usage:end -->

Note: `--json` is a **global** flag and may come before the subcommand.

- `SRC`: txt/md/pdf — text is extracted automatically; markdown headings become spoken chapter markers and code blocks are skipped.
- `--engine` (default auto): auto prefers piper > edge-tts > espeak-ng, whichever is installed.
- `--split-chapters`: one output file per H1/H2 chapter (md, or pdf with an outline).
- `--format` (default mp3): mp3/ogg need ffmpeg; `wav` works with espeak-ng alone.
- `--rate`: words per minute (80–450); `--voice`: engine-specific voice name or piper model path.
- `--force`: only when the user explicitly wants an existing output overwritten.

Interpret the JSON result `{src, outputs, engine, duration_s, chars}`: tell the user which engine spoke, the output file(s), and the duration. Exit code 3 means a TTS engine or ffmpeg is missing — relay the install hint from stderr (espeak-ng is the minimal engine: `sudo apt install espeak-ng`; suggest `--format wav` when ffmpeg is absent).

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
