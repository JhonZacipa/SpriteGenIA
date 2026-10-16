---
name: SpriteGen
description: Una mesa de luz de animación tradicional — el tablero está oscuro y el vidrio es el único plano iluminado.
colors:
  board-0: "#100e0b"
  board-1: "#17140f"
  board-2: "#201c15"
  board-3: "#2b261d"
  board-4: "#35301f"
  rule: "#3a3327"
  rule-2: "#524734"
  rule-3: "#6b5e46"
  ink: "#efe9dc"
  ink-2: "#b8ae99"
  ink-3: "#8f8677"
  glass: "#f2ece0"
  glass-2: "#e4dccb"
  glass-ink: "#1a1712"
  glass-off: "#24211a"
  glass-off-2: "#2d2921"
  p-sprite: "#6d9dd8"
  p-animation: "#d8a54c"
  p-terrain: "#5fa87b"
  p-tileset: "#4fa8a0"
  p-model3d: "#a58ad8"
  camera: "#c8392b"
  camera-hi: "#d1402f"
  camera-2: "#e8563f"
  on-camera: "#ffffff"
  done: "#5fa87b"
  done-dim: "rgba(95, 168, 123, 0.15)"
  mark-dim: "rgba(216, 165, 76, 0.15)"
  scrim: "rgba(8, 7, 5, .74)"
  chip-edge: "rgba(0, 0, 0, .5)"
typography:
  display:
    fontFamily: "Consolas, 'Cascadia Mono', ui-monospace, 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.2em"
  title:
    fontFamily: "'Segoe UI Variable Text', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "10.5px"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "0.1em"
  heading:
    fontFamily: "'Segoe UI Variable Text', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.015em"
  body:
    fontFamily: "'Segoe UI Variable Text', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  control:
    fontFamily: "'Segoe UI Variable Text', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "normal"
  datum:
    fontFamily: "Consolas, 'Cascadia Mono', ui-monospace, 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "0.01em"
    fontFeature: "tabular-nums"
rounded:
  chip: "2px"
  sheet: "3px"
  panel: "5px"
  pill: "99px"
spacing:
  hair: "3px"
  tight: "6px"
  field: "9px"
  sheet: "11px"
  frame: "14px"
components:
  button-camera:
    backgroundColor: "{colors.camera}"
    textColor: "#ffffff"
    typography: "{typography.control}"
    rounded: "{rounded.sheet}"
    padding: "10px 14px"
    width: "100%"
  button-camera-hover:
    backgroundColor: "{colors.camera-hi}"
    textColor: "#ffffff"
  button-camera-disabled:
    backgroundColor: "{colors.board-2}"
    textColor: "{colors.ink-3}"
  button-default:
    backgroundColor: "{colors.board-3}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.sheet}"
    padding: "10px 14px"
    width: "100%"
  button-default-hover:
    backgroundColor: "#35301f"
    textColor: "{colors.ink}"
  button-mini:
    backgroundColor: "{colors.board-2}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sheet}"
    padding: "4px 9px"
  button-icon:
    backgroundColor: "{colors.board-3}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sheet}"
    height: "32px"
    width: "32px"
  button-side:
    backgroundColor: "{colors.board-1}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sheet}"
    padding: "7px 10px"
  input:
    backgroundColor: "{colors.board-0}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "8px 10px"
    width: "100%"
  input-focus:
    backgroundColor: "{colors.board-1}"
    textColor: "{colors.ink}"
  sheet-tab:
    backgroundColor: "{colors.board-1}"
    textColor: "{colors.ink-3}"
    rounded: "3px 3px 0 0"
    padding: "7px 3px"
  sheet-tab-active:
    backgroundColor: "{colors.board-0}"
    textColor: "{colors.ink}"
  viewer-tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.sheet}"
    padding: "6px 11px"
  viewer-tab-active:
    backgroundColor: "{colors.board-0}"
    textColor: "{colors.ink}"
  ruler-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    typography: "{typography.datum}"
    padding: "5px 9px"
  ruler-button-active:
    backgroundColor: "{colors.board-3}"
    textColor: "{colors.ink}"
  pill:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  pill-active:
    backgroundColor: "{colors.board-2}"
    textColor: "{colors.ink}"
  archive-leaf:
    backgroundColor: "{colors.board-1}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "5px"
  archive-leaf-active:
    backgroundColor: "{colors.board-3}"
    textColor: "{colors.ink}"
  xsheet-frame:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    typography: "{typography.datum}"
    padding: "4px 8px"
    width: "100%"
  xsheet-frame-active:
    backgroundColor: "{colors.mark-dim}"
    textColor: "{colors.ink}"
