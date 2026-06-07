# Oubliette Table — Authored-Content Pipeline (design v0.1)

*Status: design doc, to be approved before building. Scope decided with the user:
**core world content** (items, stat blocks, NPCs, places, scenario); on-disk format
**JSON**; the **map** and **character creation** are deferred to their own arcs, but
this design lays the seams for both. Companion to `oubliette-table-spec-v0.2.md`
(the engine spec); this covers only how authored world content gets defined,
validated, and loaded.*

> Tags as in the spec: **[LOCKED]** (decided), **[PROPOSED — confirm]** (default this
> doc introduces), **[OPEN]** (undecided). Decisions made with the user are **[LOCKED]**.

---

## 0. Why, and the one rule

Today the world is hand-coded in `seed.py` (one PC, one merchant, a few items, two
enemy templates, one scene). That can't scale to authored, long-form play. The
pipeline lets a creator define a world **as data, not code**, and load it with a
guarantee:

> **A content pack either loads whole and valid, or it fails at load with a clear
> report — it never loads partially or breaks mid-game.** **[LOCKED — the user's
> "doesn't easily break" requirement]**

That guarantee is enforced by strict per-entity schemas **plus** a whole-pack
**cross-reference linter** that validates the pack as a graph *before* any of it
becomes game state.

---

## 1. Core concepts

| Term | Meaning |
|---|---|
| **Content pack** | A versioned, immutable bundle of world data (a directory of JSON files) that produces an authored baseline. |
| **Authored baseline** | The deterministic starting state the engine seeds from — replaces `seed_world()`. Per the engine spec, it is NOT event-sourced; it's the fixed seed that the event log replays on top of. |
| **Campaign** | A play-through: a **world pack** (versioned) + a **created party** (from character creation at start) + the **event log**. All three are needed to reconstruct state. |
| **Authored vs runtime canon** | Pack entities load as canon `origin: authored, status: confirmed` (load-bearing). Runtime `create_entity` content stays `provisional` (spec §11). The firewall and canon lifecycle are unchanged. |

**Replay implication [LOCKED].** A save pins `pack_id + pack_version` and stores the
created party. Reload = `load_pack(pinned) + inject(stored party) + replay(events)`.
So packs are **immutable once published**; editing a pack mints a new version. A
save opened against a changed/missing pack version warns rather than silently
diverging.

---

## 2. Pack layout [PROPOSED — confirm]

One directory per pack; **one JSON file per content type** (not one file per entity
— easier to diff, validate, and hand-edit before the authoring UI exists). JSON was
chosen for bulletproof validation/tooling; the future Creator UI writes these files
so humans rarely hand-edit raw JSON.

```
content/packs/brightvale/
  pack.json          # manifest: id, schema_version, name, version, author, entry_scenario
  items.json         # [ Item, ... ]
  statblocks.json    # [ StatBlock, ... ]   (the bestiary + NPC combat stats)
  npcs.json          # [ NPC, ... ]
  places.json        # [ Place, ... ]       (a graph via `exits` → map-ready)
  scenarios.json     # [ Scenario, ... ]    (start location + optional demo party)
```

`brightvale` is the **default pack** — our current seed migrated to data (§7).

---

## 3. Schemas (the core of this doc)

All schemas are **strict**: unknown fields are rejected (`model_config =
ConfigDict(extra="forbid")`), required fields must be present. Shown as a JSON
example + the validating Pydantic sketch. Ids are stable, unique-within-type slugs.

### 3.1 Pack manifest — `pack.json`
```json
{
  "id": "brightvale",
  "schema_version": 1,
  "name": "The Brightvale Market",
  "version": "1.0.0",
  "author": "OublietteDev",
  "description": "A starter market town.",
  "entry_scenario": "brightvale_market"
}
```
```python
class PackManifest(BaseModel):
    id: str
    schema_version: int          # this doc defines version 1
    name: str
    version: str                 # semver; bumps mint a new immutable pack version
    author: str = ""
    description: str = ""
    entry_scenario: str          # which Scenario a new campaign starts in
```

### 3.2 Item — `items.json`
Extends the engine's `Item` with optional `weapon`/`armor` blocks (so combat & the
inventory panel are future-proof). AC-from-equipment math is still deferred, but the
data is captured now.
```json
{
  "id": "leather_jerkin", "name": "leather jerkin", "category": "armor",
  "description": "Supple boiled leather.", "base_value": 10, "tags": ["light"],
  "slot": "body",
  "armor": { "base_ac": 11, "type": "light", "dex_cap": null },
  "weapon": null
}
```
```python
class WeaponProfile(BaseModel):
    attack_bonus: int = 0
    damage: str                  # dice spec, e.g. "1d6+1"
    properties: list[str] = []   # "finesse", "light", "two-handed", ...

class ArmorProfile(BaseModel):
    base_ac: int
    type: Literal["light", "medium", "heavy", "shield"]
    dex_cap: int | None = None   # for the eventual AC computation

class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    category: Literal["weapon","armor","gear","consumable","treasure","misc"] = "misc"
    description: str = ""
    base_value: int | None = None
    tags: list[str] = []
    slot: str | None = None      # equip slot: main_hand/off_hand/body/feet/...
    weapon: WeaponProfile | None = None
    armor: ArmorProfile | None = None
```

