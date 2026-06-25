"""The Arena bridge (combat Stage 2): pure data mapping between Oubliette's
state/content models and The Arena's tactical-engine models.

Two directions, no I/O and no live-loop wiring (that is Stage 3 — "flip the
switch"):

  OUT  Oubliette party (`Character`) + chosen enemies (bestiary `StatBlock`,
       ephemeral `CombatantTemplate`, or a persistent NPC `Character`) + an
       `EncounterRequest` → an Arena `Encounter` (inline `creature_data`, teams,
       starting hexes on a default grid keyed to terrain kind).

  BACK the Arena handoff result dict (`arena.handoff.build_result`) → an
       Oubliette `CombatResult` (absolute final HP per *persistent* entity,
       fallen-enemy XP + loot).

Fidelity is "basic-attack" (D-COMBAT-4): every combatant fields ONE basic attack
built from Oubliette's flat `attack_bonus` + `damage` dice spec. Real ability
scores are carried across faithfully; to reproduce the flat `attack_bonus`
exactly — the Arena rolls to-hit as ability_mod + proficiency_bonus — we solve
for a (carrier-ability, proficiency_bonus) pair that lands on it without
corrupting the real scores (see `_solve_to_hit`). Saves/skills/rich actions are
Stage 4.

The back-map needs a correspondence between Arena combatants (keyed by display
name in the result) and Oubliette entities; `build_encounter` returns an
`EncounterPlan` carrying that map, which `result_to_combat_result` consumes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    TargetType,
)
from arena.models.character import Creature, CreatureSize, CreatureType, PlayerCharacter
from arena.models.conditions import BuffEffect
from arena.models.encounter import CombatantEntry, Encounter, TerrainHex, TerrainType
from arena.models.monster import Monster
from arena.paths import DATA_DIR

from ..content.schemas import StatBlock
from ..content.srd_schemas import SrdEquipment
from ..enums import Ability
from ..rules import derive
from ..state.models import Character
from ..tools.schemas import ValueEntry
from .feature_bridge import engine_resource_key, feature_actions, features_for
from .schemas import CombatResult, ConsumedItem, Outcome, TerrainSpec
from .templates import CombatantTemplate

# --- Defaults ------------------------------------------------------------

GRID_WIDTH = 20
GRID_HEIGHT = 15
_PLAYER_COL = 2
_ENEMY_COL = GRID_WIDTH - 3
DEFAULT_DAMAGE_TYPE = DamageType.SLASHING

_ABILITY_LONG = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
# Preference order for the to-hit carrier ability (natural attack stats first).
_CARRIER_ORDER = ["str", "dex", "con", "wis", "int", "cha"]


# --- Small pure helpers --------------------------------------------------

def _norm_abilities(abilities: dict) -> dict[str, int]:
    """Normalise an Oubliette abilities dict (keys may be the `Ability` enum or
    short strings like "str") to plain short-key ints, defaulting to 10."""
    out = {k: 10 for k in _ABILITY_LONG}
    for k, v in abilities.items():
        key = getattr(k, "value", k)
        if key in out:
            out[key] = int(v)
    return out


def _mod(score: int) -> int:
    """SRD ability modifier."""
    return (score - 10) // 2


def _ability_scores(short: dict[str, int]) -> AbilityScores:
    return AbilityScores(**{_ABILITY_LONG[k]: v for k, v in short.items()})


def _parse_damage(spec: str) -> tuple[str, int]:
    """Split an Oubliette dice spec ("2d6+1", "1d4-1", "1d6") into (dice, flat).
    Falls back to ("1d4", 0) on anything unparseable."""
    m = re.match(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$", spec or "")
    if not m:
        return "1d4", 0
    dice = f"{int(m.group(1))}d{int(m.group(2))}"
    flat = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    return dice, flat


def _solve_to_hit(short: dict[str, int], attack_bonus: int) -> tuple[str, int]:
    """Return (carrier_ability_long, proficiency_bonus) so that the Arena's
    to-hit (ability_mod(carrier) + proficiency_bonus) equals `attack_bonus`
    exactly, without altering the real ability scores.

    The Arena clamps proficiency_bonus to [2, 9]. For SRD monsters the natural
    attacking ability already satisfies this (attack_bonus = mod + prof by
    construction); otherwise we pick whichever real ability lets prof land in
    range. If no ability yields an in-range prof (very extreme inputs) we clamp
    and accept a residual on the to-hit only.
    """
    # (-mod, carrier_priority, ability, prof): prefer the highest real ability
    # modifier (the creature's natural attacking stat → the SRD decomposition,
    # e.g. a goblin lands on DEX+prof2), tie-broken by carrier preference.
    exact: list[tuple[int, int, str, int]] = []
    for i, key in enumerate(_CARRIER_ORDER):
        prof = attack_bonus - _mod(short[key])
        if 2 <= prof <= 9:
            exact.append((-_mod(short[key]), i, key, prof))
    if exact:
        _, _, key, prof = min(exact)
        return _ABILITY_LONG[key], prof
    # Unreachable target (very extreme inputs): pick the (carrier, clamped prof)
    # that minimises the to-hit residual. Damage and ability scores stay exact;
    # only the to-hit drifts by the unavoidable residual.
    best: tuple[int, int, str, int] | None = None  # (residual, priority, ability, prof)
    for i, key in enumerate(_CARRIER_ORDER):
        prof = min(9, max(2, attack_bonus - _mod(short[key])))
        residual = abs(attack_bonus - (_mod(short[key]) + prof))
        cand = (residual, i, key, prof)
        if best is None or cand < best:
            best = cand
    assert best is not None
    return _ABILITY_LONG[best[2]], best[3]


def _basic_attack(
    name: str,
    short: dict[str, int],
    attack_bonus: int,
    damage: str,
    damage_type: DamageType,
    proficiency_bonus: int,
    carrier_long: str,
    magic_bonus: int = 0,
) -> Action:
    """One melee basic-attack Action whose to-hit resolves to `attack_bonus`
    (via the solved carrier ability + proficiency_bonus) and whose damage is the
    literal dice spec with a flat bonus (no ability modifier, so it is exact).
    A `magic_bonus` (an equipped +X weapon, B3) adds to the damage and flags the
    attack magical for the packet tag; the to-hit half is the CALLER's job — it
    solves (carrier, prof) against the already-boosted attack_bonus. The bridge
    carries no Arena equipment at all: equipping anything would flip the engine
    from stored-AC to computing AC from gear, clobbering the story-derived AC."""
    dice, flat = _parse_damage(damage)
    return Action(
        name=name,
        description=f"{name}: +{attack_bonus} to hit, reach 5 ft., one target.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name=name,
            attack_type="melee_weapon",
            ability=carrier_long,
            reach=5,
            damage=[DamageRoll(dice=dice, damage_type=damage_type,
                               bonus=flat + magic_bonus)],
            magical=magic_bonus > 0,
        ),
        ai_priority=6,
    )


def arena_spell_action(spell_id: str) -> Action | None:
    """The generated Arena Action for a spell id (`arena/data/spells/srd/`,
    produced by tools/gen_spells.py — deterministic parse of the same
    5e-database the spells chapter came from). None when the spell wasn't
    expressible (control/utility families) or the id is unknown — the bridge
    skips it gracefully per the D-COMBAT-2 cap."""
    path = DATA_DIR / "spells" / "srd" / f"{spell_id}.json"
    if not path.is_file():
        return None
    try:
        return Action.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def spell_actions(char: Character) -> list[Action]:
    """The caster kit (B4): the sheet's cantrips + spells (prepared list when the
    class prepares, else known), each loaded from the generated library and BAKED
    with this caster's numbers — the same philosophy as the +X gear bake:

      - `Attack.ability` ← the spellcasting ability (the generator emits a
        placeholder). To-hit = its mod + the creature's proficiency_bonus; for
        chargen PCs the weapon solve lands on the real proficiency bonus (the
        chargen invariant attack_bonus = prof + best physical mod), so spell
        attacks come out exact.
      - `SavingThrowEffect.dc` ← 8 + prof + mod (the engine's data fallback is
        a flat 10; it never computes caster DCs from data-driven actions).
      - the literal `MOD` token in healing dice ← the spellcasting modifier.

    Spells the generator skipped simply don't appear — they stay story-side."""
    sheet = char.sheet
    if sheet is None or sheet.spellcasting_ability is None:
        return []
    sa = sheet.spellcasting_ability
    mod = char.ability_mod(sa)
    dc = 8 + char.proficiency_bonus + mod
    ability_long = _ABILITY_LONG[sa.value]

    leveled = sheet.spells_prepared or sheet.spells_known
    out: list[Action] = []
    for spell_id in dict.fromkeys([*sheet.cantrips_known, *leveled]):
        action = arena_spell_action(spell_id)
        if action is None:
            continue
        _bake_spell_action(action, ability_long, dc, mod)
        out.append(action)
    return out


