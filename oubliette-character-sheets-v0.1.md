# Oubliette Table — Character Sheets & Character Creation (chargen)

**Design doc v0.1** · 2026-06-08 · status: DRAFT, awaiting OublietteDev's sign-off

A mechanically-complete D&D character: built by the rules at creation, displayed
on a real sheet, and tracked faithfully through play — with a full SRD backbone
(classes, races, subclasses, backgrounds, spells, equipment) behind it.

---

## §0. Thesis

The same invariant as the rest of Oubliette holds: **code owns the numbers; the
LLM narrates.** A character's every derived value (AC, saves, skill mods, spell
DC, slots, HP) is computed by the rules from the player's build choices and
equipment — never asserted by the model, never typed in by the player. Chargen is
the player's one authoring act: they make *choices*; code validates them against
the SRD and produces the sheet.

## §1. Decisions LOCKED (this session)

- **Full mechanical SRD** backbone (not a reference-only sheet).
- **Character-complete now, effects later**: every buildable/derivable number is
  computed and rules-enforced (abilities, proficiency, AC in all its variants,
  saves, skills, initiative, passive scores, spell save DC + attack, slot/known/
  prepared counts, hit dice, HP, ASIs, leveling, rests, resource tracking). Spell
  and feature **effects** are stored as full structured SRD data and surfaced as
  authoritative reference, but auto-*resolution* (damage, conditions, buffs) waits
  for the combat arc — there's no loop to apply them to yet. Nothing is faked; the
  character is 100% correct, the effects simply aren't auto-applied.
- **All three ability-generation methods** at creation: standard array, point-buy,
  4d6-drop-lowest (via the seeded/logged RNG).
- **Full SRD backbone** as the content goal (all SRD classes/races/subclasses/
  backgrounds, spells as data). I draft the content; OublietteDev verifies rules accuracy.

## §2. Architecture

Four pieces, layered onto what already exists:

1. **The SRD ruleset** — a new, *global* data layer (separate from world packs)
   holding the system content. Same strict-JSON style as content packs.
2. **The character model** — `state.Character` gains a nested `CharacterSheet`
   carrying the D&D build (race/class/background/abilities/proficiencies/features/
   spells). NPCs keep `sheet = None` (they run on stat-block combat stats).
3. **The derivation engine** — pure functions in `rules/` that compute every
   derived number from (sheet + equipped items + ruleset). Stored = build choices
   + protected mutable state; derived = recomputed, never trusted from the wire.
4. **Chargen + the sheet UI** — a creation wizard in the New Game flow, and a full
   sheet panel in the ☰ menu (the stubbed "Party Sheets").

### §2.1 Why the SRD is a separate global layer, not merged into worlds

Class/race/background/spell data is **system content** — identical across every
world — so it lives once in `oubliette/content/srd/` and loads into a `Ruleset`
object carried on `LoadedWorld.ruleset`. It is NOT merged into each world's repo.

The only overlap is **equipment** (SRD weapons/armor/gear vs a world's special
items). To stay back-compatible (and not perturb the existing parity tests that
pin each world's baseline), SRD equipment is **not** auto-injected into a world's
item catalog. Instead, when a character is created, the specific gear they were
granted is registered into the repo's item catalog from the ruleset (event-sourced,
so replay re-registers it). World packs are otherwise untouched. *(Future, opt-in:
expose the full SRD gear catalog to a world's merchants — deferred, not needed for
chargen.)*

## §3. SRD content schemas (new, in `content/srd/`)

Strict Pydantic (`extra="forbid"`), same discipline as `content/schemas.py`. One
file per type; a whole-ruleset linter aggregates errors (like the pack loader).

- **`CharClass`** — id, name, hit_die (d6..d12), primary_ability, saving_throws
  (2 abilities), armor/weapon/tool proficiencies, skill_choices (pick N from a
  list), starting_equipment (options), spellcasting (none/full/half/third/pact +
  ability + known-vs-prepared), subclass_level, and a **level table** (1–20):
  proficiency-bonus is global, but features-gained, ASI levels, cantrips/spells
  known, and spell slots per level live here.
