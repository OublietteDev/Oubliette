# Oubliette Table — Project Knowledge

> A single, self-contained briefing for anyone (human or AI assistant) picking up this
> project. It consolidates what's been learned across many build sessions: the vision,
> the architecture, who's building it, the conventions that keep things from breaking,
> and where things stand. Plain-language first; technical specifics where they matter.

---

## 1. What Oubliette is

**Oubliette Table** is a non-commercial, open-source **AI Dungeon Master text RPG** built
on the **Dungeons & Dragons SRD 5.1** (the openly-licensed slice of 5e, CC-BY). You play
in a web browser: you type what your character does, and an AI narrates the world and runs
the game as your DM.

It's an homage to an earlier game called **"Tidefall,"** and it exists to fix Tidefall's
core flaw. In Tidefall the AI *was* the game — it held all the state in its head and in its
prose, so it could quietly forget your gold, contradict itself, or let you talk it into
anything. Oubliette's whole design is the opposite of that.

### The core invariant (the "firewall") — the single most important idea

> **The AI narrates and proposes. The code owns the state and the rules. The model is
> never the authority on a number, and the player never holds the pen.**

Concretely, two structural facts enforce this:

1. **Only code can change protected game state** (your HP, gold, inventory, XP, conditions,
   level). The AI can't write those directly — it can only *request* a change by calling a
   structured "tool" (like `give`, `transact`, `award_xp`, `travel`, `start_quest`). The
   player can never emit those tool calls, and the code validates every one before applying
   it. So "I have 10,000 gold" from a player simply doesn't happen.