def _bake_spell_action(
    action: Action, ability_long: str, dc: int, mod: int,
) -> None:
    """Resolve the generator's caster placeholders against real numbers, in
    place: attack ability, save DC, the MOD healing/temp-HP tokens, and the
    DC buff-value token. Shared by the caster kit (B4) and scrolls (C5)."""
    if action.attack is not None:
        action.attack.ability = ability_long
        # C3: damage rolls flagged with an ability_modifier placeholder
        # ride the caster's spellcasting ability too (Spiritual Weapon's
        # 1d8 + MOD force damage).
        for dr in action.attack.damage:
            if dr.ability_modifier is not None:
                dr.ability_modifier = ability_long
    if action.saving_throw is not None and action.saving_throw.dc is None:
        action.saving_throw.dc = dc
    if action.healing and "MOD" in action.healing:
        # A non-positive modifier just drops the term (a heal never rolls
        # negative, and the engine's dice parser only sees plain "+N").
        action.healing = action.healing.replace(
            "+MOD", f"+{mod}" if mod > 0 else "")
    if action.grants_temporary_hp and "MOD" in action.grants_temporary_hp:
        # Heroism: temp HP equal to the casting modifier (floor 1).
        action.grants_temporary_hp = action.grants_temporary_hp.replace(
            "MOD", str(max(1, mod)))
    for be in action.buff_effects:
        # C4: a buff value of the literal "DC" token carries THIS
        # caster's spell save DC into the buff (Sanctuary's ward DC —
        # checked at attack time, long after the cast).
        if be.value == "DC":
            be.value = dc


def equipped_magic(
    char: Character, catalog: dict[str, SrdEquipment] | None
) -> tuple[int, int]:
    """(weapon_bonus, ac_bonus) from the character's equipped +X magic items (B3).

    The SRD's +X items are generic enchantments ("Weapon, +1", "Armor, +2",
    Ring/Cloak of Protection...) with no base-item profile, so the deterministic
    reading is: an equipped weapon-type magic item enchants THE wielded attack
    (best one counts — bonuses of the same kind don't stack in 5e), and every
    equipped defensive magic item adds its bonus to AC (armor + shield + ring DO
    stack). Ammunition is skipped — the basic attack is melee. Pack items aren't
    in the SRD catalog and carry no mechanics yet."""
    weapon_bonus, ac_bonus = 0, 0
    if not catalog:
        return 0, 0
    for item_id in char.equipped:
        item = catalog.get(item_id)
        if item is None or not item.magic_bonus:
            continue
        if item.item_type == "weapon":
            weapon_bonus = max(weapon_bonus, item.magic_bonus)
        elif item.item_type != "ammunition":
            ac_bonus += item.magic_bonus
    return weapon_bonus, ac_bonus


