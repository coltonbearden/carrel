---
description: Stamp a visible signature block onto a PDF, write a sha256 manifest for files (optionally gpg-signed), or verify a manifest — using the carrel CLI
argument-hint: <stamp|manifest|verify> <pdf or paths> [text/image/page/key]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: sign
---

Handle this signing request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel sign` is a group with `stamp`, `manifest` and `verify`; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel sign --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel sign [OPTIONS] COMMAND [ARGS]...

  Sign things: stamp PDFs, hash manifests, verify both.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  manifest  Write a sha256 manifest for PATHS (directories recurse).
  stamp     Stamp a visible signature block onto a PDF page.
  verify    Recompute a sha256 manifest (and its gpg signature, if present).
```

```text
Usage: carrel sign manifest [OPTIONS] PATHS...

  Write a sha256 manifest for PATHS (directories recurse).

Options:
  -o, --out PATH  Manifest file to write (sha256sum format).  [default: MANIFEST.sha256]
  --gpg           Also write a detached armored signature (OUT.asc).
  --key ID        gpg key id/email to sign with (implies --gpg).
  --force         Allow overwriting an existing manifest.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

```text
Usage: carrel sign stamp [OPTIONS] SRC

  Stamp a visible signature block onto a PDF page.

Options:
  --text TEXT                     Stamp text. Default: "Signed by <user> on <ISO date>".
  --image PATH                    Signature image (png/jpg) drawn above the text.
  --page PAGE                     Page to stamp: 'first', 'last' or a 1-based number.  [default:
                                  last]
  --pos [top-left|top-right|bottom-left|bottom-right]
                                  Page corner for the stamp.  [default: bottom-right]
  -o, --out PATH                  Output file. Default: SRC.signed.pdf.
  --force                         Allow overwriting an existing output file.
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```

```text
Usage: carrel sign verify [OPTIONS] MANIFEST

  Recompute a sha256 manifest (and its gpg signature, if present).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```
<!-- usage:end -->

- **stamp SRC**: draws a visible signature block (`--text`, default "Signed by <user> on <ISO date>"; optional `--image` png/jpg above it) on `--page first|last|N` at `--pos <corner>`. Output `SRC.signed.pdf` by default; the original is untouched. This is a *visible* mark, not a cryptographic PDF signature — say so when the user asks about legal/cryptographic signing, and point them at `manifest --gpg` for integrity.
- **manifest PATHS...**: writes a `sha256sum`-format manifest (`MANIFEST.sha256` by default, `-o` to choose; directories recurse). `--gpg` (or `--key ID`, which implies it) also writes a detached armored signature `OUT.asc` — needs gpg with a usable key (exit 3 → relay the hint).
- **verify MANIFEST**: recomputes every hash and, when `MANIFEST.asc` exists, checks the gpg signature. Interpret the JSON: list files that are `ok`, `changed`, or `missing`, and the signature result.

Never pass `--force` unless the user explicitly wants an existing output/manifest replaced. Use `--json` and report the output path(s); after `stamp`, confirm with `carrel inspect OUT --json` that the page count is unchanged. For the redact → verify → manifest flow see this plugin's `document-clerk` agent.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
