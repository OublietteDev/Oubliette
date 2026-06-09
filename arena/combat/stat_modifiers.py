"""Pure query functions for computing effective stats from equipment, feats, and features.

This module never mutates state — it reads creature.equipment, creature.feats,
and creature.features, then returns computed effective values that account for
armor, shields, magic bonuses, passive item effects, feat bonuses, and feature
bonuses.

Pattern follows condition_effects.py: pure functions, no side effects.
"""

from arena.models.character import Creature
from arena.models.items import Item, ItemType, EquipmentSlot
from arena.combat.buff_effects import (
    get_buff_ac_bonus,
    get_buff_speed_bonus,
    get_buff_speed_multiplier,
    get_buff_damage_resistances,
    get_buff_damage_immunities,
)


# ── Equipment Helpers ─────────────────────────────────────────────────


def _get_equipped_items(creature: Creature) -> list[Item]:
    """Get all items that are actively equipped (slot != NONE).

    Items with equipment_slot NONE are carried but not worn/wielded,
    so they don't contribute passive effects.
    """
    return [
        item for item in creature.equipment
        if item.equipment_slot != EquipmentSlot.NONE
    ]


def _get_feats(creature: Creature) -> list:
    """Get feats from a creature (PlayerCharacter only).

    Uses getattr so base Creature (monsters) returns [] without error.
    """
    return getattr(creature, "feats", [])


def _get_features(creature: Creature) -> list:
    """Get features from a creature (PlayerCharacter only).

    Uses getattr so base Creature (monsters) returns [] without error.
    """
    return getattr(creature, "features", [])


def get_equipped_armor(creature: Creature) -> Item | None:
    """Find the armor item equipped in the ARMOR slot, if any.

    Returns the first Item with item_type ARMOR and equipment_slot ARMOR,
    or None if no armor is equipped.
    """
    for item in creature.equipment:
        if item.item_type == ItemType.ARMOR and item.equipment_slot == EquipmentSlot.ARMOR:
            return item
    return None


def get_equipped_shield(creature: Creature) -> Item | None:
    """Find the shield item equipped in the OFF_HAND slot, if any.

    Returns the first Item with item_type SHIELD and equipment_slot OFF_HAND,
    or None if no shield is equipped.
    """
    for item in creature.equipment:
        if item.item_type == ItemType.SHIELD and item.equipment_slot == EquipmentSlot.OFF_HAND:
            return item
    return None


def get_weapon_magic_bonus(creature: Creature, source_item_name: str) -> int:
    """Get the magic_bonus for an equipped weapon by its name.

    Used when computing attack bonuses for auto-generated weapon actions.
    Matches by item name against the Action's source_item field.

    Returns 0 if no matching equipped weapon is found.
    """
    for item in creature.equipment:
        if item.item_type == ItemType.WEAPON and item.name == source_item_name:
            return item.magic_bonus
    return 0


# ── Ability Scores ──────────────────────────────────────────────────


def get_effective_ability_score(creature: Creature, ability: str) -> int:
    """Get base ability score + equipment bonuses + feat bonuses + feature bonuses.

    Per 5e rules, no ability score can exceed 30.

    Args:
        creature: The creature to evaluate.
        ability: Ability name (e.g., "strength", "dexterity").

    Returns:
        The effective ability score as an integer (capped at 30).
    """
    base = creature.ability_scores.get_score(ability)
    equip_bonus = sum(
        item.bonus_ability_scores.get(ability.lower(), 0)
        for item in _get_equipped_items(creature)
    )
    feat_bonus = sum(
        feat.bonus_ability_scores.get(ability.lower(), 0)
        for feat in _get_feats(creature)
    )
    feature_bonus = sum(
        feat.bonus_ability_scores.get(ability.lower(), 0)
        for feat in _get_features(creature)
    )
    return min(30, base + equip_bonus + feat_bonus + feature_bonus)


def get_effective_ability_modifier(creature: Creature, ability: str) -> int:
    """Get the modifier derived from the effective ability score.

    Equivalent to (effective_score - 10) // 2.
    """
    return (get_effective_ability_score(creature, ability) - 10) // 2


# ── Armor Class ──────────────────────────────────────────────────────


def _get_unarmored_defense_type(creature: Creature) -> str | None:
    """Check features for an Unarmored Defense override.

    Returns "monk", "barbarian", or None.
    """
    for feature in _get_features(creature):
        if feature.unarmored_defense:
            return feature.unarmored_defense.lower()
    return None