def _drink_action(item: SrdEquipment, qty: int) -> Action:
    """One self-targeted "drink it" Action for a mapped consumable. The entry
    invariant of the handoff-v2 contract is set HERE: the action enters combat with
    ``current_uses == uses_per_rest == the inventory stack quantity``, so the result's
    ``consumables_used`` diff is exactly what the fight consumed. ``source_item_id``
    carries the catalog id back out so the story side debits the right stack."""
    consumable = item.consumable
    assert consumable is not None and (
        consumable.healing or consumable.grants_resistance or consumable.ability_set
    )
    if consumable.healing:
        effect = f"regain {consumable.healing} hit points"
        healing, buffs = consumable.healing, []
    elif consumable.grants_resistance:
        # The buff is indefinite engine-side: the SRD durations ("1 hour")
        # outlast any encounter, and buffs end with the combat anyway.
        effect = f"resistance to {consumable.grants_resistance} damage"
        healing = None
        buffs = [BuffEffect(stat="damage_resistance", modifier_type="resistance",
                            value=consumable.grants_resistance)]
    else:
        # ability_set (Giant Strength): an engine "set" buff — floor semantics,
        # exactly the SRD's "no effect if your score is already equal or higher".
        healing = None
        parts, buffs = [], []
        for short, score in consumable.ability_set.items():
            ability = _ABILITY_LONG.get(short, short)
            parts.append(f"{ability.capitalize()} becomes {score}")
            buffs.append(BuffEffect(stat=ability, modifier_type="set", value=score))
        effect = ", ".join(parts)
    bonus = "bonus" in (consumable.action or "").lower()
    return Action(
        name=item.name,
        description=f"Drink the {item.name}: {effect}.",
        action_type=ActionType.BONUS_ACTION if bonus else ActionType.ACTION,
        target_type=TargetType.SELF,
        range=0,
        healing=healing,
        buff_effects=buffs,
        uses_per_rest=qty,
        current_uses=qty,
        source_item=item.name,
        source_item_id=item.id,
        ai_priority=3,
    )


def _drinkable(item: SrdEquipment | None) -> bool:
    """Structured consumables the engine can express: healing dice (B1),
    resistance grants (B3), and `ability_set` potions like Giant Strength
    (B5 — the engine's "set" buff). Poisons still wait on blade-coating."""
    if item is None or item.mechanics != "structured" or item.consumable is None:
        return False
    # Belts of Giant Strength carry ability_set in the same mechanics slot but
    # are WORN gear (category "gear"), not drinkable — only true consumables.
    if item.category != "consumable":
        return False
    return bool(item.consumable.healing or item.consumable.grants_resistance
                or item.consumable.ability_set)


def consumable_actions(
    char: Character, catalog: dict[str, SrdEquipment] | None
) -> list[Action]:
    """The Arena actions for the drinkable consumables in a character's inventory.

    Catalog items with structured, engine-expressible mechanics (see `_drinkable`)
    become drink actions. Scroll variant stacks (a `spell` rider) are handled by
    `scroll_actions` (C5); items with ``mechanics == "none"`` stay story-side.
    Stacks of the same item aggregate into ONE action carrying the total
    quantity as its uses."""
    if not catalog:
        return []
    qty_by_id: dict[str, int] = {}
    for stack in char.inventory:
        if stack.spell is not None:
            continue
        if not _drinkable(catalog.get(stack.item_id)):
            continue
        qty_by_id[stack.item_id] = qty_by_id.get(stack.item_id, 0) + stack.qty
    return [_drink_action(catalog[item_id], qty) for item_id, qty in qty_by_id.items()]


# RAW spell-scroll save DCs by the inscribed spell's level. The scroll's fixed
# attack bonus is NOT modeled — spell-attack to-hit comes out as the reader's
# casting mod + proficiency instead (exact for full casters, close otherwise).
_SCROLL_DC = {0: 13, 1: 13, 2: 15, 3: 15, 4: 17, 5: 17, 6: 18, 7: 18, 8: 19, 9: 19}

_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def scroll_actions(
    char: Character, catalog: dict[str, SrdEquipment] | None
) -> list[Action]:
    """Castable actions for the scroll stacks in a character's inventory (C5).

    A scroll stack (the A5 `spell` rider) becomes the inscribed spell, cast AT
    the inscribed level, costing NO slot — the scroll is the cost. The action
    enters with the B1 entry invariant (uses == stack qty) and carries the
    variant riders (`source_item_spell`/`source_item_spell_level`) so the
    handoff debits the exact (item, spell, level) stack, not just "a scroll".
    `fixed_cast_level` makes the engine apply the full upcast machinery (a
    5th-level Magic Missile scroll fires 7 darts) with no slot picker.

    Deliberate approximations: anyone HOLDING a scroll can read it (no
    class-list gate — the DM decides who gets scrolls); save DCs come from the
    RAW scroll table, not the reader; reaction spells (Shield) are skipped
    (no popup route for item-cast reactions yet); spells the generator can't
    express stay story-side, like everywhere else."""
    if not catalog:
        return []
    sheet = char.sheet
    sa = sheet.spellcasting_ability if sheet else None
    mod = char.ability_mod(sa) if sa else 0
    ability_long = _ABILITY_LONG[sa.value] if sa else "intelligence"

    qty_by_variant: dict[tuple[str, str, int | None], int] = {}
    for stack in char.inventory:
        if stack.spell is None or stack.item_id not in catalog:
            continue
        key = (stack.item_id, stack.spell, stack.spell_level)
        qty_by_variant[key] = qty_by_variant.get(key, 0) + stack.qty

    out: list[Action] = []
    for (item_id, spell_id, rider_level), qty in qty_by_variant.items():
        action = arena_spell_action(spell_id)
        if action is None or action.action_type == ActionType.REACTION:
            continue
        base_level = action.spell_level or 0
        level = max(rider_level or base_level, base_level)
        _bake_spell_action(
            action, ability_long, _SCROLL_DC.get(level, 13), mod,
        )
        suffix = ""
        if base_level:  # leveled spells show the inscribed level
            suffix = f" ({_ORDINAL.get(level, f'{level}th')}-level)"
            action.fixed_cast_level = level
        action.name = f"Scroll: {action.name}{suffix}"
        action.resource_cost = {}        # the scroll is the cost, not a slot
        action.uses_per_rest = qty
        action.current_uses = qty
        action.rest_type = None
        action.source_item = catalog[item_id].name
        action.source_item_id = item_id
        action.source_item_spell = spell_id
        action.source_item_spell_level = rider_level
        action.ai_priority = 3
        out.append(action)
    return out


# Weapon-profile readers (C5). Damage TYPE lives only in the CS4 item
# description prose ("1d8 slashing damage" — deterministic generation, so the
# shape is reliable); ranges in the property strings ("thrown (range 20/60)").
_WEAPON_DMG_TYPE_RE = re.compile(r"\d+d\d+ (\w+) damage")
_WEAPON_RANGE_RE = re.compile(r"range (\d+)/(\d+)")


