---
description: Save email attachments, split an mbox into .eml files, group eml/mbox messages into threads, or convert an Outlook .pst export with the carrel CLI
argument-hint: <attachments|split|threads|pst> <file or folder> [--out-dir DIR]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: mail
---

Handle this email-file request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel mail` is a group; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel mail --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel mail [OPTIONS] COMMAND [ARGS]...

  Attachments, mailbox splitting, threads and Outlook exports for eml/mbox files.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  attachments  Save every attachment of FILES (eml or mbox) into --out-dir.
  pst          Convert an Outlook SRC (.pst/.ost) into eml or mbox files via readpst.
  split        Split BOX (an mbox) into one .eml file per message under --out-dir.
  threads      Group the messages in PATHS (eml/mbox files or directories) into threads.
```

```text
Usage: carrel mail attachments [OPTIONS] FILES...

  Save every attachment of FILES (eml or mbox) into --out-dir.

  File names are sanitised (no separators, no leading dots); collisions get -1, -2, … suffixes
  unless --force. JSON: one record per message with the written paths, sizes and sha256 digests.

Options:
  --out-dir DIRECTORY  Directory to write attachments into (created if missing).  [required]
  --force              Overwrite same-named files instead of suffixing -1, -2, …
  --fail-empty         Exit 5 when no attachment was found.
  --json               Machine-readable JSON output.
  --help               Show this message and exit.
```

```text
Usage: carrel mail pst [OPTIONS] SRC

  Convert an Outlook SRC (.pst/.ost) into eml or mbox files via readpst.

  `--format eml` writes one .eml per message (readpst -e); `--format mbox` writes one `mbox` file
  per mail folder (readpst -r), which `carrel mail split` can then take apart.

  Needs readpst (sudo apt install pst-utils); exit 3 with that hint otherwise. JSON: {src, out_dir,
  format, files, via}.

Options:
  --out-dir DIRECTORY  Directory readpst writes into (one subfolder per mail folder).  [required]
  --format [eml|mbox]  One .eml per message (readpst -e), or one mbox file per mail folder (readpst
                       -r).  [default: eml]
  --json               Machine-readable JSON output.
  --help               Show this message and exit.
```

```text
Usage: carrel mail split [OPTIONS] BOX

  Split BOX (an mbox) into one .eml file per message under --out-dir.

  Names come from --template; messages are numbered in mailbox order and the bytes are written as
  stored. Refuses to overwrite without --force. JSON: [{n, path, subject, date, message_id}].

Options:
  --out-dir DIRECTORY  Directory to write the .eml files into (created if missing).  [required]
  --template TEXT      File name template: {n} index, {date} YYYY-MM-DD, {subject} slug, {id}
                       message id.  [default: {n}_{date}_{subject}.eml]
  --force              Overwrite existing files.
  --json               Machine-readable JSON output.
  --help               Show this message and exit.
```

```text
Usage: carrel mail threads [OPTIONS] PATHS...

  Group the messages in PATHS (eml/mbox files or directories) into threads.

  Threads follow Message-ID / In-Reply-To / References; `depth` is the reply-chain length when the
  parent is present. JSON: [{root_subject, first_date, messages: [{where, message_id, date, from,
  subject, depth}]}].

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```
<!-- usage:end -->

- Choose the subcommand from intent: "pull the attachments out of X" → `attachments FILE...` (eml or mbox **files**, not folders) `--out-dir DIR`; "break this mailbox into messages" → `split box.mbox --out-dir DIR` (an mbox file); "what conversations are in here" → `threads PATH...` (files **or** folders); "I exported Outlook to a .pst" → `pst FILE.pst --out-dir DIR` (needs readpst: `sudo apt install pst-utils`; exit 3 says so). `--format eml` writes one `.eml` per message, `--format mbox` one `mbox` file per mail folder.
- Reading the mail itself needs no subcommand: `.eml` and `.mbox` are desk file types, so `carrel inspect`, `carrel index` + `carrel search`, `carrel pack` and `/carrel-finance:refs` all read them directly, and the `carrel-guard` Read hook turns them into text for you. Conversion targets differ by type: `.eml` → md, txt, html or pdf; `.mbox` → md or txt only (anything else exits 4 and lists the real targets).
- `carrel convert msg.eml --to pdf` renders the message's **text**, never its HTML, so converting a message can never fetch a tracking pixel or pull in a local file; `--to html` keeps the sender's HTML (opening that in a browser will fetch whatever it references, exactly like opening the mail would).
- Attachments and split messages are never overwritten without `--force`; colliding names get `-1`, `-2`, … suffixes.
- Prefer `--json` and report paths, sizes and sha256 digests back to the user; for threads, show root subject, participants and dates.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