---

# Design System: SpriteGen

## Overview

**Creative North Star: "La Mesa de Luz"**

A traditional animation light table. The board is dark, worn wood; the glass is the one luminous
field on the page, and everything the user actually judges — a pixel sprite with a transparent
background — sits on it. Everything else is stationery arranged around that glass: sheets hung from
a peg bar, a ruled exposure sheet down the right, an archive bin along the bottom with a labelled
edge per piece. The interface never competes with the artwork for brightness.

The system is dense and instrumental, not spacious. This is a tool kept open for hours with a game
engine on the other monitor: every parameter that matters is visible at once, the machine prints its
own state in the peg bar instead of blocking the app behind a spinner, and no panel hides a number
behind an accordion. Density here is a courtesy, not a compromise.

Materials are flat paper on board: 1px rules, 3px and 5px corners, no gradients, no blur, no glass
or frosted panels anywhere. Depth comes from four steps of board tone and a hairline, not from
shadow. Color is information: four "pencil" hues classify content kinds, one amber marks what is
being pointed at, and one camera red is reserved by law to the act of spending GPU time. The world's
only decorative object is the runic corner sprite pinning the glass — and the user drew it with this
very tool.

**Key Characteristics:**
- One luminous surface (the glass); everything else is dark board.
- Camera red is rationed to the generate action and the progress rail; the finished job turns developer green.
- Pencil amber marks a piece; a view setting deliberately gets no mark.
- Every datum is monospace with tabular figures; every label is uppercase micro-sans.
- Flat by law: 1px rules and tonal layering, no gradients, no blur, no glass.
- Offline by law: system font stacks and inline SVG symbols, never a CDN.
- Motion is one 170ms token, state-carrying only; no entrance choreography.

## Colors

A worn-wood board palette (four near-black browns) carrying warm bone ink, one bright bone-white
glass, four muted colored-pencil hues used as classification, and a single grease-pencil red.

### Primary
- **Camera Red** (`{colors.camera}`): the generate action. It appears on the primary "Generar" buttons of
  every sheet (Generar, Animar, Klein, Terreno, Efectos, the queue) and on the progress rail inside
  the peg-bar job box, while the GPU is working. Nowhere else.
- **Camera Red, lit** (`{colors.camera-hi}`): the hover state and border of the camera buttons only.
- **Developer Green** (`{colors.done}`): the job finished WELL. The job lamp, border and its wash
  (`{colors.done-dim}`) in the `done` state, and the engine-on dot in the machine strip. Red on a
  finished job read as an error (user-reported), so success answers the camera in green; it shares
  the terrain pencil's hue but is its own token, because it codes an outcome, not a piece kind.

### Secondary
- **Pencil Amber** (`{colors.p-animation}`): the mark. It is the active sheet tab's 2px inset rule,
  the current-frame playhead in the exposure sheet, the global focus ring, the caret, the checkbox
  `accent-color`, the favourite star, the hidden-item tools, the help button's active fill, and the
  left rule of a help note. Amber is also the animation pencil in the archive legend, which is why
  it doubles as the mark: what the amber touches is the piece under the needle.
- **Pencil Amber, wash** (`{colors.mark-dim}`): the row fill behind the active frame in the
  exposure sheet.

### Tertiary — the pencil legend
Five hues classify content kind and nothing else. They appear as 7px dots in the archive filter
pills and 6px dots on each archive leaf, and as the left rule of a model note.
- **Sprite Blue** (`{colors.p-sprite}`): still sprites; also the left rule of the engine/model note.
- **Terrain Green** (`{colors.p-terrain}`): terrain sets; also the engine-on dot in the peg bar.
- **Tileset Teal** (`{colors.p-tileset}`): exported tilesets.
- **Model Violet** (`{colors.p-model3d}`): 3D models (GLB).
- (Animation takes Pencil Amber, above.)