def weapon_kit_actions(
    char: Character, catalog: dict[str, SrdEquipment] | None
) -> list[Action]:
    """Every carried weapon staged as its own attack action (C5 — the design
    call: 5e's free object interaction makes weapon swapping free, so there is
    NO switch action; the longsword AND the javelin are simply both available).

    - melee weapons attack with STR (finesse: the better of STR/DEX), ranged
      with DEX; the engine adds proficiency to every attack (proficiency with
      the weapon is assumed). The ability mod rides the damage roll too.
    - a thrown-property melee weapon gets a SECOND, ranged "(thrown)" action
      that decrements from inventory like a potion (B1 round-trip — thrown
      javelins are gone after the fight). Pure-ranged thrown weapons (darts)
      consume on every shot.
    - the sheet's basic "Attack" stays first with its solved/DM-tweaked
      numbers and the B3 magic bake; the kit adds options, not a replacement.

    Approximations, deliberate: ammunition is not tracked and hand economy is
    not policed (per the design call); versatile uses the one-handed die; the
    melee action of a thrown weapon never decrements (the last javelin is
    still swingable)."""
    if not catalog:
        return []
    str_mod = char.ability_mod(Ability.STR)
    dex_mod = char.ability_mod(Ability.DEX)

    qty_by_id: dict[str, int] = {}
    for stack in char.inventory:
        qty_by_id[stack.item_id] = qty_by_id.get(stack.item_id, 0) + stack.qty
    for item_id in char.equipped:           # equipped but not stacked: still carried
        qty_by_id.setdefault(item_id, 1)

    out: list[Action] = []
    for item_id, qty in qty_by_id.items():
        item = catalog.get(item_id)
        if (item is None or item.category != "weapon" or item.weapon is None
                or not item.weapon.damage):
            continue
        props = [p.lower() for p in item.weapon.properties]
        is_ranged = "ranged" in item.tags
        finesse = any(p.startswith("finesse") for p in props)
        thrown_prop = next((p for p in props if p.startswith("thrown")), None)
        reach = 10 if any(p.startswith("reach") for p in props) else 5

        m = _WEAPON_DMG_TYPE_RE.search(item.description or "")
        try:
            dmg_type = DamageType((m.group(1) if m else "").lower())
        except ValueError:
            dmg_type = DamageType.BLUDGEONING
        ability = ("dexterity" if is_ranged or (finesse and dex_mod > str_mod)
                   else "strength")
        flat = item.weapon.attack_bonus      # pack-authored flat bonus, usually 0

        def _attack_action(name, attack_type, *, rng=None, rng_long=None,
                           consumes=False) -> Action:
            a = Action(
                name=name,
                description=f"{item.name}: {item.weapon.damage} {dmg_type.value}.",
                action_type=ActionType.ACTION,
                target_type=TargetType.ONE_CREATURE,
                range=rng or reach,
                attack=Attack(
                    name=name,
                    attack_type=attack_type,
                    ability=ability,
                    reach=reach,
                    range_normal=rng,
                    range_long=rng_long,
                    damage=[DamageRoll(dice=item.weapon.damage,
                                       damage_type=dmg_type, bonus=flat,
                                       ability_modifier=ability)],
                    properties=props,
                ),
                ai_priority=5,
            )
            if consumes:
                a.uses_per_rest = qty       # B1 entry invariant
                a.current_uses = qty
                a.source_item = item.name
                a.source_item_id = item_id
            return a

        rng = rng_long = None
        range_src = thrown_prop or next(
            (p for p in props if p.startswith("ammunition")), None)
        if range_src:
            rm = _WEAPON_RANGE_RE.search(range_src)
            if rm:
                rng, rng_long = int(rm.group(1)), int(rm.group(2))

        if is_ranged:
            # Pure ranged weapon: one action. Thrown ones (darts) consume.
            out.append(_attack_action(
                item.name, "ranged_weapon",
                rng=rng or 30, rng_long=rng_long,
                consumes=thrown_prop is not None,
            ))
        else:
            out.append(_attack_action(item.name, "melee_weapon"))
            if thrown_prop is not None and rng:
                out.append(_attack_action(
                    f"{item.name} (thrown)", "ranged_weapon",
                    rng=rng, rng_long=rng_long, consumes=True,
                ))
    return out


@dataclass
class StagedResources:
    """What a PC's resource trackers looked like when the encounter was staged —
    the reference the back-map needs to turn the handoff's *remaining* counts into
    Oubliette's absolute *used* mappings (the CS5 op shape). `resources_used_full`
    keeps even un-carried entries (unlimited pools) so the absolute write-back
    never wipes them."""

    slots_max: dict[int, int] = field(default_factory=dict)
    slots_used: dict[int, int] = field(default_factory=dict)
    resources_max: dict[str, int] = field(default_factory=dict)
    resources_used_full: dict[str, int] = field(default_factory=dict)


def staged_resources(char: Character, ruleset) -> StagedResources:
    """Snapshot a PC's CURRENT slot/resource state (CS5 trackers vs derived
    maxima). Empty for sheet-less characters — nothing to stage or write back."""
    if ruleset is None or char.sheet is None:
        return StagedResources()
    slots_max = derive.spell_slots(char, ruleset)
    resources_max = {
        name: info["max"]
        for name, info in derive.class_resources(char, ruleset).items()
        if not info["unlimited"]      # an unlimited pool isn't a depletable counter
    }
    return StagedResources(
        slots_max=slots_max,
        slots_used={k: v for k, v in char.spell_slots_used.items() if k in slots_max},
        resources_max=resources_max,
        resources_used_full=dict(char.resources_used),
    )


def _resources_in(staged: StagedResources) -> tuple[dict[int, int], dict[str, int]]:
    """The Arena-side seed for a PC: (spell-slot maxima, class_resources holding
    the REMAINING counts — `spell_slot_<N>` keys for slots, plain names for class
    pools). The engine spends from class_resources; the maxima stay untouched, so
    the handoff-v2 derivation reads both ends cleanly (B2 in; B0 out)."""
    class_res: dict[str, int] = {}
    for lvl, mx in staged.slots_max.items():
        class_res[f"spell_slot_{lvl}"] = max(0, mx - staged.slots_used.get(lvl, 0))
    for name, mx in staged.resources_max.items():
        # Engine keys ("ki_points", "action_surge") — the engine's rider
        # presets and standard actions hard-code these; the story side keeps
        # its display names ("Ki") and the back-map reverses through the same
        # function (C1).
        class_res[engine_resource_key(name)] = max(
            0, mx - staged.resources_used_full.get(name, 0))
    return dict(staged.slots_max), class_res


