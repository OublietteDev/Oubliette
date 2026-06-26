# Phase D — Closing out the Arena's SRD 5.1 combat feature surface (v0.1)

**Provenance:** the 2026-06-26 multi-agent completeness audit (58 agents, finder →
independent-verifier → completeness-critic → synthesis; workflow `arena-srd-completeness-audit`).
Verdict: the Arena is *not* SRD-5.1-complete, but the gaps are narrow and well-located.

**Scope philosophy (OublietteDev's framing):** "feature-complete" means **"is every combat
mechanic coded in"**, NOT "is combat fully operational top-to-bottom." So gaps that are
really *the AI failing to pull a lever that already exists* are NOT Phase D — they belong to
the future AI rework. Phase D closes the gaps where a **mechanic genuinely does not exist**.

---

## Explicitly OUT of Phase D (decided, with reasons)

- **Downed-PC RAW (the "0-HP rules": Unconscious+prone on down, death-save-on-damage).**
  Deliberate design choice — downed party members stay "weirdly safe." With no live DM in the
  Arena to grant narrative leniency, code-side leniency *is* the mercy that keeps a campaign
  from ending prematurely. Monsters already die at 0 (`_check_victory`), so there is nothing
  to do on the monster side anyway.
- **Multiattack-for-AI** (monsters swing once instead of 3–4×) and **monster spellcasting**
  (Mage fights with a dagger). The *machinery* exists (PC multiattack is live; the spell
  pipeline is live) — these are the AI not driving it. → **AI rework pass**, not Phase D.
- **Lair-action CONTENT.** The mechanic is fully wired, but SRD 5.1 contains **no lair-action
  data** (verified against the cached source: 0 structured fields; the 7 "lair" substring hits
  are regional-effect prose on Ancient dragons/Couatl/Deva). Real lair actions live in the
  Monster Manual, outside the open license. Adding them = hand-authored homebrew → defer to a
  future Forge/homebrew content pass. The mechanic stays ready.
- **Pure-utility / illusion / divination / social spells** (Wish, Prestidigitation, etc.) —
  agreed out of scope; narrated story-side by the DM.

## Confirmed SOLID (do not touch — verified RAW-faithful)

Per-packet damage pipeline (immunity→resistance→vulnerability, crit-before-resist); death
saves; concentration (the old "unenforced" note is STALE — it IS enforced); **Legendary AND
Lair actions** (mechanic — refutes the standing hunch); conditions Prone/Paralyzed/Restrained/
Stunned/Grappled/Invisible/Blinded; action economy (slots, reaction reset, PC Extra Attack,
Dash/Disengage/Dodge/Hide/Help/Shove, difficult terrain, prone costs, cover-to-AC).

---

## Package D-MON — "Monsters fight by their stat block"

This is OublietteDev's primary target. Most of it rides on one piece of plumbing: **structured fields
on the Arena monster model + a re-parse of the cached source** (`tools/gen_arena_monsters.py`,
reads `tools/raw/srd-monsters-raw.json`, writes `arena/data/monsters/srd/`). No re-download
needed; fully git-recoverable; OublietteDev to eyeball the regenerated bestiary in-game (human-readable
structure + art intact) after the regen.

| ID | Item | Source data | Work |
|----|------|-------------|------|
| **D-MON-1** | **Legendary Resistance** (25 monsters) | present (`special_abilities` name) | `legendary_resistance_count` on model; in `resolve_saving_throw`, a legendary creature that fails a meaningful save with charges left converts to success + decrements; reset per encounter. AI policy: spend on save-or-lose. |
| **D-MON-2** | **Recharge (5–6) abilities** (71 monsters) | present (`usage:{type:"recharge on roll", min_value}`) — currently flattened to `uses_per_rest:2` at `gen_arena_monsters.py:283` | add `recharge_min` to Action; emit it from source instead of the `uses_per_rest` hack; roll d6 at start of turn in `process_start_of_turn`, restore on ≥ min. |
| **D-MON-3** | **Regeneration** (7 monsters) + Rejuvenation note | prose `special_abilities` | structured `regeneration:{amount, negated_by:[types]}`; heal at start of turn unless a negating damage type was taken since last turn (per-round damage-type tags already exist in the packet pipeline). |
| **D-MON-4** | **Trait primitives** (see triage below) | prose `special_abilities` names | structured flags hydrated from trait names; each wires into an existing hook. |
| **D-MON-5** | **Monster reactions** (12 monsters: Parry, etc.) | present (`reactions` array) — generator drops it entirely | add `_reactions` parse to generator; populate monster reaction list; wire Parry (+AC) into `check_ac_reaction_options`. |

### D-MON-4 trait triage

**WIRE (combat-relevant), grouped by the primitive each needs:**

| Primitive | Traits |
|-----------|--------|
| Advantage on **saves** | Magic Resistance (31, vs spells) · Brave / Dark Devotion (vs frightened) · Fey Ancestry (vs charm/sleep) |
| Advantage on **attacks** | Pack Tactics (17, ally adjacent to target) · Reckless (both directions) · Blood Frenzy (vs damaged target) · Surprise Attack (first round) |
| **Start-of-turn** | Regeneration / Rejuvenation (covered by D-MON-3) |
| **Death-triggered** | Undead Fortitude (CON save → 1 HP) · Relentless Endurance · Death Burst (AoE on death) |
| **Move-then-strike rider** | Charge (14) · Pounce (6) · Trampling Charge (5) · Rampage |
| **On-hit save rider** | Stench (poison aura) · Petrifying Gaze · Heated Body / Heated Weapons |
| **Damage interaction** | Magic Weapons (12, attacks count as magical) · Lightning/Elemental Absorption (heal from a type) · Damage Transfer |

**SKIP (no mechanical hook in a hex tactical sim) — ~50+ traits:** all Keen-senses,
Amphibious/Water Breathing/Hold Breath, Spider Climb, False Appearance, Shapechanger (23 —
narrative + huge), camouflage/Web traits, Echolocation, Devil's Sight, Sunlight Sensitivity
(no light model), Flyby/Incorporeal (2D grid), Standing Leap/Sure-Footed/Ice Walk/Earth Glide,
telepathy/Mimicry, Immutable Form, Siege Monster, Illumination, Swarm (complex; revisit if
needed). Real SRD traits, but nothing to *do* in the Arena.

---

## Package D-SPELL/COND/ACT — the medium list (the rest of "coded in")

Order roughly by impact-to-effort. Each is a self-contained mechanic.

| ID | Item | Note |
|----|------|------|
| **D-AOE-1** | **AoE shape geometry** (cone/line/cube → currently all resolve as RADIUS bursts; Lightning Bolt = 100ft sphere) | True shape resolvers keyed on TargetType + an aim direction/endpoint from the caster. Highest-impact, heaviest item; aiming-input has a light GUI dependency (basic version now, polish with the eventual UI pass). |
| **D-ZONE-1** | **Zone friendly-fire** — Cloudkill/Stinking Cloud/etc. hardcode `affects_enemies_only=True` (`manager.py:3120`); allies stand safe in the caster's cloud | drop the hardcode for indiscriminate zones. |
| **D-WALL-1** | **Wall `damage_on_enter` is dead code** + wall spells route through a circular zone, not a blocking barrier | tag wall spells `is_wall`, route through the (currently-dead) ActiveWall path with line geometry + blocks_movement/los + functioning entry damage. (This is the real "walls" gap behind the earlier precondition.) |
| **D-CTRL-1** | **Control spells lose their signature mechanic** — Slow (no action-economy limit), Confusion (just incapacitated), Spirit Guardians (no slow), Spike Growth (single hit, not per-5ft no-save), Chain Lightning (single target) | add the missing primitives incrementally: action-economy-restriction field, random-behavior resolver, movement-debuff on zones, per-distance no-save damage, chain resolver. |
| **D-COND-1** | **Charmed** is inert — can attack its charmer | forbid a charmed creature from targeting its `AppliedCondition.source` in attack legality + AI scoring (reuses frightened-flee source tracking). |
| **D-COND-2** | **Exhaustion** levels inert | tier branches: L2 speed×0.5, L3 attack/save disadvantage, L4 max-HP halved, L5 speed 0, L6 death. |
| **D-COND-3** | **Incapacitation doesn't end concentration** | in `apply_condition`, when applying STUNNED/PARALYZED/UNCONSCIOUS/INCAPACITATED, call `end_concentration`. |
| **D-ACT-1** | **Ready** action unreachable in real play (engine exists; no GUI/AI call site; only CREATURE_MOVES trigger fires) | surface Ready in tactics popup + fire attack/cast/enters-range triggers + resolve readied *spells* (not just attacks). (AI side of Ready can wait for the AI pass.) |
| **D-ACT-2** | **Player-initiated Grapple** absent (escape-only; Shove has full infra, Grapple has none) | `execute_grapple` mirroring `execute_shove` (contested Athletics), surface in radial/tactics menu. |
| **D-ACT-3** | **Cover doesn't apply to DEX saves** (AC only) | pass effect-origin position into `resolve_saving_throw` for area DEX saves; add cover's +2/+5. |
| **D-ACT-4** | **Ranged**: long range refused entirely + no in-melee disadvantage | allow attacks within `range_long` at disadvantage; add disadvantage when a hostile is within 5ft of the ranged attacker. |

---

## Sequencing (multi-session OK)

1. **Session 1 — D-MON plumbing + regen.** Add monster-model fields (recharge, regeneration,
   legendary-resistance count, trait flags, reactions); patch `gen_arena_monsters.py`; regenerate
   `arena/data/monsters/srd/`; **OublietteDev eyeballs the bestiary in-game** (structure + art). Then
   D-MON-1 (Legendary Resistance) + D-MON-2 (Recharge) — the two headline items — with lab fights.
2. **Session 2 — D-MON-3/4/5.** Regeneration, the trait primitives (batched by shared hook), monster reactions.
3. **Sessions 3+ — D-SPELL/COND/ACT.** Lead with the cheap high-value ones (D-ZONE-1, D-COND-1/2/3,
   D-ACT-3/4), then the heavier D-AOE-1 / D-WALL-1 / D-CTRL-1 / D-ACT-1/2.

## Method & gotchas

- **Deterministic parse only** (the CS4/bestiary lesson): the source JSON is authoritative; never
  LLM-transcribe stat tables. Regen via `python tools/gen_arena_monsters.py tools/raw/srd-monsters-raw.json arena/data/monsters/srd`.
- **Stale-server gotcha:** oubliette-side (bridge) changes are invisible until an app-server
  restart; Arena code reloads fresh per fight. Monster-data changes are Arena-side (load fresh).
- Each mechanic ships with lab-fight verification (the C6 lab battery pattern) + tests; keep the
  suite green.