- **`Subclass`** — id, name, parent class, features by level.
- **`Race`** + **`Subrace`** — ability score increases, size, speed, darkvision,
  languages, racial traits (feature refs), subrace bonuses.
- **`Background`** — skill/tool/language proficiencies, equipment, a feature, and
  the flavor tables (personality/ideals/bonds/flaws) for the sheet.
- **`Spell`** — id, name, level, school, casting_time, range, components, duration,
  concentration, ritual, classes, and **description text** (the effect is reference
  text now; structured effect data is a thin extra field reserved for the combat
  arc).
- **`Feat`** — id, name, prerequisite, effect (ability bumps + feature text).
- **`Condition`** — the 15 SRD conditions as reference (used by the future combat
  arc; listed on the sheet when applied).
- **`SrdEquipment`** — extends the existing `content.Item` shape with the mechanics
  already half-present there (`WeaponProfile`, `ArmorProfile`): damage dice,
  properties, AC formula inputs (base_ac, type, dex_cap), weight, cost, category.

A `Feature` is referenced by id+source (race/class/subclass/background/feat) and
resolves to its SRD text for display and DM context.

## §4. The character model (`state.models`)

`Character` gains one optional field: `sheet: CharacterSheet | None = None`.

**`CharacterSheet`** (the build — set at creation, changed only by level-up):
- `race`, `subrace`, `char_class`, `subclass`, `background` (ruleset ids)
- `base_abilities` (the chosen scores) + `ability_method` (how they were generated)
  — final post-racial scores are written to the existing `Character.abilities` so
  all current code keeps working unchanged
- `saving_throw_proficiencies`, `skill_proficiencies` (the latter already on
  Character), `expertise`
- `armor_proficiencies`, `weapon_proficiencies`, `tool_proficiencies`, `languages`
- `features` (list of feature refs), `feats`
- `speed`, `size`, `alignment`, and the background flavor (traits/ideals/bonds/flaws)
- spellcasting (casters): `spellcasting_ability`, `cantrips_known`, `spells_known`,
  `spells_prepared`

**Protected mutable state** (already on Character, plus new): `hp`, `max_hp`,
`conditions`, `gold`, `inventory`, `equipped`, `xp`, `level`; **new**:
`spell_slots_used` (per level), `hit_dice_used`, and a generic
`resources: {name: {max, used}}` for charged features (rage, channel divinity, ki…).

**Derived (computed, never stored authoritatively):** AC, initiative, save mods,
skill mods, passive scores, spell save DC, spell attack, proficiency bonus,
spell-slot maxima, carrying capacity. The Phase-1 placeholder fields
(`armor_class`/`attack_bonus`/`damage` as plain numbers) become *computed* for PCs
with a sheet; NPCs keep using the stat-block values.

## §5. The derivation engine (`rules/derive.py`)

Pure functions over `(sheet, equipped_items, ruleset)` — replay-safe, unit-tested
against known SRD characters:
- `armor_class(...)` — unarmored 10+DEX; unarmored-defense variants (barbarian
  +CON, monk +WIS); light (base+DEX), medium (base+min(DEX,2)), heavy (base);
  +shield; + feature bonuses.
- `save_mod`, `skill_mod` (+expertise), `initiative`, `passive(skill)`
- `spell_save_dc` = 8 + prof + ability_mod; `spell_attack` = prof + ability_mod
- `max_hp` (class die at L1 + CON, + per-level average-or-rolled), `spell_slots`
  (full/half/third/pact tables), `proficiency_bonus` (exists)

## §6. Chargen flow

A wizard, in the New Game flow (so New Game becomes: **pick world → set the table
→ create your character → begin**). The UI proposes choices; the **backend
validates the whole build against the ruleset** (the firewall: you can't pick more
skills than the class allows, can't overspend point-buy, can't learn spells off
your list, etc.). Steps:

1. **Race** (+ subrace) 2. **Class** 3. **Background** 4. **Ability scores**
(method picker → assign → racial bonuses shown) 5. **Skills/proficiencies**
(resolve the class/background picks) 6. **Spells** (casters: cantrips + known/
prepared) 7. **Equipment** (choose from class/background options) 8. **Details**
(name, alignment, flavor) → **Create**.

