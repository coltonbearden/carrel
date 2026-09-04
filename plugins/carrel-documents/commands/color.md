---
description: Color tools via the carrel CLI — dominant palette of an image, WCAG contrast check of two hex colors, or ICC profile conversion (cmyk, gray, p3, srgb) with the profile embedded
argument-hint: <palette|check|convert> <image or colors> [count/profile/output]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: color
---

Handle this color request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel color` is a group with `palette`, `check` and `convert`; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel color --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel color [OPTIONS] COMMAND [ARGS]...

  Color tools: dominant palette, ICC profile conversion, WCAG contrast.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  check    WCAG contrast ratio of FG on BG (hex colors, e.g.
  convert  Convert SRC into an ICC profile and embed the profile in the output.
  palette  Dominant colors of SRC as hex + proportion (median-cut quantization).
```

```text
Usage: carrel color check [OPTIONS] FG BG

  WCAG contrast ratio of FG on BG (hex colors, e.g. #333 #fafafa).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel color convert [OPTIONS] SRC

  Convert SRC into an ICC profile and embed the profile in the output.

  CMYK targets are written as JPEG/TIFF (PNG cannot store CMYK).

Options:
  --to-profile P  Target ICC profile: .icc path or builtin alias (cmyk, gray, p3, srgb).  [required]
  -o, --out FILE  Output path [default: <SRC>.<profile>.png/.jpg].
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

```text
Usage: carrel color palette [OPTIONS] SRC

  Dominant colors of SRC as hex + proportion (median-cut quantization).

  Human mode shows rich color swatches; --json prints one JSON array of {"hex", "proportion"} sorted
  by coverage.

Options:
  --n INTEGER RANGE  Number of colors to extract.  [default: 8; 1<=x<=256]
  --json             Machine-readable JSON output.
  --help             Show this message and exit.
```
<!-- usage:end -->

- **palette SRC** (`--n`, default 8): dominant colors as `[{hex, proportion}]` sorted by coverage (median-cut). Good for "what are this image's brand colors" — present them as hex codes with rough percentages, largest first.
- **check FG BG**: WCAG contrast ratio of two hex colors (`#333 #fafafa`). Report the ratio and whether it passes AA (4.5:1 normal text, 3:1 large text) and AAA (7:1); when it fails, propose a darker/lighter variant and re-check it.
- **convert SRC --to-profile P**: converts into an ICC profile (`.icc` path or alias `cmyk`, `gray`, `p3`, `srgb`) and embeds it. CMYK output is written as JPEG/TIFF because PNG cannot store CMYK. Output defaults to `<SRC>.<profile>.png/.jpg`; the original is never modified. To *preview* a profile without converting, use `carrel proof` instead.

Use `--json` for every subcommand and interpret the result conversationally. Exit code 4 means the input is not an image or a color could not be parsed — ask for a valid hex value.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