def get_passive_ac_bonus(creature: Creature) -> int:
    """Sum of bonus_ac from all equipped items, feats, and features.

    This is separate from armor AC and shield AC — it represents
    passive bonuses from items like Ring of Protection or Cloak of
    Protection, feats like Dual Wielder, and features like Fighting
    Style: Defense, that stack with armor.
    """
    equip = sum(item.bonus_ac for item in _get_equipped_items(creature))
    feat = sum(feat.bonus_ac for feat in _get_feats(creature))
    feature = sum(f.bonus_ac for f in _get_features(creature))
    return equip + feat + feature


def get_effective_armor_class(creature: Creature) -> int:
    """Compute the effective AC from equipment, feats, and features.

    5e Armor Class Rules:
    - No armor: 10 + DEX modifier (or Unarmored Defense if applicable)
    - Light armor: base_ac + DEX modifier + magic_bonus
    - Medium armor: base_ac + min(DEX modifier, max_dex_bonus) + magic_bonus
    - Heavy armor: base_ac + magic_bonus (no DEX)
    - Shield: +2 + shield magic_bonus (additive)
    - Passive AC bonuses from equipment, feats, and features (additive)

    Fallback: if the creature has no equipment at all, return the stored
    creature.armor_class value unchanged (backward compatibility for
    creatures created before the equipment system or with manually set AC).

    Returns:
        The computed effective AC as an integer.
    """
    # Backward compatibility: no equipment → use stored AC (+ any active buffs)
    if not creature.equipment:
        return creature.armor_class + get_buff_ac_bonus(creature)

    armor = get_equipped_armor(creature)
    shield = get_equipped_shield(creature)

    if armor is None:
        # Has equipment but no armor → check for Unarmored Defense feature
        unarmored_type = _get_unarmored_defense_type(creature)
        dex_mod = get_effective_ability_modifier(creature, "dexterity")

        if unarmored_type == "monk":
            wis_mod = get_effective_ability_modifier(creature, "wisdom")
            base_ac = 10 + dex_mod + wis_mod
        elif unarmored_type == "barbarian":
            con_mod = get_effective_ability_modifier(creature, "constitution")
            base_ac = 10 + dex_mod + con_mod
        else:
            base_ac = 10 + dex_mod
    else:
        armor_base = armor.armor_class or 10
        magic = armor.magic_bonus
        dex_mod = get_effective_ability_modifier(creature, "dexterity")

        armor_type = (armor.armor_type or "").lower()
        if armor_type == "light":
            base_ac = armor_base + dex_mod + magic
        elif armor_type == "medium":
            max_dex = armor.max_dex_bonus if armor.max_dex_bonus is not None else 2
            base_ac = armor_base + min(dex_mod, max_dex) + magic
        elif armor_type == "heavy":
            base_ac = armor_base + magic
        else:
            # Unknown armor type — treat as light armor
            base_ac = armor_base + dex_mod + magic

    # Add shield bonus
    if shield is not None:
        shield_base = shield.armor_class if shield.armor_class is not None else 2
        base_ac += shield_base + shield.magic_bonus

    # Add passive AC bonus from other equipped items, feats, and features
    base_ac += get_passive_ac_bonus(creature)

    # Add temporary AC bonus from active buffs (Shield, Haste, etc.)
    base_ac += get_buff_ac_bonus(creature)

    return base_ac


# ── Speed ────────────────────────────────────────────────────────────


def get_effective_speed(creature: Creature) -> int:
    """Get base walking speed + equipment bonuses + feat bonuses + feature bonuses.

    Minimum 0 (speed can't go negative).
    """
    base = creature.speed.get("walk", 30)
    equip_bonus = sum(item.bonus_speed for item in _get_equipped_items(creature))
    feat_bonus = sum(feat.bonus_speed for feat in _get_feats(creature))
    feature_bonus = sum(f.bonus_speed for f in _get_features(creature))
    buff_bonus = get_buff_speed_bonus(creature)
    total = base + equip_bonus + feat_bonus + feature_bonus + buff_bonus
    # Apply buff speed multipliers (Haste x2, Slow x0.5)
    multiplier = get_buff_speed_multiplier(creature)
    total = int(total * multiplier)
    return max(0, total)


# ── Damage Resistances & Immunities ──────────────────────────────────


