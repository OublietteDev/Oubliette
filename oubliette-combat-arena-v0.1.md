# The Arena — Combat Integration Design Doc v0.1

**Status:** DRAFT for OublietteDev's review. Started 2026-06-09.
**Arc:** Combat — the last of the "big three" (see `oubliette-endgame-roadmap`).
**Companion memory:** `oubliette-combat-arc`.

---

## 1. Intent

Oubliette's combat seam has always been a placeholder: the DM senses violence,
emits an `EncounterRequest`, and a dumb auto-resolve loop (`combat/engine.py
auto_resolve`) trades blows until someone drops. We are replacing that placeholder
with **The Arena** — OublietteDev's mature, standalone tactical 5e combat simulator
(~45k LOC, 93 test files, pygame + pydantic; formerly `dnd_combat_sim`).

When a fight breaks out mid-story, the player clicks **"Enter the Arena,"** plays the
fight out on a hex grid (tokens, initiative, full action economy, AI-controlled
enemies), and the **outcome flows back into the browser story**. Combat is an app,
not prose — the long-stated vision.

## 2. Why this is far cheaper than it looks

Two findings from reading the old project change the cost ceiling:

1. **The combat engine is GUI-free.** The entire `src/combat/` package (12k LOC of
   real 5e rules — initiative, action economy, damage, conditions, concentration,
   death saves, reactions, legendary/lair actions) imports **zero pygame** (verified
   by grep). The 27k-LOC pygame GUI sits *on top* of a clean headless engine. The
   hard part is already decoupled.
2. **Replay is a non-problem.** The Arena rolls plain `random` dice (not seeded).
   Normally that clashes with Oubliette's byte-identical-replay rule — but Oubliette
   records combat as **one result event** (absolute final HP/XP/loot, decision D7)
   and re-applies *that* on reload; it **never re-runs the fight** (D9). The fight
   can roll however it likes; only its outcome is persisted.

The integration is therefore **wiring, not invention**: encounter-in, result-out,
across a process boundary.

## 3. Locked decisions

- **D-COMBAT-1 — Launch The Arena as the interactive tactical app.** The fight is a
  real desktop window the player plays; the result returns to the browser. Reuses ~all
  existing work. Local-play only (how OublietteDev plays). *Not chosen:* headless auto-resolve
  (throws away the board); port-the-board-to-web (someday upgrade, most work).
- **D-COMBAT-2 — Cap the primitives.** Keep the GameEffect/EffectBlock primitives
  already built + working; cover the SRD spells/abilities real play needs; **stop.** No
  universal-generator ambition (the open-ended pit that caused the original burnout).
- **D-COMBAT-3 — Enter-button + hard input lock.** The browser shows an "⚔ Enter the
  Arena" button rather than auto-popping the window — player controls when they tab
  over. While a fight is unresolved, the browser **stops accepting player input**
  (turn endpoint rejects, composer locked, clear "combat underway" notice) so nothing
  can corrupt game state mid-fight. Mirrors the existing `session_ended` composer-lock
  pattern.
- **D-COMBAT-4 — Party-aware bridge, PC-first play.** Build the encounter bridge to map
  the **whole party** (`repo.party()` already returns a list) and support multiple
  fighters per side — but the **first runs field a single PC.** Eventual goal: up to
  4 players in one shared-world party (they act as one party toward the DM). The Arena
  already supports multiple combatants on either side.
- **D-COMBAT-5 — Damage as a packet pipeline (keystone refactor, see §4).** Rework The
  Arena's damage model from a pre-collapsed single int into a structured damage-event
  pipeline *before authoring any new fidelity content.* Sequenced after the integration
  is proven end-to-end and before Stage 4, because the two work streams are independent
  and this ordering costs zero rework.

## 4. The damage-packet pipeline (keystone)