2. **Every change and every die roll is written to an append-only log before it takes
   effect.** Reloading a saved game **replays that log** to rebuild the exact state — it
   never re-rolls the dice or re-asks the model. The formula is literally:
   **`state = seed(the authored world) + replay(the event log)`**. This guarantees a
   reloaded game is *byte-for-byte identical*. (Only the narration prose is "best effort" —
   it's regenerated, not stored.)

This firewall is the spine of the entire codebase. When in doubt about a design decision,
ask: *does this keep the code as the authority on state, and the model as the storyteller?*

---

## 2. Who's building it, and how to work with them

**OublietteDev** is the creator. **OublietteDev is a biologist by training**, and a self-directed/amateur
programmer — sharp and deeply engaged, but coming from a different field. He leans on his AI
collaborators for design and implementation.

**How to communicate with him (this matters):**
- **Lead with plain language and a concrete analogy** before (or instead of) the technical
  term. Define jargon in a few words the first time it's unavoidable.
- **Frame design decisions as *player/game experience*, not implementation mechanics.** When
  there's a fork in the road that's genuinely his call, describe the trade-off in terms of
  how the game will *feel* to play.
- Keep the warmth; never condescend. He's not behind — he's just not a career coder.
- He often **interviews the live AI DM** and drops feedback `.txt` files in the repo root —
  watch for those.
- He's on a Claude Pro plan and is comfortable spending tokens on multi-agent fan-out when it
  buys quality.

**Two worlds carry real emotional weight — treat them with care:**
- **Brightvale** is *not* throwaway demo data. It's the world OublietteDev played with his **wife**
  and **Claude Opus 3** around 2023–24. A big motivation for the authoring tools is to
  **expand Brightvale and surprise her** with it reborn in this engine. Protect it from
  accidental loss; be encouraging about the expansion.
- **Atria** is his current, actively-developed world (see §6).

---

## 3. The technology, in brief

- **Language:** Python (pydantic v2 for data models, FastAPI for the web servers, pytest for
  tests). Front-ends are **single self-contained HTML files** with vanilla JS and embedded
  CSS — no build step, no frameworks, no CDNs.
- **Persistence:** an **event store in SQLite** (the append-only log). One save file:
  `oubliette-save.sqlite`.
- **The AI model** sits behind a swappable interface (`LLMClient`): a `ScriptedLLMClient`
  (an offline, deterministic stand-in used by tests and previews) and an `AnthropicLLMClient`
  (the real Claude DM, called over the network). The live DM has been **Claude Sonnet**
  (OublietteDev may upgrade to an Opus-tier DM if coherence ever lags).
- **Structured output:** the model is always made to answer in a strict schema (forced tool
  use), so its narration and its proposed tool calls come back as validated data, not free
  text to be parsed.

### The three programs

| Program | Where | Port | What it is |
|---|---|---|---|
| **The game** | `oubliette/app/` | 8000 | The player's browser chat UI — the actual game. |
| **The Forge** | `oubliette/creator/` | 8001 | The world-authoring tool — build/edit content packs via friendly forms. Never touches save files. |
| **The Arena** | `arena/` | (desktop) | A tactical 5e combat simulator (pygame). Launches as a separate window when a fight breaks out; the result folds back into the story. |

### How to run it

- **Live game (real Claude DM):** `python -m oubliette.app.server` — this path loads the
  `.env` (which holds `ANTHROPIC_API_KEY`, gitignored), picks the live DM, and opens a
  browser at `http://127.0.0.1:8000`. **A bare `uvicorn …:app` launch runs the *scripted*
  DM instead** (only responds to canned phrases) — that's for tests/previews, not real play.
- **The Forge:** `python -m oubliette.creator.server` → `http://127.0.0.1:8001`.
- **Tests:** `pytest` from the repo root runs **both** the Oubliette suite and the Arena
  suite (thousands of tests; "full suite" counts in history are the combined number).
- Install: `pip install -e .[web]` (the `.venv` already has it).

---

## 4. How a "world" is built (content packs)

A **world is a pack** — a folder under `oubliette/content/packs/<id>/` containing JSON files,
one per content type:

- `pack.json` — the manifest (id, name, version, which scenario starts a new game, world-map
  image, bestiary knowledge-gate setting).
- `items.json`, `statblocks.json` (creatures), `npcs.json`, `places.json`, `lore.json`,
  `quests.json`, `scenarios.json` (the opening setup + starting party).

**The core guarantee:** a pack **loads whole-and-valid or fails loudly** — strict schemas
(unknown fields are errors, not silent drops) plus a whole-pack **cross-reference linter** that
checks every connection resolves (an NPC's home is a real place, a shop only prices what it
stocks, a quest's giver exists, etc.). All problems are reported together, in one list.

**Two pillars of The Forge** make authoring safe for a non-coder:
1. **One rulebook** — The Forge validates with the *game's own* loader, so its green "✓ Ready"
   means the game will load it.
2. **Pick, don't type** — every cross-reference is a dropdown of things you've already made
   (place exits, NPC homes, quest givers, reward items), so the whole "unknown id" class of
   errors is impossible by construction. Internal ids are auto-generated and hidden, and stay
   stable when you rename, so references never break.

**Saving is never destructive:** every save first writes a timestamped backup to a sibling
`pack-backups/` folder (outside the packs root, gitignored).

### The SRD layer (shared by every world)
Separately from world packs, `content/srd/` holds the **global D&D ruleset** — all 12 classes
(+ subclasses), 9 races (+ subraces), 319 spells, ~590 items (mundane + magic + poisons), 334
monsters, 15 conditions, the (single SRD) background and feat. This is **content-complete**.
A created character draws from this layer; world packs add their own flavor on top.

---

## 5. The major systems (what exists today)

The core vision is **built and playable in the browser with a live streaming AI DM.** The
systems below are all shipped unless noted:

- **The DM turn loop** — every turn: *assess* (what is the player trying to do? does it need a
  roll? a fight? a trade?) → *roll* (the model sets the difficulty; **the code supplies the
  character's bonus from the sheet** and rolls the dice) → *resolve* (narrate + propose tool
  calls) → *apply* (validate and commit). The model is called fresh each turn with a compact
  context packet (scene, who's present, party stats, recent beats, relevant lore, active/offered
  quests) — it does **not** remember prior turns except through that recap.
- **Character creation + sheets** — full SRD chargen (all ability-score methods, races/subraces
  with their choices, classes, backgrounds, feats-or-ASI), a derived character sheet, and
  **player-uploaded portraits**. Multiclassing is deferred.
- **Leveling, rests, resources** — XP-gated leveling (the DM grants XP via the `award_xp` tool;
  combat awards it automatically), long/short rests, spell slots and class resources (Ki, Rage,
  etc.), all event-sourced so they survive reload.
- **Multi-character party** — a new game can build a party of up to 6 heroes (tabbed builder +
  tabbed sheets). The party shares **one gold purse** and shares XP; rests are party-wide;
  narration and the sidebar HUD are party-aware.
- **Travel + place hierarchy** — the DM moves the party with a `travel` tool. Places nest
  (a town contains districts; a dungeon contains rooms). Sub-locations under the same parent are
  auto-reachable from each other; explicit `exits` connect separate areas. NPCs are "present"
  only at their home location, which keeps the DM's context scoped.
- **World map** — pins on assignable map art, two levels deep, in both The Forge (arrange) and
  the player's Map panel. Unvisited areas stay a redacted "Unknown" pin (redaction is
  **server-side** — unvisited names never reach the browser).
- **Audio soundscape** — a location-driven ambient mixer. Sounds ride the place hierarchy (a
  town theme passes down to its districts); the DM reports time-of-day and weather each turn,
  which filter the cues. Authored in The Forge; audio is *derived state, never AI-played* (the
  firewall again). Players get Music/SFX sliders and mute.
- **Bestiary** — a searchable panel of the loaded world's creatures + the full 334-monster SRD
  library, source-badged, with portraits. An optional per-world "knowledge gate" can hide
  high-CR creatures until the party has faced them.
- **Lore** — authored world history/legend the DM weaves in (not recites). It surfaces
  situationally: a city's lore appears whenever the party is anywhere inside that city.
- **Table contract + start menu** — a session-zero safety/tone agreement (a tone dial plus
  Lines/Veils — content the DM never depicts vs. fades to black) stored per-campaign; a start
  menu (single save: Continue resumes, New Game erases — no save slots).
- **Player journal** — the player's own notes (quests/NPCs/locations). **Deliberately invisible
  to the DM**, so a player can't induce a hallucination by writing false "facts" into it.
- **Trade window + haggle** — buying/selling are ordinary code-validated transactions at
  merchant prices; a basket can be settled at once or haggled (the DM rolls a social check and
  adjusts the price — a soft, model-set economy by design).
- **Quests** — emergent (the DM starts/advances them) *and* **authored** (see §7). One quest
  active at a time; rewards are handed out through the normal `give`/`transact` tools so they can
  even be renegotiated. An **Active Quest** panel shows the current one.
- **Quality-of-life** — token-by-token streaming narration; an explicit **Out-of-Character
  toggle** (the sole signal for table-talk); an **`end_session`** tool that lets the DM gracefully
  exit a hostile/bad-faith interaction (model welfare).

### Combat — "The Arena"
Combat is **a separate tactical app, not prose.** The Arena is a mature ~45k-line hex-grid 5e
combat simulator (OublietteDev's older project, folded in). When a fight breaks out in the story, the
browser shows an "⚔ Enter the Arena" button and **locks input**; clicking it launches the pygame
Arena, you play the fight on the board, and the **result folds back** into the story as a single
recorded event (so replay never re-runs the fight — only its outcome is persisted).

A **bridge** maps the party and the bestiary into the Arena and maps the result back. Two big
arcs are done: **Phase B** (the Arena consumes Oubliette's full SRD content — items, potions,
spell slots, spells, portraits-as-tokens, resource round-trip) and **Phase C** (Arena
"completeness" — class features, more spells, on-hit riders, reactions like Shield, Mirror Image,
Turn Undead, Banishment, scrolls, weapon kits, grapple/escape, vision/light, prone movement,
re-prepare-on-long-rest, the C6 lab battery). The original "burnout" pitfall — trying to build a
*universal* effect generator — is explicitly **capped**: build only what real play needs.

**Phase D — closing the SRD feature surface (started 2026-06-26).** A thorough multi-agent
*completeness audit* (58 agents; finder → independent-verifier → completeness-critic → synthesis)
asked "is the Arena SRD-5.1-combat-complete?" Verdict: feature-rich and RAW-faithful in many hard
places (the damage pipeline, death saves, concentration, most conditions, **and — refuting a
standing hunch — legendary AND lair actions** are all solid), but with targeted gaps. The biggest
cluster was **"monsters fight below their stat block."** Phase D closes the *mechanic* gaps (the
plan is `docs/roadmap/oubliette-phase-d-plan-v0.1.md`); AI-driven gaps (monsters not *using*
multiattack/their spell lists) are deferred to a future AI pass, and a few RAW deviations are kept
on purpose (downed PCs stay "weirdly safe" — no live DM to grant mercy; lair-action *content* is
out because the SRD ships none). **Done so far (lab + integration tested, suite 2668 green):**
D-MON-1 **Legendary Resistance** (a boss turns 3 failed save-or-lose throws into successes, never
wasted on plain damage saves), D-MON-2 **Recharge** (breath weapons roll a real d6 to recur),
D-MON-3 **Regeneration** (start-of-turn heal, suppressed a turn by acid/fire), and **D-MON-4a**
(commit 0152be6) — the first batch of trait primitives wired into existing hooks: **Magic
Resistance** (advantage on saves vs spells), **Brave/Dark Devotion** (vs frightened) & **Fey
Ancestry** (vs charmed), **Pack Tactics** (advantage when an ally is within 5 ft of the target),
and **Magic Weapons** (now keyed off the structured flag, not just the trait name). Save/attack
logs tag the source (`[Magic Resistance]`, `[Pack Tactics]`). New `traits_lab` bench +
`test_monster_traits.py` (14). **BRIDGE FIDELITY CONFIRMED (corrects a momentary false alarm this
session):** D-MON traits DO reach real story→Arena fights — the bridge entry point
`enemy_from_statblock` prefers the full-fidelity Arena stat block via `arena_monster_file`, and the
Oubliette bestiary id ↔ `arena/data/monsters/srd/<id>.json` alignment is **334/334 exact**; the flat
`statblock_to_monster` fallback only hits synthetic templates + pack-authored monsters with no
generated Arena file (a minor edge tied to the deferred Forge creature editor). **D-MON-4b**
(commit 7467922, suite 2681 green) closes the death-triggered batch: **Undead Fortitude** (zombie/
ogre_zombie — a CON save DC 5+damage on a 0-HP hit drops it to 1 HP instead, unless the blow was
radiant or a crit; `apply_damage` gained an `is_critical` arg + `check_undead_fortitude`) and
**Death Burst** (steam/ice/magma mephits + magmin — detonate on death, indiscriminate save-for-
damage within radius via a new `_reconcile_death_bursts` pass in `_check_victory`, cascades). New
`Monster.undead_fortitude` flag + `DeathBurst` submodel, generator parses both from prose, 6 srd
files regen'd; `test_death_triggered.py` (11) + `death_triggered_lab` bench. **Relentless Endurance
= no-op** (0 SRD monsters; it's a half-orc PC trait the death-prevention framework already serves —
`get_death_prevention_features` now also reads monster `special_abilities`). **Death Burst covers
all 5 SRD monsters** — the dust mephit's condition-only burst (blinded, per-turn re-save) is now
modeled too (commit 417bc45): `DeathBurst` gained `condition_on_fail` (and `damage_dice` is now
optional), the generator parses the "or be <condition>" prose, and `_fire_death_burst` applies
damage and/or the condition on a failed save (the condition rides `apply_condition` with
`duration_type=end_of_turn` so the existing re-roll handles recovery).

**Magic Resistance — full lifecycle (commit 96e1ae2) + a legacy-data gotcha (commit 5549773).**
4a only added the advantage on a spell's OPENING save; RAW it applies to *every* save against the
spell. Wired the recurring sites (each effect carrier already records its spell origin):
condition re-saves (`conditions.py` start/end-of-turn — shake Hold Person via `ac.spell_level`/
`ac.condition`), debuff shake-offs (`buff_effects.py`, Bane), zone saves (`zones.py` — Spirit
Guardians/Web/Cloudkill; also fixed the main `ActiveZone` creation at `manager.py:3126` to carry
`spell_level`, it had defaulted to 0), and the dominate damage re-save. MR stays advantage-only
(never immunity); concentration CON saves stay correctly excluded; one narrowing kept — it triggers
on *spells*, not the broader "spells and other magical effects" (no clean flag for non-spell magical
saves). **GOTCHA (bit OublietteDev's playtest):** the pre-bridge **legacy lab caster files**
(`elara.json`, `brother_aldric.json`, also Shade) baked their spell actions with **`spell_level: None`**,
which silently disables Magic Resistance / upcasting / Dispel / spell-origin detection for those
labbed casters — Hold Person on the bearded devil rolled flat. **Real play was always fine** (the
shipped `arena/data/spells/srd` library carries correct `spell_level`, and lab chars bypass the
bridge that would bake it). Fixed by backfilling `spell_level` from the library; added a regression
test that loads the REAL bearded_devil + elara Hold Person. First thing to check if a *lab* spell
misbehaves: is `spell_level` None on that legacy character's baked action? Suite 2685 green.

**D-MON-4c — move-then-strike (commit b26118a, suite 2692 green).** Charge/Pounce/Trampling Charge
expressed as on-hit riders gated on movement: `OnHitRider` gained `requires_charge_ft` (the gate)
and `save_dc_fixed` (Trampling Charge's DC is NOT 8+prof+mod — triceratops 13 vs computed 17 — so
it's taken verbatim from the block). `MovementTracker.turn_start_position` (set at turn start) lets
the manager's `get_applicable_riders` filter charge riders via `_attacker_charged` (has_moved AND
closed ≥ threshold/5 hexes toward the target). Generator parses 23 monsters (12 Charge, 6 Pounce,
5 Trampling Charge) → `Feature.on_hit_rider`; prone applied indefinitely (stand-up clears). NOT
modeled: minotaur's "pushed away" clause, and the lion/triceratops "bonus attack vs a prone target"
follow-up. `test_move_then_strike.py` (6) + `charge_lab` bench. **Rampage** (gnoll: on-kill bonus
move+bite) is a different shape (not a move-then-strike rider) — deferred with the AI rework.

**4c playtest fix (commit 0a01f7f).** OublietteDev's charge_lab showed "no monster charged" — two causes:
(1) a **latent bug**: `complete_attack` never actually applied ANY on-hit rider's condition (it
passed a bool as `save_to_end`, an `AppliedCondition` where a `Condition` enum was expected, and
iterated a single return) — so Charge/Pounce prone AND **Stunning Strike's stun** silently no-op'd;
the rider tests only cover the pure `resolve_rider`, so it went unnoticed. Fixed + regression test.
(2) **lab geometry**: beasts started ~18 hexes out, so they Dashed in (Dash = no attack) and then
meleed from a standstill — the move-then-strike gate never opened. Retuned charge_lab to ~6-hex
clean lanes (charge range); verified the Lion Pounces Thorin prone, etc. NOTE: the AI does not
maneuver to *set up* a charge (deferred AI rework) — charge fires automatically when the engagement
move is a straight run-in, so a charge bench must position beasts at one-turn-melee range. GOTCHA
for future labs: high-AC targets make charge attacks miss, hiding the rider (gate only logs on a hit).
**UI follow-up (OublietteDev, deferred to the Arena UI arc):** a charge hit currently looks like a normal
melee swing — it wants its own run-in/impact animation so the bonus-damage+prone hit isn't mistaken
for an ordinary attack. Logged in [[oubliette-arena-ui-cleanup]] (animation backlog).

**D-MON-5 — monster Parry reaction (commit fb289c6, suite 2703 green).** The generator dropped the
source `reactions` array; now it parses Parry → a +AC reaction Action (Shield's shape) on 6 SRD
monsters (knight +2, gladiator +3, erinyes +4, bandit_captain, ...). `complete_attack` calls
`_evaluate_monster_parry` on a hit vs a non-player target: if the creature's Parry AC bonus would
drop the attack roll below its AC, it spends its reaction and the hit becomes a miss. Melee-only,
never on a nat-20 crit, once/round; players still choose via the reaction popup (this is the monster
auto path, mirroring `_evaluate_ai_damage_reduction`). RAW "must see attacker / wield a melee weapon"
not checked. `test_monster_reactions.py` (8) + `parry_lab`; verified live (knight parried 6/40
marginal hits). Other reactions (Split, Unnerving Mask) left out.

**D-MON-6 — aura/retaliation/advantage traits (full repo suite 2723 green; new file `test_monster_aura_traits.py` +19, `dmon_aura_lab`).** The final batch, four traits across two mechanics, all flag-driven on `Feature` (hydrated from monster `special_abilities`):
- **Blood Frenzy** (`attack_advantage_vs_damaged`, on sahuagin/hunter_shark/giant_shark/quipper/swarm_of_quippers) — advantage on a *melee* attack vs a target below its HP max. Folded straight into `get_attack_advantage` (both creatures already in scope).
- **Reckless** (`reckless_attacker` → new `Condition.RECKLESS` pseudo-condition, on minotaur/berserker) — at the start of an AI monster's turn `_process_reckless_start_of_turn` re-applies RECKLESS (rounds=1, so the condition tick at turn-start clears last turn's instance first). `get_attack_advantage`: a RECKLESS attacker has advantage on its melee; *any* attack vs a RECKLESS target has advantage. Only fires for a conscious, action-capable monster with a melee attack (a ranged/incapacitated creature shouldn't hand out free advantage). PCs are never auto-recklessed.
- **Stench** (`aura_save_condition`/`aura_save_ability`/`aura_save_dc`/`aura_range`, on ghast DC10·5ft, hezrou DC14·10ft) — `_process_stench_start_of_turn` runs at the victim's turn-start (after the condition tick, so last turn's stench-poison has expired): a CON save or poisoned (rounds=1); a *success* records per-(victim,source) immunity in `self._stench_immune` for the rest of the fight (RAW 24h). Indiscriminate, like Death Burst.
- **Heated Body** (`retaliate_damage_dice`/`retaliate_damage_type`, on azer 1d10·salamander 2d6·remorhaz 3d6) — `complete_attack` calls `_apply_heated_body` on a landed melee hit vs a creature with the trait: the attacker takes the fire packet, no save, per-hit (so each multiattack swing retaliates). A parried swing already set `hit=False`, so it doesn't trigger.

**Surprise Attack (bugbear) deferred** — the Arena models no surprise/ambush at all (no surprise round, no SURPRISED condition, no ambush setup). Rather than fake it, OublietteDev chose to split Surprise Attack into the backlog, paired with a future surprise/ambush subsystem (which would also unlock Assassinate and story-bridge ambushes). With that deferral, **Package D-MON is closed** (Rampage + charge follow-ups stay with the AI rework).

**D-COND trio — the first slice of the final D-SPELL/COND/ACT package (full repo suite 2748 green; 3 new test files: `test_concentration_incap.py` +7, `test_charmed_targeting.py` +9, `test_exhaustion.py` +9; new `cond_lab` bench). Three condition fixes in one neighborhood, Arena-only (Surprise Attack stays parked — it touches Oubliette):**
- **D-COND-3 — incapacitation ends concentration.** New `manager._reconcile_concentration()` sweep (mirrors `_reconcile_grapples`), wired into the `_check_victory` reconcile batch after death-bursts. Any CONCENTRATING creature that is now incapacitated (INCAPACITATED/STUNNED/PARALYZED/PETRIFIED/UNCONSCIOUS) **or at 0 HP** drops concentration via `end_concentration(…, self.combatants)`, so the spell's linked conditions/buffs are stripped off their targets too. Chose a sweep over the audit's literal "hook in `apply_condition`" because most of the ~8 `apply_condition` call sites don't thread `combatants` (no linked-target cleanup) and `is_conscious` is pure-HP (no UNCONSCIOUS condition on KO) — the sweep closes a **latent bug too**: a concentrating caster dropped to 0 used to keep its concentration. BANISHED deliberately excluded (off-plane ≠ incapacitated; P-BANISH needs its links to survive).
- **D-COND-1 — charmed can't target its charmer.** Charmer = the CHARMED condition's `source` (a creature name, same convention as FRIGHTENED's fear source). Two layers: (1) AI — `build_context` drops the charmer from `enemies` entirely, so the AI never scores it as a target; (2) legality — the attack/effect entry points refuse the charmer (`execute_effect` only for **harmful** actions via `_action_is_harmful`: attack/save/conditions/control/dispel, so a charmed creature may still buff/heal its charmer). Helpers `_charmer_names` / `_charm_forbids_target` on the manager. **Live-test bug found by OublietteDev + fixed:** the guard was first only on `execute_attack` (volleys/AI), but the GUI's normal single-target attack goes through **`execute_attack_hit_check`** — so a charmed hero could still melee its charmer in real play despite the unit test passing. Guard added to `execute_attack_hit_check` too; regression test now drives that exact path. (Lesson: the unit test exercised the wrong chokepoint — mirror the GUI's actual call path.) Confirmed the Dryad's "Fey Charm" applies charmed via `saving_throw.conditions_on_fail` (an earlier single-line grep wrongly concluded no SRD monster applies charmed; JSON arrays are multi-line).
- **D-COND-2 — exhaustion tiers go live** (were stored 1-6 but inert). All in `condition_effects.py` via `exhaustion_level()` + `effective_max_hp()`: L2-4 speed ×0.5 / L5+ speed 0 (`get_movement_multiplier`), L3+ disadvantage on attacks (`get_attack_advantage`) and on all saves (`get_save_advantage`), L4+ max-HP halved — capped in `apply_healing` + `regeneration` + on reaching L4 in `apply_condition`, L6 = collapse (drops to 0 HP). **L1 (ability-check disadvantage) intentionally skipped** — the Arena's ability-check surface (shove/grapple/hide contests) is scattered with no central roller, and the audit scoped L2-L6. Also fixed a **latent Dash bug**: `execute_dash` now applies the movement multiplier, so a grappled/restrained/exhausted-5+ creature no longer gains full speed from Dash.
- **`cond_lab` bench** (`tools/labs/cond_lab.bat`): Charmed Knight (new `cond_charmed_knight.json`, pre-charmed by the Dryad present in the fight) for D-COND-1; Thorin's existing **Poisoned Fang** (applies exhaustion on hit) vs an Ogre for the live D-COND-2 tier walk; Brother Aldric's Spirit Guardians + the Ogre focus-fire for the D-COND-3 KO branch. Note: **no SRD monster applies exhaustion** (only Thorin's homebrew Poisoned Fang does), so that tier walk is driven by a hero; charmed/stunned/paralyzed ARE applied by monsters via `saving_throw.conditions_on_fail` (Dryad Fey Charm, etc.). The stun/paralyze→concentration branch is still test-only on the bench (the lab uses the reliable 0-HP path). **OublietteDev live-verified D-COND-2 (exhaustion to L2 via Thorin stabbing Aldric) and D-COND-3 (beating Aldric unconscious mid-concentration ends it); D-COND-1 charmed fixed after his report — pending his re-test of the hit-check guard.**

**D-SPELL/COND/ACT cheap cluster — D-ZONE-1 + D-ACT-3 + D-ACT-4 (full repo suite 2767 green; +30 tests: `test_ranged_disadvantage.py` +11, `test_cover_dex_saves.py` +4, plus updates; new `cheap_cluster_lab`). Three self-contained fixes in the attack/save/zone resolution. NOT yet committed, NOT yet live-verified.**
- **D-ZONE-1 — zone friendly-fire.** The persistent-zone creation in `_execute_zone_spell` hardcoded `affects_enemies_only=True`, so allies stood safe in the caster's own Cloudkill/Stinking Cloud/Web/Spike Growth. Now `affects_enemies_only=action.zone_follows_caster`: only a caster-following aura (Spirit Guardians — RAW "creatures of your choice", the lone such SRD zone) spares allies; every placed cloud is indiscriminate. Deriving from `zone_follows_caster` is robust across SRD JSON / bridge / baked lab actions without tagging each spell. (The caster is still spared by the per-tick `caster_id` check in zones.py — the audit flagged allies, not self.)
- **D-ACT-4 — ranged long range + in-melee disadvantage.** `is_in_range` now allows a ranged attack out to `range_long` (was refused past `range_normal`). New `ranged_positional_disadvantage()` (in actions.py) flags disadvantage when the shot is past normal range (within long) and/or a hostile, conscious, action-capable creature is within 5 ft of the shooter; folded into `resolve_attack_hit`'s disadvantage tally (so both the GUI two-phase path and the volley/AI `resolve_attack` wrapper get it). **Test-infra gotcha surfaced:** `roll_with_advantage/disadvantage` live in `arena.util.dice` and call *that* module's `roll_die`, so tests patching `arena.combat.actions.roll_die` don't control the adv/dis path — newly-disadvantaged ranged tests had to be repositioned to non-adjacent (straight roll) or updated; 5 pre-existing tests adjusted (is_in_range long-range semantics, two forced-movement blast tests moved off melee range, three aura ranged tests given a real `range_normal` + non-adjacent target).
- **D-ACT-3 — cover applies to DEX saves.** `resolve_saving_throw` gained a `cover_bonus` param (added to the modifier, logged `[cover: +N]`); `resolve_effect` computes it for DEX saves from the cover between the effect's origin and the target (`+2` half / `+5` three-quarters — the same values cover gives AC). New `effect_origin` param on `resolve_effect` so a placed blast measures cover from the clicked hex (threaded from `execute_effect_at_hex`), not the caster; caster-centered effects fall back to the caster. Only DEX saves benefit.
- **`cheap_cluster_lab`** (`tools/labs/cheap_cluster_lab.bat`): Gareth Spike Growth / Elara Web over an ally (Valeria) for D-ZONE-1; Kael's longbow at a 190-ft Distant Sentry (long range) and over an adjacent Goblin (in-melee) for D-ACT-4; an Exposed + a Covered Cultist flanking a three-quarters-cover wall for D-ACT-3's Fireball save.
- **Playtest round 1 (OublietteDev):** D-ZONE-1 ✅ and D-ACT-4 ✅ live-verified (zone hits allies; ranged disadvantage fires for both long-range AND a foe within 5 ft of the shooter, whichever target he picks). D-ACT-3 **looked broken but isn't** — cover is measured from the blast's CENTRE (RAW), so centring the Fireball on the cultist gives it no cover (a creature at ground zero is fully exposed). Confirmed working end-to-end through the real `execute_effect_at_hex` path: with the wall between the blast centre and the target the save logs `[cover: +5]`. Reworked the lab to a two-cultist line (Exposed at the centre, Covered behind the wall at the blast edge) so the bonus shows up on the natural aim — Fireball the Exposed Cultist, watch the Covered one get +5. **OublietteDev re-tested with the new lab — D-ACT-3 confirmed working. Cheap cluster committed `f9b665e`; all three live-verified.**
- **RAW note from OublietteDev (→ D-CTRL-1, not this batch):** Spike Growth in the Arena uses a one-time DEX save; RAW it deals 2d4 per 5 ft *travelled* through it (voluntary or forced), no save. That's exactly the D-CTRL-1 "Spike Growth single hit, not per-5ft no-save" item in the heavy tail — already queued, deferred to that work.

**D-ACT-2 (player Grapple) + D-ACT-1 (Ready) — DONE & live-verified, committed `c442151` (suite 2321 green).**
- **D-ACT-2 — player Grapple.** `execute_grapple` mirrors `execute_shove` (contested Athletics vs the
  target's Athletics/Acrobatics; bard dice can swing it). Success → GRAPPLED (speed 0), held until the
  target spends its action to **Escape** (which contests *the grappler's* Athletics — a hero grab stores
  no fixed `escape_dc`, so `execute_escape_grapple`'s no-DC branch handles it) or the grappler is
  downed (`_reconcile_grapples` already frees it). RAW size cap honored (no target >1 size larger; the
  too-large path doesn't consume the action). Tactics-popup entry + click-an-adjacent-enemy flow (no
  sub-popup); `grapple_lab`. **OublietteDev confirmed:** grab works, ogre (Large) grabbable, grappler-death frees
  the target. No-escape/no-flee = AI behavior, correctly deferred to the AI rework.
- **D-ACT-1 — Ready.** The engine existed but was **unreachable + half-wired**. Added a two-stage
  `ReadyPopup` (pick action → pick trigger) to the Tactics popup. **All four triggers now fire** (only
  CREATURE_MOVES did): enters-reach (range-gated via `_trigger_in_range`), moves, **attacks** (fired at
  BOTH `execute_attack` and `complete_attack` — the AI/convenience path doesn't route through
  complete_attack), **casts** (at the universal `_mark_action_type_used` chokepoint, gated on
  `spell_level`, after the spell resolves). Each fire is a no-op unless someone readied that trigger, and
  a `_resolving_ready` re-entrancy guard prevents cascades. **Readied actions resolve by shape**
  (`manager.resolve_readied_action`): a placed radius burst (Fireball) does its **full AoE centered on
  the trigger creature's hex** (reuses `_resolve_effect_targets_at_hex`); a save spell (Hold Person)
  resolves via `resolve_effect` (which deducts the slot + starts concentration itself — do NOT also call
  `start_concentrating`, that double-call ends the first instance and strips the linked condition); an
  attack resolves as **exactly one** `resolve_attack` — multi-ray/dart spells (Scorching Ray, Magic
  Missile) bundle all rays into the damage list, so looping by `target_count` would multiply the whole
  bundle (the Magic-Missile-9-darts bug OublietteDev's question surfaced). Filter (`ready_popup.is_readyable`):
  attacks + single-target save spells (one_creature/ally/**enemy** — Hold Person is `one_enemy`, my first
  filter wrongly excluded it) + placed sphere/cylinder bursts; excludes self, zones, and the directional
  cone/line/cube shapes (those wait on D-AOE-1). **Slot spent on release**, not at ready — a deliberate
  player-friendly deviation from RAW (OublietteDev explicitly preferred it). `ready_lab`.
- **Latent bug fixed en route:** `try_move` now refuses voluntary movement when a condition has zeroed
  the mover's speed (paralyzed/stunned/grappled/restrained/petrified/unconscious). The AI walks a path
  **hex-by-hex** and its loop only broke on death — so a readied Hold Person that paralyzed a mover
  mid-path used to let it keep strolling. One central guard fixes both the AI walk and the GUI. **OublietteDev
  confirmed Hold Person now freezes the target; Magic Missile dealt one cast (12 force, 3 darts).**
- GOTCHA reaffirmed: the GUI's normal single attack is `execute_attack_hit_check`→`complete_attack`;
  `execute_attack` is the AI/volley/convenience path and resolves via `resolve_attack_*` directly (never
  through complete_attack) — anything that must fire on "a creature attacked" has to hook BOTH.

**D-CTRL-1 — control-spell signatures (full repo suite green; new `test_ctrl_spells.py` +31, `ctrl_lab`). All five sub-mechanics DONE & LIVE-VERIFIED by OublietteDev** (after the playtest-fix round below). Order was OublietteDev's call: CTRL first, then the geometry pair.
- **Chain Lightning** — data only. The resolver (`chain_effects.py`) + manager wiring (`manager.py` ~3000) already existed; the JSON just never set the chain fields. Added `chain_target_count:3` + `chain_range:30` to `chain_lightning.json`; it now arcs to 3 secondaries (each rolls its own save).
- **Slow — action economy.** Modeled off the existing **"Slow" debuff buff** (already carries speed×0.5 / AC−2 / DEX-save−2) rather than a new condition, so the whole effect ends as one unit on the spell's end-of-turn re-save — no buff/condition desync. `condition_effects.is_slowed()` keys off that buff; `can_use_action_type` now bars reactions and gives a slowed creature an action **XOR** a bonus (either slot only while NEITHER is spent). New `manager._reaction_blocked()` folds Slow (and Confusion) into every reaction-eligibility site (OAs, Shield, Parry, Counterspell, Uncanny Dodge).
- **Spike Growth — per-5ft no-save hazard.** New `Action.movement_hazard` + `ActiveZone.movement_hazard_dice/type`; hazard zones are SKIPPED by the normal start-of-turn/entry save tick and instead deal their dice (2d4) on **every 5-ft step** via new `zones.process_zone_movement_step`, hooked into `_commit_move`. No `already_damaged` guard (every step hurts, including the entering step). Difficult terrain still laid down. JSON: `movement_hazard:true`, `damage_on_success:"none"`. **Movement model is hex-by-hex** (GUI `_advance_player_move` + AI both call `try_move` per adjacent hex), so per-step = per-5ft. **SIMPLIFICATION:** forced movement (push/pull into spikes) teleports to the final hex, so it does NOT yet trigger per-5ft damage — needs a hex-line path reconstruction (no line helper exists yet). Voluntary walk-through is the playtest path and works end-to-end.
- **Spirit Guardians — difficult terrain.** New `difficult_hexes` param on `get_reachable_hexes`/`find_path` (bumps a hex's enter-cost to ≥10), threaded through `MovementTracker`. New `ActiveZone.slows_movement` + `Action.zone_slows`; `manager._get_zone_difficult_hexes(creature_id)` computes the slowing-aura hexes affecting the mover (enemy of caster; caster/allies spared) and sets `movement.difficult_hexes` at turn start (the aura is static during an enemy's turn). JSON: `zone_slows:true`. The radiant save-damage was already there; this adds the slow.
- **Confusion — d10 behavior table.** New `CONFUSED` condition (+ `CONDITION_DISPLAY` "CF" badge). JSON now applies `confused` (not `incapacitated`) on a failed save → end-of-turn Wis re-save (Hold Person pattern), concentration-linked. Start-of-turn hook `_process_confusion_turn` rolls a d10: 1=`_confused_random_move` (full move, random hex direction, no action), 2-6=freeze, 7-8=`_confused_attack` (one melee vs a random **adjacent** creature — friend or foe — via low-level `resolve_attack`), 9-10=act normally (falls through). Short-circuits BEFORE AWAITING_ACTION so it auto-resolves for both PC and AI. Can't take reactions (folded into `_reaction_blocked` + `can_use_action_type`). SIMPLIFICATIONS: random walk doesn't provoke OAs; "reach" = 5 ft.
- **`ctrl_lab`** + new lab caster **`characters/control_warden.json`** ("Cassia the Confounder" — level-11 wizard chassis off Elara with full slots 1-6 and all five control spells appended; built so one hero can demo everything). Pack of Ogre+4 goblins clustered for Chain Lightning; a Bruiser starts adjacent to Cassia so a Confusion "lash out" has a neighbour. **GOTCHA: the lab caster EMBEDS copies of the spell actions (character actions are inline, not file refs) — editing a spell JSON does NOT reach the warden until it's regenerated** (re-run the generator: deepcopy Elara, append the five current spell JSONs, full slots).

**Playtest round 1 (OublietteDev, commit 3b670b1) → fixes (full repo suite green; test_ctrl_spells +6 = 31).**
- **Chain Lightning: WORKING AS INTENDED (RAW), no change.** OublietteDev expected a sequential bounce (arc 30 ft from each new target). RAW Chain Lightning is "three bolts leap from [the first target] to as many as three other targets, each within 30 ft **of the first target**" — not a chain-of-chains. His two flanking enemies were ~25 ft from the primary, so all three legitimately got hit. Explained; resolver was already correct.
- **Confusion "did nothing" was just a d10 roll** (2-6 = 50% "freeze"). Not a bug — but the screenshot's "save None DC None to end" surfaced a REAL bug: **Confusion was being routed as a persistent condition-CLOUD** (`_is_zone_creating_spell` matches concentration+area+conditions_on_fail). So nobody was confused at cast, the condition only applied on start-of-turn-in-cloud with NO re-save, and it evaporated the moment a creature left the 10-ft sphere. **Fix:** new `Action.aoe_condition_once` (Confusion + Slow set it) excludes such spells from zone routing → they resolve as a one-time burst, applying the condition AT CAST with a proper end-of-turn Wis re-save, concentration-linked, riding the creature wherever it goes.
- **Confusion random walk now provokes opportunity attacks** (OublietteDev asked): `_confused_random_move` routes each step through `try_move` (OA checks + zone/hazard entry) instead of the raw movement tracker. OAs auto-resolve (prompts disabled) since it's mid-auto-resolution — a player reactor doesn't get an Attack/Skip popup mid-stumble.
- **Slow "doesn't work / monsters unaffected" — TWO bugs.** (1) **No visible indicator:** Slow applied as a buff, and token badges only render *conditions*. Fix: added a `SLOWED` condition (the "SL" badge + now the `is_slowed()` source — badge and action-economy limit stay in lockstep); the speed/AC/DEX-save penalties still ride on the "Slow" buff alongside it; both applied on the same failed save, both concentration-linked, both re-save end-of-turn at the same DC. (2) **THE BIG ONE — main-save DC was hardcoded ~10.** `resolve_effect` computed `dc = save.dc or 10`, and **81/87 SRD spell JSONs carry `dc: null`**, so every Arena-native caster's save spell (Fireball, Slow, Confusion, …) resolved against DC 10 regardless of the caster (a level-11 wizard's Slow was DC 10, not 15). `dc_ability` was never consulted either. New `_resolve_save_dc(user, action)`: explicit `save.dc` wins (bridge/stat-block), else `dc_ability` (monster: 8+prof+mod), else caster spell DC (8+prof+spellcasting mod), else 10. Used for the main save AND the buff re-save. **Latent, pre-existing, repo-wide — and it passed the ENTIRE suite with zero fallout** (nothing depended on the DC-10 default). Bridged PCs (whose `save.dc` is injected) are unchanged.
- Spirit Guardians, Spike Growth confirmed working by OublietteDev ("just as powerfully broken as RAW").

**D-AOE-1 — AoE shape geometry (full repo suite green; new `test_aoe_shapes.py` +15; `aoe_lab`). DONE & LIVE-VERIFIED by OublietteDev** (after the GUI-aiming fix below + the QoL round). Cone/line/cube no longer resolve as radius bursts.
- **Geometry lives in new `arena/grid/aoe_shapes.py`:** `aoe_hexes(action, origin, aim, grid)` dispatches by `target_type` — sphere/cylinder = radius from the aim hex; cube = offset-square around the aim; **line** = a 5-ft-wide hex line emanating from the caster toward the aim, extended to full length; **cone** = a widening wedge (pixel-space angle ≤ 30° of the aim direction, within length). **Reuses the existing `hex_line` cube-lerp from `line_of_sight.py`** (the very primitive that was the precondition for forced-movement spikes — it already existed, used by LOS/cover). Placed shapes (sphere/cube) center on the aim; emanating shapes (line/cone) start at the caster and the aim only sets direction.
- **Targeting:** `_resolve_effect_targets_at_hex` now builds the shape hex set and keeps creatures whose **footprint overlaps** it (was: everyone within `area_size` of the clicked hex). Lightning Bolt is a real line — zaps the row, spares the creature one row off it.
- **GUI preview:** `_render_aoe_preview` highlights the same `aoe_hexes` set (preview == reality) and the friendly-fire red-warning reuses it. Emanating shapes skip the placement-range gate (they aim by direction, self-limit to length) — fixes the latent bug where `range:0` cone/line spells couldn't be aimed at all.
- **Spell data was already correct** (`lightning_bolt`=line, `burning_hands`/`cone_of_cold`=cone, `thunderwave`/`slow`=cube) — only the resolver was wrong. Added Thunderwave's RAW **push 10 ft** (was missing) so it can shove into spikes.
- **FOLDED-IN: forced movement into Spike Growth (OublietteDev's queued item).** Forced movement teleports straight to the destination (no per-step hook), so new `zones.process_zone_movement_path(from, to, …)` reconstructs the shoved path via `hex_line` and deals one hazard tick (2d4, no save) per spike hex crossed — "2d4 per 5 ft travelled (voluntary OR forced)". Hooked into `_apply_pending_forced_movement`. Verified end-to-end: Thunderwave shoves a goblin through Spike Growth → thunder damage + per-hex piercing.
- **`aoe_lab`** + new lab caster **`characters/aoe_warden.json`** ("Vesper the Geometer" — lvl-11 wizard off Elara with Lightning Bolt/Cone of Cold/Burning Hands/Thunderwave/Spike Growth/Fireball + full slots). Line cultists in a row with an off-line flanker; a cone cluster; a Shove Dummy for the Thunderwave→spikes combo.
- **SIMPLIFICATIONS (first pass):** areas aren't clipped at walls/total cover (revisit with D-WALL-1's LOS work); cone is an angular approximation, not an exact RAW template; cube is an offset-square approximation; 5-ft line is exactly 1 hex wide. GOTCHA reaffirmed: **lab casters EMBED spell copies** — regenerate the warden after editing a spell JSON.

**QoL round (OublietteDev, committed `99321c1`; live-verified — "Confirmed it all works"). Right-click cancel + lab ergonomics (suite green).** (1) **Right-click anywhere now cancels an in-progress spell aim / hex placement** — `_handle_right_click` previously only cancelled when the click landed near your own token (extracted `_is_targeting`/`_cancel_targeting`; far-from-token while aiming → cancel, on-token → cancel + reopen radial menu). (2) **aoe_lab ergonomics for the shove-into-spikes test:** the Shove Dummy is now a new immobile 400-HP `monsters/training_dummy.json` (speed 0, STR 6, no actions — survives all day, easy to push), and Vesper gained **"Practiced Shove"**, a BONUS-action 10-ft push with no save (forced movement always applies when `save_success is None`), so Spike Growth (action) + shove (bonus) land in ONE turn — Thunderwave (full action) still works too. test_aoe_shapes +1 (=15: end-to-end no-save push through spikes via the manager).

**🐛 Practiced-Shove-after-a-cast bug — FIXED (commit `2221c21`, suite green; `test_radial_ability_slot.py` +1).** Root cause was suspect (b), but sharper: **Practiced Shove lives in `creature.actions` with `action_type=bonus_action`, NOT in `creature.bonus_actions`.** The radial menu only treats `bonus_actions` entries as bonus slots; an `actions`-list entry gets categorized as an Items/Abilities slot, and those slots hardcoded `is_disabled=action_used`. So spending the **action** (any spell cast) greyed out the bonus shove for the rest of the turn — even though its bonus slot was untouched. The engine executed it fine (the manager-level cast-then-shove was already unit-tested green in `test_aoe_shapes`); only the GUI gating was wrong. **Fix:** new `RadialMenu._slot_used_for(action)` gates each utility slot on the action's *real* `action_type` (bonus→bonus slot, reaction→reaction slot, else action slot), mirroring `ItemsPopup._is_disabled` (which already did this for items). Group slots now grey only once every contained action's slot is spent. Generalizes to any bridged/homebrew bonus-typed action stored in `actions`. (Lesson again: the bug lived purely in GUI gating; the engine path was already correct + tested.)

**Playtest round 1 (OublietteDev, commit 81d794f) → GUI aiming fix (full repo suite green; test_aoe_shapes +3 = 17).** OublietteDev: Lightning Bolt + Cone of Cold "still a sphere, activates the second I click"; Thunderwave/Fireball fine. Root cause was NOT the embedded data (target_types were correct `area_line`/`area_cone`) — it was the **GUI cast FLOW for range-0 AoE**. Two GUI gates assumed every range-0 area spell is a self-centered burst (written for Spirit Guardians/Turn Undead): (1) the radial-menu selection at `combat.py:~1509` cast range-0 area spells **immediately, centered on the caster** (aim = caster hex → for a line/cone, origin==aim → my new geometry returns an EMPTY set, so it actually hit nothing while *looking* like the old caster-centered sphere), and (2) the SELECTING_TARGET click gate `dist_feet <= range` rejected every aim-click for a range-0 spell. Why Thunderwave worked: Elara's embedded copy is range **5** (placed flow), not 0. **Fix:** new pure predicate `aoe_shapes.is_emanating(action)` (line/cone) used in 3 GUI spots — emanating shapes are excluded from the self-centered immediate cast (they enter the normal aim phase) and their aim-click is gated by **length (area_size)**, not placement range. Preview already aimed correctly. Verified in `aoe_lab`: Lightning Bolt aimed east hits the cultist row + spares the off-line flanker; Cone of Cold aimed at the cluster fans out. **Lesson reaffirmed (test the real path): the manager-level cast (`execute_effect_at_hex` with a real aim) was always correct and unit-tested green — the bug lived entirely in the GUI's range-0 routing, which no unit test exercised.**

**D-WALL-1 — wall spells as real barriers (commit `b5ce6d3` + lab polish `6cf7b0c`; full suite green: arena 2384, oubliette 469; `test_wall_spell_combat.py` +13; `wall_lab` + `wall_warden`). THE LAST PHASE D MECHANIC — Phase D is now CLOSED & LIVE-VERIFIED by OublietteDev ("This seals it: Phase D is done").** The wall MODEL (panels, blocking flags, concentration cleanup) + the movement/LOS-blocking wiring already existed but were **unreachable dead code**: nothing called `_execute_wall_spell`, `wall_damage_on_enter` was stored but never read, and the spell data carried no `is_wall`/`wall_*` fields (Wall of Fire was a plain DEX-save line burst). Now walls are live, aimable, and dangerous.
- **Cast entry:** `manager.execute_wall_line(start, end)` draws the wall as a hex line between two points (`hex_line`), capped at `wall_length`; routes to `_execute_wall_spell` (slot + concentration). `_is_zone_creating_spell` now excludes `is_wall`, so a concentration+area+save wall never mis-routes as a lingering cloud.
- **Blocking is immediate:** `_execute_wall_spell` refreshes `movement.blocked_hexes` right after creating the wall (otherwise only recomputed at turn start, so the caster's own remaining movement would ignore a fresh wall).
- **Entry damage (the dead `damage_on_enter`, now live):** `process_wall_movement_step` (hooked in `_commit_move`, beside the Spike Growth hazard) burns a creature that *steps into* a damaging wall; `process_wall_start_of_turn` burns one that *starts its turn* inside; on-cast, a wall materialising atop a creature burns it. No save (RAW Wall of Fire ongoing); caster spared; mirrors `zones._apply_hazard_tick` (magical packet + concentration check).
- **GUI:** two-click line placement (pick spell → click one end within range → click far end). Live preview reuses the same `hex_line`+cap so **preview == reality**; right-click cancels; `_is_targeting`/`_cancel_targeting` know the new `_pending_wall`/`_wall_anchor` state.
- **Data:** tagged Wall of Fire (opaque/passable, 5d8 fire on entry), Wall of Ice (block move+LOS, 10d6 cold), Wall of Thorns (block move, 7d8 piercing), Blade Barrier (passable, 6d10 slashing); **authored the two pure barriers the SRD gen had skipped** — Wall of Force + Wall of Stone (block move+LOS, indestructible). Manifest updated.
- **SCOPE (pragmatic slice, OublietteDev's call):** indestructible while concentrating (panel-HP / attacking-a-wall deferred — the model supports it via `WallPanel.max_hp`/`damage_panel`, just no attack-a-hex routing); damage-side nuance simplified ("inside the wall always burns", no one-chosen-side); on-appear DEX save modelled as a no-save tick.
- **Bench:** `wall_lab` + `wall_warden` ("Mason the Wallwright", L11, all six walls, full slots 1-6) + `wall_lab.bat`. **GOTCHA reaffirmed:** the GUI two-click flow + preview aren't exercised by any unit test (pygame); the manager path they call IS fully tested.
- **Lab-polish round (commit `6cf7b0c`, live-verified by OublietteDev):** two playtest fixes. (1) **Placed walls were invisible** — a wall blocks even when narratively invisible (Wall of Force), so enemies stopped at thin air with no cue. New `CombatScreen._render_active_walls` draws each active wall's hexes per frame, color-keyed by type (fire=orange/ice=cyan/thorns=green/blade=silver/stone=grey/**force=faint blue shimmer**) with a gentle global pulse; mirrors `_render_aoe_zones`. (2) **Length fencepost** — a 100-ft wall placed as 21 hexes = 105 ft; the cap limited gap-count (distance), but an N-hex wall spans N-1 gaps. New `CombatManager.wall_line_hexes(start, end, action)` is the single source of truth (caps the hex COUNT at length/5), shared by `execute_wall_line` AND the GUI preview → preview==reality guaranteed. 100-ft walls are now exactly 20 hexes. (Lengths themselves are RAW: 100 ft Force/Stone/Ice/Blade Barrier, 60 ft Fire/Thorns.)

**🏁 PHASE D COMPLETE.** Every SRD-5.1 combat mechanic in the audit is now coded in (D-MON 1-6, D-COND 1-3, D-ZONE-1, D-ACT 1-4, D-CTRL-1, D-AOE-1, D-WALL-1). Out-of-scope-by-decision: downed-PC RAW, multiattack-for-AI + monster spellcasting (AI rework), lair-action CONTENT (no SRD data), Surprise Attack (needs an ambush subsystem), destructible-wall HP (Forge/homebrew pass). See `docs/roadmap/oubliette-phase-d-plan-v0.1.md`. **Next: OublietteDev's live playtest of the wall_lab + Shove fix, then the post-Phase-D direction call (AI rework? Forge editors? audio arc?).**

---

## 6. The worlds

- **Brightvale** (`packs/brightvale/`) — the small, default, **standalone** pack and the
  sentimental one (OublietteDev + his wife + Opus 3). A market square, a gate, the merchant Thom. Handle
  with care; it's coupled to several tests (see "creature coupling" in the gotchas).
- **Atria** (`packs/atria/`) — OublietteDev's **real, actively-developed world.** Note: **the city
  inside Atria is itself named "Brightvale"** (place ids are `brightvale_*`) — distinct from the
  standalone Brightvale pack; don't confuse them. Atria's Brightvale is a coastal city on
  Silverfin Bay with districts (the Coin Quarter/market, Silverfin Docks, the Palladian Ward
  government district, the Lantern & Wake tavern) and **Seraphel's Roost**, an island out in the
  bay (its own top-level region). Cast: Governor Eustace Broadbarrel, Elder Elaida, Captain
  Bromley (the gossipy boat captain), and **Seraphel**, a grief-touched ancient protector dragon.
  The backstory (Alden the fisherman-founder who freed Seraphel and died saving the city) lives
  in `the_story_of_alden.md`.

---

## 7. Authored quests (the most recent feature — how it works)

World authors can now pre-write quests in The Forge, offered to the party during play (before
this, quests were only emergent). Key design, decided with OublietteDev:

- **Every quest is tied to exactly one source:** a **giver NPC** *or* a **place** (a place-given
  quest carries a "found at a notice board in <location>" discovery note, so the DM presents it as
  *found*, not handed over). Never ambient.
- **Two layers of text:** a **player-facing hook** and a separate **DM-only briefing** (the secret
  truth/twist/intended ending the players never see directly).
- **Advisory rewards** — gold/item/note shown to the DM, who grants them through the normal tools
  (renegotiable). The engine never auto-grants.
- **Branching chains** — completing a quest can fork to different next-quests based on the
  **outcome** the DM reports ("spared" → quest B, "killed" → quest C). Chains are an implicit
  graph; a quest is reachable if it's a root or some branch's target.
- **Two-tier discoverability** so quests aren't invisible until stood-upon:
  - *In-region (ambient):* anywhere in the party's **top-level area** (e.g. all of the city), the
    DM gets a sparse signpost — counts + locations + each quest's optional **rumor** line — so it
    can nudge the party toward where work is, **without** leaking hook/briefing/outcomes.
  - *At the source:* only on arrival does the DM get the full hook + secret briefing + reward +
    outcomes, and only there can it accept the quest.

**Implementation notes for whoever touches this:** authored quests live in `quests.json` and as a
separate session layer (NOT canon). The runtime uses an `accept_quest` tool; the offer set is a
**pure, replay-stable derivation** (`oubliette/quest/offers.py`) recomputed from the event log
each turn (the authored-quest link rides the quest-started record; the chosen outcome rides the
quest-updated payload and is never applied to state — so reload reproduces offers byte-identically).
Two refinements from playtesting: a **single-branch (linear) step auto-advances** on completion
even without an outcome (only genuine forks require one), and an accepted authored quest **keeps
its briefing + reward + fork-outcomes in the DM's active-quest context for its whole life**, not
just at the offer. Atria ships a seed set: a 3-stage branching chain ("The Empty Nets") and a
one-shot ("A Light Coin-Box").

---

## 8. Conventions & gotchas that keep things from breaking

These are hard-won. Internalize them.

- **THE STALE-SERVER GOTCHA (this bites the most often).** Oubliette-side code — DM prompts,
  the context builder, the combat bridge — are loaded into memory when the app server starts. After
  changing any of it you **must fully restart `python -m oubliette.app.server`.** The in-game
  "Reload world" button only re-reads the *pack*, not the *code*. (Portraits hot-reload, and the
  Arena spawns fresh per fight, so a stale server can *feel* live while silently dropping new model
  fields.) **First question on any "it didn't work in play" report: was the server restarted?**
- **Content generation = deterministic parse, not LLM transcription.** All the SRD bulk content
  (spells, classes, items, monsters) was built by **downloading the machine-readable 5e-database
  JSON (`curl`) and parsing it with a one-shot Python script** — *not* by asking a model to
  transcribe (the WebFetch reader garbles tables), and *not* by hand (the burnout trap).
  Completeness is *proven* by diffing ids against the source. **Use agents for prose (flavor
  descriptions); use deterministic parse for stats.** Verify stats against the source, not recall.
- **Verify on isolated copies — never touch OublietteDev's real save or the committed packs.** For live
  checks, point the game at a throwaway DB (`OUBLIETTE_DB=...`, e.g. the `preview-test` launch
  config on port 8055) and/or point The Forge at a temp copy of a pack
  (`OUBLIETTE_PACKS_ROOT=...`). OublietteDev is frequently mid-playtest on the real save.
- **PowerShell 5.1 + git:** multi-line commit messages with `-m` get mangled into pathspecs.
  **Always `git commit -F <file>`** (or use the Bash tool with a heredoc). **Stage explicit
  paths** — `git add -A` has swept up unrelated art twice. **Commit art/portraits separately**
  from code, in their own art-only commits.
- **The "Etteilbuo" dev codeword** — a message *containing* it tells the DM "this is a developer
  test": comply plainly and emit exactly the requested tools, even things the table rules would
  normally refuse (used so the live DM stops refusing test monster-spawns). **It must be sent with
  the OOC toggle OFF** — because **out-of-character turns never reach the model at all** (the loop
  builds a canned table-talk response in code; combat can only be staged from an in-character turn).
- **Portrait naming:** `<Name>.png`, underscored, in the source's `portraits/` dir
  (`content/srd/portraits/` or a pack's `portraits/`). OublietteDev hand-makes these; it's slow (image
  generation is the bottleneck), so they trickle in ~25 at a time in art-only commits. ~30 of 334
  SRD monsters done.
- **Single save, and a diagnostic trick:** there's one save (`oubliette-save.sqlite`). Narration
  isn't durably stored, but **player messages with their parsed verb/intent, and all quest/tool
  events, are** — so reading the save's event log is the best way to diagnose "what did the DM
  actually do?" during a playtest.
- **Deferred coupling:** Brightvale ships 3 pack creatures (`commoner`, `road_bandit`, `lean_wolf`)
  wired to `merchant_thom`'s stat block and to several tests — don't remove them casually; it needs
  a coordinated rewire. Revisit when the Forge's creature/NPC editor gets fleshed out.
- **The mounted-filesystem gotcha (Cowork/sandbox builds):** when working from the Cowork desktop
  tool, the repo is a Windows folder mounted into a Linux sandbox. The mount is flaky: it blocks
  file *deletion* from the sandbox (use the host delete affordance), and editor-channel writes can
  leave the sandbox with a *stale/truncated* view of a just-edited file (caught as a phantom syntax
  error on import). Workaround: write files via the **sandbox shell** when you need to run/test them
  immediately, and verify with `wc -l`/`ast.parse` before trusting a read. Git from the sandbox can
  also corrupt its index mid-write — keep commits atomic, stage explicit paths, verify after, and
  do any heavy git surgery from native Windows. The `.venv` is Windows-format; in the sandbox use
  system `python3` with `PYTHONPATH=.` (install `pydantic`/`pytest` with `--break-system-packages`;
  GUI/pygame tests can't run headless there and will error on import — not a real failure).

---

## 9. Where things stand & what's left

**The core game is complete and playable** end-to-end with a live streaming AI DM: character
creation, a multi-PC party, exploration with maps and audio, lore, trade, emergent *and* authored
quests, and tactical combat in the Arena.

**Phase C progress (as of the 2026-06 build sessions):** C1–C3 done (feature bridge, monster
data, spell curation 58→130). **C4 — P-VISION-LIGHT is COMPLETE**: fog/darkness/daylight as
obscuring/light zones with faithful pairwise vision (you can't see / can't be seen → advantage &
disadvantage cancel; darkvision does NOT pierce fog/magical darkness, blindsight & truesight do;
daylight dispels magical darkness of ≤ its level), plus the detection trio (See Invisibility, True
Seeing, Mislead). Attack/save log lines now carry a roll-type label (`[normal]`/`[advantage:…]`/
`[disadvantage:…]`). **C4 — P-CONTROL Dominate Person/Beast/Monster is COMPLETE**: a failed WIS
save flips the target to the caster's `team` + `is_player_controlled` (the radial then drives it
with its own actions — the turn loop keys off `is_player_controlled`); reverts on the caster losing
concentration or the target succeeding a WIS re-save when it takes damage; creature-type gated.
Full control is a deliberate simplification of RAW (caster-commands-each-turn) — fun > fiddly.
Lives in `arena/combat/domination.py`. **Compulsion is now BUILT** (`arena/combat/compulsion.py`):
WIS save → a COMPELLED condition that, at the start of the creature's turn, drags it toward the
caster (forced "pull", spends its full speed) and bars its reactions; concentration-linked,
reverts via the generic cleanup. Simplified vs RAW to single-target / toward-the-caster /
no per-turn re-save. **C4 — condition-zones / P-TERRAIN is COMPLETE**: `ActiveZone` now
applies a condition on a failed start-of-turn/entry save (folded into `_resolve_zone_damage`) —
Stinking Cloud (CON save or incapacitated, ≈ "lose your action"), Sleet Storm (DEX save or prone +
heavily obscured + difficult terrain), Plant Growth (instant difficult terrain, no save/zone). Zone
effects stay enemies-only (RAW hits all — a noted simplification). **C4 — Bardic Inspiration &
Cutting Words is COMPLETE** (`arena/combat/bardic.py`): a banked inspiration die flips an attack —
the inspired creature adds it (own miss → hit), a defending bard subtracts it via Cutting Words
(enemy hit → miss). **→ C4 is COMPLETE and its whole punch-list is now CLOSED** (the 2026-06-25
"wrap-up" session — commits 32db19f / 3a94ef7 / 2a6b149 / 6069630, 2586 green): (1) **real bard
sheets feed the pools** — `arena_bridge._bardic_resources` injects inspiration USES (CHA mod, min 1)
+ DIE size (d6→d8→d10→d12 at L1/5/10/15) and the feature-bridge emits a `cutting_words` Feature for
College of Lore bards, so it lights up from a genuine story→Arena handoff (not just hand-set
resources); (2) **dice now cover saves / contested checks / damage**, not just attacks (Bardic
Inspiration rescues a near-miss save or a lost grapple/shove contest; Cutting Words docks a
contested check and blunts a would-be-lethal damage roll) — still auto-optimal; (3) **player-choice
prompt** — a spend/skip popup on a player attacker's missed attack (own-attack only; NPCs auto-spend;
`BardicInspirationPopup` + manager `_pending_bardic_choice`, mirroring the reroll-popup pattern) —
**LIVE-VERIFIED by OublietteDev (2026-06-25)**: grant→spend→empty→re-grant loop all confirmed in `bard_lab`.
The fix-ups it took to get there: the GUI player path is `execute_attack_hit_check`→`complete_attack`
(NOT the `execute_attack` convenience method) — the prompt had to suppress auto-spend + defer there
(commit 84902cc); and the popup-positioning copied a `GridView.hex_to_screen` call that doesn't
exist — both the bard popup AND the latent forced-save-reroll popup now center on screen (commit
743ddfc). The prompt only fires when the die *could* reach the AC (miss-by ≤ die); else no prompt.
(4) Compulsion (above). Also fixed Cowork-session suite drift that was left red: 4 stale `adv:`/`dis:`
label assertions + the missing DOMINATED display badge. **→ Every C4 item is now live-verified or
unit-tested; 2587 green.** Per-feature playtest labs: `vision_lab`, `dominate_lab`, `terrain_lab`,
`bard_lab` (launch via `tools/lab.py <name>`; `bard_lab` has an AC-15 Practice Dummy so every miss
pops the prompt, plus Lyric for the grant + auto Cutting Words demo).

**Open / future work (roughly in the order it tends to come up):**
- **Stretch C4 one-offs** (metamagic, time stop, antimagic…) — mostly "do last or never". (The
  deferred Compulsion and the bard approximations are now DONE & live-verified — see above. Could
  still extend the spend/skip prompt to saves / Cutting Words if play wants the choice there; today
  those stay auto-optimal.)
- **Arena UI/UX cleanup pass (someday, BIG)** — OublietteDev's call (2026-06-25): the Arena was never
  optimized for looks on its first pass; it's functional but ugly. A dedicated visual/UX overhaul is
  wanted eventually — not scheduled yet. See [[oubliette-arena-ui-cleanup]].
- **C5 stragglers — DONE (2026-06-25, unit-tested, not yet live-played):** (1) **prone movement
  penalty** — a "Stand Up" Tactics entry (shown only while prone, like Escape-when-grappled) spends
  half your speed and clears prone; it's *movement, not an action*, so it stays available after you
  attack and even when the action is spent. Crawling now costs double per hex via a `cost_multiplier`
  on the movement tracker + a `cost_multiplier` arg on `get_reachable_hexes` (the old blanket 0.5
  budget-halving was replaced so standing composes correctly — `get_movement_cost_multiplier()` in
  `condition_effects.py` returns 2 while prone). (2) **re-prepare spells on long rest** — a prepared
  caster swaps its readied list inside a window that **opens on a long rest and closes once the party
  acts** (`reprepare_window_open(events)` in `rules/rest.py` — pure log derivation: latest long-rest
  seq > latest player_message seq). **Faithful split** (OublietteDev's call): cleric/druid/paladin prepare
  from their WHOLE class list; wizard only from its spellbook (`spells_known`) — driven by a new
  `prepares_from_spellbook` flag on `SpellcastingProfile` (set True on wizard in classes.json).
  Event-sourced via a new `spells_prepared` StateOp + `EventKind.SPELLS_PREPARED` + `repo.set_spells_prepared`
  (replay-stable). Firewall = `derive.validate_prepared_choice` (exact count, no dupes, drawn from
  `derive.prepare_pool`). New `/api/prepare_spells` endpoint; sheet now carries `preparation` /
  `can_reprepare` / `prepare_pool` / `prepared_ids`. UI: a "Prepare Spells" button + checkbox modal
  on the character sheet (index.html), enabled only while the window is open. **C6:** the final
  "ship-readiness" combat playtest — **lab battery now BUILT** (see below).
- **The Forge creature/NPC editor** — currently the weakest authoring section; enriching it would
  also unblock the deferred Brightvale-creature cleanup.
- **More portraits** — the ongoing art grind (OublietteDev). 56/334 as of this session.
- **Possible later:** richer cross-turn "session memory" for the DM; non-gold coinage (a purist
  nicety, probably never).

**Per-feature test beds (the C6 battery):** standalone Arena encounters launched by name via
`tools/lab.py <name>` (or a root `.bat`) drop you straight into a fight to playtest in isolation.
A lab is `arena/data/encounters/<name>_lab.json`; combatants are **referenced** by `creature_id`
(`characters/<pc>.json`, `monsters/<m>.json` — compact & robust) or **inlined** via `creature_data`
(needed only when you must pre-apply a condition/HP — inline validates as base `Creature`, so it
loses PlayerCharacter machinery like death saves; reference a real PC when you need those). Every
entry still needs a `creature_id` label even when inlined (use `lab/<x>`). `tools/lab.py` auto-lists
all encounters if the name is unknown. **`arena/tests/test_labs_load.py` guards the whole battery
loads** (headless `CombatManager.load_encounter`). Benches now on hand:
- `vision_lab`, `dominate_lab`, `terrain_lab`, `bard_lab` (C4 features).
- **`prone_lab`** (C5) — inline prone Crawler (player-driven) + a 0-speed Prone Dummy (stays down) +
  Valeria + goblins: Stand Up, crawl-doubling, melee-adv / ranged-dis vs prone, shove-to-prone.
- **`martial_lab`** — Valeria (Pal) + Shade (Rogue) + Thorin (Ftr) vs ogre/hobgoblin/goblins:
  Divine Smite, Sneak Attack, Action Surge, Second Wind, multiattack, opportunity attacks, Uncanny Dodge.
- **`caster_lab`** — Elara (Wiz) + Brother Aldric (Cleric) vs skeletons/zombies/orc: concentration
  + damage-saves, Hold Person, Web, Sculpt Spells, Magic Missile, Spirit Guardians, Turn/Destroy
  Undead, Cure Wounds.
- **`downed_lab`** — squishy Lyric (L1 bard) + Willow + Aldric vs ogre/goblin: death saves, Healing
  Word pickup, Cure Wounds, stabilize, auto-crit on a downed creature.
- Easy future adds if play wants them: a grapple/escape bench, a Shield/readied-action reaction bench,
  Mirror Image / Banishment benches. Repo root tidied earlier: loose design docs →
  `docs/{design,roadmap,feedback}/`; SRD source dumps → gitignored `tools/raw/`.

**C6 playtest round 1 — OublietteDev's feedback + fixes (2026-06-25, 2628 green, unit-tested; not yet
re-played).** From a detailed grind across all four benches:
- *Confirmed working (no change):* prone Stand Up (the "15→15" he saw is correct — crawl is full
  budget at double cost = 15 ft of travel, standing spends half = 15 ft left, also 15 ft); Smites;
  Action Surge; Extra Attack/multiattack; concentration save-on-damage; auto-crit on a downed target;
  healing-to-revive; **one-concentration-at-a-time** (`start_concentrating` drops the prior spell —
  testable now with Web + Hold Person on Elara); **Sculpt Spells** (Elara HAS it — it's passive;
  test by Fireballing with Aldric in the blast: he takes 0).
- *RAW clarification, not a bug:* 3 death-save successes = **stabilized at 0 HP** (stops rolling),
  NOT standing with 1 HP.
- *Fixed (code):* (1) **Hidden now grants advantage** and attacking **reveals** you — `get_attack_advantage`
  never checked `HIDDEN` (only INVISIBLE/fog); added the advantage source + a reveal (clear HIDDEN)
  alongside the HELPED-clear in `actions.py`. (2) **Self-centered area spells auto-cast on the caster** —
  a range-0 `area_*` non-attack spell (Spirit Guardians aura, Turn Undead burst) now casts immediately
  instead of asking for a hex (`_handle_combat_action` in combat.py). (3) **Ally Stabilize** —
  new "Stabilize" Tactics entry (shown only when a dying ally is adjacent): a DC 10 WIS (Medicine)
  check on an adjacent unconscious PC → stabilized; the only non-healing way to stop a friend's death
  saves. `execute_stabilize` + `death_saves.stabilize_creature` + radial/popup/combat-screen wiring.
- *Fixed (data/lab):* (4) **Web** in Elara's char file was a stale single-target version → made it the
  proper 20-ft-cube zone (matches the spell library + RAW), so it now starts concentration on cast
  (visible badge) and restrains. (5) **Turn Undead** — Brother Aldric's file listed "Destroy Undead"
  but not "Channel Divinity: Turn Undead" (the name the bridge keys on) AND lab characters bypass the
  feature-bridge, so the action wasn't there at all → added the feature + baked the Turn Undead action
  (DC 15, 30 ft, undead-only) + a `channel_divinity` resource. (6) **caster_lab spacing** was ~70 ft
  caster-to-undead (Turn Undead is 30 ft / Spirit Guardians 15 ft) → tightened to ~25 ft so short-range
  abilities reach from the start.
- GOTCHA reminder: the re-prepare + any oubliette-side change needs the app-server restart; Arena
  labs load fresh each launch (no restart), so these combat fixes show up on the next lab run.

**C6 playtest round 2 — OublietteDev's second pass + fixes (2026-06-25, 2630 green).** The big lesson he
spotted: most of these were **stale LEGACY lab character files** (Shade/Aldric/Elara were authored
for the pre-bridge Arena), whose baked actions/features bypass the feature-bridge and so miss the
modern wiring. Fixes:
- **Cunning Action: Hide (Shade)** forced a click + didn't tag — his bonus actions had
  `standard_effect=None`, so the radial routed them to `select_action` (target mode) instead of the
  self-cast standard logic. Set `standard_effect` = dash/disengage/hide on all three Cunning Action
  bonus actions in shade.json. ALSO: attacking an unseen target now gives the attacker **disadvantage**
  — `get_attack_advantage` gained a HIDDEN-target case (mirrors INVISIBLE), so monsters swing at a
  hidden hero at disadvantage.
- **Spirit Guardians (Aldric) wouldn't auto-cast** — his legacy action had `range=15` (should be 0;
  the 15 is the *radius*), so the range-0 autocast missed it. Set range→0 AND broadened the autocast
  to fire on `range == 0 OR zone_follows_caster` (combat.py) so any caster-following aura self-casts.
- **Web → Hold Person left the web on the ground + restrained stuck** — `_cleanup_orphaned_zones`
  only checked "is the caster concentrating on ANYTHING," so switching Web→Hold Person (still
  concentrating) kept the orphaned Web zone. Now it compares the caster's current concentration spell
  name to the zone name, and when a zone fades it strips its condition (`source=zone.name`) off every
  creature. Fixes the lingering animation AND the stuck restrained.
- **Sculpt Spells (Elara) did nothing** — her feature had the *name* but `sculpt_spells=None` (the
  engine flag the bridge would set). Set `sculpt_spells: true` on the feature. Now an ally in her
  Fireball takes 0.
- Tests: arena/tests/test_combat_fixes.py grew (HIDDEN target disadvantage, zone-switch teardown).
- **Stabilize confirmed working live by OublietteDev.** ✅
- All six confirmed working by OublietteDev on the next pass; only two follow-ups remained (now both DONE
  below).

**C6 playtest round 3 — the last two combat features (2026-06-25, 2634 green).**
- **Frightened/turned creatures now flee.** A frightened creature's AI turn now moves it to maximize
  distance from its fear source (RAW "can't move closer"); if cornered (can't increase the distance)
  it falls through to a normal turn and attacks at disadvantage. `pathfinding.find_flee_destination`
  (max distance from one point) + `AIController._frightened_flee_dest` (maps the FRIGHTENED condition's
  `source` = caster name → that combatant's position) + an early branch in `plan_turn` before the
  HP-retreat check. Makes Turn Undead actually push undead away.
- **Opportunity-attack player prompt.** When an enemy's move provokes an OA from a PLAYER creature,
  an Attack/Skip popup now appears (`OpportunityAttackPopup`); AI reactors still auto-fire. Mechanism:
  `try_move` splits reactors — AI ones fire inline, player ones queue into `manager._pending_oa` and
  the move DEFERS (extracted `_commit_move`); `resolve_opportunity_attack_choice(make)` fires/skips
  each then completes the move. The GUI shows the popup + pauses the AI runner (mirrors the Shield/
  bardic reaction-popup pattern); `_advance_move_substep` pauses-not-aborts when `_pending_oa` is set.
  GATED by `manager._oa_prompts_enabled` (only the interactive CombatScreen sets it True) so headless/
  AI-only contexts keep the synchronous auto-fire — important because `ai/executor.py` also calls
  try_move and can't show a popup. Reaction economy was already correct (an OA consumes the one
  reaction/round). Tests: arena/tests/test_combat_fixes.py (flee plan; OA defer→attack, skip, AI auto-fire).

**The C6 audit-after-playtest open question (OublietteDev, 2026-06-25):** after the grind + straggler-bug
pass, run an audit for the last missing combat pieces — **legendary actions** and **lair actions**
are the suspected remaining gap (`Encounter` already has `has_lair`/`lair_actions` fields and the
manager tracks `legendary_points`, so some scaffolding exists — verify depth during the audit).

## Post-Phase-D: AI + Forge arc (started 2026-06-26)

Direction after the Arena was sealed. Goal: make monsters fight their stat block, then let
non-coders author monster behavior in the Forge. **Guiding split (locked with OublietteDev): competence
is free, personality is authored.** Competence = uses multiattack / casts its spell list / fires
signature abilities — automatic from the stat block, nobody authors it. Personality = how it
chooses (brave/cowardly, who it targets, melee/ranged, protects allies) — authored as an AI
*profile*, the only thing the Forge edits. Roadmap (this order, deliberate): **1) The Brain**
(pure code: multiattack → monster spellcasting → signature abilities); **2) Forge AI editor**
(easy mode = a few plain-English questions + presets; pro mode = full numeric knob board; both
write the same `AIProfile`, most knobs already in `arena/ai/behavior.py`); **3) Monster editor**
(create creatures, attach a profile). The Brain comes first because profile knobs are meaningless
without competence, and building it reveals which knobs are real.

- **Brain Slice 1 — Multiattack (DONE, live-verified 2026-06-26).** The engine already supported
  monster multiattack (`get_extra_attack_count` reads the Multiattack ability's `extra_attack_count`
  from `special_abilities`); the AI just planned one swing. Fix: `AIController._plan_action` now emits
  one SELECT_ACTION+EXECUTE_ATTACK pair per swing (`num_attacks` from `get_extra_attack_count`), and
  `executor._resolve_attack_target` re-targets the nearest living foe when a swing drops its target
  (no flailing at corpses). Fidelity note: all swings use the creature's *best* attack (3 claws), not
  the literal "bite + 2 claws" split — consistent with how the player's Extra Attack already works;
  "fine unless the public complains." Tests: `arena/tests/test_ai_multiattack.py` (5). Bench:
  `multiattack_lab` (dragon/troll=3, owlbear=2, lone wolf=1 control).

- **Brain Slice 2 — Monster spellcasting (DONE, live-verified 2026-06-26).** Root cause: the casting
  *machinery* already worked (the hand-authored `monsters/mage.json` casts fine), but the 36 SRD
  caster stat blocks carry their spells as PROSE in a `special_abilities` "Spellcasting" Feature
  ("3rd level (3 slots): fireball ..."), and the AI only scores `actions` — so a Mage saw only its
  Dagger. Fix = a content binder, engine untouched: `arena/util/monster_spells.py` parses the prose,
  binds each named spell to the shared spell library (`arena/data/spells/srd/`, ~158 spells),
  stamps the monster's save DC, and emits a baked spell Action. Applied to the 30 effective casters
  via `tools/bake_monster_spells.py` (idempotent, re-runnable) and wired into `gen_arena_monsters.py`
  (no longer DEFERRED) so a regen reproduces it. Spells absent from the library (~54 utility:
  detect magic, light, tongues, scrying…) are skipped + reported — a monster never casts them in a
  fight anyway. Gates mirror the hand-authored casters: self-teleports → `is_in_melee` (escape only),
  damaging area spells → `enemies_in_range >= 2`. Lich 19 spells, Archmage 12, Mage 10. Bench:
  `monster_caster_lab`. Tests: `test_monster_spell_binding.py` (10).
  THREE bugs surfaced + fixed in the same slice (all pre-existing, exposed by monsters casting):
  - **AI area-burst self-centering** (`ai/scoring.py` + `ai/controller.py`): `execute_effect(target_id)`
    expands an AoE around the CASTER, so AI bursts (Fireball/Ice Storm) landed on the caster's own
    square (Ice Storm even dumped its terrain there) and only hit the lone "included" target. Fix:
    non-concentration `area_*` spells now carry a `target_hex` on the enemy → routed through
    `execute_effect_at_hex` (centers on the cluster). Concentration auras (Spirit Guardians) stay
    caster-centered. Tests: `test_ai_aoe_targeting.py` (3). Note: `target_type` is a `TargetType`
    enum — use `.value` for "area" prefix checks.
  - **uses_per_rest not enforced on teleports** (`combat/manager.py` `execute_teleport`): only checked
    spell-slot cost, never the per-rest cap, so a gated Misty Step was castable unlimited times (saw
    377). Fix: added the check-and-decrement that `resolve_effect` already does. Fixes ALL limited
    teleports, players included. Tests: `test_teleport.py` (+2).
  - **Sacred Flame honored cover** (`models/actions.py` + `combat/actions.py`): cover correctly adds
    +2 to DEX saves (incl. from any intervening creature — RAW), but Sacred Flame's text says it
    ignores cover. Added an `ignores_cover` Action flag, set on `sacred_flame.json`. Tests:
    `test_cover_dex_saves.py` (+1). NB: an attacker's own ally in the line granting the target cover
    is RAW and intentional — left as-is.
  Full suite 2407 green.

- **Brain Slice 3 — Signature abilities + AoE aiming (DONE, live-verified 2026-06-26). BRAIN PHASE
  COMPLETE.** (A) Breath weapons were never used: a once-per-rest ability at the generated default
  `ai_priority=5` lands at willingness 0.375 in `should_use_limited_ability` — just under the 0.4
  threshold (0.5 × (0.5 + 0.5·pri/10)). Fix: `gen_arena_monsters.py` now stamps recharge abilities at
  ai_priority 9 (signature: used freely, exempt from the early "save your one use" conservation which
  only spares pri≥8); `tools/bake_signature_priorities.py` migrated the 38 existing breath/recharge
  abilities (Fire/Cold/Lightning/Poison Breath, Petrifying Breath, Horror Nimbus, Spores…). Dragons
  now open with breath, bite when it's spent. (B) AoE cluster aiming: Slice 2 moved burst execution to
  the target hex but `score_effect_action` still measured the cluster from the CASTER — fixed to score
  at the blast's real center (the target for non-concentration bursts; caster for concentration auras),
  so per-enemy ranking auto-picks the densest cluster. Legendary actions were already handled
  (`controller.plan_legendary_action`, Phase D) — not a gap. Charge-SETUP maneuvering deferred (minor;
  charge fires when in range). Bench: `breath_lab`. Tests: `test_ai_signature_abilities.py` (2, incl.
  pri-5-fails regression) + cluster test in `test_ai_aoe_targeting.py`. Full suite 2411 green.
  Backlog idea (OublietteDev, playtest): AoE/cone AIM INDICATORS in the GUI — hard to see what a breath/blast
  is targeting (see [[oubliette-arena-ui-cleanup]]).

## Forge Phase 2 — AI personality editor (started 2026-06-26)

Reusable named personalities: author a profile once, attach it to many monsters (OublietteDev's framing).
Architecture: author/store named profiles per-pack → monster references one by name → the bridge
resolves the name to a full `AIProfile` and bakes it onto the Arena Monster. Easy mode (plain-English
questions + presets) and pro mode (full knob board) both write the same `AIProfile`. The Forge is a
FastAPI + vanilla-JS single-page app (`oubliette/creator/`), editors are modal forms
(FORMS/WIRES/CONFIRMS → commitEntry → POST `/api/pack/{id}/save`).

- **Phase 2a — Plumbing, presets-first (DONE, 474 green).** Carries an `ai_profile` *name* from a pack
  StatBlock to the Arena. `oubliette/content/schemas.py` StatBlock gained `ai_profile: str | None`;
  `arena_bridge.statblock_to_monster` passes it through; `enemy_from_statblock` lets a pack author's
  choice override the rich SRD file's default. The Arena already resolves a preset name →
  `DEFAULT_PROFILES` (`controller._get_profile`). Tests: `tests/test_arena_bridge.py` (+5). A power
  user can hand-set `"ai_profile": "berserker"` today and it works.

- **Phase 2b — Storage layer (DONE, 478 green).** Packs can now hold named personalities. New
  `AiProfile` schema in `oubliette/content/schemas.py` (id + name + the 13 `AIProfile` knobs, mirrored
  1:1 with range bounds). `loader.py` parses optional `ai_profiles.json` (missing = empty → existing
  packs unaffected), dup-id checks, → `LoadedWorld.ai_profiles`. Forge `server.py` registers the kind
  in PACK_FILES/_TYPES + scaffolds `ai_profiles.json=[]` in new packs. Tests: `tests/test_creator_server.py`
  (+4).

- **Phase 2b — Bridge resolution (DONE, 481 + 2411 green).** Custom personalities now fight. Flow:
  pack `ai_profiles` → `Session.ai_profiles` → `arena_launch._resolve_enemies` → `enemy_from_statblock(
  ..., ai_profiles=)` resolves a stat block's custom profile *id* against the pack's profiles and bakes
  it onto the Monster as `ai_profile_inline` (a plain dict — `model_dump(exclude={"id"})` — so
  `arena/models` needn't import `AIProfile`, and it survives the serialized-encounter trip to the
  standalone Arena process). `controller._get_profile` prefers `ai_profile_inline` (builds `AIProfile(
  **inline)`, falls back on malformed), else the named preset, else default. Preset names ride as the
  string (no inline). Tests: `tests/test_arena_bridge.py` (+3).

- **Phase 2b — Editor UI (DONE, browser-verified 2026-06-27). FORGE PHASE 2 COMPLETE.** The
  "AI Personalities" editor in `oubliette/creator/static/index.html` (registered as a content kind in
  ORDER/TITLES/SINGULAR/EDITABLE + FORMS/WIRES/CONFIRMS, like every other editor). **Easy mode** = 4
  plain-English questions (How brave? Who does it hunt? How does it fight? Protects allies?) + a row of
  preset buttons (Berserker/Archer/Battle-mage/Coward/Bodyguard); **Pro mode** = the 13 `AIProfile`
  knobs. Both write the SAME inputs: the Pro inputs are the single source of truth; easy answers and
  presets call `aipApply()` on them; `confirmAiProfile` reads the Pro inputs. Easy answers map via
  `AIP_EASY`, presets via `AIP_PRESETS`, defaults `AIP_DEFAULTS`; `aipDeriveEasy` best-effort fills the
  easy dropdowns when editing. The **creature form** gained a personality dropdown
  (`aiProfileOptions`: Default + built-in styles + this world's custom profiles) read into
  `statblock.ai_profile`; `describe()` shows the chosen personality on the card. Verified live via the
  preview browser: no console errors, create a "Cowardly Goblin" (preset + easy override), it appears
  in the creature dropdown, attaches to a creature, card updates. The full loop works:
  author personality → tag a creature → (bridge already) → it fights that way in the Arena.
  No new Python tests (pure frontend; server/loader/bridge already covered). Oubliette 481 / Arena 2411.

  **→ NEXT: Phase 3 — the monster editor** (richer creature authoring; the personality dropdown is
  already in place). See `oubliette-ai-forge-arc` memory.

## Forge Phase 3 — the Monster Editor (started 2026-06-27)

Plan: `docs/roadmap/oubliette-phase-3-monster-editor-plan-v0.1.md`. Goal: a non-coder can author a
creature that actually fights well. **Key finding that shaped the phase:** "competence is free" only
held for the 354 SRD monsters (each ships a full Arena combat file); a *brand-new* authored creature
has no such file, so the bridge falls back to the flat `statblock_to_monster` mapping = ONE generic
attack per turn. Ability scores / AC / HP / CR / damage resistances+immunities+vulns+condition-
immunities DO carry; the *moves* don't. **Locked decisions (OublietteDev):** ships open-source → expose the
engine's REAL combat primitives; escape hatch = structured **data + safe expressions, never
executable code** (a downloaded pack must never run code); **architecture = Option A** — packs may
carry the engine's real `Monster` JSON (`packs/<id>/monsters/<sb_id>.json`), the bridge already
prefers a rich file via `arena_monster_file`, so "clone an existing creature" = copy+rename. Sequence:
**3a** richer fields → **3b-1** bridge prefers pack combat file + server reads `monsters/` →
**3b-2** clone → **3b-3** ability builder → **3b-4** advanced raw-data editor + `ai_use_condition`.

- **Phase 3a — Richer identity & defense fields (DONE, browser-verified 2026-06-27, 485 green).**
  The creature form (`oubliette/creator/static/index.html` `statblockForm`/`confirmStatblock`) now
  exposes the StatBlock fields it omitted: size (select), type, alignment, **challenge rating** (the
  standard 5e ladder 0–30 incl. 1/8–1/2; drives the bestiary gate), hit dice, AC note, **saving-throw
  bonuses** (6-grid, optional), **speed** (walk/fly/swim/climb/burrow, ft → "N ft."), **damage
  resistances / immunities / vulnerabilities / condition immunities** (the combat-honored star of 3a;
  the flat mapping already reads these), senses (darkvision + passive perception), languages, and
  portrait. Empty inputs delete their key (packs stay clean). The creature card (`describe`) now leads
  with "Medium beast · CR 1/4 · …". Deferred to 3b (where it gains teeth): `skill_bonuses` numeric dict.
  - **Fat-finger guard (OublietteDev's call):** fields the engine reads against a fixed vocabulary are now
    **checkbox pick-lists**, not free text, so a typo can't silently no-op (or, for skills, hard-fail
    the pack load — the loader validates skills). `checklist()`/`readChecklist()` helpers over
    **13 damage types**, **15 SRD conditions**, **18 SRD skills** (token must match the engine), and
    **16 standard languages** + a free-text "other" for prose cases (telepathy, "understands…").
    Tokens verified against `arena/models/{conditions,actions}.py` + `oubliette/enums.py Skill`.
    **Traits stay free text** by design — prose, no closed vocab, not parsed mechanically (real
    mechanical specials come from the 3b ability builder).
  - **Portrait picker:** a real file picker (mirrors the character sheet's flow) replaces the filename
    text box. New Forge endpoints `POST/GET /api/pack/{id}/portrait/{…}` save raw bytes (format
    preserved → PNG transparency survives) into the pack's `portraits/<id>.<ext>` — the same dir the
    game + Arena read (`arena_bridge PortraitDirs.pack`). Keyed by creature id (slug of the name for a
    not-yet-saved creature); the explicit `portrait` filename is stored so it resolves even if id/slug
    diverge. Tests: `test_creator_server.py` (+4: upload/serve, replace-extension, bad-type, guards).
    Browser-verified the full picker (choose → upload → preview loads → Remove), no console errors.

- **Phase 3b-1 — Bridge prefers a pack combat file (DONE, 2026-06-27, 494 green). THE OPTION-A
  KEYSTONE.** A pack creature may now ship a full Arena `Monster` JSON at `packs/<id>/monsters/<sb_id>.json`
  (same shape as the SRD set); the bridge fights THAT instead of the flat one-swing mapping, so a
  Forge-authored creature gets multiattack / breath / distinct attacks. `arena_bridge.arena_monster_file`
  now takes a `search_dirs` list (pack dir first, then SRD) and returns the first VALID file — a
  malformed authored file is skipped (degrades to SRD/flat, never crashes a fight). `enemy_from_statblock`
  gained `pack_monster_dir`; `arena_launch._resolve_enemies` derives it from `session.pack_id`
  (`_CONTENT_ROOT/packs/<id>/monsters`) and threads it. Pack file wins even over a matching SRD id (an
  author's custom take). xp + ai_profile still ride from the StatBlock (identity stays the bestiary
  record). No new cross-process risk: rich pack monsters use the SAME serialize-into-the-Arena path the
  SRD rich monsters already use. Forge server: `GET/PUT/DELETE /api/pack/{id}/monster/{sb_id}` (PUT
  validates against the real `arena.models.monster.Monster`, so a broken combat file can't be saved;
  DELETE reverts to flat/SRD, idempotent); `read_pack` now returns `monster_files` (which creatures have
  a combat file, for an editor badge). Content-save only writes the kind JSONs (never subdirs) and
  `_backup_pack` copies the whole tree, so `monsters/` is preserved + backed up for free. Tests: +5
  bridge (preferred / xp+profile override / missing→flat / malformed→flat / overrides-SRD-id), +4 server
  (round-trip+listing / invalid rejected / delete reverts+idempotent / guards).

- **Phase 3b-2 — "Start from an existing creature" / clone (DONE, browser-verified 2026-06-27, 497
  green).** The fast on-ramp: copy ANY SRD monster (334) or this-world creature — its full combat kit
  AND its stats/identity — under a new id, then land in the editor to rename/tweak. Source is never
  touched. Server (read-only): `GET /api/srd/monsters` (picker list from `content/srd/bestiary.json`,
  cached, sorted by CR) + `GET /api/srd/monster/{id}` ({statblock: the rich bestiary StatBlock incl.
  description, combat: the matching `arena/data/monsters/srd/<id>.json` or null}). All 334 bestiary ids
  align 1:1 with arena combat files. Client (`index.html`): a "Start from existing…" button on the
  Creatures group → searchable picker modal (pack creatures + SRD, name/CR/type + source badge) →
  `cloneFrom` mints a new id (`uniqueId(slugify(name))`), copies the StatBlock (drops `srd_ref` +
  `portrait` for a fresh creature), and — if the source has a combat file — renames it and PUTs it to
  `monsters/<new_id>.json` via the 3b-1 endpoint, then inserts the StatBlock + opens the editor.
  statblocks.json stays client-owned (persists on Save); the combat file writes immediately (like
  portraits). Cards now show a "⚔ custom combat" badge when a creature has a combat file
  (`state.monsterFiles` from `read_pack`). Tests: +3 server (list / statblock+combat / 404).
  **NEXT: 3b-3 — the ability builder** (compose attacks/multiattack/save-effects/recharge from the
  engine primitives), then 3b-4 advanced raw-data editor.

**Foundational decisions that are settled** (don't relitigate without reason): SQLite behind a
repository abstraction; async edges / sync core; LLM-first routing behind the model seam;
provider-native structured output; only protected state + entity-creation are event-sourced
(open "flavor" content is plain last-write-wins); combat results carry absolute final values (not
deltas) so applying them is idempotent; difficulty numbers (DCs) are intentionally model-set (the
soft layer), state numbers are code-owned.

---

*Keep this file current as the project evolves — it's the fastest way for a new collaborator to
become useful without re-reading the whole history.*