def _deduplicate_strings(items: list[str]) -> list[str]:
    """Deduplicate a list of strings case-insensitively, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for s in items:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            result.append(s)
    return result


def get_effective_damage_resistances(creature: Creature) -> list[str]:
    """Get base resistances + equipment + feat + feature + buff granted resistances, deduplicated."""
    all_res = list(creature.damage_resistances)
    for item in _get_equipped_items(creature):
        all_res.extend(item.grants_damage_resistances)
    for feat in _get_feats(creature):
        all_res.extend(feat.grants_damage_resistances)
    for feature in _get_features(creature):
        all_res.extend(feature.grants_damage_resistances)
    all_res.extend(get_buff_damage_resistances(creature))
    return _deduplicate_strings(all_res)


def get_effective_damage_immunities(creature: Creature) -> list[str]:
    """Get base immunities + equipment + feat + feature + buff granted immunities, deduplicated."""
    all_imm = list(creature.damage_immunities)
    for item in _get_equipped_items(creature):
        all_imm.extend(item.grants_damage_immunities)
    for feat in _get_feats(creature):
        all_imm.extend(feat.grants_damage_immunities)
    for feature in _get_features(creature):
        all_imm.extend(feature.grants_damage_immunities)
    all_imm.extend(get_buff_damage_immunities(creature))
    return _deduplicate_strings(all_imm)


def get_effective_condition_immunities(creature: Creature) -> list[str]:
    """Get base condition immunities + equipment + feat + feature granted ones, deduplicated."""
    all_ci = list(creature.condition_immunities)
    for item in _get_equipped_items(creature):
        all_ci.extend(item.grants_condition_immunities)
    for feat in _get_feats(creature):
        all_ci.extend(feat.grants_condition_immunities)
    for feature in _get_features(creature):
        all_ci.extend(feature.grants_condition_immunities)
    return _deduplicate_strings(all_ci)


# ── Attack Modifiers ────────────────────────────────────────────────


def get_weapon_attack_bonus(creature: Creature, action_source_item: str | None) -> int:
    """Get the magic_bonus to add to attack rolls for a weapon action.

    Looks up the weapon in creature.equipment by matching the action's
    source_item field to the item's name.

    Args:
        creature: The attacking creature.
        action_source_item: The source_item field from the Action, if any.

    Returns:
        The magic_bonus (0-3) from the matching equipped weapon, or 0.
    """
    if action_source_item is None:
        return 0
    return get_weapon_magic_bonus(creature, action_source_item)


# ── Saving Throw Proficiencies ─────────────────────────────────────


def get_effective_saving_throw_proficiencies(creature: Creature) -> list[str]:
    """Get base saving throw proficiencies + feat + feature granted ones, deduplicated.

    Returns lowercase ability names.
    """
    base = [s.lower() for s in creature.saving_throw_proficiencies]
    for feat in _get_feats(creature):
        base.extend(s.lower() for s in feat.grants_saving_throw_proficiencies)
    for feature in _get_features(creature):
        base.extend(s.lower() for s in feature.grants_saving_throw_proficiencies)
    return _deduplicate_strings(base)


# ── Initiative ────────────────────────────────────────────────────────


def get_initiative_bonus(creature: Creature) -> int:
    """Get flat initiative bonus from feats and features (e.g., Alert = +5).

    This is added on top of the DEX modifier during initiative rolls.
    """
    feat_bonus = sum(feat.bonus_initiative for feat in _get_feats(creature))
    feature_bonus = sum(f.bonus_initiative for f in _get_features(creature))
    return feat_bonus + feature_bonus


# ── Critical Hit Modifications ────────────────────────────────────────


def get_effective_crit_range(creature: Creature) -> int:
    """Get the minimum d20 roll that counts as a critical hit.

    Default is 20. Champion Fighter with Improved Critical returns 19.
    Stacks across features and feats.

    Returns:
        The minimum natural roll for a crit (floor at 2 to prevent guaranteed crits).
    """
    reduction = 0
    for f in _get_features(creature):
        reduction += f.crit_range_reduction
    for f in _get_feats(creature):
        reduction += f.crit_range_reduction
    return max(2, 20 - reduction)


def get_bonus_crit_dice(creature: Creature) -> int:
    """Get total bonus weapon damage dice on critical hits.

    Barbarian Brutal Critical adds +1/+2/+3 extra dice.

    Returns:
        The number of extra weapon damage dice to roll on a crit.
    """
    bonus = 0
    for f in _get_features(creature):
        bonus += f.bonus_crit_dice
    for f in _get_feats(creature):
        bonus += f.bonus_crit_dice
    return bonus


# ── Stealth ──────────────────────────────────────────────────────────


def has_stealth_disadvantage(creature: Creature) -> bool:
    """Check if equipped armor imposes disadvantage on Stealth checks.

    Returns True if the creature has armor equipped with
    stealth_disadvantage=True. Per 5e, certain medium and all heavy
    armors impose disadvantage on Dexterity (Stealth) checks.
    """
    armor = get_equipped_armor(creature)
    if armor is not None and armor.stealth_disadvantage:
        return True
    return False


# ── Evasion ──────────────────────────────────────────────────────────


def has_evasion(creature: Creature) -> bool:
    """Check if creature has Evasion (Rogue/Monk).

    Evasion modifies DEX save outcomes: on success take 0 damage instead
    of half, on fail take half instead of full.
    """
    for f in _get_features(creature):
        if f.has_evasion:
            return True
    for f in _get_feats(creature):
        if f.has_evasion:
            return True
    return False


# ── Extra Attack ────────────────────────────────────────────────────


def get_extra_attack_count(creature: Creature) -> int:
    """Get total number of attacks when taking the Attack action.

    Returns the highest extra_attack_count from features and feats.
    Default is 1 (single attack). Extra Attack feature sets this to 2.
    Fighter 11th sets to 3, Fighter 20th sets to 4.

    Note: takes the MAX rather than summing, because you don't stack
    Extra Attack from multiclassing — you use the best one.
    """
    max_count = 1  # Default: 1 attack per Attack action
    for f in _get_features(creature):
        if f.extra_attack_count > max_count:
            max_count = f.extra_attack_count
    for f in _get_feats(creature):
        if f.extra_attack_count > max_count:
            max_count = f.extra_attack_count
    # Monsters carry their abilities in `special_abilities` (not `features`), so a
    # monster's Multiattack — a dragon's bite + two claws — lives there. Read it too,
    # so monster multiattack is live, not just a PlayerCharacter mechanic.
    for f in getattr(creature, "special_abilities", []):
        if getattr(f, "extra_attack_count", 0) > max_count:
            max_count = f.extra_attack_count
    return max_count


# ── Stat Breakdown Functions (for tooltips) ──────────────────────────


def get_ac_breakdown(creature: Creature) -> list[tuple[str, str]]:
    """Return a labeled breakdown of AC components for tooltip display.

    Each entry is (label, value_text). The last entry is the total.
    """
    lines: list[tuple[str, str]] = []

    if not creature.equipment:
        lines.append(("Stored AC", str(creature.armor_class)))
        return lines

    armor = get_equipped_armor(creature)
    shield = get_equipped_shield(creature)

    if armor is None:
        unarmored_type = _get_unarmored_defense_type(creature)
        dex_mod = get_effective_ability_modifier(creature, "dexterity")

        if unarmored_type == "monk":
            wis_mod = get_effective_ability_modifier(creature, "wisdom")
            lines.append(("Unarmored Defense (Monk)", f"10 + DEX({dex_mod}) + WIS({wis_mod}) = {10 + dex_mod + wis_mod}"))
        elif unarmored_type == "barbarian":
            con_mod = get_effective_ability_modifier(creature, "constitution")
            lines.append(("Unarmored Defense (Barb)", f"10 + DEX({dex_mod}) + CON({con_mod}) = {10 + dex_mod + con_mod}"))
        else:
            lines.append(("Unarmored", f"10 + DEX({dex_mod}) = {10 + dex_mod}"))
    else:
        armor_base = armor.armor_class or 10
        magic = armor.magic_bonus
        dex_mod = get_effective_ability_modifier(creature, "dexterity")
        armor_type = (armor.armor_type or "").lower()

        if armor_type == "heavy":
            base_text = f"{armor_base}"
            if magic:
                base_text += f" + {magic} magic"
            lines.append((armor.name, base_text))
        elif armor_type == "medium":
            max_dex = armor.max_dex_bonus if armor.max_dex_bonus is not None else 2
            used_dex = min(dex_mod, max_dex)
            base_text = f"{armor_base} + DEX({used_dex})"
            if magic:
                base_text += f" + {magic} magic"
            lines.append((armor.name, base_text))
        else:
            base_text = f"{armor_base} + DEX({dex_mod})"
            if magic:
                base_text += f" + {magic} magic"
            lines.append((armor.name, base_text))

    if shield is not None:
        shield_base = shield.armor_class if shield.armor_class is not None else 2
        shield_text = f"+{shield_base}"
        if shield.magic_bonus:
            shield_text += f" + {shield.magic_bonus} magic"
        lines.append((shield.name, shield_text))

    # Passive bonuses from equipment (excluding armor and shield)
    for item in _get_equipped_items(creature):
        if item.bonus_ac and item != armor and item != shield:
            lines.append((item.name, f"+{item.bonus_ac}"))

    for feat in _get_feats(creature):
        if feat.bonus_ac:
            lines.append((f"{feat.name} (feat)", f"+{feat.bonus_ac}"))

    for feature in _get_features(creature):
        if feature.bonus_ac:
            lines.append((f"{feature.name}", f"+{feature.bonus_ac}"))

    # Active buff AC bonuses (Shield, Haste, etc.)
    buff_ac = get_buff_ac_bonus(creature)
    if buff_ac:
        # List individual buff sources
        for buff in creature.active_buffs:
            for mod in buff.modifiers:
                if mod.stat == "ac" and mod.modifier_type == "flat_bonus" and isinstance(mod.value, (int, float)):
                    val = int(mod.value)
                    sign = "+" if val > 0 else ""
                    lines.append((f"{buff.name} (spell)", f"{sign}{val}"))

    total = get_effective_armor_class(creature)
    lines.append(("Total", str(total)))
    return lines


def get_speed_breakdown(creature: Creature) -> list[tuple[str, str]]:
    """Return a labeled breakdown of speed components for tooltip display."""
    lines: list[tuple[str, str]] = []
    base = creature.speed.get("walk", 30)
    lines.append(("Base", f"{base} ft"))

    for item in _get_equipped_items(creature):
        if item.bonus_speed:
            sign = "+" if item.bonus_speed > 0 else ""
            lines.append((item.name, f"{sign}{item.bonus_speed} ft"))

    for feat in _get_feats(creature):
        if feat.bonus_speed:
            sign = "+" if feat.bonus_speed > 0 else ""
            lines.append((f"{feat.name} (feat)", f"{sign}{feat.bonus_speed} ft"))

    for feature in _get_features(creature):
        if feature.bonus_speed:
            sign = "+" if feature.bonus_speed > 0 else ""
            lines.append((feature.name, f"{sign}{feature.bonus_speed} ft"))

    # Active buff speed bonuses
    buff_spd = get_buff_speed_bonus(creature)
    if buff_spd:
        for buff in creature.active_buffs:
            for mod in buff.modifiers:
                if mod.stat == "speed" and mod.modifier_type == "flat_bonus" and isinstance(mod.value, (int, float)):
                    val = int(mod.value)
                    sign = "+" if val > 0 else ""
                    lines.append((f"{buff.name} (spell)", f"{sign}{val} ft"))

    buff_mult = get_buff_speed_multiplier(creature)
    if buff_mult != 1.0:
        for buff in creature.active_buffs:
            for mod in buff.modifiers:
                if mod.stat == "speed" and mod.modifier_type == "multiply" and isinstance(mod.value, (int, float)):
                    lines.append((f"{buff.name} (spell)", f"x{float(mod.value)}"))

    total = get_effective_speed(creature)
    lines.append(("Total", f"{total} ft"))
    return lines


def get_ability_score_breakdown(creature: Creature, ability: str) -> list[tuple[str, str]]:
    """Return a labeled breakdown of an ability score for tooltip display."""
    lines: list[tuple[str, str]] = []
    base = creature.ability_scores.get_score(ability)
    lines.append(("Base", str(base)))

    for item in _get_equipped_items(creature):
        bonus = item.bonus_ability_scores.get(ability.lower(), 0)
        if bonus:
            sign = "+" if bonus > 0 else ""
            lines.append((item.name, f"{sign}{bonus}"))

    for feat in _get_feats(creature):
        bonus = feat.bonus_ability_scores.get(ability.lower(), 0)
        if bonus:
            sign = "+" if bonus > 0 else ""
            lines.append((f"{feat.name} (feat)", f"{sign}{bonus}"))

    for feature in _get_features(creature):
        bonus = feature.bonus_ability_scores.get(ability.lower(), 0)
        if bonus:
            sign = "+" if bonus > 0 else ""
            lines.append((feature.name, f"{sign}{bonus}"))

    total = get_effective_ability_score(creature, ability)
    mod = (total - 10) // 2
    mod_sign = "+" if mod >= 0 else ""
    lines.append(("Total", f"{total} ({mod_sign}{mod})"))
    return lines
