# Content-First Plan — SRD Completion → Arena Fidelity v0.1

**Status:** DRAFT for OublietteDev's review. Written 2026-06-09.
**Arc:** Closes the content gap found by the Arena deep audit, then finishes Arena fidelity (Stage 4).
**Companion docs:** `oubliette-combat-arena-v0.1.md` (the Arena integration design), memory `oubliette-arena-audit` (the full audit).
**Executor:** Opus, working with OublietteDev. This doc is written to be executed without re-deriving the audit.

---

## 1. Intent & the organizing rule

The Arena audit (2026-06-09, seven-agent ground truth) found that the combat engine is far more
complete than assumed; the real gaps are (a) **content that exists in neither project** (the SRD
magic-item chapter), (b) **bridge fidelity** (PCs arrive with no spells/items/features), and
(c) **resource round-trip** (nothing spent in the Arena is recorded back — infinite potions/slots).

OublietteDev's directive: **make Oubliette content-complete from the SRD's point of view FIRST, then make
the Arena consume it faithfully.** After Phase A, Oubliette is only touched for prompt refining,
balance, and small immersion features — never for schema or critical systems. Re-opening an
Oubliette system mid-Arena-work means re-updating the Arena too: twice the work.

**THE ORGANIZING RULE: Phase A freezes the Oubliette-side contracts.** Everything the Arena will
later need must be *designed into the data now*, even though the Arena doesn't read it yet:

1. **Item schema** — generated magic items carry structured mechanics fields (healing dice, +X
   bonuses, resistance grants, ability buffs), not just prose, so the bridge later maps them
   without touching Oubliette.
2. **Portrait convention** — PC portraits use the same `portrait_url` convention the bestiary
   already established, so Arena tokens just read it.
3. **Resource ops** — already frozen: CS5 built `spell_slots_used` / `resources_used` /
   `hit_dice_used` with full StateOp/replay plumbing (`oubliette/rules/rest.py`,
   `oubliette/record/events.py:48`). Phase B writes into these; nothing new needed.

After Phase A the dependency is one-way: **Arena reads Oubliette; Oubliette never learns about
the Arena's internals.**

---

## 2. What the audit found missing (the inputs to this plan)