### 3.3 StatBlock — `statblocks.json` (bestiary + NPC combat)
Replaces the hardcoded enemy templates and gives NPCs combat stats by reference.
```json
{
  "id": "road_bandit", "name": "road bandit", "kind": "monster",
  "abilities": {"str":11,"dex":12,"con":12,"int":10,"wis":10,"cha":10},
  "hp": 11, "armor_class": 12, "attack_bonus": 3, "damage": "1d6+1",
  "xp": 25, "skills": ["stealth"], "traits": [],
  "loot": [{"gold": 8}], "description": "A desperate road-robber.", "srd_ref": null
}
```
```python
class LootEntry(BaseModel):           # gold XOR item (mirrors ValueEntry)
    gold: int | None = None
    item: str | None = None
    qty: int = 1

class StatBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: Literal["monster", "npc"] = "monster"
    abilities: dict[str, int] = {}        # str..cha
    hp: int
    armor_class: int
    attack_bonus: int = 0
    damage: str = "1d4"
    xp: int = 0
    skills: list[str] = []                # proficient skills (SRD skill ids)
    traits: list[str] = []                # special abilities (prose for now)
    loot: list[LootEntry] = []
    description: str = ""
    srd_ref: str | None = None
```

### 3.4 NPC — `npcs.json`
A world character (kind=npc). Combat stats come from a referenced StatBlock.
```json
{
  "id": "merchant_thom", "name": "Thom", "stat_block": "commoner",
  "disposition": "cautious and shrewd; greedy when flattered",
  "description": "A leather-goods merchant.", "role": "merchant",
  "home_location": "brightvale_market", "gold": 500,
  "inventory": [
    {"item":"traveling_boots","qty":2}, {"item":"leather_satchel","qty":1},
    {"item":"sturdy_belt","qty":3}, {"item":"waterskin","qty":4}, {"item":"riding_gloves","qty":2}
  ],
  "price_list": {"traveling_boots":10,"leather_satchel":15,"sturdy_belt":5,"waterskin":4,"riding_gloves":8}
}
```
```python
class InvEntry(BaseModel):
    item: str
    qty: int = 1

class NPC(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    stat_block: str | None = None         # → StatBlock id (combat)
    disposition: str = ""                 # feeds the DM's DC-setting (D8)
    description: str = ""
    role: str = ""                        # "merchant", "quest_giver", ... (advisory)
    home_location: str | None = None      # → Place id (where they're present)
    gold: int = 0
    inventory: list[InvEntry] = []
    price_list: dict[str, int] = {}       # merchant asking prices (→ Item ids)
```

### 3.5 Place — `places.json` (a graph; map-ready)
```json
{
  "id": "brightvale_market", "name": "Brightvale Market Square",
  "description": "A crowded market square in the town of Brightvale. Thom's leather stall stands nearby...",
  "tags": ["town","safe"],
  "exits": [{"to":"brightvale_gate","label":"north toward the gate"}],
  "position": null
}
```
```python
class Exit(BaseModel):
    to: str                               # → Place id
    label: str = ""                       # prose ("north toward the gate")

class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str                      # becomes the SCENE when the party is here
    tags: list[str] = []
    exits: list[Exit] = []                # the connection graph the MAP derives from
    position: dict | None = None          # {x,y} — reserved for the map UI; optional now
```
*Map seam:* `exits` already give the map its edges; `position` is reserved for later
coordinates. NPCs are linked to a place via `NPC.home_location` (not duplicated here),
so "who's present" is a derived query.

### 3.6 Scenario — `scenarios.json`
Ties it together: where a campaign begins. The **party is normally created at New
Campaign** (character creation, deferred) — `default_party` exists only so a pack can
ship a playable demo / test party until chargen lands.
```json
{
  "id": "brightvale_market", "name": "A Morning at Brightvale",
  "start_location": "brightvale_market",
  "scene_override": null,
  "party_source": "creator",
  "default_party": [ { "...": "a full character definition (see §6)" } ]
}
```
```python
class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    start_location: str                   # → Place id
    scene_override: str | None = None     # optional: override the place description as the opening scene
    party_source: Literal["creator", "default"] = "creator"
    default_party: list[dict] = []        # PC definitions used when party_source == "default" (demo/test)
```

---

## 4. Validation — two layers

### 4.1 Schema layer (per entity)
Strict Pydantic (`extra="forbid"`, required fields, typed). Catches malformed
entities with field-level errors.