### Neutral
- **Board Black** (`{colors.board-0}`): the peg bar, field wells, the archive bin, the body behind an
  open drawer, the pinned Registro — the recessed layer.
- **Board** (`{colors.board-1}`): the page ground, archive leaves, side actions.
- **Board, raised** (`{colors.board-2}`): the sheets column, the exposure sheet, the glass bezel,
  the modal — the paper layer.
- **Board, lifted** (`{colors.board-3}`): default button faces, active leaves, hover fills.
- **Rule** (`{colors.rule}`) and **Rule, bright** (`{colors.rule-2}`): the two hairline weights.
  Every panel, row, field and tab edge is one of these two at 1px. `rule-2` is also the scrollbar
  thumb and the peg holes' rim.
- **Ink** (`{colors.ink}`), **Ink-2** (`{colors.ink-2}`), **Ink-3** (`{colors.ink-3}`): the three
  text weights — read now, read next, read if you look. Labels sit at Ink-2, secondary data and
  placeholders at Ink-3.
- **Glass** (`{colors.glass}`) / **Glass-2** (`{colors.glass-2}`): the two tones of the lit checker.
- **Glass Ink** (`{colors.glass-ink}`): type placed on the lit glass (the empty state).
- **Glass Off** (`{colors.glass-off}`) / **Glass Off-2** (`{colors.glass-off-2}`): the dark checker
  the `Luz` toggle swaps in, for judging a sprite against a map ground.

### Named Rules

**The Camera Note Rule.** Camera red belongs to what puts the GPU to work and nothing else: the
`.btn.camera` primaries and the job progress fill while a job runs. A destructive action, an error,
a badge, a chart or a highlight may never borrow it. A FINISHED job leaves the red behind: the done
state is developer green (`{colors.done}`), because red-at-rest reads as failure. Audit test: if a
red element does not either start GPU work or show GPU work in progress, it is wrong.

**The Pencil Mark Rule.** Amber marks *what points at a piece* — the active sheet, the current
frame, the focused control, the favourited or hidden item. A **view setting** does not take the
mark: the scale ruler (Ajustar/×1/×2/×4/×6) and the archive filter pills mark their selection with a
neutral raised fill and a brighter hairline instead. The one deliberate exception is the global
reveal switch (`#btnReveal.on`), which takes a full amber fill on a dark label, because leaving
hidden content revealed has consequences and must be loud.

**The Struck Take Rule.** Destruction carries no ink at all. Delete reads as a cancelled take: on
hover the label gets a 1px `line-through` in Ink-2 over a neutral 135° hazard hatch
(`rgba(255,255,255,.05)` stripes on the lifted board), and a confirm dialog naming the consequence
backs it. Never color a destructive control.

**The One Lit Field Rule.** The glass is the brightest thing on the page and stays that way. No
other surface may be lighter than Board-3 at rest.

## Typography

**Display Font:** the mono stack (Consolas / Cascadia Mono / ui-monospace / SF Mono / Menlo /
DejaVu Sans Mono)
**Body Font:** the sans stack (Segoe UI Variable Text / Segoe UI / system-ui / -apple-system /
Helvetica Neue / Arial)
**Label/Data Font:** the same mono stack, always with `font-variant-numeric: tabular-nums`

**Character:** two typefaces, both resident on the machine, doing two jobs with no overlap: the sans
speaks (labels, help text, prose), the mono counts (every number, size, seed, frame index, spec
line, clock and count). The pairing reads as a shop form filled out on a typewriter over a printed
sheet. No webfont is loaded and none may be: the app must run with the network off.

### Hierarchy
- **Display / wordmark** (mono, 700, 14px/1, 0.2em tracking, uppercase): the title block in the peg
  bar, over a second mono line at 8.5px/0.16em that prints the real archive count. This title block
  is the page's only display moment and there is exactly one of it.
- **Title** (sans, 500, 10.5px, 0.1–0.14em tracking, uppercase, Ink-2): sheet heads, panel heads,
  field labels, the archive head. The Registro tightens to 10px/0.08em.
- **Heading** (sans, 600, 15px, 0.01–0.02em): the two headings that are not labels — the glass
  empty state and the modal head. One step above body, well below the wordmark; it is the only
  sans size above 13.5px in the system.