Output: a fully-built `Character` (with sheet + computed derived stats), recorded
as a `CHARACTER_CREATED` event that replaces the scenario's `default_party`
stopgap. A **quick-start** option ("play a pre-made hero") uses the scenario's
`default_party` when present, so testing/jumping in stays one click.

Everyone starts at **level 1**. A player who wants a higher-level start says so in
the **table contract** (e.g. "begin at level 5"); the DM reads it and levels them
up once the leveling flow exists (CS5). Hacky-but-cheap, and it rides the channel
we already built.

## §7. The character sheet panel

The stubbed "Party Sheets" ☰ entry becomes a full sheet: identity (race/class/
background/level/alignment), ability scores + mods, saves, the skill list with
mods + proficiency dots, AC/HP/initiative/speed/proficiency-bonus, hit dice,
spellcasting block (DC/attack/slots + known/prepared with descriptions on click),
features (grouped by source, with text), proficiencies & languages, and equipment.
Read-only display of code-owned numbers — the whole point of the project. (Per-PC,
built to hold a party though only the one PC exists today.)

## §8. Persistence / event-sourcing

- `EventKind.CHARACTER_CREATED` — carries the built character + the ids of granted
  SRD items (registered into the repo catalog on apply/replay). `Session.open`
  uses it as the PC when present; else falls back to `default_party`. Replay-safe
  and byte-identical (D9).
- Level-up / rests / resource spend land in **CS5** with their own events
  (`CHARACTER_LEVELED`, `REST_TAKEN`, plus `StateOp`s for slot/hit-die/resource
  changes) — same record-then-apply discipline as everything else.

## §9. Licensing

The backbone is the **SRD 5.1**, available under **CC-BY-4.0**. We ship the
required attribution (a `SRD-OGL-NOTICE`/`NOTICE` file + an in-app credit): *"This
work includes material from the System Reference Document 5.1 ('SRD 5.1') by
Wizards of the Coast LLC, available under the Creative Commons Attribution 4.0
International License."* Oubliette is non-commercial/open-source, so this is clean.
(SRD version is an open question — see §10.)

## §10. Open questions — RESOLVED (2026-06-08, with OublietteDev)

1. **SRD version** — **5.1** (classic 5e / 2014 rules).
2. **Multiclassing** — **deferred**; single-class now, modelled so a class *list*
   can be added later.
3. **Feats** — **included**; feat-or-ASI offered at ASI levels (the SRD feat set
   is small).
4. **Starting level** — **level 1 only** in chargen. A player who wants to begin
   higher writes it into the **table contract** ("start me at level 5") and the DM
   levels them up once leveling exists (CS5). Deliberately a little hacky — it
   reuses the contract channel and saves chargen complexity now.
5. **HP on level-up** — offer both; **default average**.
6. **Party size** — **PC-only now** (companions gated on combat/recruit), built to
   hold a party.
7. **Quick-start hero** — **yes**, kept beside full chargen.

**Doc APPROVED — building begins at CS0.**

## §11. Build order

- **CS0 — Ruleset data model + loader. ✅ BUILT (2026-06-08, 140 tests green).**
  `content/srd_schemas.py` (CharClass/Subclass/Race/Subrace/Background/Spell/Feat/
  Condition/SrdEquipment, strict, full real shapes); `content/ruleset.py`
  (`Ruleset` + `load_ruleset()` with a whole-ruleset cross-ref linter, standalone
  helpers so no cycle with `loader.py`); vertical slice in `content/srd/*.json`
  (fighter + wizard w/ the full 20-row SRD slot table, human/elf/dwarf +
  high-elf/hill-dwarf, soldier/acolyte, 6 wizard spells, 3 feats, 3 conditions,
  10 equipment); `NOTICE` (SRD 5.1 CC-BY attribution); `LoadedWorld.ruleset` +
  `Session.ruleset` wired (NOT merged into world item catalogs — parity preserved).
  Tests `tests/test_srd_ruleset.py` (11).