### 4.2 Cross-reference linter (whole pack)
After every entity parses, validate the pack **as a graph**. Collect *all* problems
into one aggregated report (don't stop at the first) and refuse to load if any exist:

- **Unique ids** within each type; ids referenced anywhere must resolve.
- **Item refs** exist: NPC `inventory.item`, NPC `price_list` keys, StatBlock `loot.item`,
  default-party equipment/inventory.
- **StatBlock refs** exist: `NPC.stat_block`.
- **Place refs** exist: `NPC.home_location`, every `Exit.to`, `Scenario.start_location`.
- **Scenario**: `entry_scenario` (manifest) resolves; `start_location` resolves.
- **Loadout sanity** (default party): equipped items are in inventory; equip slots known.
- **Pricing sanity**: every `price_list` item is also stocked in that NPC's inventory
  (you can't sell what you don't hold — matches the trade window's assumption).
- **(Map, when enabled)** exit graph well-formed (targets exist; optionally:
  reachability / bidirectionality). Deferred with the map, but the data is checked now.

Output: a `PackValidationError` listing every issue with the file + id + field, e.g.
`npcs.json: merchant_thom.price_list references unknown item 'belt'`.

---

## 5. Loading & engine integration

```python
def load_pack(pack_id: str) -> LoadedWorld:
    """Read pack files → validate (schema + linter) → build the authoritative
    baseline. Raises PackValidationError (aggregated) on any problem."""
```

- `LoadedWorld` carries the `InMemoryRepository` (characters, items) **plus** authored
  `CanonRecord`s (origin=authored, status=confirmed) for NPCs/places/lore so retrieval
  (canon search) and the canon lifecycle work over authored content too.
- `seed_world()` is replaced by `load_pack(default_pack_id)`. `Session.open` seeds from
  the pack; a `SESSION_MARKER(start)` event records `pack_id + pack_version` so reload
  re-seeds from the right pack.
- Authored entities map onto existing engine models 1:1: `Item → state.Item`,
  `StatBlock → combat template / a statted Character`, `NPC → state.Character(kind=npc)`
  `+ CanonRecord`, `Place → scene + present-NPC query (+ later map)`, `Scenario → start
  location + party`.

---

## 6. Seams for the deferred arcs

### 6.1 Character creation (deferred, but designed for)
- The **party is not in the world pack.** At **New Campaign**, a character-creation UI
  produces the PC(s); they're stored **with the save** (they're authored-at-start and
  deterministic, so replay re-injects them).
- A reusable `CharacterDef` schema (abilities, class, ancestry, background, starting
  kit, equipment, equipped) is shared by chargen output *and* `Scenario.default_party`,
  so the demo party and a created party use the same shape. (Full chargen — class/
  ancestry/kit option data — is its own arc; this doc only reserves the seam.)
- Loading: `Session.open` builds state from `load_pack(world) + inject(party)`.

### 6.2 Map (deferred, but data is ready)
- The map is **derived from `Place.exits`** (the graph) + optional `Place.position`
  coordinates. No separate map authoring needed; when we build the map arc it consumes
  places. The linter already checks exit integrity.

---

## 7. Migration: the default Brightvale pack

P1 migrates today's `seed.py` content into `content/packs/brightvale/`:
- **items.json** — boots, knife, leather_jerkin, healing_draught, traveling_boots,
  leather_satchel, sturdy_belt, waterskin, riding_gloves (with categories + the new
  weapon/armor blocks).
- **statblocks.json** — `road_bandit`, `lean_wolf` (from the combat templates), plus a
  `commoner` for Thom.
- **npcs.json** — `merchant_thom` (stock + price_list).
- **places.json** — `brightvale_market` (the current scene; one exit stub).
- **scenarios.json** — `brightvale_market` with `party_source: "default"` and a
  `default_party` holding today's PC, **until chargen exists**.

`load_pack("brightvale")` must produce a baseline **equal to today's `seed_world()`**
(a migration test pins this), so nothing downstream changes behavior.

---

## 8. Build order for P1 (after this doc is approved)

1. `content/schemas.py` — the strict Pydantic models above (schema_version 1).
2. `content/loader.py` — read pack dir → parse → cross-reference linter → `LoadedWorld`;
   aggregated `PackValidationError`.
3. Migrate Brightvale → `content/packs/brightvale/*.json`.
4. Swap `seed_world()` → `load_pack("brightvale")`; record pack id/version on session start.
5. Tests: valid pack loads & equals the old seed; a broken pack (bad ref, missing field,
   dup id, unstocked price) yields a clear aggregated error; replay still byte-identical.

P2 (authoring UI), P3 (character creation), P4 (bestiary/map/party-sheet panels) follow
as their own arcs, in that order.

---

## 9. Open questions [OPEN]

1. **Pack registry / save pinning** — where the list of installed packs lives and how a
   save resolves its pinned `pack_id + version` (and what to do on a version mismatch:
   warn + best-effort, or refuse). Lean: warn + load, flag divergence risk.
2. **Editing the default pack during dev** — bumping `version` on every tweak is noisy;
   maybe a dev mode that doesn't pin strictly. Decide before P2.
3. **SRD reference data** (skills/abilities, eventually classes/rules) — keep in code
   (current enums) or move into a base "SRD pack"? Lean: keep SRD core in code for now;
   authored packs add *world* content, not rules — revisit with the Bestiary/Rules arc.
4. **Per-type files vs per-entity files** — §2 proposes per-type; large packs might want
   per-entity later. Loader should be agnostic (glob a type's directory if present).
5. **Encounters / quests / factions schemas** — out of v1 scope; slot in as new files +
   linter rules without breaking schema_version 1 (additive).
