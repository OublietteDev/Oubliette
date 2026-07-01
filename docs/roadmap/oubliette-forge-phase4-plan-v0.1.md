# Forge Phase 4 — Combat stats for NPCs

**Status:** COMPLETE (4a + 4b shipped) · **Date:** 2026-06-27 (updated 2026-06-30) · **Owner:** OublietteDev (+ Claude)
**Predecessor:** Forge Phase 3 (creature authoring) — COMPLETE, committed through `965b535`.

---

## 1. Goal

Today an NPC is flavor, commerce, and placement: a name, a disposition, an
inventory, a home. They can be *dragged* into a fight, but only as a placeholder
(10 HP, AC 10, +2 to hit, 1d4). Phase 4 gives NPCs **real combat stats** so a
captain of the guard fights like a Fighter 3 and Seraphel fights like the ancient
blue dragon she is.

The design follows one honest distinction that already lives in the data:

> **Is this NPC a *person* or a *creature*?**
> A person (blacksmith, guard, rival adventurer) is built with the **player
> chargen + level-up system**. A creature (Seraphel, a displacer beast) is
> authored with the **Phase 3 monster editor**.

We do **not** invent combat math a third time. Phase 4 is mostly *wiring
together two systems that already exist* and exposing them through the NPC editor.

---

## 2. The fork: one choice, three outcomes

The NPC editor grows a **Combat** section with a single routing choice:

