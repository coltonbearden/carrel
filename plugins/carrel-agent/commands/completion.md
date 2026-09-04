---
description: Set up shell tab-completion for the carrel CLI (bash, zsh, or fish) using carrel's own completion script
argument-hint: <bash|zsh|fish>
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel), Bash(echo $SHELL)
carrel-command: completion
---

Set up carrel shell completion for: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel completion --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel completion [OPTIONS] {bash|zsh|fish}

  Print a completion script for SHELL (bash, zsh, or fish).

    eval "$(carrel completion bash)"      # ~/.bashrc
    eval "$(carrel completion zsh)"       # ~/.zshrc, after compinit
    carrel completion fish > ~/.config/fish/completions/carrel.fish

  The script is produced in-process by click; an unknown shell exits 2. With --json, emits {"shell":
  ..., "script": ...}.

Options:
  --install-hint  Append, as a comment block, how to enable the script in that shell.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```
<!-- usage:end -->

- `SHELL` is one of `bash`, `zsh`, `fish`; an unknown shell exits 2. If the user didn't say which, check `echo $SHELL` and ask only if it's ambiguous.
- `--install-hint` appends, as a comment block, how to enable the script in that shell — run with it once and relay the instructions verbatim.
- `--json` returns `{shell, script}` if you need to inspect the script rather than print it.

Do **not** modify the user's `~/.bashrc`, `~/.zshrc` or fish config yourself — this plugin's tools are limited to running carrel. Show the exact one-liner from the help (`eval "$(carrel completion bash)"` in `~/.bashrc`; zsh after `compinit`; fish writes to `~/.config/fish/completions/carrel.fish`) and let the user add it, then tell them to open a new shell (or `source` the rc file) and try `carrel <Tab>`.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