- **CS1 — Character model + derivation engine. ✅ BUILT (2026-06-08, 156 tests green).**
  `state.models`: `FeatureRef` + `CharacterSheet` (the build); `Character.sheet`
  (+ `spell_slots_used`/`hit_dice_used` trackers); `Item` enriched with
  `armor_type`/`dex_cap`/`damage`; loader `_project_item` carries them (seed.py oracle
  updated to match → byte-identical parity preserved). `rules/derive.py`: AC (light/
  medium/heavy/shield + monk/barbarian unarmored defense), saves, skills (+expertise),
  initiative (+Alert), spell save DC/attack, slots, cantrips/prepared counts, max HP,
  racial ability application, + a `sheet_stats()` snapshot. Tests `tests/test_derive.py`
  (16) vs known SRD characters. NOTE: feature HP bonuses (Tough/Hill Dwarf) + fighting-
  style AC are CS5 refinements; hard-class schema stress (warlock pact/sorcerer/half-
  casters) pending the SRD source.
- **Schema-stress pass — ✅ DONE (2026-06-08, 162 tests green).** Before CS2/the
  content fleet, authored the hard classes from 5thsrd.org to lock the schema:
  Sorcerer (full caster + **Sorcery Points**), Warlock (**Pact Magic** — separate
  `PactProgressionRow`, short-rest recharge), Barbarian (**Rage** + unarmored defense,
  -1=unlimited at 20). Added `ClassResource` (sorcery points/ki/rage/channel divinity,
  sparse per-level) + `pact_magic_progression` to `CharClass`; `CharacterSheet.
  resources_used`; derive gained pact-slot handling, `class_resources`, `slots_recharge`.
  **Grounding technique confirmed:** WebFetch on 5thsrd.org transcribes full tables
  verbatim IF the prompt demands every cell (no summarizing) — the fleet recipe.
