---
description: Turn a text, markdown, or PDF document into a spoken audiobook (mp3/ogg/wav) using the carrel CLI
argument-hint: <txt|md|pdf file> [voice/engine/format wishes]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Create an audiobook from: $ARGUMENTS

Run the carrel CLI via Bash. **First run `carrel audiobook --help`** to confirm the exact flags available in the installed version, then map the user's request onto them — never invent flags. The expected interface is:

```
carrel --json audiobook SRC [-o OUT.mp3] [--voice VOICE] [--rate 170] [--engine auto|espeak|piper|edge-tts] [--split-chapters] [--format mp3|ogg|wav]
```

Note: `--json` is a **global** flag and must come before the subcommand.

- `SRC`: txt/md/pdf — text is extracted automatically; markdown headings become spoken chapter markers and code blocks are skipped.
- `--engine` (default auto): auto prefers piper > edge-tts > espeak-ng, whichever is installed.
- `--split-chapters`: one output file per H1/H2 chapter (md, or pdf with an outline).
- `--format` (default mp3): mp3/ogg need ffmpeg; `wav` works with espeak alone.
- `--rate`: words per minute; `--voice`: engine-specific voice name.

Interpret the JSON result `{src, outputs, engine, duration_s, chars}`: tell the user which engine spoke, the output file(s), and the duration. Exit code 3 means a TTS engine or ffmpeg is missing — relay the install hint from stderr (espeak-ng is the minimal engine: `sudo apt install espeak-ng`; suggest `--format wav` when ffmpeg is absent).

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
