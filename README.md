# Oubliette Table

A non-commercial, open-source AI-DM text RPG built on the D&D SRD. The thesis:
**code owns state and the rules; the LLM only narrates and proposes; the player
never holds the pen.** See [`oubliette-table-spec-v0.2.md`](docs/design/oubliette-table-spec-v0.2.md)
for the full design (and [`oubliette-table-design-v0.1.md`](docs/design/oubliette-table-design-v0.1.md)
for the original rationale).

## Status: Phase 4 — web chat UI (on Phase 0–3)

**Play in your browser:** install the web deps once (`pip install -e ".[web]"`),
then run `oubliette-play` (or double-click `play.bat` on Windows). A chat window
opens: talk to the DM on the left, watch the live character sheet, inventory, and
canon on the right. It uses the real model when `ANTHROPIC_API_KEY` is set (env or
`.env`), else the scripted offline DM.

## Earlier phases

Per spec §14, we build *through the seams* so later phases are substitutions, not
rewrites. Everything runs with a **scripted (offline) DM** — no API key required.

- **Phase 0** (tag `phase-0`): the core non-combat loop end to end.
- **Phase 1** (tag `phase-1`): the combat *boundary* (§8) — declarative
  `EncounterRequest` in, instantiation from live state + templates (ephemeral
  combatants, D5), a `CombatResult` with absolute values (D7) out, applied as one
  recorded result; non-combat exits (parley/flee) first-class. Engine internals
  are a placeholder the real tactical prototype slots in behind later.
- **Phase 2** (tag `phase-2`): the **event log** is now real. Authoritative state
  is rebuilt by `seed(authored baseline) + replay(events)`; every protected
  mutation decomposes into atomic, replayable `StateOp`s applied through one path
  (live + replay); the RNG emits `ROLL` events (recorded, never re-rolled); the
  log persists to **SQLite**. Reload is byte-identical for authoritative state
  (D9). Run with `--db PATH` to persist and reload.
- **Phase 2.5/2.6** (tags `phase-2.5`, `phase-2.6`): harness ergonomics validated
  against the live model — typed tool schemas, state/scene context, combat-summon
  prompt, item-id resolution, and short-term turn continuity.
- **Phase 3** (tag `phase-3`): the **canonization lifecycle** + **retrieval**. The
  DM creates world content with `create_entity` (born `provisional`) and confirms
  it with `promote_canon`; canon is event-sourced and rebuilds byte-identically on
  replay; keyword retrieval feeds relevant canon back into context so the DM stays
  consistent (its long-term memory). Verified live: the model named an NPC, then
  reused it by retrieval instead of duplicating.
- **Phase 4** (tag `phase-4`): the **web chat UI** above (FastAPI + a
  self-contained page, no build step) — narration, roll/effect/combat chips, and
  the live sheet/inventory/canon, all in the browser.
- **Phase 5** (tag `phase-5`): the **trade window** (§9) — ask a merchant to see
  their wares and an in-window popup opens showing their priced stock and gold
  (which caps what they'll pay). Buying/selling are ordinary code-validated
  `transact`s at merchant-set prices, so the firewall holds for free. Verified
  live: the model summons the window on a browse request.
- **Phase 6** (tag `phase-6`): **streaming + UI polish**. The DM's narration now
  streams token-by-token over SSE (the `narration` field is pulled out of the
  partial structured-output JSON as it generates), with a blinking cursor,
  markdown (bold/italic/paragraphs), and message fade-ins.
- **Phase 7** (tag `phase-7`): **trade basket + haggle**. The trade window now has
  quantity steppers on both sides and a running net total; **Settle** executes the
  whole basket as one validated transact at listed prices, while **Haggle** sends
  the selection to the DM as a chat proposal — it rolls persuasion/deception and
  settles at an *adjusted* price (the soft economy, §8/§11, wired to the window).
  The merchant's priced stock is now in the DM's context too, so it can negotiate.
- **Phase 8** (tag `phase-8`): a **player menu** (extensible registry — add an entry
  to `MENU_ITEMS`) and the first item, a **player journal**: modular sections with
  status-grouped entries (e.g. Quests → In-Progress / Completed) and markdown notes.
  The journal is **deliberately invisible to the DM** — stored in its own table,
  never read into context — so player notes can't induce hallucination or bloat the
  prompt. (Bestiary & Party Sheets are stubbed "soon" menu slots; **Map** is now live —
  see below.)
- **Phase 9** (tag `phase-9`): the **Inventory panel**. Moved off the sidebar into a
  menu panel: a section per party member, items grouped into Weapons / Armor (with
  AC) / Gear / Consumables / Other, plus an **Equipped** section with equip/unequip
  toggles. Loadout changes are event-sourced (an `equip` op) so they persist and
  replay. (Total-AC-from-equipment is deferred to the rules pass.)
- **Phase 10** (tag `phase-10`): the **world map**, both halves, as pins on
  assignable map art. In **The Forge**, the map editor lets you assign a **world map
  image** (e.g. Atria) and a **sub-map image** per top-level area, then drag each place
  as a **pin** onto it (hover shows name + description); double-click a ★ area to arrange
  the places inside it (two levels — no grandchildren). Pins store a `position` as a
  percentage of the map image, so they stay aligned across screen sizes; `world_map`
  (manifest) + `map_image`/`position` (places) persist via the normal save. In the
  **game**, the Map menu opens those pins on the same art: hover a pin for its name +
  description, double-click a discovered area to open its sub-map, breadcrumb back out.
  Identities are **earned by visiting** — an area the party hasn't reached is just an
  *Unknown* pin (no name, description, or contents) until they travel there. Redaction is
  server-side in `/api/map`, so unvisited content never reaches the browser; DM-invented
  locations simply don't appear (you can only `travel` to authored places). Fits the
  DM-driven, location-to-location travel model (no free roam).
- **Phase 11 — the Soundscape** (S1–S5; see [`oubliette-audio-mixer-v0.1.md`](docs/design/oubliette-audio-mixer-v0.1.md)):
  a **location-driven ambient audio mixer**, derived from state — the LLM never plays a
  sound. Looping **beds** + sparse randomized **one-shots**, each tagged music/sfx, riding
  the place tree (a top-level **theme passes down** into its children) and conditioned on
  **time-of-day & weather**, which are now **engine state the DM reports** each turn
  (`ENVIRONMENT_CHANGED`, replay-safe). The browser mixer (Web Audio) crossfades on travel
  behind a one-time "enable sound" gate, with Music/SFX volume sliders; the Scene card shows
  the live `☀️ Day · Clear`. Authored in **The Forge** (a per-place Soundscape editor; sounds
  copied into the pack, portable like art) with a missing-file warning, and a game "↻ Reload
  world" button that picks up Forge edits mid-session. (S6 — the actual weather/night sounds
  + feel-tuning — is the remaining, mostly-authoring step.)

