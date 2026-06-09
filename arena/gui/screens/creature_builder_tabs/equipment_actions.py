"""Auto-generate actions from equipment items.

Pure logic module (no Pygame imports) — fully testable.
"""

from __future__ import annotations


def build_weapon_action(item: dict) -> dict:
    """Build a weapon attack action dict from an equipment item dict."""
    name = item.get("name", "Weapon")
    damage_dice = item.get("damage_dice", "") or ""
    damage_type = item.get("damage_type", "slashing") or "slashing"
    magic_bonus = item.get("magic_bonus", 0)
    weapon_props = item.get("weapon_properties", [])
    range_normal = item.get("range_normal") or 0
    range_long = item.get("range_long") or 0

    # Determine attack type
    if "ammunition" in weapon_props:
        attack_type = "ranged_weapon"
    elif range_normal > 0 and "thrown" not in weapon_props:
        attack_type = "ranged_weapon"
    else:
        attack_type = "melee_weapon"

    # Determine attack ability
    if attack_type == "ranged_weapon":
        ability = "dexterity"
    else:
        ability = "strength"

    # Reach
    reach = 10 if "reach" in weapon_props else 5

    # Build damage roll
    damage: list[dict] = []
    if damage_dice:
        dmg_entry: dict = {
            "dice": damage_dice,
            "damage_type": damage_type,
            "ability_modifier": ability,
        }
        if magic_bonus > 0:
            dmg_entry["bonus"] = magic_bonus
        damage.append(dmg_entry)

    # Build attack sub-dict
    attack: dict = {
        "name": f"{name} Attack",
        "attack_type": attack_type,
        "ability": ability,
        "reach": reach,
        "damage": damage,
        "properties": list(weapon_props),
    }
    if range_normal > 0:
        attack["range_normal"] = range_normal
    if range_long > 0:
        attack["range_long"] = range_long

    # Determine action range
    if attack_type == "ranged_weapon" and range_normal > 0:
        action_range = range_normal
    else:
        action_range = reach

    return {
        "name": f"{name} Attack",
        "description": f"Attack with {name}.",
        "action_type": "action",
        "target_type": "one_creature",
        "range": action_range,
        "attack": attack,
        "source_item": name,
        "ai_priority": 5,
    }


def _build_consumable_effects(item: dict, action: dict) -> None:
    """Populate effect fields on a consumable action dict from item data.

    Shared by both potions and scrolls.  Mutates *action* in place.
    """
    # Healing
    healing = item.get("effect_healing") or None
    if healing:
        action["healing"] = healing

    # Target type override (default is "self" but effects may target others)
    effect_target = item.get("effect_target_type") or None
    if effect_target:
        action["target_type"] = effect_target

    # Range override for targeted effects
    effect_range = item.get("effect_range")
    if effect_range and effect_range > 0:
        action["range"] = effect_range

    # Conditions applied/removed
    cond_applied = item.get("effect_conditions_applied", [])
    if cond_applied:
        action["conditions_applied"] = list(cond_applied)

    cond_removed = item.get("effect_conditions_removed", [])
    if cond_removed:
        action["conditions_removed"] = list(cond_removed)

    # Saving throw + damage
    save_ability = item.get("effect_save_ability") or None
    effect_dmg_dice = item.get("effect_damage_dice") or None
    effect_dmg_type = item.get("effect_damage_type") or None

    if save_ability:
        save_data: dict = {
            "ability": save_ability,
            "dc": item.get("effect_save_dc") or 10,
            "damage_on_success": item.get("effect_save_damage_on_success") or "none",
        }
        if effect_dmg_dice and effect_dmg_type:
            save_data["damage_on_fail"] = [
                {"dice": effect_dmg_dice, "damage_type": effect_dmg_type},
            ]
        if cond_applied:
            save_data["conditions_on_fail"] = list(cond_applied)
        action["saving_throw"] = save_data
    elif effect_dmg_dice and effect_dmg_type:
        # Direct damage without a saving throw (rare, but possible)
        # Represent as an attack-less action with damage info in description
        action["description"] += f" Deals {effect_dmg_dice} {effect_dmg_type} damage."


