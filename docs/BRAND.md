# carrel — brand guide

carrel is a private library study desk for files and AI agents. The identity is
**warm lamplight on dark wood**: scholarly, quiet, precise — but unmistakably a
modern CLI tool, not a heritage press. Every color, letterform, and sentence
should feel like working at a good desk after hours.

All brand values are defined **here once** and consumed everywhere: the SVG
assets in `assets/`, the README, and the TUI theme
(`src/carrel/desk/styles.tcss`, `$carrel-*` variable block). Derive from this
file; never improvise a new hex per artifact.

## Palette

Dark-first. One warm accent family (Lamplight/Brass), one cool secondary
(Dusk), cream neutrals (Paper/Parchment), espresso surfaces (Ink → Grain).
Swatch sheet: `assets/palette.svg`.

| Name | Hex | Role | Usage rules |
|---|---|---|---|
| **Ink** | `#14100A` | App/background | The default canvas. Everything sits on Ink. |
| **Walnut** | `#211A11` | Panels, cards, bars | Raised surfaces one step above Ink. |
| **Umber** | `#2C2416` | Inputs, wells, code rows | Interactive/inset surfaces one step above Walnut. |
| **Grain** | `#443826` | Borders, rules, dividers | Hairlines only — never text, never fills larger than a rule. |
| **Paper** | `#F2EADA` | Primary text, "the lit page" | Body text on any dark surface; the page motif in the mark. |
| **Parchment** | `#A19278` | Secondary text | Captions, metadata, muted labels on dark surfaces. |
| **Lamplight** | `#F2A93C` | Primary accent | The brand color: the mark, focus states, highlights, links on dark. Small doses — it is the lamp, not the room. |
| **Brass** | `#B07C24` | Dim accent | Low-emphasis chrome: scrollbars, tertiary labels, accent text on Paper (large sizes only). |
| **Dusk** | `#6E9EBF` | Cool secondary | Informational states, the occasional book spine, agent/`--json` callouts. Never competes with Lamplight in the same element. |

### Contrast (measured, WCAG relative luminance)

- Paper on Ink ≈ 15.3:1 — body text everywhere. ✓
- Lamplight on Ink ≈ 9.4:1 — accent text/icons on dark. ✓
- Dusk on Ink ≈ 6.6:1 — secondary accent text on dark. ✓
- Parchment on Ink ≈ 6.4:1 — muted text. ✓
- Ink on Lamplight ≈ 9.4:1 — text on amber buttons/badges. ✓
- **Never** set Lamplight text on Paper (≈ 1.7:1). On light surfaces use Ink
  for text and Brass only for large decorative type (≈ 3.1:1).

### Light backgrounds

The brand is dark-first. On light pages (GitHub light theme, print), use the
assets as-is: `logo.svg` carries its own Ink tile, and `banner.svg` /
`social-preview.svg` carry their own Ink canvas with rounded transparent
corners. Do not recolor the mark for light mode; the tile is the mark's frame.

## Logo

Files: `assets/logo.svg` (square, 512 grid), used in `assets/banner.svg` and
`assets/social-preview.svg`.

The mark is a **study carrel in profile that reads as a letter C**: the top arm
is the lamp arm ending in a glowing bulb, the left stroke is the carrel
partition, the longer bottom arm is the desk surface — with a light cone
falling on a cream page. All geometry is hand-authored: one stroked path
(56/512 ≈ 11% stroke, round caps/joins), three circles, one triangle, one
rect. No traced or third-party artwork.

Usage:

- **Sizes**: legible from 16 px (C silhouette + bulb survive) to 512 px+. Use
  the SVG; if you must rasterize, export at 2× the display size.
- **Clear space**: keep a margin of at least the stroke width (11% of the mark
  height) free around the tile.
- **Don't**: recolor the amber, remove the tile on busy backgrounds, add
  effects (shadows, gradients beyond the built-in glow), rotate, or set the
  wordmark in a font next to the drawn wordmark.

### Wordmark

"carrel", lowercase, hand-drawn geometric monoline (x-height 64, stroke 18,
round caps — circles and quarter-arcs only). It lives as reusable `<g>` path
groups inside `banner.svg` and `social-preview.svg`; copy those paths verbatim
if the wordmark is needed elsewhere. Stroke color: Paper on dark surfaces.
Never retype it in a system font as a substitute for the drawn letterforms in
brand artwork (plain prose "carrel" in text is of course fine — always
lowercase).

## Typography

No bundled or fetched fonts — system stacks only, everywhere (README, SVG
`<text>`, docs):

- **UI / prose**: `ui-sans-serif, -apple-system, 'Segoe UI', Roboto,
  'Helvetica Neue', Arial, sans-serif`
- **Code / commands / hex values**: `ui-monospace, 'Cascadia Code', Menlo,
  Consolas, 'Liberation Mono', monospace`

Conventions: the product name is always lowercase `carrel`; command examples
are always monospace; headings sentence-case (never ALL CAPS except file-name
conventions like README).

## TUI theme

`src/carrel/desk/styles.tcss` maps the palette 1:1:

| tcss variable | Brand color |
|---|---|
| `$carrel-accent` | Lamplight `#F2A93C` |
| `$carrel-accent-dim` | Brass `#B07C24` |
| `$carrel-cool` | Dusk `#6E9EBF` |
| `$carrel-bg` | Ink `#14100A` |
| `$carrel-panel` | Walnut `#211A11` |
| `$carrel-panel-alt` | Umber `#2C2416` |
| `$carrel-border` | Grain `#443826` |
| `$carrel-text` | Paper `#F2EADA` |
| `$carrel-muted` | Parchment `#A19278` |

A palette change is a variable-block change; never hardcode hex below the
block.

## Voice

- **Quiet confidence.** Say what a command does, show it doing it. No
  superlatives, no "blazingly fast", no emoji.
- **The desk metaphor is seasoning, not sauce.** One touch per surface
  (a heading, the tagline) — commands, flags, and errors stay literal.
- **Two audiences, one register.** Prose addresses the human; every example
  shows the agent path too (`--json`, exit codes) without switching tone.
- **Honest by default.** Name limitations where they matter (estimates are
  labeled estimates; degraded capabilities say what to install). Never claim
  an unshipped feature.
- Tagline, verbatim: *"A library desk for your files — and your agents."*

## Message architecture

Three layers, in this order, wherever carrel introduces itself (D-024):

| Layer | Text | Where it belongs |
|---|---|---|
| **Motto** | *A library desk for your files — and your agents.* | `product.json` `tagline`; the banner; the docs-site subtitle |
| **Functional line** | **Read, index, pack and file your documents — from the terminal, for you and your agents.** | first line of `README.md` and `docs/index.md`; the GitHub description; the start of the PyPI summary |
| **Three use cases** | give Claude the right context · read what the agent can't · turn an inbox into an archive | the README's "Three things to try", in that order |

The motto says what carrel *is* and is the only line allowed to be evocative. The functional
line says what it *does*, in verbs, to a reader who has never heard of it — it is the one that
has to survive being read alone in a search result. The use cases are ordered by why people
arrive, not by how impressive they are: context-for-an-agent first, the accounting inbox last.

Each use case gets two sentences, a command block that has been run, and one honest limitation.
The limitation is not a disclaimer to be minimised — it is what makes the other two sentences
believable.
