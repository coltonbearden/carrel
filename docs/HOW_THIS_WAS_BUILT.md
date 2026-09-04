# How this was built

carrel v0.1.0 — the core library, 24 CLI commands, the desk TUI, 501 tests, five Claude Code plugins, and the docs — was designed, built, tested, and released in a single day (2026-07-16) by an autonomous multi-agent build running in [Claude Code](https://claude.com/claude-code): one orchestrating session directing specialized subagents, with a human setting the goal and constraints up front and reviewing at the gates.

This page is the factual account, from the primary sources committed in this repo:

- [STATE.md](https://github.com/coltonbearden/carrel/blob/main/STATE.md) — the running state file the build resumed from
- [BUILD_PLAN.md](BUILD_PLAN.md) — the wave plan and acceptance criteria
- [DECISIONS.md](DECISIONS.md) — the decision log
- [specs/](https://github.com/coltonbearden/carrel/tree/main/specs) — the 15 module specs
- [AGENTS.md](AGENTS.md) — the builder agents and the agents carrel ships
- [TEST_REPORT.md](TEST_REPORT.md) — the executed proof

## The shape: phases, gated by commits

The build ran as eight phases (0–7), each ending in a `phase(N)` commit that captured verified state — never intentions. From the git history:

```
phase(0): bootstrap + environment discovery
phase(1): ideation — product is carrel; vision, feature matrix, product.json
phase(2): architecture, module specs, walking skeleton (core lib + lazy CLI), builder agents
phase(3): build plan — 4 waves, MVP line, scope guards
phase(5): test report — 501 tests, 7 executed recipes, marketplace install + slash-command proof
phase(6): visual identity, README, docs package, CI, cookbook 08-09
phase(7): finalize.sh tested (dry run, temp-dir run, rename round-trip green)
```

There is no `phase(4)` commit because phase 4 *is* the build itself: four waves of parallel implementation, each with its own `wave(N)` commit.

Phase 0 probed the machine ([ENVIRONMENT.md](ENVIRONMENT.md)) rather than assuming one; phase 1 chose the product; phase 2 fixed the architecture and wrote binding specs before any feature code; phase 3 planned the waves. Everything before the first module was about making parallel work safe.

## The waves: parallel subagents behind an MVP line

[BUILD_PLAN.md](BUILD_PLAN.md) defines the mechanism: *waves of ≤4 parallel subagents; the orchestrator verifies each wave by running smoke tests personally, then commits `wave(N)`.* The four waves, as committed:

```
wave(1): fixtures + core tests, doctor, mcp, pack, edit — 163 tests green
wave(2): convert, ocr, inspect, diff, index/search/tag/note — full md→pdf→txt chain verified
wave(3): thumb/extract-images/proof/color, watch/organize/dedupe, redact/sign/form,
         marketplace + 5 plugins — MVP complete
wave(4): audiobook, desk TUI, snippets+cookbook, integration review + fixes
```

Two structural details did a lot of work:

- **The MVP line** sits between waves 3 and 4: everything above it had to pass before anything below was attempted. The flagship TUI and the audiobook command were deliberately last — nice-to-haves could not put the core at risk.
- **Wave 1 could not assume shared fixtures existed** (they were being built concurrently in the same wave), so each wave-1 task synthesized its own test inputs. Coordination constraints were designed out rather than managed.

## The subagents: narrow roles, hard boundaries

Five builder agents live in [`.claude/agents/`](https://github.com/coltonbearden/carrel/tree/main/.claude/agents), each with a role and an honesty rule ([AGENTS.md](AGENTS.md) has the full table):

| Agent | Role | The rule that kept it honest |
|---|---|---|
| `module-builder` | One spec per dispatch: command module + its tests | Touches only the paths its spec's **Owns** line lists; pastes real pytest output; no stubs, no TODOs |
| `test-engineer` | Fixtures, integration tests, cookbook validation | Fixtures generated programmatically, never hand-crafted binaries; drives the real CLI, no filesystem mocking |
| `integration-reviewer` | Adversarial cross-module review | Read-only tools; verifies by execution, not by reading reports; reports, never fixes |
| `doc-smith` | Reference docs, guides, cookbook recipes | Never documents a flag it didn't see in real `--help` output; runs every recipe before writing it down |
| `design-artist` | SVG logo/banner, palette, README/TUI theming | Original hand-authored SVG only; palette defined once in [BRAND.md](BRAND.md) |

Work was divided by **specs**: 15 of them in [specs/](https://github.com/coltonbearden/carrel/tree/main/specs) (`00-core.md` through `14-fixtures.md`). Each spec carries an **Owns:** line — the exact file paths that agent may write — and an **Acceptance** section of concrete, testable assertions. The core spec's interfaces were declared *binding as written*, so four agents could build against them simultaneously without drift.

## The discipline: claims are verified by execution

The rule that shaped everything, from [AGENTS.md](AGENTS.md): *every agent's completion report must contain executed output (pytest tails, real invocations), and the reviewer re-runs everything anyway. Claims are verified by execution, never trusted.*

What that produced, all recorded with real output in [TEST_REPORT.md](TEST_REPORT.md):

- **501 tests passing** across 20 test files, on fixtures for all 11 supported file types — fixtures themselves generated by a committed script, never hand-edited.
- **7 cookbook recipes executed end-to-end**, each with observed proof (a search hit surfacing OCR'd text, a dedupe run reporting `5 files → 2 survivors`, a sentinel phrase surviving an md→html→pdf→txt conversion relay).
- **The marketplace flow run for real**: `claude plugin validate` → `marketplace add` → `install` → a headless slash-command invocation that drove the CLI and summarized a fixture PDF.
- **An adversarial integration sweep of all 24 commands**: `--help`, a real fixture invocation, parseable `--json`, missing-file and missing-binary failure paths, and a grep for adapter-layer violations. Its findings were fixed and re-verified.
- **The rename machinery tested by renaming**: `finalize.sh` was proven by actually renaming the product to a throwaway name and back, with the full suite green after the round trip.

## The decisions

Four decisions were logged in [DECISIONS.md](DECISIONS.md) as they were made:

- **D-001** — lock the marketplace manifest schema to the live Claude Code docs, validated by `claude plugin validate`.
- **D-002** — Python ≥3.12 + uv; external binaries only through a single adapter layer.
- **D-003** — the flagship experience is a Textual TUI, not a local web UI.
- **D-004** — never force-install optional binaries; features degrade with an install hint (exit 3) and `carrel doctor` reports what the environment enables.

## The timeline

All from `git log`: first commit (`phase(0)`) at 04:30, the `v0.1.0` tag at 06:53 the same morning — about two hours and twenty minutes from empty directory to released product, in 14 commits. Publication and polish followed the same day.

What the timeline doesn't show is where the leverage came from: almost none of those minutes were spent writing code sequentially. They were spent writing *specs and contracts* that let four agents build in parallel, and *executing proof* that what they built was real.
