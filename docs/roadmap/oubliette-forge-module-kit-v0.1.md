# Forge Module Kit — v0.1

*2026-07-02. Scope agreed with OublietteDev after a two-agent audit of the Forge and the
content pipeline. Guiding question: "what does a typical published module add to a
session, and where does the Forge come up short?"*

## Findings that shaped the scope

- The world-and-story half of a module is already well covered: places/exits/art/
  soundscapes, NPCs with commerce and combat routing (Phase 4), branching quests
  with hooks/rumors/DM-only briefings, lore, AI profiles, bestiary gating.
- **Items are the big cheap gap.** Pack `content.Item` knows only name/category/
  value/slot/weapon/armor. The SRD side (`srd_schemas.SrdEquipment`) already carries
  the full Phase-A frozen magic-item contract — `item_type`, `rarity`, `magic_bonus`,
  `requires_attunement`, `mechanics`, `ConsumableMechanics`, `PoisonMechanics` — and
  the Arena bridge + `use_item` tool already CONSUME all of it. Pack items were just
  never upgraded; `equipped_magic`'s docstring says so outright
  (`arena_bridge.py:280` "Pack items aren't in the SRD catalog and carry no
  mechanics yet").
- **SRD 5.1 ships exactly ONE background** (Acolyte — verified in
  `oubliette/content/srd/backgrounds.json`). Every character in every world is a
  former temple servant. (An earlier subagent report claiming 13 backgrounds was
  wrong.)
- Character options are SRD-only by explicit deferral. Full custom classes/races/
  freeform spells are a huge mechanical surface → deferred to v2.0
  (see `oubliette-v2-wishlist.md`).
- Framing that priced the scope: every player option has a **table half** (prose the
  AI DM honors for free — a real advantage of this architecture) and an **Arena
  half** (structured data the engine must execute — where all cost lives).
  Backgrounds ≈ 100% table half; spells ≈ the inverse, hence the chassis approach.

## The arc — three stages, in order

### Stage 1 — Rich magic items (LOW cost, HIGH module impact)

Bring pack items to parity with the Phase-A contract. No new engine mechanics.

1. **Schema**: extend `content.Item` (`content/schemas.py`) with the same fields as
   `SrdEquipment`'s magic block — `item_type`, `rarity`, `magic_bonus`,
   `requires_attunement`, `mechanics`, `consumable`, `poison`. Share the shapes
   (import `ItemType`/`ConsumableMechanics`/`PoisonMechanics` from `srd_schemas`,
   or hoist to a shared module) — do NOT fork the contract.
2. **Linter** (`content/loader.py`): `mechanics == "structured"` requires a
   `consumable` or `poison` payload; `magic_bonus` only on sensible `item_type`s;
   scroll items reference a real spell; friendly aggregated errors as usual.
3. **Catalog plumbing**: the bridge's equipment catalog and the `use_item` /
   `give` resolution become SRD + pack merged (pack wins on id collision — same
   tier rule as today's item projection). Update `equipped_magic` + docstring,
   `_drink_action` sourcing, and the session-open fallback attach
   (`runtime/session.py:129`).
4. **Forge UI** (`creator/static/index.html`, item editor ~775–858): `item_type`
   dropdown, rarity, attunement checkbox, magic bonus, and conditional sub-forms —
   consumable mechanics (healing dice / ability set / resistance / duration /
   action), poison (type, save DC, damage, conditions, duration), scroll (spell
   picker + level). **Edit tool or Python only — never PowerShell bulk edits on the
   HTMLs (mojibake).**
5. **Tests + live check**: schema/linter/round-trip via `test_creator_server.py`
   patterns; bridge test that an equipped pack +1 sword raises attack/damage and a
   pack healing potion becomes a drink action; live-verify in a fight.
   **Gotcha: oubliette-side changes need an app-server restart** (stale-server trap).

### Stage 2 — Custom backgrounds (LOW cost)

Packs contribute backgrounds that merge into the ruleset for chargen.

1. **Pack file**: `packs/<id>/backgrounds.json`, schema = the existing
   `srd_schemas.Background` shape (skills, tool profs, equipment refs, feature,
   personality/ideals/bonds/flaws). Equipment refs may point at pack items
   (Stage 1 synergy).
2. **Ruleset merge**: chargen options become pack-aware — SRD + active pack's
   backgrounds. Id collisions with SRD are a lint error (no shadowing character
   options; keep it simple). Touches both chargen surfaces: the main app's
   campaign chargen and the Forge's embedded person-NPC wizard
   (`/api/chargen/options` must know the pack).
3. **Forge editor**: new Backgrounds panel — name, 2-skill picker, tool profs,
   starting equipment refs, feature name+text, roleplay-table lists.
4. **Tests + live check**: build a "Silverfin Dockhand", roll a character with it,
   confirm skills/gear/feature land on the sheet and the DM context.

### Stage 3 — Chassis spell builder (MEDIUM cost)

Custom spells constrained to shapes the Arena already executes. The author picks a
**chassis** and fills in numbers; the Forge emits both halves.

1. **Chassis set (v1)**: `bolt` (spell attack roll → damage), `blast` (save vs
   half/none + AoE shape the Arena already telegraphs), `heal`, `hex` (save vs
   condition, with duration/concentration). Fields: level, school, classes,
   range, damage dice+type or condition, save ability, AoE shape+size, simple
   upcast rule (extra dice per slot level).
2. **Two outputs per spell**: a `packs/<id>/spells.json` entry (chargen-side:
   list membership, level, description) + a generated Arena action file
   (`packs/<id>/spells/<spell_id>.json` sidecar, mirroring the `monsters/`
   pattern; bridge learns the pack-first spell-action lookup alongside
   `arena/data/spells/srd/`).
3. **Forge editor**: chassis picker + a live "stat block" preview of the generated
   spell text so authors see what players will read.
4. **Explicitly out (v2.0)**: summons, walls, teleports, freeform effects.
5. **Tests + live check**: author a signature Atria spell, learn it in chargen,
   cast it in the Arena, confirm damage/save/AoE and slot spend round-trip.

## Cheap riders (grab only if the adjacent code is already open)

- Monster complex-trait form fields (legendary resistance, regeneration, undead
  fortitude, death burst) — engine supports them; today raw-JSON only.
- "Save this build to the scenario's default party" affordance (chargen exists).
- Per-place DM-only notes field ("the third flagstone hides a lever").

Otherwise these live on the v2.0 wishlist — don't let them creep this arc.

## Test gates

Baseline at arc start: oubliette 3002 green, arena 2475 green, main clean.
Each stage lands green + live-verified before the next begins.