def _bardic_resources(char: Character) -> dict[str, int]:
    """Bard-only engine resources the SRD `by_level` resource table can't express:
    the inspiration USES count (CHA modifier, min 1 — scales with an ability, not
    level) and the inspiration DIE size (d6→d8→d10→d12 at L1/5/10/15). Empty for
    non-bards. Injected flat into `class_resources` so the Arena's bardic.py reads
    them directly (it expects plain ints under `bardic_inspiration` /
    `bardic_inspiration_die`, not the derived {max,...} resource shape)."""
    sheet = char.sheet
    if sheet is None or (sheet.char_class or "").strip().lower() != "bard":
        return {}
    level = char.level
    die = 6 if level < 5 else 8 if level < 10 else 10 if level < 15 else 12
    return {
        "bardic_inspiration": max(1, char.ability_mod(Ability.CHA)),
        "bardic_inspiration_die": die,
    }


def _size(value: str | None) -> CreatureSize:
    try:
        return CreatureSize((value or "medium").strip().lower())
    except ValueError:
        return CreatureSize.MEDIUM


def _creature_type(value: str | None) -> CreatureType:
    # StatBlock types look like "humanoid (goblinoid)" — take the leading word.
    head = (value or "humanoid").strip().lower().split(" ")[0].split("(")[0]
    try:
        return CreatureType(head)
    except ValueError:
        return CreatureType.HUMANOID


def _loot_to_value(entries) -> list[ValueEntry]:
    """Map content `LootEntry` (gold|item/qty) → boundary `ValueEntry`
    (gold|item_id/qty)."""
    out: list[ValueEntry] = []
    for e in entries:
        if getattr(e, "gold", None) is not None:
            out.append(ValueEntry(gold=e.gold))
        elif getattr(e, "item", None) is not None:
            out.append(ValueEntry(item_id=e.item, qty=getattr(e, "qty", 1)))
    return out


# --- OUT: Oubliette → Arena creatures ------------------------------------

def character_to_player(
    char: Character,
    catalog: dict[str, SrdEquipment] | None = None,
    ruleset=None,
) -> PlayerCharacter:
    """Map a party member (`Character`, kind=pc) → an Arena `PlayerCharacter`.
    With a `catalog` (the SRD equipment dict), the inventory's drinkable
    consumables ride along as item actions (B1). With a `ruleset`, the CURRENT
    spell-slot/class-resource state is staged in (B2) — a wizard who already
    spent slots in the story does not arrive recharged."""
    short = _norm_abilities(char.abilities)
    # +X gear (B3): the weapon bonus joins the to-hit BEFORE solving so the
    # engine's carrier+prof roll lands on the boosted number exactly; the AC
    # bonus joins the story-derived AC (the story derivation ignores magic).
    weapon_bonus, ac_bonus = equipped_magic(char, catalog)
    to_hit = char.attack_bonus + weapon_bonus
    carrier, prof = _solve_to_hit(short, to_hit)
    sheet = char.sheet
    char_class = sheet.char_class if sheet else "Adventurer"
    race = sheet.race if sheet else "Human"
    slots_max, class_res = _resources_in(staged_resources(char, ruleset))
    class_res.update(_bardic_resources(char))   # bard inspiration uses + die size
    casting_ability = (
        _ABILITY_LONG[sheet.spellcasting_ability.value]
        if sheet and sheet.spellcasting_ability else None
    )
    save_profs = (
        [_ABILITY_LONG[a.value] for a in sorted(sheet.saving_throw_proficiencies,
                                                key=lambda a: a.value)]
        if sheet else []
    )
    # C1: class features ride in two ways — engine Feature objects (extra
    # attacks, smite/sneak/stun riders, auras, evasion...) and curated Actions
    # (Second Wind, Rage, Flurry...). Bonus actions go in their own list: the
    # radial menu surfaces `bonus_actions` as individual slots.
    extra_actions, bonus_actions = feature_actions(char, carrier)
    # C4: reaction spells (Shield) go to `reactions`, NOT `actions` — they
    # are cast via the engine's hit-reaction popup, never from the radial.
    all_spells = spell_actions(char)
    reaction_spells = [a for a in all_spells
                       if a.action_type == ActionType.REACTION]
    turn_spells = [a for a in all_spells
                   if a.action_type != ActionType.REACTION]
    return PlayerCharacter(
        name=char.name,
        size=_size(sheet.size if sheet else None),
        ability_scores=_ability_scores(short),
        armor_class=max(1, char.armor_class + ac_bonus),
        max_hit_points=max(1, char.max_hp),
        current_hit_points=max(0, char.hp),
        proficiency_bonus=prof,
        character_class=char_class,
        level=char.level,
        race=race,
        is_player_controlled=True,
        speed={"walk": sheet.speed if sheet else 30},
        saving_throw_proficiencies=save_profs,
        spellcasting_ability=casting_ability,
        spell_slots=slots_max,
        class_resources=class_res,
        features=features_for(char),
        actions=[
            _basic_attack(
                "Attack", short, to_hit, char.damage,
                DEFAULT_DAMAGE_TYPE, prof, carrier, magic_bonus=weapon_bonus,
            ),
            *turn_spells,
            *consumable_actions(char, catalog),
            *scroll_actions(char, catalog),
            *weapon_kit_actions(char, catalog),
            *extra_actions,
        ],
        bonus_actions=bonus_actions,
        reactions=reaction_spells,
    )