- **CS2 — Chargen.**
  - **Backend (the firewall) — ✅ BUILT (2026-06-08, 180 tests green).** `rules/chargen.py`:
    `CharacterBuild` (strict — the player's choices) + `build_character()`, which
    validates the whole build against the ruleset (aggregating every violation into
    one `ChargenError`) and returns a fully code-derived level-1 `Character` + the
    granted SRD gear. Enforces: ability method (standard array / point-buy ≤27 /
    rolled 3–18), class skill allotment (count + from-list + no background overlap),
    expertise needs proficiency, background free-language count, caster cantrip/spell
    counts + on-list + castable-level (non-casters get none), subrace required-iff-
    defined + race match, subclass only when the class grants it by this level,
    equipment choices complete + in range. Numbers (HP/AC/saves/attack) come from
    `rules.derive` — added `spells_known_count()`. `EventKind.CHARACTER_CREATED` +
    shared `install_character()` apply path (live + replay); `Repository.register_item`
    /`install_pc`; `Session.emit_character_created()` (record-then-apply). Quick-start
    = simply don't emit the event (falls back to `default_party`). Replay round-trip
    proven byte-identical. Tests `tests/test_chargen.py` (18).
    *(Known content-slice gaps, not validator gaps: only 2 wizard cantrips ship of 3
    needed, and sorcerer/warlock spell lists are empty — CS4 fills them. Racial skill/
    weapon proficiencies and extra languages that live in trait TEXT aren't auto-applied;
    wizard spellbook-vs-prepared is folded for now. All land with CS4/CS5.)*
  - **UI + New Game integration — ✅ BUILT (2026-06-08, 186 tests green).** New Game is now
    pick world → set the table → **create your character** → begin. The wizard (`ng-step-character`
    in the SPA) renders entirely from the ruleset — three new endpoints: `GET /api/chargen/options`
    (classes/races/backgrounds/per-class spells+equipment + ability constants, no SRD hardcoded in
    the browser), `POST /api/chargen/preview` (runs the firewall live → aggregated errors OR the
    fully code-derived sheet), and `POST /api/new` extended with an optional `build` (pre-validated
    BEFORE the save is erased — an invalid build can't cost you your game; absent = quick-start).
    Form covers identity, origin (race/subrace/class/background), all three ability methods
    (standard-array & rolled pool assignment, point-buy with live budget), skills (background grants
    locked), spells (casters), equipment choices, languages. Live preview panel shows AC/HP/saves/
    abilities/features/gear as you build; **Begin** stays disabled until the build is valid + named.
    Quick-start ("play a pre-made hero") skips it. Verified end-to-end in-browser (race-condition on
    out-of-order preview responses found & fixed with request sequencing). Tests in
    `tests/test_server_frontend.py` (+6): options, preview accept/reject, new-with-build, invalid-
    build-preserves-save, quick-start.
- **CS3 — Sheet panel. ✅ BUILT (2026-06-08, 188 tests green).** The stubbed "Party
  Sheets" (👥) ☰ entry is now the full read-only sheet. `GET /api/sheet` returns the
  party's code-derived sheets (`_sheet_member` over `derive.sheet_stats` + the build +
  ruleset for display names and spell/feature text). The panel (`sheet-overlay` in the
  SPA) renders: identity line, combat stats row (AC/HP/Init/Speed/Prof/hit-dice), ability
  cards (mod + score), saving throws & all 18 skills with proficiency/expertise **dots**,
  a spellcasting block (DC/attack + slot pills + cantrips/prepared with descriptions on
  click), class resources, features grouped by source (expandable), proficiencies &
  languages, equipment (equipped marked), and personality flavor. Degrades gracefully for
  a sheet-less quick-start hero (basics only — no identity/spellcasting/features). Verified
  end-to-end in-browser (fighter sheet + quick-start degradation; spellcasting render via a
  synthetic payload since no caster is buildable until CS4). Tests in
  `tests/test_server_frontend.py` (+2): full PC sheet + quick-start degradation.
- **CS4 — SRD content fill (the slog).** Author the full backbone into
  `content/srd/*.json`, in chunks — I draft, OublietteDev verifies. Runs alongside CS1–CS3
  using the slice, then completes the set.
- **CS5 — Leveling, rests, resources. ✅ BUILT (2026-06-08, 212 tests green).**
  - **CS5a — Rests + tracking.** New absolute StateOps (`slots_used`/`hit_dice_used`/
    `resources_used`/`max_hp`/`level`) + repo setters. `rules/rest.py`: long rest (full
    HP, all slots, short+long-recharge resources reset, regain ½-level hit dice) and
    short rest (pact slots, short-recharge resources, optional hit-die healing rolled
    via the seeded RNG → recorded as absolute `hp_set`). `REST_TAKEN` event (via
    `emit_state`); `POST /api/rest`; the sheet grows a rest bar + shows used/max for
    slots/resources/hit-dice. Tests `tests/test_rest.py` (6).
  - **CS5b — Level-up.** `rules/levelup.py`: `level_up()` validates the choice (ASI sums
    to 2 / feat / cap 20; subclass required-at-its-level + class match; HP average-or-rolled
    in die range) and rebuilds the character one level up, carrying protected state over;
    `level_up_plan()` drives the UI. `CHARACTER_LEVELED` event reuses `install_character`
    (replay reinstalls the whole rebuilt PC). `GET /api/levelup/plan` + `POST /api/levelup`
    (server rolls HP via RNG when chosen). The sheet's rest bar gains a **Level Up** button →
    a modal (HP method, ASI/feat, subclass) with the firewall surfaced. NOTE: learning new
    cantrips/spells on level-up is deferred to CS4 (no caster is buildable until content lands;
    slots themselves are derived from level, so they already scale). Tests `tests/test_levelup.py`
    (16) + HTTP flow in `test_server_frontend.py`. The slice ships `champion` (fighter) +
    `evocation` (wizard) subclasses, so the subclass path is real & tested.
- **CS6 — DM context integration.** Feed the mechanical sheet + features/spells
  (reference) into `build_context` so the DM narrates rules-aware and calls for the
  right saves/checks.

*Effects resolution (spell damage, conditions, buffs) is explicitly out of scope
until the combat arc — by decision §1.*
