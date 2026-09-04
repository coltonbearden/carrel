---
description: Soft-proof an image against an ICC profile (cmyk, gray, p3, srgb or a .icc file) with the carrel CLI — see how it will print or display, and how much the colors shift
argument-hint: <image> <profile alias or .icc path> [intent] [output]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: proof
---

Soft-proof: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel proof --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel proof [OPTIONS] SRC

  Soft-proof SRC against an ICC PROFILE (simulate print/display output).

  Writes the proofed image and reports the color shift: mean/max per-channel delta and the share of
  pixels that moved visibly. With --json, prints the report as one JSON object.

Options:
  --profile PROFILE               Path to a .icc file, or builtin alias: cmyk, gray, p3, srgb.
                                  [required]
  --out FILE                      Proofed image path [default: <SRC>.proof.png].
  --intent [perceptual|relative]  Rendering intent.  [default: perceptual]
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```
<!-- usage:end -->

- `--profile` (required): a `.icc` path or a builtin alias — `cmyk` ("how will this print"), `gray`, `p3` (wide-gamut displays), `srgb`. `carrel doctor --json` lists the `icc_dirs` where system profiles live if the user names a specific printer profile.
- `--intent perceptual` (default; pleasing overall) or `relative` (colorimetric; exact in-gamut colors, clipped out-of-gamut).
- `--out FILE` defaults to `<SRC>.proof.png`; the original is never modified.

Use `--json` and translate the report for the user: the proofed image path, mean/max per-channel delta, and the share of pixels that moved visibly — "X% of pixels shift noticeably; the largest changes are in <channel>" is more useful than raw numbers. Offer `carrel diff SRC OUT --mode image --out heatmap.png` to show *where* the shift lands, and `carrel color convert --to-profile` when the user wants to actually embed the profile rather than preview it. Exit code 4 means the input is not an image or the profile could not be read.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
