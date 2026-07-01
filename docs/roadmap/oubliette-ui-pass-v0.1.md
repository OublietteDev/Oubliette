# The UI Pass — all three apps (v0.1)

*Drafted 2026-07-01 from a three-agent code audit (one per app) plus a visual
walkthrough of the two web apps. Scope per OublietteDev: the polish pass covers the
**Arena** (pygame), the **Forge** (world builder), and the **Oubliette table**
(player app). The playtest snapshot is frozen at commit `84644a7` — this arc's
work will NOT reach the playtester, so we can be bolder than a spot-fix pass.*

---

## The one-sentence verdict per app

- **Oubliette table** — already the house style done right: real CSS tokens,
  serif/sans hierarchy, gold-on-dark. Needs a *tightening* pass, not a redesign.
- **Forge** — same palette, same fonts, genuinely consistent at a glance (the
  Atria map editor is a highlight). Its debt is **UX**, not looks: monster
  forms with 9 stacked sections, validation that only speaks at the footer,
  nested editors with no breadcrumb home.
- **Arena** — the good news: it is NOT structurally rotten. Colors are already
  centralized (`arena/util/constants.py` COLORS), panels/popups are separated,
  assets have graceful fallbacks. The hideousness is **surface debt**: magic
  pixel numbers in 15+ files, no typography scale, nine popups each inventing
  their own layout, procedurally-drawn icons, and a bare-rectangles look that
  never got an art pass. A facelift is very tractable.

**The unifying idea: one "house style" — the Phantom's dark-wood-and-gold
table — expressed three times.** The web apps already share it by copy-paste;
the Arena approximates it by accident (warm dark wood + parchment + gold).
The pass makes it deliberate everywhere.

---

## Stage 1 — Shared design tokens (web apps) · small

Both web UIs are single-file HTML with an identical hand-copied `:root`
palette. They will drift (label colors already have: Forge labels are muted,
main-app labels are gold; buttons are `.btn` there and `.act` here; two
different error reds; H2 is 18px vs 20px).

- Extract ONE canonical token block (colors + spacing scale + font stack +
  button/overlay/modal recipes). Simplest honest mechanism given the
  no-build-step constraint: a `tokens.css` served by both apps, or a shared
  fragment both servers inline at render time. Decide by effort; either kills
  drift.
- Reconcile the known divergences (labels → gold, one error red `--bad-soft`,
  one modal header size, alias `.btn`/`.act`).
- Adopt the Forge's `.toast` in the main app (it has no transient feedback).

## Stage 2 — Oubliette table tightening · small-medium

From the audit, in priority order:

1. **Pending-bar collision** (new since today: combat-bar + wrap-bar +
   rest-bar can all exist): show ONE at a time, priority combat > wrap > rest;
   wrap/rest get a dismiss ✕.
2. **System-message readability**: muted italic on transparent is the worst
   contrast in the app — give it a subtle panel background.
3. **Mobile/narrow floor**: one breakpoint that stacks the 320px sidebar (or
   tucks it behind a toggle); stack chargen rows under 480px; `max-height` +
   scroll on all modals.
4. **Focus/locked states**: visible `:focus` outlines on buttons; dim the
   composer visibly when a pending bar locks it.
5. Token cleanups from Stage 1 land here for free (button gradient variable,
   standard disabled opacity).

## Stage 3 — Forge UX pass · medium

Looks fine; *feels* like a spreadsheet in places. In priority order:

1. **Creature editor → tabs** (Core / Abilities / Combat / Defenses / Loot) —
   the chargen wizard's party-tabs pattern already in the file is the
   template. Biggest single UX win in the Forge.
2. **Per-field validation**: required-field marks + errors next to the field
   they belong to (today: one line at the modal footer after you hit Save).
3. **Soundscape sub-editor**: pull the 60-line inherited-cues block out of the
   place form into its own drawer/modal (the attacks editor is the precedent).