- **Body** (sans, 400, 13.5px/1.5, Ink): the page default. Field prose and notes drop to 12–13px;
  the glass empty state runs 13px/1.65 capped at 46ch.
- **Control** (sans, 500, 13px/1.2): buttons. Minis and tabs step down to 11–12px; the camera
  primary is the only 600.
- **Datum** (mono, 400, 10–12px, tabular figures): the spec line under the glass, exposure-sheet
  values, frame rows, archive leaf meta, the job clock, the scale ruler, and the numeric inputs
  (`input[type=number]` and the seed field switch to mono in place).

### Named Rules

**The Tabular Datum Rule.** Anything a person compares between two rows — a size, a seed, a frame
index, a count, a duration — is set in the mono with `font-variant-numeric: tabular-nums`. A number
set in the sans is a mistake.

**The Single Voice Rule.** There is one display element on the page: the peg-bar title block. New
surfaces take their titles from the uppercase micro-sans Title role, never from a second large face.

**The English Prompt Hint Rule.** The interface is Spanish; generation prompts are English. Every
field that takes an English prompt labels it with an inline `(en inglés)` hint in the lowercase,
untracked `.hint` treatment — never by translating the label.

## Layout

The page is a fixed workshop, not a scrolling document: `body` is `height: 100vh; overflow: hidden`
with a three-row grid — the peg bar (50px), the desk (`minmax(0,1fr)`), and the archive bin.

**The desk** is a three-column grid at 14px gap and 14px padding: the sheets column at a fixed
**352px**, the glass at `minmax(0,1fr)`, and the exposure sheet at a fixed **296px** (42px when
collapsed to its spine).

**The sheets column** is itself `grid-template-rows: minmax(0,1fr) auto auto`. Only the daily sheets
(Generar, Animar) scroll; the rare-tab drawer (a 4-column tab strip that costs no height when
folded) and the **Registro** are pinned to the foot. The Registro is a 4-column grid holding six
numeric parameters permanently in view — a hard user requirement, not a convenience.

**Spacing rhythm** is small and consistent: 3px between adjacent chips, 6px between rows, 9–11px
between fields and stacked controls, 14px for panel padding and the desk gap. Panel interiors run
9–14px; nothing on the desk is padded above 14px except the glass stage (26px, so the runic corners
never crop the art).

**Responsive is structural, not fluid.** Four steps, each collapsing one thing:
- **≤1500px**: the sheets column narrows to 330px, the exposure sheet to 268px.
- **≤1400px**: the peg-bar tagline drops.
- **≤1240px**: the desk becomes a single column and the page starts scrolling
  (`overflow: auto; height: auto`), inner scrollers release, the glass takes `min-height: 62vh`, the
  archive bin grows to a 260px cap, and the peg bar stacks into one column at auto height.
- **≤720px**: the runic corners shrink from 104px to 68px, the Registro halves to 2 columns, the
  glass bezel stacks its three zones, and the spec line left-aligns and wraps.

The archive bin is a `repeat(auto-fill, minmax(304px, 1fr))` grid of labelled leaves in a fixed
172px band, foldable to its head. The column floor is set by the longest engine label in the
catalogue, so the meta line never truncates.

### Named Rules

**The Never-Cover Rule.** Work in progress is printed in the peg bar — lamp, text, clock, progress
rail — and never as an overlay. Nothing may block the application while the machine runs; a job can
last thirty minutes and the user must keep working through it.

**The Fold, Don't Shrink Rule.** Under pressure the table folds a panel away (the drawer, the
exposure-sheet spine, the archive) rather than compressing type or the six pinned numbers.

## Elevation & Depth

**This system has no elevation.** Depth is tonal: four board tones (`board-0` recessed → `board-3`
lifted) plus two hairline weights carry every plane relationship on the desk. There are no ambient
shadows, no gradients, no blur, no backdrop-filter and no translucent panels anywhere in the shipped
stylesheet.

Four shadows exist, and each is a physical claim about an object rather than a UI depth cue:

### Shadow Vocabulary
- **Peg hole** (`box-shadow: inset 0 1px 1px rgba(0,0,0,.8)`): the drilled register holes in the
  peg bar. Inset only.
