"""Read a content pack, validate it whole, and build the authored baseline.

Two validation layers (design doc §4):
  1. **Schema** — each entity is parsed by its strict Pydantic model.
  2. **Cross-reference linter** — the parsed pack is checked as a graph (refs
     resolve, ids unique, merchants stock what they price, loadouts are sane).

Both layers AGGREGATE: every problem found is collected into one
`PackValidationError`, so an author sees the whole list at once instead of
fixing-and-rerunning. A pack loads whole-and-valid or not at all.

P1 builds only the repository baseline (characters + items) — proven equal to the
old `seed.seed_world()`. Authored canon for NPCs/places is a later step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ..canon.models import CanonRecord
from ..coin import authored_to_cp
from ..enums import Ability
from ..state.models import Character, Item as StateItem, ItemStack
from ..state.repository import InMemoryRepository
from .ruleset import _VALID_SKILLS, Ruleset, load_ruleset
from .schemas import (NPC, AiProfile, AuthoredQuest, BattleMap, BestiaryGate,
                      Item, Lore, Place, PackManifest, Scenario, StatBlock)
from .srd_schemas import Background, PackSpell, SrdEquipment

DEFAULT_PACK = "brightvale"
_PACKS_ROOT = Path(__file__).parent / "packs"


class PackValidationError(Exception):
    """A pack that failed schema and/or cross-reference validation. Carries the
    full aggregated list of problems (`.errors`)."""

    def __init__(self, pack_id: str, errors: list[str]) -> None:
        self.pack_id = pack_id
        self.errors = errors
        body = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"content pack {pack_id!r} failed validation:\n{body}")


@dataclass(frozen=True)
class PlaceNode:
    """A runtime view of a Place: enough for the engine to move the party between
    locations and tell the DM where it can go (the full authoring Place stays in
    the pack)."""

    id: str
    name: str
    description: str
    parent: str | None
    exits: tuple[str, ...]        # destination Place ids
    image: str | None = None     # illustration filename (in the pack's images/ folder)
    map_image: str | None = None  # background map shown when drilled INTO this place
    position: dict | None = None  # {x, y} percent coords for the map (authored in The Forge)
    sounds: tuple = ()           # soundscape cues (AudioCue dicts) — the location's audio
    battle: "BattleMap | None" = None  # authored battlefield (location-battles arc) —
                                 # the combat bridge reads it when a fight starts here
    safe_haven: bool = False     # a safe overnight spot (rest gating, difficulty S3)
    encounters: tuple = ()       # authored KeyedEncounters bound here (living-world W1) —
                                 # the trigger module reads them each in-character turn


@dataclass
class LoadedWorld:
    """The authored baseline a campaign seeds from. `repository` is the engine's
    runtime state (characters + items); `canon` is the authored CanonRecords
    (NPCs/places) the session seeds for retrieval; `scene` is the opening
    location's prose; `places` is the location graph (for travel). The pack
    id/version are pinned onto the session so reload re-seeds correctly."""

    repository: InMemoryRepository
    canon: list[CanonRecord]
    scene: str
    location: str            # the start Place id — the party's current location
    places: dict             # {place_id: PlaceNode}
    pack_id: str
    pack_version: str
    world_map: str | None = None   # the top-level map background image filename (manifest)
    ruleset: Ruleset | None = None  # the global SRD ruleset (chargen/sheet/derivation)
    pack_name: str = ""            # the pack's display name (manifest.name; bestiary source label)
    statblocks: tuple = ()         # the pack's authored StatBlocks (this-world bestiary section)
    bestiary_gate: "BestiaryGate | None" = None   # per-world bestiary knowledge cutoff (manifest)
    quests: tuple = ()             # the pack's authored quests (offered during play, not canon)
    ai_profiles: tuple = ()        # the pack's authored AI personalities (Forge-authored monster behavior)
    # Forge Phase 4a: {npc entity id -> its StatBlock id}, only for NPCs that carry
    # one. Lets the combat bridge give a recurring creature-NPC (Seraphel) her full
    # statblock kit *with* persistent-entity semantics — the runtime Character drops
    # the stat_block ref, so this is how the entity is mapped back to its block.
    npc_statblocks: dict = field(default_factory=dict)
    # Module-kit S1: the ONE mechanics catalog every magic-item consumer reads —
    # the Arena bridge (equipped +X, drink actions) and the `use_item` tool. SRD
    # equipment first, the pack's items layered over it (pack wins on id collision,
    # the same precedence the repo's give/lookup tiers use).
    mechanics_catalog: dict = field(default_factory=dict)   # {item_id: SrdEquipment}


# --- file reading ------------------------------------------------------------
def _read_json(path: Path, filename: str, errors: list[str]):
    """Return parsed JSON, or None (recording an error) if missing/malformed."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None                      # optional file; caller decides if required
    except json.JSONDecodeError as e:
        errors.append(f"{filename}: invalid JSON ({e})")
        return None