- **Oubliette SRD catalog is mundane-only.** `oubliette/content/srd/equipment.json`: 238 items =
  weapon 37 / armor 13 / gear 141 / misc 40 / consumable 7. Exactly ONE potion (Potion of Healing,
  present only because it's PHB ch. 5). The SRD 5.1 magic-item chapter (~240 items) is absent.
- **The Arena has no item library at all.** No items dir under `arena/data/`; potions exist only
  inline in 5 hand-authored demo characters. Scroll usage is unimplemented engine-side.
- **Acquisition is catalog-gated.** Inventory is id-referenced (`ItemStack.item_id`); the `give`
  tool validates ids. Un-cataloged items cannot be granted. (CreateEntity can mint flavor items,
  but they carry no mechanics.)
- **PC portraits don't exist yet** (bestiary portraits do). Both are meant to carry into the
  Arena as board tokens.
- **Engine-side gaps relevant later (Phase B):** consumable `charges` never decremented; magical
  damage tags never written; cantrip scaling authored off; handoff result schema v1 returns no
  spent-resource/consumption data.

---

## 3. Phase A — Oubliette SRD completion (the "close out Oubliette" pass)

### A1. SRD magic-item catalog (the centerpiece)

**Method — the proven playbook, fourth use:** deterministic parse of the 5e-bits/5e-database
JSON (`src/2014/5e-SRD-Magic-Items.json`), fetched via curl + parsed in Python.
**NOT WebFetch (known to garble tables), NOT hand-authoring (the burnout pit), NOT LLM generation.**
Same shape as `tools/gen_bestiary.py` / `tools/gen_arena_monsters.py` / the CS4 equipment fill.
Build it as `tools/gen_magic_items.py`, validate every record against the Item model on write.

**Honest difficulty note (differs from the equipment fill):** magic-item mechanics in the source
live mostly in *prose* (`desc` arrays), not structured fields. Deterministic extraction still
works, but per-family **pattern rules**, applied in this priority order:

| Family | Pattern source | Structured fields to emit |
|---|---|---|
| Healing potions (4 tiers) | dice in desc ("2d4 + 2") | `consumable.healing: "2d4+2"`, action cost |
| +1/+2/+3 weapons/armor/shields | name + rarity | `magic_bonus: N`, base-item link |
| Ability-score potions (Giant Strength etc.) | score in desc ("becomes 21") | `consumable.ability_set: {str: 21}`, duration |
| Potion of Resistance / similar | damage type in desc | `consumable.grants_resistance: <type>`, duration |
| Spell scrolls (by level) | level table | `consumable.casts_spell_level: N` (mechanics deferred — see F3) |
| Everything else (wondrous, rings, rods…) | — | prose `description` + `mechanics: "none"` marker |

The `mechanics: "none"` marker matters: it tells the Phase-B bridge, deterministically, what it
can carry into combat vs. what stays story-flavor. **No item is skipped** — content-complete means
the DM can grant any SRD item; only the *mechanization* is tiered.

Schema additions to the Item model (design once, here): new categories (`potion`, `scroll`,
`wand`, `ring`, `rod`, `staff`, `wondrous`), a `consumable` mechanics sub-object, `magic_bonus`,
`rarity`, `requires_attunement: bool` (recorded, NOT enforced — attunement mechanics deferred).
Fold into the same catalog namespace `ruleset.equipment` so `give`/inventory/validation work
unchanged the moment the file lands.

**Verify:** catalog count lands near the SRD's ~240; every mappable-family item has structured
mechanics; full test suite green; live check = DM `give`s a Potion of Greater Healing in a real
session and it appears in inventory.

### A2. SRD completeness sweep (find anything else that's missing)

One bounded enumeration task — check Oubliette coverage of every SRD 5.1 chapter, report, fill
only what's worth filling. Checklist: races (9 — chargen should already have them; verify),
backgrounds (SRD has 1: Acolyte), feats (SRD has 1: Grappler), **poisons (~14 — combat-relevant,
likely worth adding to the catalog with the A1 schema)**, diseases (3 — probably lore-only),
madness/traps/objects/planes (lore-only; skip or note). Output: a short gap report for OublietteDev,
then fill the agreed items with the same deterministic method. This sweep is what makes
"content-complete from the view of the SRD" a *checked* claim instead of a hoped one.

### A3. Player-character portraits (new Oubliette feature)

Bestiary portraits exist with a `portrait_url` convention; PCs have nothing. Build the PC side
now so the Arena token work in Phase B is read-only.

- Storage: `portrait_url` on Character (same convention as bestiary StatBlock).
- Display: character sheet panel; whatever chargen/Forge surface fits.
- **Fork F2 for OublietteDev (game experience):** where does the art come from? (a) a curated preset
  gallery shipped with Oubliette, (b) player-uploaded image, (c) generated art. Pick before
  building; the *convention* is the frozen contract either way, so this fork can't cause rework.

**Verify:** PC shows a portrait in the browser; the URL survives save/replay.

### A4. DM awareness (light touch)

Adding items to the catalog automatically makes them grantable (validation keys off the catalog).
Optionally teach the DM prompt that magic items exist and roughly when to hand them out — but this
is the "prompt refining" OublietteDev reserved for later; do nothing here beyond confirming `give` works.
Loot-table balance is explicitly a Phase-B7/later concern.

**Phase A exit criteria:** SRD catalog complete (A1 + agreed A2 fills), PC portraits live, suite
green, and — the point — **no Oubliette schema/system changes anticipated for the rest of the
project.**

---

## 4. Phase B — Arena fidelity (consumes Phase A; Oubliette is read-only from here)

Ordering inside Phase B: correctness first (the state-divergence class), then the PC's kit, then
polish. Each stage shippable alone.

- **B0 — Handoff result schema v2 (the contract).** Extend `arena/handoff.py build_result` to
  report, per PC: spell slots remaining, class resources remaining, consumables used (item id +
  qty), temp HP, death-save state. Version the schema (`schema: 2`); keep v1 fields intact.
  Design this ONCE — it's the Arena-side twin of the Phase-A freeze.
- **B1 — The potion vertical slice (prove the pipeline with one molecule).** Potion of Healing
  end-to-end: story inventory → bridge maps it to an Arena Item with `potion_action_type` →
  player drinks it mid-fight (UI already supports this) → **fix the engine charge decrement**
  (audit: `charges` never decremented) → handoff v2 reports consumption → Oubliette decrements
  the ItemStack. Live-verified in a real fight.
- **B2 — Resource round-trip.** Bridge carries current slots/resources IN (from
  `spell_slots_used` etc.); handoff v2 brings spent state OUT; map onto the existing CS5 ops.
  Pure wiring — the model and rests already exist.
- **B3 — Scale items.** Bridge maps the whole A1 catalog: consumables with mechanics become Arena
  item actions; +X gear becomes `magic_bonus` items (AC/to-hit already honor it); `mechanics:
  "none"` items stay story-side. Write the "magical" damage tag for magic weapons (packets were
  built for this — closes the audit's immunity-bypass gap).
- **B4 — PC kit fidelity (the big one).** Deterministic spell-action generator
  (5e-database spells → Arena Action JSON, central spell library keyed by spell id — the Arena
  currently has none); bridge reads the real sheet: spells known/prepared + slots, speed, saving
  throw proficiencies, equipment-derived loadout. Cap per D-COMBAT-2: generate what the existing
  primitives express (the audit's 12-spell probe: ~85% of combat spells), skip the rest
  gracefully (summon/transform/illusion families).
- **B5 — Engine quick wins** (any order, small): enable cantrip scaling in generated/authored
  data; roll-vs-AC breakdown in the combat log; AI friendly-fire check on AoE scoring; AoE
  template preview if cheap.
- **B6 — Portraits as tokens.** Arena tokens read `portrait_url` for monsters (bestiary) and PCs
  (A3). Read-only consumption of frozen conventions.
- **B7 — Playtest & balance.** Generated monsters apply their SRD conditions; live-play loop
  drives everything else (this loop has found every real bug so far). Balance/loot/prompt
  refinement happens here, against real fights.

**Still deferred, guilt-free:** Polymorph/Wild Shape, illusions/perception, flying speeds,
surprise, grapple, legendary resistance, attunement enforcement, scroll *casting* (see F3),
multi-PC parties, web board.

---

## 5. Forks for OublietteDev (decide before the relevant stage, not before starting)

- **F1 — Magic-item scope (decide before A1):** generate ALL ~240 SRD items vs. combat-relevant
  subset. *Recommendation: all* — "content-complete" is the stated goal, marginal cost of the
  long tail is near zero (prose + `mechanics: "none"`), and the DM gets the whole toy box.
- **F2 — PC portrait source (decide before A3):** preset gallery / upload / generated. Pure
  game-experience call; no rework risk either way.
- **F3 — Scrolls (decide before B3):** scrolls-as-castable need the spell library (B4) and new
  engine wiring (audit: scroll usage unimplemented). *Recommendation: catalog them in A1
  (acquirable, flavor + `casts_spell_level`), defer mechanization until after B4, maybe forever
  if playtests don't miss them.*
- **F4 — How magic items enter play (decide during B7):** purely DM-organic `give` vs. any
  loot-table guidance in the prompt. Balance-pass material; no code dependency.

---

## 6. Guardrails (the ones that have held — keep holding them)

1. **Deterministic generation only** for content at scale. Hand-authoring item/spell mechanics is
   the documented burnout pit. If a family can't be pattern-extracted, it ships as prose with
   `mechanics: "none"` — that is a *success state*, not a failure.
2. **The cap (D-COMBAT-2) is validated by data** — the audit's expressibility probe showed no
   universal generator is needed. Build only handlers/content real play reaches.
3. **Contracts before content consumers.** A1 schema and B0 schema each get designed once, in
   writing, before code that reads them.
4. **Every stage ends green + live-checked.** The full-suite count is the regression net
   (2,340 + new); the live-play loop is the truth-teller for what tests can't see.
5. **After Phase A, any proposed Oubliette schema/system change is a STOP-and-discuss** — that's
   the whole point of the ordering.

---

## 7. Verification ledger (what "done" means, per stage)

| Stage | Green check | Live check |
|---|---|---|
| A1 | catalog ≈ SRD count, mappable families structured, suite green | DM gives Greater Healing potion; it lands in inventory |
| A2 | gap report delivered; agreed fills validated | — |
| A3 | portrait persists through save/replay | PC portrait visible in browser |
| B0/B1 | slice tests both directions | drink a potion in a real fight; inventory decrements after |
| B2 | resource ops round-trip tests | cast in a fight; slots reflect it story-side; long rest restores |
| B3 | catalog-wide bridge mapping tests | +X weapon hits harder; magical bypasses immunity |
| B4 | spell library validates against Action model; caster PC gets kit | wizard casts a real spell in the Arena |
| B6 | — | your face and the dragon's face on the board |