**The problem (OublietteDev's burnout wound, confirmed in code).** By the time damage reaches
`combat/damage.py apply_damage`, it is already **one `int` + one `damage_type` string**.
`roll_damage` accepts a *list* of typed `DamageRoll`s and **sums them**, keeping the
per-type breakdown only in a `details` list used for logging and then discarded.
Consequences:
- Mixed-type attacks (flametongue = slashing+fire; Divine Smite = weapon+radiant) can't
  apply resistance per type — they're one blob with one type when defenses run.
- Damage tags (magical / silvered / adamantine), the source creature, and "can this be
  reduced at all" are gone before modifiers fire.
- Every new interaction (Heavy Armor Master flat subtract, Uncanny Dodge halve,
  reaction-based reduction) becomes a special case wedged into `_apply_damage_modifiers`.

**The model.** Damage stays a **packet list** until the last possible moment:

```
DamageEvent
  packets: [ DamagePacket{ amount:int, dtype:str, tags:set[str], source, can_reduce:bool }, ... ]
  context: { attacker, target, is_critical, action_source }
```

The event flows through an **ordered chain of handlers**, each free to inspect, split,
zero, or transform packets, in 5e order:
`immunity → resistance → vulnerability → flat reductions (features) → reaction reductions → temp HP`.
Damage is **realized into HP only at the end**, when no handler will act further —
"applies when it stops being acted on." Healing and temp-HP get the same single
realization point.

**Why now-ish, not first and not last.** It's foundational for extensibility, but the
integration wire (§5) never touches damage internals, so doing integration first
creates no rework. We do the refactor **before** Stage 4 fidelity (new spells/modifiers)
because *that* content is what's painful to redo on a bad foundation. Existing content
(23 monsters, basic attacks) already works and is not re-authored. Strong existing test
coverage (`test_combat_damage`, `test_damage_reduction`, `test_resolve_effect`, …) is
the safety net for the refactor.

## 5. Integration map (the wire & seams)

**Oubliette swap point** — entirely in `oubliette/runtime/loop.py _run_combat` +
`oubliette/combat/boundary.py`. Today: `run_encounter()` → `auto_resolve` →
`CombatResult` → `result_to_ops` → ONE `COMBAT_RESULT` event. All of that wiring
(validation, ephemeral-vs-persistent enemies, write-back, non-combat exits
parley/flee/bribe, XP/loot/leveling, replay) is built and tested. Only `auto_resolve`
is the placeholder.

**New flow:**
1. `_run_combat` calls a bridge that writes an Arena **encounter file** from the live
   party (`repo.party()`) + chosen bestiary monsters + the DM's `EncounterRequest`
   (enemies, terrain kind).
2. It spawns The Arena process in **launch-into-this-fight** mode (new — §6 Stage 1),
   blocked in a thread executor (the turn loop is async; don't freeze the event loop).
   The browser is locked (D-COMBAT-3) while the player fights.
3. On `COMBAT_ENDED`, The Arena writes a **result file**: `winner`, per-combatant final
   HP/conditions (keyed by id+team), and who fell. (`CombatManager.winner` exists;
   `_check_victory` already decides by team; combatants carry `.creature` with live
   HP/conditions; `serialization.py`/`load_combat_state` prove round-trip.)
4. The bridge maps that result → Oubliette `CombatResult` (absolute values, D7) → the
   existing `result_to_ops` → ONE `COMBAT_RESULT` event. Story resumes with the digest.

**The data bridge (the shared core, needed regardless of UI choice):**
- Oubliette `state.models.Character` (+ `CharacterSheet`, abilities, equipment, AC,
  attacks) → Arena `PlayerCharacter`/`Creature`.
- Oubliette enriched bestiary `StatBlock` (334 SRD monsters, structured per-action data
  + portrait URLs for tokens) → Arena `Monster`.
- `EncounterRequest.enemies` + terrain → Arena `Encounter` (combatants, positions on a
  default grid keyed to terrain kind, teams).
- Return path as above. Both sides are pydantic and similar in spirit (abilities/AC/
  HP/actions/conditions) but differ in field detail — bounded mapping work.
- **Fidelity starts low:** PCs as basic-attack stat blocks (their `attack_bonus`/
  `damage`); monsters use the bestiary's structured primary + multiattack. Spells and
  class features layer in at Stage 4.

## 6. Build order (each stage shippable on its own)

- **Stage 0 — Adopt & rename.** Fold `dnd_combat_sim` into the repo as a top-level
  `arena/` package (rename `src`→`arena`, rewrite imports, move its tests under
  `tests/arena/`, add `pygame` as an optional `[arena]` extra in pyproject, register
  `arena*` in packages.find + package-data for assets/data). Reskin UI strings
  "D&D 5e Combat Simulator" → "The Arena." Pure plumbing; its 93 tests pass unchanged.
- **Stage 1 — Launch-and-return.** New Arena entry mode: start directly into a given
  encounter file and, on `COMBAT_ENDED`, write the result file and quit. Verify by
  hand against an existing playtest encounter.
- **Stage 2 — The bridge.** Encounter-out (Oubliette → Arena) and result-in
  (Arena → `CombatResult`), party-aware, basic-attack fidelity. Unit-tested both ways.
- **Stage 3 — Flip the switch.** Replace `auto_resolve` behind `run_encounter`: write
  encounter → spawn Arena (executor) → read result → `CombatResult`. Add the browser
  "Enter the Arena" button + input lock (D-COMBAT-3). First real fight from inside a
  story; XP/loot/leveling/replay already work downstream.
- **Stage 3.5 — Damage-packet keystone (§4).** Refactor before any new content.
- **Stage 4 — Fidelity, capped (D-COMBAT-2).** Map the actual party's class actions/
  spells + Atria-relevant monster abilities onto existing primitives — only what real
  play needs. Iterate against live playtests.

## 7. Open questions / deferred

- **Multi-PC party (up to 4)** — model + UI is its own arc; bridge is built ready for it.
- **Encounter battlefield generation** — Stage 2 starts with a default grid + auto-
  placement keyed to terrain kind; richer terrain authoring (cover, hazards) later.
- **Companions/recruitment** (recruit/join_party, rest/heal) — long-deferred, gated on
  combat existing; revisit after Stage 3.
- **Portrait/token sharing** — The Arena should consume the bestiary `portrait_url`
  convention for board tokens (per `oubliette-bestiary-arc`).
- **Process model** — subprocess vs. in-process pygame on a thread; subprocess is
  cleaner (isolation, crash containment). Decide at Stage 3.
- **Chargen dependency** — higher fidelity tracks the character-sheets arc; not a blocker
  (we start at basic-attack fidelity).
