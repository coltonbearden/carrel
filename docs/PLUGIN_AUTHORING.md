# PLUGIN_AUTHORING — adding a plugin to this marketplace

How to add an eighth (ninth, ...) plugin to the carrel marketplace so that it validates,
installs, and passes the repo's tests. Read one existing plugin end-to-end first —
[`plugins/carrel-inspect/`](https://github.com/coltonbearden/carrel/tree/main/plugins/carrel-inspect/) is the best template for slash commands,
[`plugins/carrel-guard/`](https://github.com/coltonbearden/carrel/tree/main/plugins/carrel-guard/) for hooks.

## Directory layout

```
plugins/<your-plugin>/
├── .claude-plugin/
│   └── plugin.json          # required manifest
├── commands/                # slash commands, one .md each (optional)
│   └── <cmd>.md
├── skills/                  # optional
│   └── <skill-name>/SKILL.md
├── agents/                  # optional
│   └── <agent-name>.md
├── hooks/                   # optional
│   └── hooks.json
├── scripts/                 # anything hooks call (must be executable)
├── README.md                # required when the plugin ships hooks (what they do, how to turn off)
└── .mcp.json                # optional MCP server registration
```

`plugin.json` — `name` is the only field Claude requires, but this repo's tests require
more (see below):

```json
{
  "name": "carrel-example",
  "description": "One sentence: what it wraps and which slash commands it adds.",
  "version": "0.1.2",
  "author": { "name": "Your Name" },
  "license": "MIT",
  "keywords": ["files", "example"]
}
```

`version` must equal the `version` in `/product.json`; `scripts/sync_product.py` rewrites
it for every `plugins/*/.claude-plugin/plugin.json` and every marketplace entry, so type
it once and run the script. The `description` must be identical in `plugin.json` and the
marketplace entry (tested).

## Command markdown: the usage-marker convention

Commands here are **thin**: they never implement logic, they instruct Claude to run the
carrel CLI and interpret its `--json` output. The one part that used to rot — the copied
`--help` text — is now **generated**. Anatomy of every shipped command:

```markdown
---
description: One line, starts with a verb, names the carrel command it wraps
argument-hint: <file> [options in plain words]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: <name>            # a key of carrel.cli.COMMANDS, e.g. convert or edit
---

<Restate the task with $ARGUMENTS.>

Run the carrel CLI via Bash. Map the user's request onto the real flags in the
`--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the
installed `carrel <name> --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
<!-- usage:end -->

<flag-by-flag guidance; which flags are global (--json/--root may precede the subcommand)>

<how to interpret the JSON result + the relevant exit codes (3 = missing binary
→ relay the install hint; 4 = bad input)>

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to
install it with `uv tool install carrel` (see the repo's INSTALL
notes), or run it as `uv run carrel ...` from the carrel repo root.
```

Then run

```bash
uv run python scripts/sync_plugins.py          # fills / refreshes every block
uv run python scripts/sync_plugins.py --check  # exit 1 + file list if anything drifted
```

What the script does, precisely:

- For every `plugins/*/commands/*.md` it reads `carrel-command:` from the frontmatter,
  captures that command's `--help` **in-process** through click at a pinned width
  (`COLUMNS=100`, so the output never depends on your terminal or on which `carrel` is on
  PATH), and replaces everything between `<!-- usage:start -->` and `<!-- usage:end -->`
  with one fenced `text` block. For click groups (`edit`, `tag`, `note`, `sign`, `form`,
  `color`, `catalog`) it emits the group's help followed by one block per subcommand.
- Text outside the markers is preserved byte for byte — that is where your hand-written
  guidance lives. Never edit inside the markers; the next run overwrites it.
- A file without both markers (exactly once, in order), without `carrel-command`, or naming
  a command that is not registered exits 1 with the path in the message.
- `--plugins-dir DIR` points it at a copy (the tests do this); the default is `plugins/`.

CI runs `--check` in the lint job next to `sync_reference.py`; `tests/test_marketplace.py`
runs it too, so a flag added to a command without regenerating fails the suite.

The binding rules for the hand-written part, all enforced by tests or convention:

- **Coverage**: every key of `carrel.cli.COMMANDS` except `mcp` (served by
  `carrel-agent/.mcp.json`) and `desk` (interactive TUI) is wrapped by **exactly one**
  command file across all plugins. Adding a CLI command means adding a command file.
- **`--help`-first safety**: the generated block is the reference version's help; the text
  tells Claude to trust the *installed* `--help` if it differs, and never to invent flags.
- **`allowed-tools` syntax**: a comma-separated list of `Bash(prefix:*)` patterns. Keep it
  to the three entries above unless the command genuinely needs another read-only helper
  (`/redact` adds `Bash(grep:*)` for verification).
- **Destructive operations dry-run first**: mirror `/organize` / `/dedupe` — show the
  plan, require explicit confirmation before `--apply` / `--force` / `--delete` /
  `--replace`.
- **Install fallback**: every command body must mention `uv tool install` or
  `uv run carrel` (tested).

## Hooks

Scripts must be bash with a shebang, executable, use `set -u` (never `set -e`), drain
stdin, parse JSON with `jq` and fall back to `python3` (see
`plugins/carrel-agent/scripts/reindex.sh` and `plugins/carrel-guard/scripts/read-guard.sh`),
**always exit 0**, print nothing on stderr in the happy path, and tolerate empty/garbage
stdin — a plugin hook must never be able to block or break a session. Bound any external
call with `timeout`. If the hook returns a decision, use the `hookSpecificOutput` shape from
<https://code.claude.com/docs/en/hooks> for that event and check the tool's input schema
before rewriting `updatedInput`.

## Register it in marketplace.json

Add an entry to `.claude-plugin/marketplace.json` `plugins[]` — explicit `./plugins/...`
source, don't rely on `pluginRoot`:

```json
{
  "name": "carrel-example",
  "source": "./plugins/carrel-example",
  "description": "Same one-liner as plugin.json",
  "version": "0.1.2",
  "author": { "name": "Your Name" },
  "license": "MIT",
  "keywords": ["files", "example"]
}
```

Then `uv run python scripts/sync_product.py` so the version fields agree with
`product.json`.

## The validate loop

```bash
claude plugin validate plugins/carrel-example   # your plugin alone
claude plugin validate .                        # the whole marketplace
# ✔ Validation passed
```

Iterate until both pass. Then install it against your local checkout and try the
commands for real (`claude plugin marketplace add <repo>` →
`claude plugin install carrel-example@carrel` — full flow in
[MARKETPLACE.md](MARKETPLACE.md)).

## What tests/test_marketplace.py will hold you to

[`tests/test_marketplace.py`](https://github.com/coltonbearden/carrel/blob/main/tests/test_marketplace.py) runs on every `uv run pytest`.
A new plugin must satisfy:

1. **Registration** — `EXPECTED_PLUGINS` at the top of the test file maps plugin name →
   its exact set of command files. **Add your plugin there**, or the
   marketplace-entries test fails (`names == set(EXPECTED_PLUGINS)`) and the
   command-inventory test won't cover you. Every directory under `plugins/` must be listed.
2. **Marketplace entry** — `source` starts with `./plugins/` and the directory exists;
   `description` and `keywords` non-empty; `version` equals `product.json`'s version.
3. **plugin.json** — parses; `name` matches the directory name; `description`,
   `version`, `author.name` present; version and description match your marketplace entry.
4. **Every `commands/*.md`** — frontmatter with `description`, `allowed-tools`
   containing `Bash(carrel`, and `carrel-command` naming a registered CLI command; both
   usage markers exactly once with a fenced `Usage: carrel <name>` block between them
   (groups: one block per subcommand); body mentions the `uv tool install`/`uv run carrel`
   fallback; `scripts/sync_plugins.py --check` exits 0.
5. **Coverage** — every CLI command has exactly one slash command (see above).
6. **Every `agents/*.md` and `skills/*/SKILL.md`** — frontmatter with `name` and
   `description`.
7. **Hooks (if you ship any)** — script executable with a bash shebang and `set -u`; exits
   0 with empty stdin, non-JSON stdin, `{}`, and with `carrel` off PATH; produces no stdout
   when it no-ops.
8. **`claude plugin validate`** — run for the repo root and every plugin dir (skipped
   when the `claude` CLI is absent); must print `Validation passed`.

Then run the suite and the validator:

```bash
uv run python scripts/sync_plugins.py --check
uv run pytest tests/test_marketplace.py -q
claude plugin validate .
```

All green → follow [CONTRIBUTING.md](CONTRIBUTING.md) for the commit/PR conventions.