4. **Nested-editor breadcrumbs**: "editing as part of NPC: {name}" banner when
   the creature editor or chargen wizard is opened from an NPC — the map
   drill-in crumbs are the in-file precedent.
5. Defer: undo/redo (structural), browser-history routing (not worth it).

## Stage 4 — The Arena facelift · the big one

Two sub-phases, deliberately ordered so the foundation makes the beauty cheap:

**4a. Foundation (mechanical, low-risk):**
- `LAYOUT` dict beside `COLORS` — every magic number (panel widths, popup
  sizes, offsets) gets a name in one place.
- Typography scale (`FONT_SIZES = {heading, body, small, ...}`) — one place to
  change the all-caps MedievalSharp-everywhere problem (keep it for headings,
  pick a readable body font for logs/popups).
- **Unified Popup base class** — nine popups currently each reinvent
  positioning/sizing/buttons; one base with a shared background, button style,
  and bounds-checking. Add the **modal overlay** while there (today you can
  click the grid behind a popup — a real playtest confusion source).
- Semantic color aliases (hp-bar colors decoupled from team colors; popup
  background into COLORS; the log's hardcoded inverted palette made
  theme-aware).

**4b. Beauty (what OublietteDev will actually see):**
- **Panels**: lean into the existing tray art (parchment/leather trays exist
  and load!) — consistent framing, padding rhythm, header treatment.
- **Tokens**: HP numbers on large tokens; team-tinted fallback discs instead
  of black; per-creature phase on the turn glow; smooth condition-icon
  scaling.
- **Icons**: replace procedural radial-menu icons with small PNG sprites
  (there's already an unused `assets/ui/buttons/` folder).
- **Action bar & radial menu**: category-distinct button styling, keyboard
  hints, hover feedback everywhere.
- **Combat log**: creature-name coloring, event icons, optional round
  timestamps.
- **Animation backlog** (from the standing memory): Charge/Pounce needs its
  own run-in/impact animation so it reads differently from a normal swing;
  animation *composition* (move→cast→projectile→impact as a sequenced state
  machine) is the structural enabler — schedule it here if we want cinematic
  feel, or defer it and do only the Charge anim ad-hoc.
- Screenshot-driven: run the C6 lab .bats and iterate against real fights.

## Stage 5 — v1.0 freeze riders

Already-known freeze work rides this arc (per the standing plan): Arena
subprocess self-dispatch + asset-path hygiene. The audit adds two cheap ones:
startup asset validation (warn on missing fonts/trays instead of failing at
first use), and a freeze note documenting the 1280×720 layout assumption.

---

## Decisions for OublietteDev (the forks that shape the arc)

1. **How deep does the Arena beauty pass go?** (a) Facelift only — 4a + the
   cheap 4b items, no animation composition; (b) Full pass — including the
   animation state machine that unlocks Charge/Pounce and cinematic
   sequencing. (b) is the "BIG visual/UX overhaul" the memory says you want
   eventually; this arc is the natural home for it, but it's the single
   biggest line item.
2. **Resolution independence now or later?** The Arena assumes 1280×720.
   Freezing that into v1.0 is fine (it scales up OK); making it truly
   responsive is ~a full day and can wait for v1.1. Recommend: freeze + note.
3. **Does the player app need real mobile support**, or is the narrow-window
   breakpoint enough? The playtester is presumably on desktop; recommend
   breakpoint-only for now.
4. **Build order.** Recommended: 1 → 2 → 3 → 4 → 5, cheap-to-expensive, so the
   web apps' shared tokens are settled before the Arena eats the calendar.
   Reversible if you'd rather see the Arena transform first.

## What this pass is NOT

- No mechanics changes anywhere (Arena mechanics are frozen-by-decision).
- No framework/build-step adoption for the web apps — single-file HTML is a
  deliberate, working constraint.
- No accessibility deep-dive (WCAG audit) — we take the free wins (contrast,
  focus states) and move on.