- **Sheet on glass** (`box-shadow: 0 0 0 1px rgba(0,0,0,.5), 0 18px 40px -18px rgba(0,0,0,.8)`):
  the one lifted object on the page — the lit glass sits above the board.
- **Camera key bevel** (`box-shadow: 0 1px 0 rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.18)`):
  a 1px seated bevel on the camera primaries only. It is a key you press, not a floating card.
- **Modal** (`box-shadow: 0 28px 60px -20px rgba(0,0,0,.9)`) over a `rgba(8,7,5,.74)` shade: the
  only true overlay in the system, and it never runs during a job.
- **Palette chip edge** (`border: 1px solid rgba(0,0,0,.5)` +
  `box-shadow: inset 0 0 0 1px rgba(255,255,255,.12)`): a dark rim and a light inner rim so a
  swatch of any hue reads as a chip against both the board and its own colour.

Marks that would read as elevation elsewhere are inset rules here: the active sheet tab is
`inset 0 2px 0` amber, the active frame row is `inset 2px 0 0` amber, the active ruler step is
`inset 0 0 0 1px` in the bright rule tone.

### Named Rules

**The Flat Board Rule.** New surfaces are separated by a board tone step and a 1px rule. Reaching
for a drop shadow, a gradient or a blur to separate two panels is out of world.

## Shapes

Paper corners, not pills. Three radii carry the whole page: **3px** (`{rounded.sheet}`) for sheets,
buttons, fields, tabs and leaves; **5px** (`{rounded.panel}`) for the large panels — the sheets
column, the glass, the bezel, the exposure sheet, the modal; and **2px** (`{rounded.chip}`) for
small chips — the title block, palette swatches, archive thumbnails, leaf tools. The only fully
round shapes are genuinely round objects: peg holes, status dots, pencil dots, the help button, the
progress rail cap, and the archive filter pills (`99px`), the single flat-pill exception, which read
as legend chips.

Borders are always exactly 1px, in `{colors.rule}` at rest and `{colors.rule-2}` when raised, active
or hovered. Two border *styles* carry meaning: **dashed** marks unavailable or veiled — a disabled
button, and a hidden archive leaf (also at `.5` opacity) — and the 135° hatch marks a struck take.

Icons are a single inline SVG symbol sheet defined once at the top of the document and referenced
with `<use href="#i-…">`: 24-unit viewBox, `fill: none`, `stroke: currentColor`, uniform
`stroke-width: 2`, square linecaps. Sizes are 16px (`.ic`), 12px (`.ic-xs`) and 44px (`.ic-big`).
No icon font, no icon package, no external request.

Motion is one token: `--t: 170ms cubic-bezier(.22,1,.36,1)`, applied only to color, background,
border and small transform state changes. The single documented exception is the progress fill's
`transform 300ms linear`, which must read as elapsed time rather than as an eased UI flourish. The
only keyframe animation is `pulse` (1.6s opacity) on the running job lamp. A
`prefers-reduced-motion: reduce` block neutralizes all of it.

### Named Rules

**The Paper Corner Rule.** A sheet's corner is not round: 3px on small things, 5px on panels, 2px on
chips. Nothing between 6px and 98px exists in this system.

**The One Transition Rule.** State changes use `--t` and nothing else. There is no entrance
choreography, no stagger and no scroll animation; an element that moves is answering an input.

## Components

### Buttons
- **Shape:** paper corner (3px), 1px border, no radius above 5px anywhere.
- **Primary (camera):** camera red fill, `camera-hi` border, white 600 label, 10px/14px padding,
  full width, with the 1px seated bevel. Reserved to the five generate actions and the queue run.
- **Default:** lifted board (`board-3`) with a bright hairline; hover lightens the face to `#35301f`
  and the border to `#6b5e46`; `:active` presses 1px down (`translateY(1px)`).
- **Disabled:** recessed board, Ink-3 label, and a **dashed** border — the control is on the sheet
  but not available.
- **Mini:** 11.5px chip button for peg-bar and archive controls, raised board on hover; its `.on`
  state is a neutral raised fill, *except* the reveal switch, which takes the amber fill.
- **Icon:** 32×32, grid-centred 16px symbol, Ink-2 → Ink on hover.
- **Side (exposure sheet):** left-aligned 12.5px rows at the foot of the panel; the favourite and
  hidden states turn label and border amber; the delete row is the struck take.

