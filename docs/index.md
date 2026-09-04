# carrel

*A library desk for your files — and your agents.*

A **carrel** is a private study desk in a library: your materials close at hand, organized your way. carrel is that desk for your local files — pdf, md, images, html, json, xml, csv — with 24 commands to convert, OCR, inspect, diff, index, search, pack, watch, and more.

It treats AI agents as first-class users of the desk: every data-producing command speaks `--json` on stable exit codes, `carrel pack` turns file trees into LLM-ready context, and the [repository doubles as a Claude Code plugin marketplace](MARKETPLACE.md) whose plugins drive the same CLI.

## Start here

```sh
uv tool install carrel   # or: pipx install carrel
carrel doctor    # what can your desk do today? (+ install hints for the rest)
```

- **[Carrel in ten minutes](QUICKSTART.md)** — a guided tour of the CLI and the desk TUI.
- **[Installing](INSTALL.md)** — the CLI plus the optional binaries that unlock each capability.
- **[Command reference](REFERENCE.md)** — every flag of all 24 commands, verified against real `--help` output.

## For agents and their operators

- **[The marketplace](MARKETPLACE.md)** — five Claude Code plugins: slash commands, agents, skills, a reindex hook, and an MCP server.
- **[Authoring a plugin](PLUGIN_AUTHORING.md)** — add your own to this marketplace.

## Inside the build

carrel v0.1.0 was designed, built, tested, and shipped in a single day by an autonomous multi-agent build. **[How this was built](HOW_THIS_WAS_BUILT.md)** tells that story from the primary sources; [Architecture](ARCHITECTURE.md), [Decisions](DECISIONS.md), and the [Test report](TEST_REPORT.md) hold the details.
