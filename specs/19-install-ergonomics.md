# spec: install ergonomics — extras, completions, adapter hooks

**Owns:** `pyproject.toml`, `uv.lock`, `src/carrel/core/adapters.py`, `src/carrel/commands/desk.py`, new `src/carrel/commands/completion.py`, `src/carrel/cli.py` (register `"completion": "completion"`), `src/carrel/commands/doctor.py` (only if removing adapter entries requires touching `CAPABILITIES` or its rendering), `docs/INSTALL.md`, `docs/CONFIGURATION.md`, `docs/DECISIONS.md` (D-007 and D-008 are already written — amend only if the implementation deviates), `tests/test_core_cli.py` (additive), new `tests/test_completion.py`, `tests/test_adapters*.py` (whichever file holds adapter tests; additive).
**Wave:** 1. (Spec 17 edits `cli.py` in wave 2; spec 16 needs the `git` adapter; spec 18 needs the `office` extra declared here.)

## Why
Textual is a hard dependency for everyone, including agents that only run `carrel pack`. Click can generate shell completions but nothing exposes them. Nine registered adapters are wired to no command yet `doctor` advertises them. There is no way to pin a specific binary when several are installed.

## pyproject.toml
- `[project.optional-dependencies]`: `tui = ["textual>=1.0"]`, `office = ["openpyxl>=3.1"]`, `tokens = ["tiktoken>=0.8"]`, `all = [the union]`. Remove `textual` from `dependencies`. Record as **D-007** (breaking for `carrel desk` on a plain install; the fix is one command).
- `[dependency-groups] dev` gains nothing new; CI's `test` job installs `--all-extras` (workflow edit belongs to spec 21 — hand the exact line to the orchestrator), `test-minimal` installs no extras and must stay green.
- sdist `exclude` gains the office fixtures spec 18 generates (`tests/fixtures/*.docx`, `*.odt`, `*.epub`, `*.xlsx`; `.rtf` is text and may ship).
- Run `uv lock`; commit `uv.lock`.

## desk.py
The existing guard (`desk.py:31`) already exits 3 when `textual` is missing; change the hint to `uv tool install 'carrel[tui]'  (from a checkout: uv sync --extra tui)` and drop the "even though it is a core dep" wording. `doctor`'s capability row for `desk` reads the same hint.

## completion.py
```
carrel completion bash|zsh|fish [--install-hint]
```
Prints click's completion script by invoking the shell-completion machinery in-process (equivalent to `_CARREL_COMPLETE=<shell>_source carrel`) — never by spawning a subprocess. `--install-hint` appends, as a comment block, the one-liner for that shell (`eval "$(carrel completion bash)"` in `~/.bashrc`; zsh with `compinit` note; `carrel completion fish > ~/.config/fish/completions/carrel.fish`). Exit 2 on an unknown shell. `--json` → `{"shell": …, "script": …}` (the command produces data, so the flag is honored).

## adapters.py
- Add `git` (`version_args=["--version"]`, hint `sudo apt install git`, purpose "changed-file lists for pack --since/--changed").
- **Override:** `CARREL_BIN_<NAME>` (NAME = adapter name upper-cased, `-` → `_`, e.g. `CARREL_BIN_ESPEAK_NG`) — when set, `have()`/`run()`/`version_of()` use that exact path instead of searching `PATH`; a set-but-nonexistent path counts as missing and the missing message includes `(override CARREL_BIN_X=/that/path not found)`. This is the single documented exception to config-free (**D-008**). `doctor` shows `via CARREL_BIN_*` next to an overridden adapter.
- **Remove** registry entries no command references: `gs`, `pngquant`, `jq`, `mlr`, `rg`, `fd`, `sqlite3`, `inotifywait`, `claude` (verified 2026-09-04: none appear in `src/carrel/commands/**` or `desk/`; `icotool` stays). Report the removal in the completion report so the orchestrator adds the one-line cut note to `docs/FEATURES.md` under Cuts ("unwired adapter entries removed; re-add with the command that uses them") — `FEATURES.md` belongs to spec 18 in this wave. Adjust any doctor test that counts adapters.

## Docs
- `INSTALL.md`: extras table (what each enables, install line for `uv tool install 'carrel[…]'`, `pipx install 'carrel[…]'`, checkout `uv sync --extra …`), completions section per shell.
- `CONFIGURATION.md`: keep the "config-free" opening; add the `CARREL_BIN_*` section as the one exception with a WSL example (pinning a Linux `pandoc` over a Windows one found via interop).

## Acceptance
- Fresh venv, `uv pip install .` (no extras): `carrel --help`, `carrel pack tests/fixtures --tree-only`, and `carrel desk` → exit 3 with the `carrel[tui]` hint (assert via subprocess in a test that builds the venv only when `uv` is present; otherwise monkeypatch the import).
- `uv sync --all-extras && uv run pytest` green; `uv sync` without extras and `uv run pytest tests/test_core_cli.py tests/test_pack.py` green (the `test-minimal` shape).
- `carrel completion bash|zsh|fish` each print a script containing `_CARREL_COMPLETE`; `--json` parses; `carrel completion powershell` exits 2.
- `CARREL_BIN_PANDOC=/nonexistent carrel doctor --json` marks pandoc missing and the message names the override; `CARREL_BIN_PANDOC=$(command -v pandoc)` (skip if absent) reports found `via CARREL_BIN_PANDOC`.
- `adapters.ADAPTERS` contains `git` and none of the nine removed names; `carrel doctor --json` adapter list matches.
- `docs/DECISIONS.md` has D-007 and D-008 filled in; `mkdocs build --strict` passes.