### Chips
- **Archive filter pills:** transparent, 1px rule, 99px, Ink-3, each carrying its 7px pencil dot.
  Selected takes a raised board fill and a brighter hairline — deliberately no amber, because a
  filter is a view setting.
- **Palette swatches:** 15px, 2px corner, dark 1px border with a `rgba(255,255,255,.12)` inner
  hairline so a near-black swatch still reads.

### Cards / Containers
- **Panels** (sheets column, glass bezel, exposure sheet, modal): raised board (`board-2`), 1px
  `rule`, 5px corner, heads on recessed board closed with a bottom hairline.
- **Archive leaf:** 56px checkered thumbnail plus a two-line labelled edge (name in sans, meta in
  mono with its pencil dot: the piece's size and the model that made it — never its seed, which
  belongs to the exposure sheet). Hover lifts 1px and brightens; active takes the lifted board and an
  Ink-3 border; hidden goes half-opacity and dashed with its tools forced visible. Per-leaf tools
  live in a 19px cluster at the top-right that fades in on hover or focus-within.

### Inputs / Fields
- **Style:** recessed board well, 1px `rule`, 3px corner, 8px/10px padding, 13px sans; numeric and
  seed fields switch to the mono with tabular figures in place.
- **Focus:** the border goes amber, the well lifts one tone to `board-1`, and the caret is amber.
  The native outline is suppressed there because the border carries the state; everywhere else,
  `:focus-visible` draws a 2px amber outline at 2px offset.
- **Checkbox:** native, with `accent-color` set to amber.
- **Field label:** uppercase micro-sans with an optional lowercase `.hint`, and a 15px round `?`
  button pushed to the right edge.

### Navigation
There is no site nav; navigation is three tab systems, each shaped for what it selects:
- **Sheet tabs (rare drawer):** a 4-across strip of folder tabs seated on the drawer body, square at
  the bottom and 3px-rounded on top. Active takes the recessed board and the amber inset rule. When
  the drawer is folded the strip closes its bottom edge and the active tab drops its mark entirely —
  a folded drawer has no current sheet.
- **Viewer tabs (glass bezel):** borderless 12px sans; active takes the recessed board plus a bright
  hairline. They select which rendition is on the glass (Sprite / Original IA / Hoja / Vídeo).
- **Scale ruler:** a segmented mono control in one bordered well with 1px dividers — `Ajustar ×1 ×2
  ×4 ×6`. Active is the neutral raised treatment; a view setting takes no mark.

### The Exposure Sheet
The right column is a ruled form: a `dt`/`dd` row per datum, hairline-separated, the label in Ink-3
sans at 0.04em and the value right-aligned in tabular mono. Clickable rows turn their value amber on
hover. Below sits the prompt box (recessed well, 12px/1.6, capped at 132px and squeezed to 60px in
frame mode), then the frame table, then the side actions pinned to the bottom with
`margin-top: auto`.

### The Light Table (signature)
The glass is a `repeating-conic-gradient` **26px two-tone checker**, not a flat field, because every
sprite is a PNG with transparency and the checker is the only honest ground. A `Luz` toggle swaps
the lit checker for the dark pair to judge a sprite against a map ground; the toggle marks itself
when the light is *off*, since lit is the resting state. Four copies of the runic corner sprite pin
the sheet at 104px, overhanging the frame by 13–15px, as register pieces. All artwork on the glass
is `image-rendering: pixelated`.

### The Frame Viewer (signature)
Stepping through an animation slices the **existing sprite sheet** in the browser — no extra server
request. The slice element sets `background-size: n*100% 100%` and
`background-position: (i/(n-1))*100% 0`; percentage positioning lands exactly on frame *i* where
rounded pixel offsets accumulate error and bleed the neighbouring frame. Two onion-skin ghosts of
the previous frames stack in the same grid cell beneath the current one at **opacity .34 /
grayscale(.5)** and **opacity .16 / grayscale(.8)** — acetates on a light table. Arrow keys step the
frame; the exposure sheet's frame table scrolls its active row into view, filling it with the amber
wash and a 2px amber playhead on its left edge. The mode is offered only for sheet animations of
2–48 frames, where a single horizontal strip is a sane thing to slice.