def statblock_to_monster(sb: StatBlock) -> Monster:
    """Map a bestiary `StatBlock` → an Arena `Monster`."""
    short = _norm_abilities(sb.abilities)
    carrier, prof = _solve_to_hit(short, sb.attack_bonus)
    dtype = DEFAULT_DAMAGE_TYPE
    if sb.actions and sb.actions[0].damage_type:
        try:
            dtype = DamageType(sb.actions[0].damage_type.strip().lower())
        except ValueError:
            dtype = DEFAULT_DAMAGE_TYPE
    return Monster(
        name=sb.name,
        size=_size(sb.size),
        creature_type=_creature_type(sb.type),
        alignment=sb.alignment,
        ability_scores=_ability_scores(short),
        armor_class=max(1, sb.armor_class),
        max_hit_points=max(1, sb.hp),
        proficiency_bonus=prof,
        damage_resistances=list(sb.damage_resistances),
        damage_immunities=list(sb.damage_immunities),
        damage_vulnerabilities=list(sb.damage_vulnerabilities),
        condition_immunities=list(sb.condition_immunities),
        challenge_rating=float(sb.cr) if sb.cr is not None else 0.0,
        experience_points=sb.xp,
        is_player_controlled=False,
        actions=[
            _basic_attack(
                sb.actions[0].name if sb.actions else "Attack",
                short, sb.attack_bonus, sb.damage, dtype, prof, carrier,
            )
        ],
    )


def template_to_monster(tmpl: CombatantTemplate) -> Monster:
    """Map an ephemeral `CombatantTemplate` → an Arena `Monster`. Templates carry
    no ability scores, so they default to 10s (mods 0) and the to-hit rides on
    proficiency_bonus alone."""
    short = {k: 10 for k in _ABILITY_LONG}
    carrier, prof = _solve_to_hit(short, tmpl.attack_bonus)
    return Monster(
        name=tmpl.name,
        ability_scores=_ability_scores(short),
        armor_class=max(1, tmpl.armor_class),
        max_hit_points=max(1, tmpl.hp),
        proficiency_bonus=prof,
        experience_points=tmpl.xp,
        is_player_controlled=False,
        actions=[
            _basic_attack(
                "Attack", short, tmpl.attack_bonus, tmpl.damage,
                DEFAULT_DAMAGE_TYPE, prof, carrier,
            )
        ],
    )


def character_to_monster(char: Character) -> Monster:
    """Map a persistent NPC (`Character`, kind=npc) used as an enemy → a (AI-
    controlled) Arena `Monster`."""
    short = _norm_abilities(char.abilities)
    carrier, prof = _solve_to_hit(short, char.attack_bonus)
    return Monster(
        name=char.name,
        ability_scores=_ability_scores(short),
        armor_class=max(1, char.armor_class),
        max_hit_points=max(1, char.max_hp),
        current_hit_points=max(0, char.hp),
        proficiency_bonus=prof,
        experience_points=char.xp,
        is_player_controlled=False,
        actions=[
            _basic_attack(
                "Attack", short, char.attack_bonus, char.damage,
                DEFAULT_DAMAGE_TYPE, prof, carrier,
            )
        ],
    )


# --- Portrait token art (B6) ----------------------------------------------

@dataclass
class PortraitDirs:
    """Where staged combatants' token art lives. The Arena already renders
    `Creature.token_image` (circle-clipped, polygon-clipped for Large+); B6 is
    just pointing that field at the right file. Every dir is optional — a
    missing dir or file means the Arena draws its colored-circle fallback.
    """

    pc: Path | None = None      # <save-dir>/character-portraits (A3 uploads)
    pack: Path | None = None    # content/packs/<pack_id>/portraits (authored)
    srd: Path | None = None     # content/srd/portraits (<Name>.png fleet)


def _token_image(dirs: list[Path | None], candidates: list[str | None]) -> str | None:
    """First existing portrait file across `dirs` (in precedence order) matching
    any candidate filename — matched CASE-INSENSITIVELY, so the SRD fleet's
    `Awakened_Shrub.png` answers for the id `awakened_shrub` on any OS, not
    just Windows. Returns an absolute path string (the encounter is played
    from a scratch dir, so relative paths would dangle). Path-separator
    candidates are rejected (same traversal guard as the app server)."""
    names = [c for c in candidates if c and "/" not in c and "\\" not in c]
    if not names:
        return None
    for directory in dirs:
        if directory is None:
            continue
        try:
            index = {p.name.lower(): p for p in directory.iterdir() if p.is_file()}
        except OSError:
            continue
        for name in names:
            hit = index.get(name.lower())
            if hit is not None:
                return str(hit.resolve())
    return None


# --- Enemy instances + encounter assembly --------------------------------

@dataclass
class EnemyInstance:
    """One resolved enemy ready to drop into an Arena encounter, plus the
    Oubliette bookkeeping the back-map needs.

    `entity_id` is set iff this enemy is a persistent entity (its final HP is
    written back); ephemeral template/bestiary spawns leave it None.
    """

    creature: Creature
    xp: int = 0
    loot: list[ValueEntry] = field(default_factory=list)
    entity_id: str | None = None


def arena_monster_file(monster_id: str) -> Monster | None:
    """The full-fidelity Arena `Monster` for an id, from the generated SRD set
    (`arena/data/monsters/srd/<id>.json`, produced by tools/gen_arena_monsters.py
    — a deterministic parse of the same 5e-database the bestiary came from). These
    carry the real combat kit — multi-type attacks, save-for-half breath weapons,
    multiattack data — that the flat StatBlock mapping can't express. Returns None
    when there's no file (then we fall back to the basic mapping)."""
    path = DATA_DIR / "monsters" / "srd" / f"{monster_id}.json"
    if not path.is_file():
        return None
    try:
        return Monster.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def enemy_from_statblock(
    sb: StatBlock, portraits: PortraitDirs | None = None
) -> EnemyInstance:
    """Prefer the generated full-fidelity Arena monster when one exists for this id
    (essentially every SRD bestiary monster); otherwise fall back to the flat
    basic-attack mapping (templates, synthetic ids). Either way, Oubliette's
    bestiary stays the source of truth for the reward (its `xp`) and loot.
    Token art (B6): the statblock's `portrait` filename or `<id>.png`, pack
    dir first then SRD — the same convention the bestiary panel serves."""
    rich = arena_monster_file(sb.id)
    if rich is not None:
        if sb.xp:
            rich.experience_points = sb.xp   # reward = Oubliette's bestiary
        creature: Monster = rich
    else:
        creature = statblock_to_monster(sb)
    if portraits is not None:
        art = _token_image([portraits.pack, portraits.srd],
                           [sb.portrait, f"{sb.id}.png"])
        if art:
            creature.token_image = art
    return EnemyInstance(creature=creature, xp=sb.xp, loot=_loot_to_value(sb.loot))


