---
description: Find duplicate files (exact hash groups, or near-duplicate images) and optionally reclaim space, using the carrel CLI
argument-hint: <folders...> [near-duplicates?] [delete policy]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: dedupe
---

Find duplicates in: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel dedupe --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel dedupe [OPTIONS] DIRS...

  Report duplicate files under DIRS (recursively; hidden entries skipped).

  Default is report-only. Deletion needs BOTH --delete newest|oldest AND --apply; without --apply
  the deletions are only planned. The kept member of each group is never deleted. JSON output is a
  list of {hash, files, kept, deleted}.

Options:
  --near                    Perceptual matching for images (64-bit dHash, Hamming distance <= 8)
                            instead of exact content hashing. Non-image files are ignored in this
                            mode.
  --delete [newest|oldest]  Which duplicates to delete per group (by mtime); the other end of the
                            range is kept. Requires --apply to actually remove files.
  --apply                   Actually delete (only together with --delete).
  --json                    Machine-readable JSON output.
  --help                    Show this message and exit.
```
<!-- usage:end -->

Note: `--json` is a **global** flag and may come before the subcommand.

- Exact duplicates: content hash groups (size-prefiltered). `--near`: images only, perceptual dHash clustering (catches resized/re-encoded copies).
- **Report-only is the default** — nothing is ever deleted without BOTH `--delete <policy>` AND `--apply`. Never pass `--apply` unless the user explicitly confirmed deletion after seeing the report; the kept member of each group is never deleted.

If the installed carrel predates `dedupe` (its `--help` reports no such command), say so; you may fall back to comparing `carrel inspect --json` sha256 values for a small set of files, but do not guess flags.

Interpret the JSON `[{hash, files, kept, deleted}]`: show each duplicate group, which copy would be kept, and the reclaimable bytes. Then ask before any destructive re-run.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
