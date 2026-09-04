# PLUGIN_AUTHORING — adding a plugin to this marketplace

How to add a sixth (seventh, ...) plugin to the carrel marketplace so that it validates,
installs, and passes the repo's tests. Read one existing plugin end-to-end first —
[`plugins/carrel-inspect/`](https://github.com/coltonbearden/carrel/tree/main/plugins/carrel-inspect/) is the best template.

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
└── .mcp.json                # optional MCP server registration
```

`plugin.json` — `name` is the only field Claude requires, but this repo's tests require
more (see below):

```json
{
  "name": "carrel-example",
  "description": "One sentence: what it wraps and which slash commands it adds.",
  "version": "0.1.0",
  "author": { "name": "Your Name" },
  "license": "MIT",
  "keywords": ["files", "example"]
}
```

`version` must equal the `version` in `/product.json` — the marketplace entries are
tested against it.

## Command markdown conventions (this repo's house style)

Commands here are **thin**: they never implement logic, they instruct Claude to run the
carrel CLI and interpret its `--json` output. Anatomy of every shipped command:

```markdown
---
description: One line, starts with a verb, names the carrel command it wraps
argument-hint: <file> [options in plain words]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

<Restate the task with $ARGUMENTS.>

Run the carrel CLI via Bash. Map the user's request onto these real flags of
`carrel <cmd>` (verify with `carrel <cmd> --help` if unsure — never invent flags):

    <the real usage line, copied from --help output>

<flag-by-flag notes; which flags are global (--json/--root precede the subcommand)>

<how to interpret the JSON result + the relevant exit codes (3 = missing binary
→ relay the install hint; 4 = bad input)>

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to
install it with `uv tool install carrel` (see the repo's INSTALL
notes), or run it as `uv run carrel ...` from the carrel repo root.
```

The binding rules, all enforced by tests or convention:

- **`--help`-first safety**: for any command whose interface might drift, tell Claude to
  run `carrel <cmd> --help` before composing flags, and what to do if the command is
  missing entirely. Never document a flag you didn't see in real `--help` output.
- **`allowed-tools` syntax**: a comma-separated list of `Bash(prefix:*)` patterns. Keep it
  to the three entries above — the command needs nothing but the carrel CLI.
- **Destructive operations dry-run first**: mirror `/organize` / `/dedupe` — show the
  plan, require explicit confirmation before `--apply` / `--force` / `--delete`.
- **Install fallback**: every command body must mention `uv tool install` or
  `uv run carrel` (tested).

Hooks: scripts must be executable, have a shebang, **always exit 0**, finish in under a
second, and tolerate empty/garbage stdin — a plugin hook must never be able to block or
break a session. See `plugins/carrel-agent/scripts/reindex.sh` for the guard pattern.

## Register it in marketplace.json

Add an entry to `.claude-plugin/marketplace.json` `plugins[]` — explicit `./plugins/...`
source, don't rely on `pluginRoot`:

```json
{
  "name": "carrel-example",
  "source": "./plugins/carrel-example",
  "description": "Same one-liner as plugin.json",
  "version": "0.1.0",
  "author": { "name": "Your Name" },
  "license": "MIT",
  "keywords": ["files", "example"]
}
```

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
   command-inventory test won't cover you.
2. **Marketplace entry** — `source` starts with `./plugins/` and the directory exists;
   `description` and `keywords` non-empty; `version` equals `product.json`'s version.
3. **plugin.json** — parses; `name` matches the directory name; `description`,
   `version`, `author.name` present; version matches your marketplace entry.
4. **Every `commands/*.md`** — frontmatter with a `description`, an `allowed-tools`
   containing `Bash(carrel`, body mentions `carrel` and the
   `uv tool install`/`uv run carrel` fallback.
5. **Every `agents/*.md` and `skills/*/SKILL.md`** — frontmatter with `name` and
   `description`.
6. **Hooks (if you ship any)** — script executable with a shebang; exits 0 with empty
   stdin, non-JSON stdin, `{}`, and with `carrel` off PATH; produces no stdout when it
   no-ops.
7. **`claude plugin validate`** — run for the repo root and every plugin dir (skipped
   when the `claude` CLI is absent); must print `Validation passed`.

Then run the suite and the validator:

```bash
uv run pytest tests/test_marketplace.py -q
claude plugin validate .
```

Both green → follow [CONTRIBUTING.md](CONTRIBUTING.md) for the commit/PR conventions.