def enemy_from_template(tmpl: CombatantTemplate) -> EnemyInstance:
    # Templates are synthetic stand-ins with no portrait source — circle fallback.
    return EnemyInstance(
        creature=template_to_monster(tmpl), xp=tmpl.xp, loot=list(tmpl.loot)
    )


def enemy_from_character(
    char: Character, portraits: PortraitDirs | None = None
) -> EnemyInstance:
    # Persistent foes are written back but (mirroring the boundary) drop no loot.
    inst = EnemyInstance(
        creature=character_to_monster(char), xp=char.xp, loot=[], entity_id=char.id
    )
    if portraits is not None:
        art = _token_image([portraits.pc], [char.portrait])
        if art:
            inst.creature.token_image = art
    return inst


@dataclass
class EncounterPlan:
    """The assembled Arena encounter plus the correspondence the back-map needs.
    Arena keys result combatants by display name, so we pin a unique name per
    combatant and index our bookkeeping by it."""

    encounter: Encounter
    persistent_ids: dict[str, str] = field(default_factory=dict)  # name -> entity_id
    loot_by_name: dict[str, list[ValueEntry]] = field(default_factory=dict)
    # B2: each PC's slot/resource state as staged (name -> snapshot), the
    # reference for turning the result's remaining counts into absolute used.
    resources_by_name: dict[str, StagedResources] = field(default_factory=dict)