### The Job Box (signature)
The machine's state is printed in the peg bar in four states: `idle` (grey lamp, "En reposo"), `run`
(amber lamp pulsing at 1.6s, brightened text, a 128×4px rail whose camera-red fill scales
horizontally over 300ms linear), `done` (developer-green lamp, border and wash — it stays lit
until acknowledged), and `fail` (Ink-3 lamp, neutral border). It occupies the middle column of the
peg bar and never expands into an overlay.

### The Help Affordance
Every control carries a long Spanish explanation in a `data-help` attribute. `wireHelp()` generates,
for each one, a keyboard-reachable 15px round `?` button (`aria-expanded`, `aria-label`) that
toggles an inline note set 12px/1.5 in Ink-2 behind a 1px amber left rule, and mirrors the same text
into `title` for hover. On a checkbox the `?` is lifted out of the label into a sibling row, because
inside it a click would toggle the box.

### Browser Chrome
The surfaces the app does not draw are themed too, and count as part of the system: `color-scheme:
dark`, `::selection` in amber at .30 (re-themed to .34 over dark ink inside the glass and bezel),
`scrollbar-color` thin in the bright rule tone with an 11px webkit thumb inset by a 3px transparent
border, amber `caret-color` and `accent-color`, and the global amber `:focus-visible` ring.

## Do's and Don'ts

### Do:
- **Do** reserve camera red (`{colors.camera}`) for what puts the GPU to work: the generate buttons
  and the progress rail while a job runs; a finished job answers in developer green (`{colors.done}`).
- **Do** use pencil amber (`{colors.p-animation}`) to mark what points at a piece — active sheet,
  current frame, focus, caret, favourite, hidden — and give view settings (scale, filters) a neutral
  raised fill instead.
- **Do** set every comparable number in the mono stack with `font-variant-numeric: tabular-nums`.
- **Do** separate planes with a board tone step plus a 1px rule (`{colors.rule}` at rest,
  `{colors.rule-2}` when raised or active).
- **Do** print long-running work in the peg bar and let the user keep working.
- **Do** ship icons as inline SVG symbols on the shared 24-unit, `stroke-width: 2`, square-cap
  sheet, referenced with `<use>`.
- **Do** keep the checker under any transparent artwork, and offer the dark checker for judging
  against a dark ground.
- **Do** show a destructive action as a struck take — line-through plus the 135° hatch — behind a
  confirm dialog that names the consequence.
- **Do** give every new control a `data-help` explanation in Spanish so `wireHelp()` can generate
  its `?` and its inline note; label English-prompt fields with the `(en inglés)` hint.
- **Do** bump the `?v=YYYYMMDDx` query on `style.css` and `app.js` in `index.html` by hand whenever
  either changes — the server runs without `--reload` and this is the only cache break.
- **Do** route all motion through `--t`, and keep the reduced-motion block intact.
- **Do** carry the runic corner sprite (`app/static/esquina.png`) as the glass's register pieces; it
  was authored by the user with SpriteGen itself and is the only shipping raster.

### Don't:
- **Don't** put camera red on anything that is not GPU work — not on delete, not on errors, not on
  badges, not on a chart.
- **Don't** mark a view setting with amber. The exception is documented and singular:
  `#btnReveal.on` takes the amber fill because revealed hidden content must be loud.
- **Don't** color destruction. It is struck, hatched and confirmed, never red.
- **Don't** load a font, an icon set or a library from a CDN, or add a build step. The app must run
  with the network off; use the two system stacks and the inline symbol sheet.
- **Don't** introduce gradients, blur, backdrop-filter, translucent panels or ambient drop shadows.
  The four shadows in the system are physical claims (peg hole, sheet on glass, key bevel, modal).
- **Don't** cover the application with an overlay while a job runs. The modal is for input only.
- **Don't** add a second display face or a second large type moment; the peg-bar title block is the
  only one.
- **Don't** use a radius between 6px and 98px, or a border thicker than 1px.
- **Don't** position a sprite-sheet frame with rounded pixel offsets; use the percentage formula, or
  the neighbouring frame bleeds in.
- **Don't** solve narrow viewports by shrinking type or the six pinned Registro numbers — fold a
  panel instead.
- **Don't** let any surface outshine the glass.