def build_potion_action(item: dict) -> dict:
    """Build a 'Use potion' action dict from an equipment item dict."""
    name = item.get("name", "Potion")
    charges = item.get("charges", 1) or 1
    potion_action_type = item.get("potion_action_type", "action") or "action"

    action_type_value = (
        "bonus_action" if potion_action_type == "bonus_action" else "action"
    )

    action: dict = {
        "name": f"Use {name}",
        "description": f"Use {name} (consumable).",
        "action_type": action_type_value,
        "target_type": "self",
        "range": 0,
        "uses_per_rest": charges,
        "rest_type": None,
        "source_item": name,
        "ai_priority": 3,
    }

    _build_consumable_effects(item, action)
    return action


def build_scroll_action(item: dict) -> dict:
    """Build a 'Use scroll' action dict from an equipment item dict."""
    name = item.get("name", "Scroll")
    charges = item.get("charges", 1) or 1
    scroll_action_type = item.get("potion_action_type", "action") or "action"

    action_type_value = (
        "bonus_action" if scroll_action_type == "bonus_action" else "action"
    )

    action: dict = {
        "name": f"Use {name}",
        "description": f"Use {name} (scroll).",
        "action_type": action_type_value,
        "target_type": "self",
        "range": 0,
        "uses_per_rest": charges,
        "rest_type": None,
        "source_item": name,
        "ai_priority": 3,
    }

    _build_consumable_effects(item, action)
    return action


def get_action_category(item: dict) -> str | None:
    """Return the actions_data category key for an item, or None."""
    item_type = item.get("item_type", "")
    if item_type == "weapon":
        return "actions"
    if item_type in ("potion", "scroll"):
        action_type = item.get("potion_action_type", "action") or "action"
        return "bonus_actions" if action_type == "bonus_action" else "actions"
    return None


def build_action_for_item(item: dict) -> dict | None:
    """Build the appropriate action dict for an item, or None."""
    item_type = item.get("item_type", "")
    if item_type == "weapon":
        return build_weapon_action(item)
    if item_type == "potion":
        return build_potion_action(item)
    if item_type == "scroll":
        return build_scroll_action(item)
    return None


def find_linked_action(
    actions_data: dict[str, list[dict]],
    source_item_name: str,
) -> tuple[str, int] | None:
    """Find an existing action linked to a source item.

    Returns (category, index) or None if not found.
    """
    for cat, action_list in actions_data.items():
        for i, action in enumerate(action_list):
            if action.get("source_item") == source_item_name:
                return (cat, i)
    return None


def remove_linked_action(
    actions_data: dict[str, list[dict]],
    source_item_name: str,
) -> bool:
    """Remove any action linked to source_item_name. Returns True if removed."""
    loc = find_linked_action(actions_data, source_item_name)
    if loc is not None:
        cat, idx = loc
        actions_data[cat].pop(idx)
        return True
    return False


def sync_equipment_actions(
    equipment_data: list[dict],
    actions_data: dict[str, list[dict]],
) -> None:
    """Full sync: ensure actions_data matches equipment_data.

    - For each weapon/potion/scroll, create or update the linked action.
    - Remove any orphaned source_item actions.
    """
    # Collect all item names that should have actions
    expected_sources: set[str] = set()

    for item in equipment_data:
        item_name = item.get("name", "")
        action = build_action_for_item(item)
        if action is None:
            # This item type doesn't generate actions; remove any stale one
            remove_linked_action(actions_data, item_name)
            continue

        expected_sources.add(item_name)
        category = get_action_category(item)
        loc = find_linked_action(actions_data, item_name)

        if loc is not None:
            old_cat, old_idx = loc
            if old_cat == category:
                # Update in place
                actions_data[old_cat][old_idx] = action
            else:
                # Category changed — remove from old, append to new
                actions_data[old_cat].pop(old_idx)
                actions_data[category].append(action)
        else:
            # New — append
            actions_data[category].append(action)

    # Remove orphaned actions (source_item set but item no longer exists)
    for cat in list(actions_data.keys()):
        actions_data[cat] = [
            a for a in actions_data[cat]
            if a.get("source_item") is None or a["source_item"] in expected_sources
        ]