# Default terrain palettes, keyed to `TerrainSpec.kind`. A starting point —
# richer/authored terrain is a later concern.
def _terrain_for(kind: str) -> list[TerrainHex]:
    if kind == "chokepoint":
        gap = {6, 7, 8}
        return [
            TerrainHex(position=(GRID_WIDTH // 2, r), terrain_type=TerrainType.WALL)
            for r in range(GRID_HEIGHT)
            if r not in gap
        ]
    if kind == "ambush_cover":
        return [
            TerrainHex(position=p, terrain_type=TerrainType.COVER_HALF)
            for p in [(8, 4), (11, 9), (9, 11), (12, 5)]
        ]
    return []


def _spawn_anchor(
    size: CreatureSize, col: int, taken: set[tuple[int, int]]
) -> tuple[int, int]:
    """First anchor hex at (or near) column `col` whose whole FOOTPRINT fits the
    grid and doesn't overlap already-claimed hexes, scanning rows centre-out and
    spilling to neighbouring columns when the preferred one is full.

    Naive one-hex spacing broke the moment real sizes arrived: a Large ogre's
    3-hex footprint overlaps the next row's anchor, the engine's
    `place_creature` refuses the collision, and the combatant silently spawns
    OFF-GRID (position=None). Claims footprint hexes in `taken` as it places.
    (Terrain isn't consulted — the default palettes keep walls away from the
    spawn columns.)"""
    from arena.grid.coordinates import HexCoord
    from arena.grid.footprint import get_occupied_hexes

    rows = sorted(range(GRID_HEIGHT), key=lambda r: (abs(r - GRID_HEIGHT // 2), r))
    cols = sorted(range(GRID_WIDTH), key=lambda q: (abs(q - col), q))
    for q in cols:
        for r in rows:
            hexes = {(h.q, h.r) for h in get_occupied_hexes(HexCoord(q, r), size)}
            if any(not (0 <= hq < GRID_WIDTH and 0 <= hr < GRID_HEIGHT)
                   for hq, hr in hexes):
                continue
            if hexes & taken:
                continue
            taken |= hexes
            return (q, r)
    return (col, GRID_HEIGHT // 2)  # grid effectively full — engine sorts it out


def _unique(name: str, used: set[str]) -> str:
    """A display name unique within the encounter ("Goblin", "Goblin 2", ...)."""
    if name not in used:
        used.add(name)
        return name
    i = 2
    while f"{name} {i}" in used:
        i += 1
    out = f"{name} {i}"
    used.add(out)
    return out


def build_encounter(
    party: list[Character],
    enemies: list[EnemyInstance],
    terrain: TerrainSpec,
    *,
    name: str = "Encounter",
    catalog: dict[str, SrdEquipment] | None = None,
    ruleset=None,
    portraits: PortraitDirs | None = None,
) -> EncounterPlan:
    """Assemble an Arena `Encounter` from the live party + resolved enemies +
    terrain. Counts are pre-expanded (one `CombatantEntry` per individual, with
    a unique `name_override`) so the returned result is matchable by name.
    With `portraits`, each PC's uploaded portrait (A3) becomes its token art
    (enemies got theirs when their instances were resolved)."""
    used: set[str] = set()
    entries: list[CombatantEntry] = []
    persistent_ids: dict[str, str] = {}
    loot_by_name: dict[str, list[ValueEntry]] = {}
    resources_by_name: dict[str, StagedResources] = {}
    taken: set[tuple[int, int]] = set()   # footprint hexes claimed by spawns

    for char in party:
        display = _unique(char.name, used)
        creature = character_to_player(char, catalog, ruleset)
        pos = _spawn_anchor(creature.size, _PLAYER_COL, taken)
        if portraits is not None:
            art = _token_image([portraits.pc], [char.portrait])
            if art:
                creature.token_image = art
        staged = staged_resources(char, ruleset)
        if staged.slots_max or staged.resources_max:
            resources_by_name[display] = staged
        creature.name = display
        entries.append(
            CombatantEntry(
                creature_id=f"pc/{char.id}",
                creature_data=creature,
                team="player",
                starting_position=pos,
                name_override=display,
            )
        )
        persistent_ids[display] = char.id  # PCs are always written back

    for inst in enemies:
        display = _unique(inst.creature.name, used)
        creature = inst.creature.model_copy(deep=True)
        creature.name = display
        pos = _spawn_anchor(creature.size, _ENEMY_COL, taken)
        entries.append(
            CombatantEntry(
                creature_id=f"enemy/{display}",
                creature_data=creature,
                team="enemy",
                starting_position=pos,
                name_override=display,
            )
        )
        if inst.entity_id:
            persistent_ids[display] = inst.entity_id
        if inst.loot:
            loot_by_name[display] = list(inst.loot)

    encounter = Encounter(
        name=name,
        grid_width=GRID_WIDTH,
        grid_height=GRID_HEIGHT,
        terrain=_terrain_for(terrain.kind),
        combatants=entries,
        use_ai_for_enemies=True,
        use_ai_for_allies=False,
    )
    return EncounterPlan(
        encounter=encounter,
        persistent_ids=persistent_ids,
        loot_by_name=loot_by_name,
        resources_by_name=resources_by_name,
    )


# --- BACK: Arena result dict → Oubliette CombatResult --------------------

_OUTCOME_MAP: dict[str, Outcome] = {"victory": "victory", "defeat": "defeat"}

# Highest handoff result schema this reader understands (arena.handoff.RESULT_SCHEMA).
# v1 results (and version-less dicts) stay readable — v2 only ADDS per-PC blocks.
_MAX_RESULT_SCHEMA = 2


def _spent_resources(
    staged: StagedResources, reported: dict
) -> tuple[dict[int, int], dict[str, int]]:
    """Turn the v2 result's REMAINING counts into Oubliette's absolute USED
    mappings (the CS5 op shape), against the staged snapshot. Anything the result
    doesn't report keeps its staged used value — unreported means untouched."""
    slots_rem = reported.get("spell_slots") or {}
    new_slots_used: dict[int, int] = {}
    for lvl, mx in staged.slots_max.items():
        remaining = (slots_rem.get(str(lvl)) or {}).get("remaining")
        if remaining is None:
            new_slots_used[lvl] = staged.slots_used.get(lvl, 0)
        else:
            new_slots_used[lvl] = min(mx, max(0, mx - int(remaining)))

    res_rem = reported.get("class_resources") or {}
    new_res_used = dict(staged.resources_used_full)
    for name, mx in staged.resources_max.items():
        # The Arena reports pools under engine keys ("ki_points"); the staged
        # snapshot and the write-back ops keep story display names ("Ki").
        remaining = res_rem.get(engine_resource_key(name), res_rem.get(name))
        if remaining is not None:
            new_res_used[name] = min(mx, max(0, mx - int(remaining)))
    return new_slots_used, new_res_used


def result_to_combat_result(handoff: dict, plan: EncounterPlan) -> CombatResult:
    """Map an Arena handoff result dict (`arena.handoff.build_result`) back into
    an Oubliette `CombatResult`.

    - Persistent combatants (PCs + persistent NPC foes) get absolute HP +
      conditions write-back; ephemeral spawns never appear (D7).
    - On victory, XP is summed from fallen enemies and loot dropped for those
      with a loot table.
    - A window closed mid-fight ("unresolved") maps to `flee`: no XP/loot, but
      the partial HP/conditions are still written back (you took your hits then
      broke away).
    """
    schema = int(handoff.get("schema", 1) or 1)
    if schema > _MAX_RESULT_SCHEMA:
        raise ValueError(
            f"Arena handoff result schema {schema} is newer than this bridge "
            f"understands (max {_MAX_RESULT_SCHEMA}) — refusing to guess at its meaning"
        )

    raw_outcome = handoff.get("outcome", "unresolved")
    outcome: Outcome = _OUTCOME_MAP.get(raw_outcome, "flee")

    combatants = handoff.get("combatants", [])
    hp_final: dict[str, int] = {}
    conditions_final: dict[str, list[str]] = {}
    loot: list[ValueEntry] = []
    xp_award = 0
    survivors: list[str] = []
    items_consumed: list[ConsumedItem] = []
    slots_used_final: dict[str, dict[int, int]] = {}
    resources_used_final: dict[str, dict[str, int]] = {}

    for c in combatants:
        cname = c.get("name", "")
        entity_id = plan.persistent_ids.get(cname)
        if entity_id is not None:
            hp_final[entity_id] = int(c.get("hp", 0))
            conditions_final[entity_id] = list(c.get("conditions", []))
            # v2: spent slots/resources (B2). Like consumption, applies on every
            # outcome — a slot burned before fleeing is still spent.
            staged = plan.resources_by_name.get(cname)
            reported = c.get("resources")
            if staged is not None and reported is not None:
                slots_used, res_used = _spent_resources(staged, reported)
                if staged.slots_max:
                    slots_used_final[entity_id] = slots_used
                if staged.resources_max:
                    resources_used_final[entity_id] = res_used
            # v2: consumables spent in the fight → inventory debits, every outcome
            # (a potion drunk before fleeing is still gone). Entries without a
            # catalog id (native Arena content) have no story-side stack to debit.
            for used in c.get("consumables_used", []) or []:
                item_id = used.get("item_id")
                qty = int(used.get("used", 0) or 0)
                if item_id and qty > 0:
                    items_consumed.append(
                        ConsumedItem(
                            char=entity_id, item_id=item_id, qty=qty,
                            spell=used.get("spell"),
                            spell_level=used.get("spell_level"),
                        )
                    )

        if c.get("team") == "enemy":
            fallen = not c.get("is_conscious", True)
            if fallen and outcome == "victory":
                xp_award += int(c.get("xp", 0) or 0)
                loot.extend(plan.loot_by_name.get(cname, []))
            elif not fallen and entity_id is None:
                survivors.append(cname)

    digest = _digest(outcome, combatants, xp_award, loot)
    return CombatResult(
        outcome=outcome,
        hp_final=hp_final,
        conditions_final=conditions_final,
        loot=loot,
        xp_award=xp_award,
        narrative_digest=digest,
        ephemeral_survivors=survivors,
        items_consumed=items_consumed,
        slots_used_final=slots_used_final,
        resources_used_final=resources_used_final,
    )


def _digest(outcome: Outcome, combatants: list[dict], xp: int, loot: list[ValueEntry]) -> str:
    fallen = [
        c.get("name", "?")
        for c in combatants
        if c.get("team") == "enemy" and not c.get("is_conscious", True)
    ]
    if outcome == "victory":
        from .boundary import loot_str
        tail = f" and {loot_str(loot)}." if loot else "."
        return (
            f"The fight ends in your favor. Fallen: {', '.join(fallen) or 'none'}. "
            f"You take {xp} XP{tail}"
        )
    if outcome == "defeat":
        return "You are beaten down and fall. The encounter is lost."
    return "You break off the fight and slip away before it is settled."
