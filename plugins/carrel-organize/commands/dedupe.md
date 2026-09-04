---
description: Find duplicate files (exact hash groups, or near-duplicate images) and optionally reclaim space, using the carrel CLI
argument-hint: <folders...> [near-duplicates?] [delete policy]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Find duplicates in: $ARGUMENTS

Run the carrel CLI via Bash. **First run `carrel dedupe --help`** to confirm the exact flags available in the installed version, then map the user's request onto them — never invent flags. The expected interface is:

```
carrel --json dedupe DIR... [--near] [--delete newest|oldest] [--apply]
```

Note: `--json` is a **global** flag and must come before the subcommand.

- Exact duplicates: BLAKE2b hash groups (size-prefiltered). `--near`: images only, perceptual dHash clustering (catches resized/re-encoded copies).
- **Report-only is the default** — nothing is ever deleted without BOTH `--delete <policy>` AND `--apply`. Never pass `--apply` unless the user explicitly confirmed deletion after seeing the report; the kept member of each group is never deleted.

If `carrel dedupe --help` reports that the command does not exist, the installed carrel predates it — say so; you may fall back to comparing `carrel inspect --json` sha256 values for a small set of files, but do not guess flags.

Interpret the JSON `[{hash, files, kept, deleted}]`: show each duplicate group, which copy would be kept, and the reclaimable bytes. Then ask before any destructive re-run.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