## Quickstart

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     # POSIX: source .venv/bin/activate
pip install -e ".[dev]"

pytest                                   # full acceptance suite (incl. front-end API)
oubliette-play                           # ← the browser chat UI (pip install -e ".[web]")
python -m oubliette.app.repl --script --scripted   # the §14.1 non-combat transcript
python -m oubliette.app.repl --combat --scripted   # the Phase 1 combat-boundary demo
python -m oubliette.app.repl --canon --scripted    # the Phase 3 canonization demo
python -m oubliette.app.repl --scripted --db save.sqlite   # persist; re-run to reload+replay
python -m oubliette.app.repl             # interactive REPL — uses the REAL model when
                                         # ANTHROPIC_API_KEY is set (in env or a .env file);
                                         # no extra deps, the adapter uses the stdlib
```

## The acceptance transcript (definition of "done" for Phase 0)

1. *"I look around the market."* → narration only; no roll, no state change.
2. *"…these worn boots are priceless dwarven heirlooms."* → a real `skill_check.deception`
   d20 roll is logged; the DM sets the DC, code supplies the sheet bonus.
3. *"Sold."* → a `transact` fires; gold and the boots move on **both** sides.
4. *"I now have 10,000 gold."* → routed `denied`; no tool fires; gold unchanged.

## Layout (mirrors spec §2)

| Package | Job |
|---|---|
| `state/` | authoritative state; the only writer of protected fields (the firewall) |
| `rules/` | pure SRD functions (ability mods, checks); no I/O |
| `record/` | the event log (`events.py` ops/replay, `store.py` SQLite/in-memory), the seeded RNG (emits ROLL events), + a non-replayed debug log |
| `runtime/session.py` | session lifecycle: durable store + materialized state, kept in sync via seed-then-replay |
| `llm/` | the `LLMClient` seam; `scripted` (offline double) + `anthropic` (real) adapters |
| `schemas.py` | typed structured-output contracts (Intent, assessment, resolution, tool calls) |
| `tools/` | the tool surface — the only doors into protected state |
| `combat/` | the combat boundary: `EncounterRequest` → placeholder engine → `CombatResult` |
| `canon/` | the canonization lifecycle: `CanonRecord`s + the canon store with keyword retrieval |
| `trade/` | the trade window (summoned tool): bounded merchant view + buy/sell as validated transacts |
| `journal/` | the player journal store (SQLite) — player-owned notes, never read into the DM context |
| `dm/` | the DM brain (assess + resolve) and the per-turn `context` builder (state/scene/canon/recent) |
| `runtime/` | the turn loop: assess → (combat \| roll → resolve) → apply → render |
| `app/` | the web server (`server.py` + `static/index.html`) and the terminal REPL |

## What this does NOT do yet

The *tactical* combat internals (only the boundary + an auto-resolve placeholder
exist) and streaming responses are still to come. Canon quarantine is modeled
(provisional vs confirmed) but quest-dependency auto-promotion isn't wired yet.
Also note: RNG *state* isn't persisted across reload (past rolls
are in the log; post-reload rolls restart from the base seed) — fine for
single-player and it doesn't affect the byte-identical-**state** guarantee, since
state 