| Choice | For | Reuses | Fidelity |
|---|---|---|---|
| **None / generic** (today's behavior) | Thom the merchant, townsfolk | the existing `stat_block` dropdown (commoner, guard) | flat, fine |
| **Author as a creature** → *Phase 4a* | Seraphel, beasts, aberrations | the **Phase 3 monster editor** | full kit (multiattack, breath, AI) |
| **Build as a character** → *Phase 4b* | recruited guard, rival NPC, an enemy mage | the **chargen + level-up** system | class-accurate; full features when recruited |

"None/generic" already works and is untouched. Phase 4 adds the other two columns.

---

## 3. Locked design decisions

1. **Snapshot, not recipe.** A person-NPC stores the *fully-built `Character`
   (with its `CharacterSheet`)*, not a build recipe to re-derive at load. The
   Forge runs the rules engine at authoring time and saves the result; the loader
   stays simple. (OublietteDev, 2026-06-27.)
2. **No routine NPC leveling.** We don't expect to re-level authored NPCs except
   when one is recruited into the party — and even then it's the normal party
   level-up path, which already takes a `Character` as input. So the snapshot
   needs no extra bookkeeping to support later leveling.
3. **Recruited allies are player-controlled.** A recruited ally joins combat the
   same way the PC does — added to the `party` list, `is_player_controlled=True`.
   This sidesteps "allied AI" entirely. (OublietteDev, 2026-06-27: "If someone complains
   when this goes public, we'll code around it" — see §9.)

---

## 4. What already exists (ground truth)

Verified against the tree at `965b535`:

- **NPC schema** — `oubliette/content/schemas.py:201` (`class NPC`). Optional
  `stat_block: str | None` reference; everything else is flavor/commerce.
- **NPC → runtime** — `oubliette/content/loader.py:299` (`_build_npc`). With a
  `stat_block` it copies hp/ac/attack/damage from the `StatBlock`; without one it
  leaves the `Character` on defaults (10/10/+2/1d4) and `sheet=None`.
- **Chargen** — `oubliette/rules/chargen.py:306` (`build_character(build,
  ruleset, char_id) -> (Character, items)`). Produces a `Character` with a full
  `CharacterSheet` and derived hp/ac/attack.
- **Level-up** — `oubliette/rules/levelup.py:162` (`level_up(char, ruleset,
  choice, ...) -> Character`). Takes a built `Character` and a `LevelUpChoice`.
- **Monster editor** — Forge Phase 3. Authors `StatBlock`s + a rich Arena
  combat file at `packs/<id>/monsters/<sb_id>.json`. Endpoints in
  `oubliette/creator/server.py` (`/api/pack/<id>/monster/<sb_id>` GET/PUT/DELETE,
  `/api/pack/<id>/monster-baseline`, `/api/srd/monster[s]`).
- **Enemy resolution** — `oubliette/combat/arena_launch.py:129`
  (`_resolve_enemies`). Precedence: **template → statblock → persistent entity**.
  A persistent entity (an NPC) goes to `enemy_from_character` → **flat one
  attack**, *bypassing* the rich-file path. **This is the seam Phase 4a opens.**
- **Rich enemy path** — `arena_bridge.py:900` (`enemy_from_statblock`) already
  prefers `packs/<id>/monsters/<sb_id>.json` over the flat mapping, bakes in the
  AI profile and portrait. Phase 4a routes creature-NPCs through this.
- **Player path** — `arena_bridge.py:660` (`character_to_player`). Maps a
  `Character` → a full-fidelity, player-controlled Arena `PlayerCharacter`:
  features, spells, class resources, magic gear. **Does not require `kind=="pc"`
  and already tolerates `sheet=None`.** So a person-NPC snapshot maps here for
  free.
- **Encounter assembly** — `arena_bridge.py:1032` (`build_encounter`) already
  takes **`party: list[Character]`** (plural) and team-tags everyone. The recruit
  slot exists today.

**Net:** the creature path is ~80% built (Phase 3 did the hard part); the person
path's *combat-side* plumbing is already there (`character_to_player` + party
list). The genuinely new work is **exposing chargen/level-up inside the Forge UI**
(Phase 4b) and **two small bridge seams**.

---

## 5. Shared storage model

Mirror the Phase 3b pattern (rich data lives in a sidecar dir, lean pointer in
the main file).

**`npcs.json`** gains an explicit kind discriminator so the editor and loader
never have to guess:

```jsonc
{
  "id": "seraphel",
  "name": "Seraphel",
  "combat_kind": "creature",      // "none" | "creature" | "person"
  "stat_block": "seraphel",       // creature: -> statblocks.json + monsters/seraphel.json
  // ...existing flavor fields unchanged...
}
```

```jsonc
{
  "id": "capt_aldric",
  "name": "Captain Aldric",
  "combat_kind": "person",                // sidecar is by CONVENTION: characters/capt_aldric.json
  // ...existing flavor fields unchanged...
}
```

> **Deviation from the original draft (shipped 4b-3):** no `character_file` field —
> the sidecar is keyed by the NPC id (`characters/<npc_id>.json`), exactly as a
> creature's combat file is keyed by its stat-block id (`monsters/<sb_id>.json`).
> One less field to keep in sync.

- **`combat_kind`** defaults to `"none"` so every existing NPC is valid
  unchanged. **Legacy data stays `"none"` even when it carries a `stat_block`** —
  every existing stat-block NPC (merchant_thom → commoner) is a *generic* one, not
  a richly-authored creature, so `"none"` (the generic-statblock lane) is the
  truthful label. `"creature"`/`"person"` are only ever set by explicit authoring.
  *(Refined from the original "`stat_block` → `creature`" inference during 4a-1, to
  avoid mislabelling every current stat-block NPC as a hand-built creature.)*
- **Creature path** reuses Phase 3 storage verbatim: `statblocks.json` entry +
  optional `monsters/<sb_id>.json`.
- **Person path** adds a new sidecar dir `packs/<id>/characters/<npc_id>.json`
  holding the snapshotted built `Character` (sheet included). Loader prefers it
  over the defaults; flavor fields (gold/inventory/price_list/disposition/home)
  still come from `npcs.json` and are merged on top.

Schema touch points: add `combat_kind` and `character_file` to `NPC`
(`schemas.py:201`); a sidecar loader + cross-ref validation in `loader.py`.

---

## 6. PHASE 4A — the creature path (Seraphel)

**Outcome:** an NPC can BE a fully-authored creature and fight its complete kit
(multiattack, breath weapon, legendary actions, AI personality) — as a recurring,
persistent foe whose HP is written back between fights.

This is the small, high-payoff slice: Phase 3 already built the editor and the
rich-file bridge. 4a is mostly *connecting* them to the NPC side.

### 4a.1 Bridge seam (the core change) — SHIPPED
In `_resolve_enemies` (`arena_launch.py`), a persistent **NPC that carries a
`stat_block`** is routed through the **statblock + rich-file** path
(`enemy_from_statblock` → full kit + AI + portrait, with the rich
`monsters/<id>.json` winning when present), then stamped persistent:
`inst.entity_id = ent.id`, `inst.loot = []` (HP write-back, no loot — the
recurring-foe policy `enemy_from_character` already follows). An NPC with no
`stat_block` keeps the flat `enemy_from_character` mapping.

Two refinements surfaced in implementation:

- **Precedence reorder: template → persistent entity → stat block** (was
  template → stat block → entity). A creature-NPC whose id matches her stat block
  (Seraphel/`seraphel`) otherwise resolved via the stat-block branch as an
  *ephemeral* copy — no entity_id, dropped loot, count > 1. Checking the repo
  first makes "is it a persistent entity?" the single decider; generic monsters
  ('a pack of wolves') aren't repo entities, so they fall through unchanged.
  Entity match is **exact-id only**, so the DM's descriptive naming still resolves
  as a stat block.
- **NPC→stat_block map on the session.** The runtime `Character` drops the
  `stat_block` ref, so the loader now exposes `LoadedWorld.npc_statblocks`
  (`{npc id -> StatBlock id}`), threaded onto `Session.npc_statblocks`. This maps
  the entity back to its block *explicitly* (no id==id convention), and supports a
  creature-NPC whose id differs from its stat block id (e.g. cloned creatures).
- **Identity preserved:** the combatant keeps the NPC's own name (`Seraphel`),
  not the stat block's species label (`Ancient Blue Dragon`).

This is the seam that makes Seraphel breathe lightning instead of swinging for
1d4. Small, surgical, well-tested.

### 4a.2 Forge UI — SHIPPED
The NPC editor (`static/index.html`, `npcForm`) gained a **"How they fight"**
selector → *Doesn't fight / generic stat line* · *A creature (monster)* · *A
person (character) — coming soon* (the person option shows **disabled** until 4b,
per OublietteDev's call). The selector drives an adaptive combat panel:
- **none**: the optional generic stat-line dropdown (today's behaviour).
- **creature**: a stat-block dropdown + three actions — **+ New creature**,
  **Start from an existing creature…** (the Phase 3b-2 clone picker, so Seraphel
  starts from the SRD blue dragon), and **✎ Author this creature's combat**
  (enabled once a block is chosen; opens the Phase 3 statblock/monster editor).
- **person**: a "coming in a later update" note.

The cross-editor handoff: New/Clone **save the character first**, then a creature
minted in the monster editor **links back** to the NPC (`stat_block` +
`combat_kind="creature"`) via a pending-link (`npcLink`), cleared on cancel so a
abandoned hop never mis-links the next creature. Live-verified end-to-end against
Brightvale (selector defaults, disabled person option, new-creature link-back,
edit-existing, cancel-safety).

### 4a.3 Tests
- `_resolve_enemies`: an NPC with a `stat_block` + a `monsters/<id>.json` yields
  the rich Monster AND keeps `entity_id` (write-back). Regression: an NPC with no
  stat_block still yields the flat fallback.
- Loader: `combat_kind` round-trips; legacy NPCs (no field) infer correctly.
- Live: author Seraphel in the Forge → reference her in an encounter → confirm
  full kit in the Arena, and HP persists across two fights.

### 4a.4 Suggested commits
1. `4a-1` schema + loader: `combat_kind` on NPC, inference for legacy data.
2. `4a-2` bridge: creature-NPC enemies use the rich statblock path (+ entity_id).
3. `4a-3` Forge UI: "Author as a creature" routes the NPC editor into the
   Phase 3 statblock/monster editor.

---

## 7. PHASE 4B — the person path (Captain Aldric)

**Outcome:** an NPC can be built as a real character — race, class, level,
features, spells, equipment — using the *same* chargen + level-up engine the
player uses. As an adversary they fight with honest, level-appropriate numbers;
recruited into the party they fight at **full class fidelity, player-controlled**.

This is the larger slice: the combat-side plumbing exists, but **chargen and
level-up are not exposed in the Forge yet** — they live in the main game's
character-creation flow. 4b builds that bridge.

### 7.1 Forge must load the SRD ruleset — SHIPPED (4b-1)
Chargen/level-up need a `Ruleset` (races, classes, backgrounds, spells,
equipment). The creator server (`oubliette/creator/server.py`) loads it via a
cached `_ruleset()` (`load_ruleset()`, pack-independent) and hands it to the
chargen endpoints.

**Shared-module decision (4b-1):** the play app's chargen *projections*
(`_chargen_options`, `_class_view`, `_preview_payload`) were pure functions of the
ruleset, so rather than duplicate them into the Forge (drift risk), they were
**extracted to `oubliette/rules/chargen_view.py`** (`chargen_options(rs)`,
`class_view(rs, cc)`, `preview_payload(char, items, rs)`). Both servers now render
chargen from one source of truth; the play app delegates to it (behaviour
unchanged, full suite green), and a creator test pins that the Forge's options are
byte-identical to the shared projection.

### 7.2 New creator endpoints (drive the existing engine)
Thin wrappers over `chargen`/`levelup` — no new rules logic:
- `GET  /api/chargen/options` → races, classes, subclasses, backgrounds, spell
  lists, equipment choices, ability-score methods. **SHIPPED (4b-1).**
- `POST /api/chargen/preview` → body is a `CharacterBuild`; returns the firewall's
  errors or the derived preview sheet (`preview_payload`). **SHIPPED (4b-2).**
- `POST /api/chargen/build` → body is a `CharacterBuild`; returns the built
  `Character` snapshot **or** the chargen firewall's validation errors.
  **SHIPPED (4b-2).**
- `POST /api/chargen/levelup/plan` → body is a `Character`; returns the next
  level's requirements. `POST /api/chargen/levelup` → body is `{character,
  choice}`; returns the leveled `Character` or validation errors. Both operate on
  the transient character in the body (no repo). **SHIPPED (4b-2).**
- `PUT  /api/pack/<id>/character/<npc_id>` → persist the snapshot to
  `characters/<npc_id>.json`; `GET`/`DELETE` to load/clear. *(4b-3)*

**Authoring decision (4b-2):** XP is a *play* gate (you grind for levels), but in
the Forge the author just dials a level. So both level-up endpoints **grant the
level-appropriate XP** (`_grant_level_xp`) before invoking the engine — an
authored NPC is assumed to have earned their level. The same `level_up` firewall
still bites (e.g. a Fighter must choose a Martial Archetype at level 3), so the
wizard drives a real plan → choice → apply loop per level. *(Open downstream
nuance for later: `enemy_from_character` awards `char.xp` as the kill reward, so a
high-level person-NPC adversary would grant level-worth XP on defeat — revisit
kill-reward calibration when person-NPC adversaries get live testing.)*

### 7.3 Forge UI — the chargen wizard
The substantial piece. A guided flow mirroring the game's chargen, embedded in
the NPC editor when **"Build as a character"** is chosen:
1. Race / subrace → class / (subclass at the right level) → background.
2. Ability scores (standard array / point-buy / roll).
3. Skills, expertise, languages, racial picks.
4. Spells (cantrips + leveled) where the class casts.
5. Equipment choices.
6. **Target level**: build at L1, then run the level-up step N−1 times,
   surfacing each level's ASI/feat/subclass/spell choices.

Reuse the game's chargen front-end components/validation where possible rather
than rebuilding the rules in JS — the server endpoints are the source of truth;
the UI just collects a `CharacterBuild` / `LevelUpChoice` and shows errors.

### 7.4 Loader — SHIPPED (4b-3)
`_build_npc` (`loader.py`): when `combat_kind=="person"`, the runtime Character is
built from the validated `characters/<id>.json` snapshot (`_build_person_npc`),
not from a stat block. The **merge rule**: the snapshot is authoritative for
combat *and belongings* (abilities, hp/ac/attack, the full sheet, equipped gear,
gold/inventory); the NPC record overlays identity + authored flavor (name,
disposition, description, home_location). *(Editor-authored commerce for a
person-NPC — a fighter who also runs a shop — is a deliberate later refinement;
for now a person's belongings ride along from their build.)*

Validation (all aggregated, pack loads whole-or-not): a `person` NPC must have a
readable, valid sidecar (`_load_person_characters`), and may **not** also set a
`stat_block` (combat comes from the character — the linter rejects the
contradiction). Repo-parity with the old seed is preserved (Brightvale has no
person NPCs, so the path is inert there).

The creator side (4b-3) added `GET/PUT/DELETE /api/pack/<id>/character/<npc_id>`
(PUT validates against the engine `Character` model so a broken snapshot can't be
written) and `character_files` in the pack read, so the editor can badge which
person-NPCs are built.

### 7.5 Bridge — adversary vs. ally
- **Adversary (default) — VERIFIED (4b-5).** The snapshot already gives honest
  numbers, so today's `enemy_from_character` flat mapping is *acceptable* — a
  level-3 enemy fighter arrives with ~28 HP / AC 16 / +5 / longsword instead of
  10/10/+2/1d4. A person-NPC has no `stat_block`, so `_resolve_enemies` falls to
  `enemy_from_character` → `character_to_monster`, which reads the snapshot's
  `max_hp`/`armor_class`/`attack_bonus`/`damage`/`abilities`/`xp` — so the WHOLE
  built sheet's combat line reaches the Arena, not just HP. **No code change was
  needed; 4b-5 is a regression test pinning that contract**
  (`test_person_npc_adversary_fights_with_its_honest_snapshot_numbers`). Full
  class-feature fidelity for AI-controlled enemies is **deferred** (§9).
- **Recruited ally — SHIPPED (4b-ally).** See §7.6.

### 7.6 Recruitment — SHIPPED (4b-ally, per-encounter)
"Fights alongside the party" needs a notion of party membership beyond the single
PC (`repo.party()` returns only `kind=="pc"` characters). **OublietteDev's call
(2026-06-30): the per-encounter stateless model** — no standing "recruited" flag.
`EncounterRequest` gained `allies: list[str]` (present-entity ids); `stage_combat`
resolves them via `_resolve_allies(request, repo, party)` and appends each to the
party list handed to `build_encounter`, where they're team-tagged `"player"` and
mapped by `character_to_player` to **player-controlled** combatants (OublietteDev's locked
decision — no allied AI). HP writes back like any party member (`persistent_ids`).
An ally is *additive*: an unknown or duplicate id is **skipped, not fatal** (unlike
an unknown ENEMY ref, which raises). The DM narrator is told to populate `allies`
with a present friendly NPC who'd plainly fight for the player (`dm/brain.py`
COMBAT instruction). **Persistent recruitment** (a recruit/dismiss mechanic +
party state across fights) is deferred to "if it matters."

### 7.7 Tests
- Endpoints: a valid `CharacterBuild` builds; an invalid one returns the firewall
  errors. Level-up applies HP/ASI/features/spells.
- Loader: a `person` NPC loads its sidecar; numbers match the built sheet; flavor
  merges; a missing/invalid sidecar fails validation loudly.
- Bridge: person-NPC as adversary → honest flat numbers; as party member →
  `character_to_player` full fidelity.
- Live: build Captain Aldric (Fighter 3) in the Forge → fight him as an enemy →
  recruit him → he fights alongside the PC with Second Wind available.

### 7.8 Suggested commits
1. `4b-1` creator loads the ruleset + `/api/chargen/options`.
2. `4b-2` `/api/chargen/build` + `/api/chargen/levelup` (server, tested headless).
3. `4b-3` character sidecar storage + loader merge + validation.
4. `4b-4` the chargen wizard UI in the NPC editor (likely several sub-commits).
5. `4b-5` adversary bridge — **SHIPPED** (verified; regression test, no code change).
6. `4b-ally` recruited ally → party list — **SHIPPED** (per-encounter, stateless).

**Phase 4 COMPLETE** as of 4b-5 + 4b-ally.

---

## 8. The `merchant_thom` cleanup (unblocked by Phase 4)

The deferred Brightvale coupling — `merchant_thom.stat_block = "commoner"` blocking
creature curation — resolves naturally here: Thom becomes `combat_kind:"none"`
(or `"creature"` pointing at a `commoner` statblock we keep deliberately). Phase 4
is the right moment to revisit the three Brightvale pack creatures and the tests
that pinned this. Do it as a follow-up once the `combat_kind` field lands (4a-1).

---

## 9. Deferred — "if people complain, we'll change it"

Consistent with the project's existing list (e.g. gold-only currency):
- **AI-controlled person-NPC fidelity.** Adversary person-NPCs use flat (honest)
  numbers, not full class features, until/unless it matters.
- **Allied AI.** Recruited allies are player-controlled, not AI-run.
- **Routine NPC leveling UI.** No standing "level up this NPC" tool; re-author or
  use the party level-up path if recruited.

---

## 10. Recommended order

**4a first, then 4b.** 4a is contained, proves the fork UX, and delivers a
visible, satisfying win (Seraphel breathes) on top of Phase 3. 4b is the larger
build (chargen-in-the-Forge) and benefits from the `combat_kind` plumbing 4a lays
down. The `merchant_thom` cleanup slots in after 4a-1. The recruited-ally
sub-slice (§7.6) is the one piece still needing a scope pass against the
party/encounter layer before we commit to it.