def _parse_list(path: Path, model: type[BaseModel], filename: str,
                errors: list[str]) -> list:
    """Parse a JSON array of `model`. A missing file is treated as empty (the
    linter catches any dangling references). Per-entity errors are aggregated."""
    data = _read_json(path, filename, errors)
    if data is None:
        return []
    if not isinstance(data, list):
        errors.append(f"{filename}: expected a JSON array")
        return []
    out = []
    for i, raw in enumerate(data):
        ident = raw.get("id", f"index {i}") if isinstance(raw, dict) else f"index {i}"
        try:
            out.append(model(**raw))
        except (ValidationError, TypeError) as e:
            for line in _format_errors(e):
                errors.append(f"{filename}: {ident}: {line}")
    return out


def _format_errors(e: Exception) -> list[str]:
    if isinstance(e, ValidationError):
        out = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "(root)"
            out.append(f"{loc}: {err['msg']}")
        return out
    return [str(e)]


# --- cross-reference linter --------------------------------------------------
def _dup_ids(entities: list, type_name: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for ent in entities:
        if ent.id in seen:
            errors.append(f"{type_name}: duplicate id {ent.id!r}")
        seen.add(ent.id)


def _lint(manifest: PackManifest | None, items: list[Item], statblocks: list[StatBlock],
          npcs: list[NPC], places: list[Place], scenarios: list[Scenario],
          quests: list[AuthoredQuest], errors: list[str]) -> None:
    """Validate the parsed pack as a graph. Appends every problem to `errors`."""
    for entities, name in [(items, "items"), (statblocks, "statblocks"),
                           (npcs, "npcs"), (places, "places"), (scenarios, "scenarios"),
                           (quests, "quests")]:
        _dup_ids(entities, name, errors)

    item_ids = {i.id for i in items}
    statblock_ids = {s.id for s in statblocks}
    place_ids = {p.id for p in places}
    scenario_ids = {s.id for s in scenarios}

    def need_item(ref: str | None, where: str) -> None:
        if ref is not None and ref not in item_ids:
            errors.append(f"{where} references unknown item {ref!r}")

    def need_place(ref: str | None, where: str) -> None:
        if ref is not None and ref not in place_ids:
            errors.append(f"{where} references unknown place {ref!r}")

    # NPCs: stat block, home, stock, pricing.
    for n in npcs:
        if n.combat_kind == "person" and n.stat_block is not None:
            errors.append(f"npcs: {n.id} is a person (combat comes from its character) "
                          f"but also sets stat_block {n.stat_block!r}")
        if n.stat_block is not None and n.stat_block not in statblock_ids:
            errors.append(f"npcs: {n.id}.stat_block references unknown stat block {n.stat_block!r}")
        need_place(n.home_location, f"npcs: {n.id}.home_location")
        stocked = {e.item for e in n.inventory}
        for e in n.inventory:
            need_item(e.item, f"npcs: {n.id}.inventory")
        for priced in n.price_list:
            need_item(priced, f"npcs: {n.id}.price_list")
            if priced not in stocked:                 # can't sell what you don't hold (§9)
                errors.append(f"npcs: {n.id}.price_list prices {priced!r} but it is not in inventory")

    # Stat block loot.
    for s in statblocks:
        for drop in s.loot:
            need_item(drop.item, f"statblocks: {s.id}.loot")

    # Place exits + sublocation parents.
    for p in places:
        for ex in p.exits:
            need_place(ex.to, f"places: {p.id}.exits")
        if p.parent is not None:
            if p.parent == p.id:
                errors.append(f"places: {p.id} is set as its own parent")
            else:
                need_place(p.parent, f"places: {p.id}.parent")

    # Scenarios: start location + default party loadouts.
    for sc in scenarios:
        need_place(sc.start_location, f"scenarios: {sc.id}.start_location")
        _lint_default_party(sc, item_ids, errors)

    # Manifest entry scenario.
    if manifest is not None and manifest.entry_scenario not in scenario_ids:
        errors.append(f"pack.json: entry_scenario references unknown scenario {manifest.entry_scenario!r}")

    _lint_quests(quests, npcs, item_ids, need_item, need_place, errors)


def _lint_quests(quests: list[AuthoredQuest], npcs: list[NPC], item_ids: set[str],
                 need_item, need_place, errors: list[str]) -> None:
    """Validate authored quests as a graph: sources resolve and are reachable, reward items
    exist, and the branch edges form a sound chain (targets exist, no self-loops, every quest
    reachable as a root or some branch's target)."""
    quest_ids = {q.id for q in quests}
    npc_by_id = {n.id: n for n in npcs}
    branch_targets = {b.to for q in quests for b in q.branches}
    for q in quests:
        # Source resolves AND is reachable. A giver NPC with no home_location can never be
        # present in a scene, so the quest could never be offered — an authoring error.
        if q.giver_npc is not None:
            npc = npc_by_id.get(q.giver_npc)
            if npc is None:
                errors.append(f"quests: {q.id}.giver_npc references unknown npc {q.giver_npc!r}")
            elif npc.home_location is None:
                errors.append(f"quests: {q.id} is given by {q.giver_npc!r}, who has no home_location "
                              f"(the quest could never be found)")
        need_place(q.giver_place, f"quests: {q.id}.giver_place")
        if q.reward is not None:
            need_item(q.reward.item, f"quests: {q.id}.reward")
        # Branch edges: each target exists and isn't the quest itself.
        for b in q.branches:
            if b.to == q.id:
                errors.append(f"quests: {q.id} branches to itself on outcome {b.outcome!r}")
            elif b.to not in quest_ids:
                errors.append(f"quests: {q.id}.branches references unknown quest {b.to!r}")
        # Reachability: a quest nobody can reach (not a root, not unlocked by any branch) is dead.
        if not q.root and q.id not in branch_targets:
            errors.append(f"quests: {q.id} is unreachable — it is not a root and no branch unlocks it")


def _lint_keyed_encounters(places: list[Place], statblocks: list[StatBlock],
                           npcs: list[NPC], ruleset: Ruleset,
                           errors: list[str]) -> None:
    """Keyed encounters (living-world W1): ids unique within their place, every
    enemy ref resolving NOW — a pack stat block, an SRD monster, or a pack NPC
    entity. A fight that cannot stage must fail at authoring time, never at the
    table. Matching mirrors the combat bridge's normalisation (id OR name,
    case/space/hyphen tolerant) but not its fuzzy trailing-word fallback:
    authored content is held to exact references."""
    def norm(s: str) -> str:
        return s.strip().lower().replace(" ", "_").replace("-", "_")

    bestiary = (getattr(ruleset, "bestiary", None) or {}).values()
    known: set[str] = set()
    for sb in (*statblocks, *bestiary):
        known.add(norm(sb.id))
        known.add(norm(sb.name))
    npc_ids = {n.id for n in npcs}
    for p in places:
        seen: set[str] = set()
        for enc in p.encounters:
            where = f"places: {p.id}.encounters[{enc.id}]"
            if enc.id in seen:
                errors.append(f"places: {p.id} has duplicate encounter id {enc.id!r}")
            seen.add(enc.id)
            for e in enc.enemies:
                if e.ref in npc_ids:
                    # A persistent NPC stages as ONE instance regardless of count
                    # (recurring-foe policy) — a count would silently vanish.
                    if e.count > 1:
                        errors.append(f"{where} names NPC {e.ref!r} with count "
                                      f"{e.count} — a persistent NPC is always one")
                elif norm(e.ref) not in known:
                    errors.append(f"{where} enemy ref {e.ref!r} is neither a stat "
                                  f"block (pack or SRD) nor a pack NPC")


def _lint_backgrounds(backgrounds: list[Background], items: list[Item],
                      ruleset: Ruleset, errors: list[str]) -> None:
    """Pack-authored backgrounds (module-kit S2): ids unique and non-shadowing
    (a pack ADDS character options, it never silently replaces an SRD one),
    skills real, and equipment grants resolving against the pack's items OR the
    SRD catalog (the merged session ruleset serves both at chargen time)."""
    _dup_ids(backgrounds, "backgrounds", errors)
    item_ids = {i.id for i in items}
    for b in backgrounds:
        if b.id in ruleset.backgrounds:
            errors.append(f"backgrounds: {b.id!r} shadows an SRD background — "
                          "give the pack's own background a new id")
        for sk in b.skill_proficiencies:
            if sk not in _VALID_SKILLS:
                errors.append(f"backgrounds: {b.id} lists unknown skill {sk!r}")
        for g in b.equipment:
            if g.item not in item_ids and g.item not in ruleset.equipment:
                errors.append(f"backgrounds: {b.id}.equipment references unknown "
                              f"item {g.item!r}")


def _lint_spells(spells: list[PackSpell], ruleset: Ruleset,
                 errors: list[str]) -> None:
    """Pack-authored chassis spells (module-kit S3): ids unique and
    non-shadowing (same rule as backgrounds — a pack ADDS options, never
    silently replaces an SRD spell), and class lists resolving against real
    classes. Chassis shape/number rules are enforced by the schema itself,
    so by the time we're here every chassis is internally sound."""
    _dup_ids(spells, "spells", errors)
    for s in spells:
        if s.id in ruleset.spells:
            errors.append(f"spells: {s.id!r} shadows an SRD spell — "
                          "give the pack's own spell a new id")
        for c in s.classes:
            if c not in ruleset.classes:
                errors.append(f"spells: {s.id} lists unknown class {c!r}")


def _lint_default_party(sc: Scenario, item_ids: set[str], errors: list[str]) -> None:
    """A default party is a list of state.Character dicts (the chargen stopgap).
    Validate each parses and that its inventory/equipped reference real items."""
    for i, raw in enumerate(sc.default_party):
        where = f"scenarios: {sc.id}.default_party[{i}]"
        try:
            pc = Character(**raw)
        except (ValidationError, TypeError) as e:
            for line in _format_errors(e):
                errors.append(f"{where}: {line}")
            continue
        held = {st.item_id for st in pc.inventory}
        for st in pc.inventory:
            if st.item_id not in item_ids:
                errors.append(f"{where} inventory references unknown item {st.item_id!r}")
        for eq in pc.equipped:
            if eq not in item_ids:
                errors.append(f"{where} equips unknown item {eq!r}")
            elif eq not in held:
                errors.append(f"{where} equips {eq!r} which is not in inventory")


# --- projection: authoring shapes -> engine runtime models -------------------
def _project_item(it: Item) -> StateItem:
    """content.Item -> state.Item. Carries the mechanical bits the derivation engine
    needs: armor base_ac/type/dex_cap (for AC math) and weapon damage."""
    return StateItem(
        id=it.id, name=it.name, category=it.category,
        tags=list(it.tags), value_cp=authored_to_cp(it.base_value),
        armor_class=(it.armor.base_ac if it.armor else None),
        armor_type=(it.armor.type if it.armor else None),
        dex_cap=(it.armor.dex_cap if it.armor else None),
        damage=(it.weapon.damage if it.weapon else None),
    )


def _project_mechanics(it: Item) -> SrdEquipment:
    """content.Item -> its mechanics-catalog entry (module-kit S1). Pack items
    share the Phase-A magic contract field-for-field, so this is a straight carry
    into the `SrdEquipment` shape the bridge and `use_item` already consume —
    a pack Flametongue behaves exactly like an SRD +1 sword, no special-casing."""
    return SrdEquipment(
        id=it.id, name=it.name, category=it.category, description=it.description,
        base_value=it.base_value, tags=list(it.tags), slot=it.slot,
        weapon=it.weapon, armor=it.armor,
        item_type=it.item_type, rarity=it.rarity, magic_bonus=it.magic_bonus,
        requires_attunement=it.requires_attunement, mechanics=it.mechanics,
        consumable=it.consumable, poison=it.poison,
        grants_resistances=list(it.grants_resistances),
        grants_immunities=list(it.grants_immunities),
    )


def mechanics_catalog(ruleset: Ruleset | None, items: list[Item]) -> dict[str, SrdEquipment]:
    """The merged magic-mechanics catalog a session plays with: the full SRD
    equipment set with the pack's items layered over it (pack wins on id collision —
    a world may deliberately reskin an SRD id)."""
    catalog: dict[str, SrdEquipment] = {}
    if ruleset is not None:
        catalog.update(ruleset.equipment)
    catalog.update({it.id: _project_mechanics(it) for it in items})
    return catalog


def _authored_canon(npcs: list[NPC], places: list[Place], lore: list[Lore]) -> list[CanonRecord]:
    """Authored NPCs, places and lore become confirmed, load-bearing canon so
    retrieval (canon search) and the canon lifecycle work over authored content
    too. The record id IS the pack slug (e.g. 'merchant_thom') — a namespace
    distinct from runtime 'canon-N' ids, so it never perturbs the session id
    counter. Not event-sourced: re-seeded from the pack on every load, like the
    repository."""
    records: list[CanonRecord] = []
    for n in npcs:
        records.append(CanonRecord(
            id=n.id, entity_type="npc", name=n.name, text=n.description,
            origin="authored", status="confirmed", load_bearing=True,
        ))
    for p in places:
        records.append(CanonRecord(
            id=p.id, entity_type="place", name=p.name, text=p.description,
            origin="authored", status="confirmed", load_bearing=True,
        ))
    for entry in lore:
        # subjects ride along as keywords so the lore surfaces when its people /
        # places are present or mentioned, without cluttering the displayed text.
        records.append(CanonRecord(
            id=entry.id, entity_type="lore", name=entry.title, text=entry.text,
            origin="authored", status="confirmed", load_bearing=True,
            keywords=list(entry.subjects) + list(entry.tags),
        ))
    return records


def _load_person_characters(base: Path, npcs: list[NPC],
                            errors: list[str]) -> dict[str, Character]:
    """Read + validate the chargen snapshot sidecar for every combat_kind=="person"
    NPC (`packs/<id>/characters/<npc_id>.json`, Forge Phase 4b). A person NPC whose
    sidecar is missing or invalid is an aggregated load error — combat comes from
    that file, so the pack can't load partially."""
    out: dict[str, Character] = {}
    for n in npcs:
        if n.combat_kind != "person":
            continue
        path = base / "characters" / f"{n.id}.json"
        raw = _read_json(path, f"characters/{n.id}.json", errors)
        if raw is None:
            if not path.exists():        # malformed JSON is already recorded by _read_json
                errors.append(f"npcs: {n.id}.combat_kind is 'person' but "
                              f"characters/{n.id}.json is missing")
            continue
        try:
            out[n.id] = Character(**raw)
        except (ValidationError, TypeError) as e:
            for line in _format_errors(e):
                errors.append(f"characters/{n.id}.json: {line}")
    return out


def _build_person_npc(n: NPC, char: Character) -> Character:
    """A person-NPC's runtime Character: the chargen snapshot is authoritative for
    combat (abilities, hp/ac/attack, the full sheet, equipped gear, belongings); the
    NPC record supplies identity + authored flavor (name, disposition, description,
    home). Editor-authored commerce for a person-NPC is a later refinement — for now
    a person's belongings ride along from their character build."""
    return char.model_copy(update={
        "id": n.id, "name": n.name, "kind": "npc",
        "disposition": n.disposition or char.disposition,
        "description": n.description or char.description,
        "home_location": n.home_location if n.home_location is not None else char.home_location,
    })


def _build_npc(n: NPC, statblocks: dict[str, StatBlock],
               person_chars: dict[str, Character] | None = None) -> Character:
    """Build a runtime npc Character. A "person" NPC runs on its chargen snapshot
    (Phase 4b); otherwise combat stats come from the referenced stat block (or
    Character defaults if none)."""
    if n.combat_kind == "person" and person_chars and n.id in person_chars:
        return _build_person_npc(n, person_chars[n.id])
    sb = statblocks.get(n.stat_block) if n.stat_block else None
    abilities = {Ability(k): v for k, v in (sb.abilities.items() if sb else {})}
    extra: dict = {}
    if sb is not None:
        extra = dict(
            hp=sb.hp, max_hp=sb.hp, armor_class=sb.armor_class,
            attack_bonus=sb.attack_bonus, damage=sb.damage, xp=sb.xp,
        )
    return Character(
        id=n.id, name=n.name, kind="npc",
        abilities=abilities,
        coin=authored_to_cp(n.gold) or 0,
        inventory=[ItemStack(item_id=e.item, qty=e.qty) for e in n.inventory],
        price_list={k: authored_to_cp(v) for k, v in n.price_list.items()},
        description=n.description,
        disposition=n.disposition,
        home_location=n.home_location,
        **extra,
    )


# --- public API --------------------------------------------------------------
def available_packs(packs_root: Path | None = None) -> list[dict]:
    """List the worlds that can be played: every pack folder with a manifest,
    as {id, name, version, recommended_difficulty}. Used by the game's New Game
    world-picker."""
    root = packs_root or _PACKS_ROOT
    out: list[dict] = []
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                manifest = json.loads((d / "pack.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                continue
            if not isinstance(manifest, dict):
                continue
            out.append({"id": d.name, "name": manifest.get("name") or d.name,
                        "version": manifest.get("version"),
                        "recommended_difficulty": manifest.get("recommended_difficulty")})
    return out


def load_pack(pack_id: str = DEFAULT_PACK, packs_root: Path | None = None) -> LoadedWorld:
    """Read `packs_root/pack_id/*.json` -> validate (schema + linter) -> build the
    authoritative baseline. Raises `PackValidationError` (aggregated) on any
    problem; the pack never loads partially."""
    base = (packs_root or _PACKS_ROOT) / pack_id
    errors: list[str] = []

    raw_manifest = _read_json(base / "pack.json", "pack.json", errors)
    manifest: PackManifest | None = None
    if raw_manifest is None:
        errors.append("pack.json: file missing or unreadable")
    else:
        try:
            manifest = PackManifest(**raw_manifest)
        except (ValidationError, TypeError) as e:
            for line in _format_errors(e):
                errors.append(f"pack.json: {line}")

    items = _parse_list(base / "items.json", Item, "items.json", errors)
    statblocks = _parse_list(base / "statblocks.json", StatBlock, "statblocks.json", errors)
    npcs = _parse_list(base / "npcs.json", NPC, "npcs.json", errors)
    places = _parse_list(base / "places.json", Place, "places.json", errors)
    lore = _parse_list(base / "lore.json", Lore, "lore.json", errors)
    scenarios = _parse_list(base / "scenarios.json", Scenario, "scenarios.json", errors)
    quests = _parse_list(base / "quests.json", AuthoredQuest, "quests.json", errors)
    ai_profiles = _parse_list(base / "ai_profiles.json", AiProfile, "ai_profiles.json", errors)
    backgrounds = _parse_list(base / "backgrounds.json", Background, "backgrounds.json", errors)
    spells = _parse_list(base / "spells.json", PackSpell, "spells.json", errors)

    # The SRD layer loads BEFORE the lint: pack backgrounds/spells are checked
    # against its sets (S2/S3), and the merged ruleset is built below.
    ruleset = load_ruleset()

    _lint(manifest, items, statblocks, npcs, places, scenarios, quests, errors)
    _lint_keyed_encounters(places, statblocks, npcs, ruleset, errors)
    _dup_ids(lore, "lore", errors)        # subjects are free-form, so only ids are checked
    _dup_ids(ai_profiles, "ai_profiles", errors)
    _lint_backgrounds(backgrounds, items, ruleset, errors)
    _lint_spells(spells, ruleset, errors)
    person_chars = _load_person_characters(base, npcs, errors)   # Phase 4b sidecars

    if errors:
        raise PackValidationError(pack_id, errors)

    # --- build the baseline (validation passed; refs are safe) ---------------
    assert manifest is not None
    scenario = next(s for s in scenarios if s.id == manifest.entry_scenario)
    statblock_by_id = {s.id: s for s in statblocks}

    party = [Character(**raw) for raw in scenario.default_party]
    npc_chars = [_build_npc(n, statblock_by_id, person_chars) for n in npcs]
    state_items = [_project_item(it) for it in items]
    pc_id = party[0].id if party else "pc"

    repo = InMemoryRepository(characters=party + npc_chars, items=state_items, pc_id=pc_id)

    place_by_id = {p.id: p for p in places}
    scene = scenario.scene_override or place_by_id[scenario.start_location].description
    place_nodes = {p.id: PlaceNode(id=p.id, name=p.name, description=p.description,
                                   parent=p.parent, exits=tuple(e.to for e in p.exits),
                                   image=p.image, map_image=p.map_image, position=p.position,
                                   sounds=tuple(c.model_dump() for c in p.sounds),
                                   battle=p.battle, safe_haven=p.safe_haven,
                                   encounters=tuple(p.encounters))
                   for p in places}

    # The session plays with a PACK-MERGED ruleset (module-kit S2/S3): the
    # pack's backgrounds and chassis spells join the SRD's (collisions are lint
    # errors above), and the equipment map IS the merged mechanics catalog — so
    # chargen can grant pack items (a background's dockhand boots), a pack
    # sorcerer can learn the world's signature spell, and every consumer of
    # `ruleset.equipment`/`ruleset.spells` sees one consistent set.
    # `load_ruleset()` returns a fresh instance per call, so this never
    # mutates another world's ruleset.
    merged_equipment = mechanics_catalog(ruleset, items)
    ruleset = replace(
        ruleset,
        backgrounds={**ruleset.backgrounds, **{b.id: b for b in backgrounds}},
        spells={**ruleset.spells, **{s.id: s for s in spells}},
        equipment=merged_equipment,
    )
    return LoadedWorld(
        repository=repo, canon=_authored_canon(npcs, places, lore), scene=scene,
        location=scenario.start_location, places=place_nodes,
        pack_id=manifest.id, pack_version=manifest.version, world_map=manifest.world_map,
        ruleset=ruleset,
        pack_name=manifest.name, statblocks=tuple(statblocks),
        bestiary_gate=manifest.bestiary_gate, quests=tuple(quests),
        ai_profiles=tuple(ai_profiles),
        npc_statblocks={n.id: n.stat_block for n in npcs if n.stat_block},
        mechanics_catalog=merged_equipment,
    )
