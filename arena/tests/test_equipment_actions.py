"""Tests for auto-generating actions from equipment items."""

import json
import pytest

from arena.gui.screens.creature_builder_tabs.equipment_actions import (
    build_weapon_action,
    build_potion_action,
    build_scroll_action,
    build_action_for_item,
    get_action_category,
    find_linked_action,
    remove_linked_action,
    sync_equipment_actions,
)
from arena.models.actions import Action
from arena.models.items import Item, ItemType


# ======================================================================
# build_weapon_action tests
# ======================================================================


class TestBuildWeaponAction:
    """Test weapon action generation."""

    def test_melee_weapon_basic(self):
        item = {
            "name": "Longsword",
            "item_type": "weapon",
            "damage_dice": "1d8",
            "damage_type": "slashing",
            "magic_bonus": 0,
            "weapon_properties": [],
            "range_normal": None,
            "range_long": None,
        }
        action = build_weapon_action(item)
        assert action["name"] == "Longsword Attack"
        assert action["source_item"] == "Longsword"
        assert action["action_type"] == "action"
        assert action["target_type"] == "one_creature"
        assert action["range"] == 5

        atk = action["attack"]
        assert atk["attack_type"] == "melee_weapon"
        assert atk["ability"] == "strength"
        assert atk["reach"] == 5
        assert len(atk["damage"]) == 1
        assert atk["damage"][0]["dice"] == "1d8"
        assert atk["damage"][0]["damage_type"] == "slashing"
        assert atk["damage"][0]["ability_modifier"] == "strength"

    def test_melee_weapon_with_reach(self):
        item = {
            "name": "Glaive",
            "item_type": "weapon",
            "damage_dice": "1d10",
            "damage_type": "slashing",
            "magic_bonus": 0,
            "weapon_properties": ["reach", "heavy", "two_handed"],
            "range_normal": None,
            "range_long": None,
        }
        action = build_weapon_action(item)
        assert action["attack"]["reach"] == 10
        assert action["range"] == 10

    def test_ranged_weapon_with_ammunition(self):
        item = {
            "name": "Longbow",
            "item_type": "weapon",
            "damage_dice": "1d8",
            "damage_type": "piercing",
            "magic_bonus": 0,
            "weapon_properties": ["ammunition", "heavy", "two_handed"],
            "range_normal": 150,
            "range_long": 600,
        }
        action = build_weapon_action(item)
        atk = action["attack"]
        assert atk["attack_type"] == "ranged_weapon"
        assert atk["ability"] == "dexterity"
        assert atk["range_normal"] == 150
        assert atk["range_long"] == 600
        assert action["range"] == 150
        assert atk["damage"][0]["ability_modifier"] == "dexterity"

    def test_finesse_weapon_defaults_to_strength(self):
        item = {
            "name": "Rapier",
            "item_type": "weapon",
            "damage_dice": "1d8",
            "damage_type": "piercing",
            "magic_bonus": 0,
            "weapon_properties": ["finesse"],
            "range_normal": None,
            "range_long": None,
        }
        action = build_weapon_action(item)
        # Finesse defaults to strength (user can override in full editor)
        assert action["attack"]["ability"] == "strength"
        assert action["attack"]["attack_type"] == "melee_weapon"

    def test_thrown_weapon(self):
        item = {
            "name": "Javelin",
            "item_type": "weapon",
            "damage_dice": "1d6",
            "damage_type": "piercing",
            "magic_bonus": 0,
            "weapon_properties": ["thrown"],
            "range_normal": 30,
            "range_long": 120,
        }
        action = build_weapon_action(item)
        # Thrown weapons are primarily melee
        assert action["attack"]["attack_type"] == "melee_weapon"
        # But still have range info
        assert action["attack"]["range_normal"] == 30
        assert action["attack"]["range_long"] == 120

    def test_magic_weapon_bonus(self):
        item = {
            "name": "+2 Longsword",
            "item_type": "weapon",
            "damage_dice": "1d8",
            "damage_type": "slashing",
            "magic_bonus": 2,
            "weapon_properties": [],
            "range_normal": None,
            "range_long": None,
        }
        action = build_weapon_action(item)
        assert action["attack"]["damage"][0]["bonus"] == 2

    def test_no_bonus_when_zero(self):
        item = {
            "name": "Dagger",
            "item_type": "weapon",
            "damage_dice": "1d4",
            "damage_type": "piercing",
            "magic_bonus": 0,
            "weapon_properties": [],
            "range_normal": None,
            "range_long": None,
        }
        action = build_weapon_action(item)
        assert "bonus" not in action["attack"]["damage"][0]

    def test_no_damage_dice(self):
        item = {
            "name": "Net",
            "item_type": "weapon",
            "damage_dice": "",
            "damage_type": None,
            "magic_bonus": 0,
            "weapon_properties": ["thrown", "special"],
            "range_normal": 5,
            "range_long": 15,
        }
        action = build_weapon_action(item)
        assert action["attack"]["damage"] == []

    def test_weapon_properties_copied(self):
        item = {
            "name": "Shortsword",
            "item_type": "weapon",
            "damage_dice": "1d6",
            "damage_type": "piercing",
            "magic_bonus": 0,
            "weapon_properties": ["finesse", "light"],
            "range_normal": None,
            "range_long": None,
        }
        action = build_weapon_action(item)
        assert "finesse" in action["attack"]["properties"]
        assert "light" in action["attack"]["properties"]


# ======================================================================
# build_potion_action tests
# ======================================================================


class TestBuildPotionAction:
    """Test potion action generation."""

    def test_potion_default_action(self):
        item = {
            "name": "Healing Potion",
            "item_type": "potion",
            "charges": 1,
        }
        action = build_potion_action(item)
        assert action["name"] == "Use Healing Potion"
        assert action["action_type"] == "action"
        assert action["target_type"] == "self"
        assert action["range"] == 0
        assert action["uses_per_rest"] == 1
        assert action["source_item"] == "Healing Potion"

    def test_potion_bonus_action(self):
        item = {
            "name": "Healing Potion",
            "item_type": "potion",
            "charges": 1,
            "potion_action_type": "bonus_action",
        }
        action = build_potion_action(item)
        assert action["action_type"] == "bonus_action"

    def test_potion_charges(self):
        item = {
            "name": "Potion of Speed",
            "item_type": "potion",
            "charges": 3,
        }
        action = build_potion_action(item)
        assert action["uses_per_rest"] == 3


# ======================================================================
# get_action_category tests
# ======================================================================


class TestGetActionCategory:
    """Test category mapping."""

    def test_weapon_returns_actions(self):
        assert get_action_category({"item_type": "weapon"}) == "actions"

    def test_potion_default_returns_actions(self):
        assert get_action_category({"item_type": "potion"}) == "actions"

    def test_potion_bonus_returns_bonus_actions(self):
        item = {"item_type": "potion", "potion_action_type": "bonus_action"}
        assert get_action_category(item) == "bonus_actions"

    def test_armor_returns_none(self):
        assert get_action_category({"item_type": "armor"}) is None

    def test_shield_returns_none(self):
        assert get_action_category({"item_type": "shield"}) is None

    def test_gear_returns_none(self):
        assert get_action_category({"item_type": "gear"}) is None

    def test_wondrous_returns_none(self):
        assert get_action_category({"item_type": "wondrous"}) is None

    def test_tool_returns_none(self):
        assert get_action_category({"item_type": "tool"}) is None


# ======================================================================
# build_action_for_item tests
# ======================================================================


class TestBuildActionForItem:
    """Test dispatch function."""

    def test_weapon(self):
        item = {"name": "Sword", "item_type": "weapon", "damage_dice": "1d8",
                "damage_type": "slashing", "magic_bonus": 0,
                "weapon_properties": [], "range_normal": None, "range_long": None}
        result = build_action_for_item(item)
        assert result is not None
        assert result["name"] == "Sword Attack"

    def test_potion(self):
        item = {"name": "Potion", "item_type": "potion", "charges": 1}
        result = build_action_for_item(item)
        assert result is not None
        assert result["name"] == "Use Potion"

    def test_armor_returns_none(self):
        assert build_action_for_item({"item_type": "armor"}) is None

    def test_shield_returns_none(self):
        assert build_action_for_item({"item_type": "shield"}) is None

    def test_gear_returns_none(self):
        assert build_action_for_item({"item_type": "gear"}) is None


# ======================================================================
# find_linked_action / remove_linked_action tests
# ======================================================================


class TestFindLinkedAction:
    """Test finding linked actions by source_item."""

    def test_finds_in_actions(self):
        actions_data = {
            "actions": [
                {"name": "Slash", "source_item": "Sword"},
            ],
            "bonus_actions": [],
        }
        result = find_linked_action(actions_data, "Sword")
        assert result == ("actions", 0)

    def test_finds_in_bonus_actions(self):
        actions_data = {
            "actions": [],
            "bonus_actions": [
                {"name": "Use Potion", "source_item": "Healing Potion"},
            ],
        }
        result = find_linked_action(actions_data, "Healing Potion")
        assert result == ("bonus_actions", 0)

    def test_returns_none_not_found(self):
        actions_data = {"actions": [], "bonus_actions": []}
        assert find_linked_action(actions_data, "Sword") is None

    def test_returns_none_empty(self):
        actions_data = {"actions": [], "bonus_actions": [], "reactions": []}
        assert find_linked_action(actions_data, "X") is None

    def test_ignores_actions_without_source_item(self):
        actions_data = {
            "actions": [{"name": "Manual Action"}],
            "bonus_actions": [],
        }
        assert find_linked_action(actions_data, "Manual Action") is None


class TestRemoveLinkedAction:
    """Test removing linked actions."""

    def test_removes_existing(self):
        actions_data = {
            "actions": [{"name": "Sword Attack", "source_item": "Sword"}],
            "bonus_actions": [],
        }
        assert remove_linked_action(actions_data, "Sword") is True
        assert len(actions_data["actions"]) == 0

    def test_returns_false_not_found(self):
        actions_data = {"actions": [], "bonus_actions": []}
        assert remove_linked_action(actions_data, "Sword") is False


# ======================================================================
# sync_equipment_actions tests
# ======================================================================


class TestSyncEquipmentActions:
    """Test full equipment → action sync."""

    def _make_actions_data(self):
        return {
            "actions": [],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
        }

    def test_creates_action_for_new_weapon(self):
        equipment = [{
            "name": "Longsword", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "slashing",
            "magic_bonus": 0, "weapon_properties": [],
            "range_normal": None, "range_long": None,
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1
        assert actions_data["actions"][0]["source_item"] == "Longsword"

    def test_creates_action_for_new_potion(self):
        equipment = [{
            "name": "Healing Potion", "item_type": "potion", "charges": 1,
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1
        assert actions_data["actions"][0]["source_item"] == "Healing Potion"

    def test_updates_action_when_weapon_modified(self):
        equipment = [{
            "name": "Longsword", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "slashing",
            "magic_bonus": 0, "weapon_properties": [],
            "range_normal": None, "range_long": None,
        }]
        actions_data = self._make_actions_data()

        # First sync
        sync_equipment_actions(equipment, actions_data)
        assert actions_data["actions"][0]["attack"]["damage"][0]["dice"] == "1d8"

        # Modify weapon
        equipment[0]["damage_dice"] = "2d6"
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1
        assert actions_data["actions"][0]["attack"]["damage"][0]["dice"] == "2d6"

    def test_removes_action_when_weapon_deleted(self):
        equipment = [{
            "name": "Longsword", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "slashing",
            "magic_bonus": 0, "weapon_properties": [],
            "range_normal": None, "range_long": None,
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1

        # Delete equipment
        equipment.clear()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 0

    def test_removes_action_when_type_changes_to_armor(self):
        equipment = [{
            "name": "Magic Weapon", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "slashing",
            "magic_bonus": 0, "weapon_properties": [],
            "range_normal": None, "range_long": None,
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1

        # Change type to armor
        equipment[0]["item_type"] = "armor"
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 0

    def test_moves_potion_action_when_category_changes(self):
        equipment = [{
            "name": "Speed Potion", "item_type": "potion",
            "charges": 1, "potion_action_type": "action",
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1
        assert len(actions_data["bonus_actions"]) == 0

        # Switch to bonus action
        equipment[0]["potion_action_type"] = "bonus_action"
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 0
        assert len(actions_data["bonus_actions"]) == 1

    def test_no_action_for_armor(self):
        equipment = [{"name": "Chain Mail", "item_type": "armor"}]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert all(len(v) == 0 for v in actions_data.values())

    def test_no_action_for_shield(self):
        equipment = [{"name": "Shield", "item_type": "shield"}]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert all(len(v) == 0 for v in actions_data.values())

    def test_preserves_manually_created_actions(self):
        equipment = [{
            "name": "Sword", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "slashing",
            "magic_bonus": 0, "weapon_properties": [],
            "range_normal": None, "range_long": None,
        }]
        actions_data = self._make_actions_data()
        # Add a manual action
        actions_data["actions"].append({
            "name": "Second Wind",
            "description": "Heal yourself",
            "action_type": "bonus_action",
        })
        sync_equipment_actions(equipment, actions_data)

        # Manual action preserved, weapon action added
        assert len(actions_data["actions"]) == 2
        names = [a["name"] for a in actions_data["actions"]]
        assert "Second Wind" in names
        assert "Sword Attack" in names

    def test_orphan_cleanup(self):
        """Actions with stale source_item are cleaned up."""
        actions_data = self._make_actions_data()
        # Pre-existing equipment action for item that no longer exists
        actions_data["actions"].append({
            "name": "Old Sword Attack",
            "source_item": "Old Sword",
        })
        equipment = []  # No equipment
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 0

    def test_multiple_weapons(self):
        equipment = [
            {
                "name": "Longsword", "item_type": "weapon",
                "damage_dice": "1d8", "damage_type": "slashing",
                "magic_bonus": 0, "weapon_properties": [],
                "range_normal": None, "range_long": None,
            },
            {
                "name": "Shortbow", "item_type": "weapon",
                "damage_dice": "1d6", "damage_type": "piercing",
                "magic_bonus": 0, "weapon_properties": ["ammunition"],
                "range_normal": 80, "range_long": 320,
            },
        ]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 2
        names = [a["name"] for a in actions_data["actions"]]
        assert "Longsword Attack" in names
        assert "Shortbow Attack" in names

    def test_empty_equipment_clears_all_equipment_actions(self):
        actions_data = self._make_actions_data()
        actions_data["actions"] = [
            {"name": "Sword Attack", "source_item": "Sword"},
            {"name": "Manual Action"},
        ]
        sync_equipment_actions([], actions_data)
        assert len(actions_data["actions"]) == 1
        assert actions_data["actions"][0]["name"] == "Manual Action"


# ======================================================================
# Model round-trip tests
# ======================================================================


class TestActionSourceItemField:
    """Test source_item field on Action model."""

    def test_default_none(self):
        action = Action(name="Test", description="test")
        assert action.source_item is None

    def test_round_trip(self):
        action = Action(
            name="Sword Attack",
            description="Attack with sword.",
            source_item="Longsword",
        )
        data = action.model_dump(mode="json")
        assert data["source_item"] == "Longsword"

        loaded = Action.model_validate(data)
        assert loaded.source_item == "Longsword"

    def test_old_action_without_source_item(self):
        """Old actions without source_item load cleanly."""
        data = {"name": "Fireball", "description": "A ball of fire."}
        action = Action.model_validate(data)
        assert action.source_item is None


class TestItemPotionActionTypeField:
    """Test potion_action_type field on Item model."""

    def test_default_none(self):
        item = Item(name="Test", item_type="potion")
        assert item.potion_action_type is None

    def test_round_trip(self):
        item = Item(
            name="Healing Potion",
            item_type="potion",
            potion_action_type="bonus_action",
        )
        data = item.model_dump(mode="json")
        assert data["potion_action_type"] == "bonus_action"

        loaded = Item.model_validate(data)
        assert loaded.potion_action_type == "bonus_action"

    def test_old_item_without_potion_action_type(self):
        """Old items without potion_action_type load cleanly."""
        data = {"name": "Dagger", "item_type": "weapon"}
        item = Item.model_validate(data)
        assert item.potion_action_type is None


# ======================================================================
# Integration: action validates as Pydantic
# ======================================================================


class TestGeneratedActionValidation:
    """Ensure generated action dicts pass Pydantic validation."""

    def test_weapon_action_validates(self):
        item = {
            "name": "Longsword", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "slashing",
            "magic_bonus": 0, "weapon_properties": ["versatile"],
            "range_normal": None, "range_long": None,
        }
        action_dict = build_weapon_action(item)
        action = Action.model_validate(action_dict)
        assert action.name == "Longsword Attack"
        assert action.source_item == "Longsword"
        assert action.attack is not None
        assert action.attack.damage[0].dice == "1d8"

    def test_potion_action_validates(self):
        item = {
            "name": "Healing Potion", "item_type": "potion",
            "charges": 1, "potion_action_type": "bonus_action",
        }
        action_dict = build_potion_action(item)
        action = Action.model_validate(action_dict)
        assert action.name == "Use Healing Potion"
        assert action.source_item == "Healing Potion"
        assert action.action_type.value == "bonus_action"

    def test_ranged_weapon_action_validates(self):
        item = {
            "name": "Longbow", "item_type": "weapon",
            "damage_dice": "1d8", "damage_type": "piercing",
            "magic_bonus": 1, "weapon_properties": ["ammunition", "heavy", "two_handed"],
            "range_normal": 150, "range_long": 600,
        }
        action_dict = build_weapon_action(item)
        action = Action.model_validate(action_dict)
        assert action.attack.attack_type == "ranged_weapon"
        assert action.attack.range_normal == 150
        assert action.attack.range_long == 600
        assert action.attack.damage[0].bonus == 1


# ======================================================================
# SCROLL item type tests
# ======================================================================


class TestItemTypeScroll:
    """Test SCROLL in ItemType enum."""

    def test_scroll_in_enum(self):
        assert ItemType.SCROLL == "scroll"
        assert "scroll" in [e.value for e in ItemType]

    def test_scroll_item_model(self):
        item = Item(name="Scroll of Fireball", item_type="scroll")
        assert item.item_type == ItemType.SCROLL

    def test_scroll_round_trip(self):
        item = Item(
            name="Scroll of Fireball",
            item_type="scroll",
            charges=1,
            potion_action_type="action",
            effect_damage_dice="8d6",
            effect_damage_type="fire",
            effect_save_ability="dexterity",
            effect_save_dc=15,
            effect_save_damage_on_success="half",
        )
        data = item.model_dump(mode="json")
        loaded = Item.model_validate(data)
        assert loaded.item_type == ItemType.SCROLL
        assert loaded.effect_damage_dice == "8d6"
        assert loaded.effect_save_dc == 15


# ======================================================================
# build_scroll_action tests
# ======================================================================


class TestBuildScrollAction:
    """Test scroll action generation."""

    def test_scroll_basic(self):
        item = {
            "name": "Scroll of Protection",
            "item_type": "scroll",
            "charges": 1,
        }
        action = build_scroll_action(item)
        assert action["name"] == "Use Scroll of Protection"
        assert action["action_type"] == "action"
        assert action["target_type"] == "self"
        assert action["range"] == 0
        assert action["uses_per_rest"] == 1
        assert action["source_item"] == "Scroll of Protection"
        assert "scroll" in action["description"].lower()

    def test_scroll_bonus_action(self):
        item = {
            "name": "Scroll of Haste",
            "item_type": "scroll",
            "charges": 1,
            "potion_action_type": "bonus_action",
        }
        action = build_scroll_action(item)
        assert action["action_type"] == "bonus_action"

    def test_scroll_with_charges(self):
        item = {
            "name": "Scroll of Magic Missile",
            "item_type": "scroll",
            "charges": 3,
        }
        action = build_scroll_action(item)
        assert action["uses_per_rest"] == 3

    def test_scroll_with_healing(self):
        item = {
            "name": "Scroll of Cure Wounds",
            "item_type": "scroll",
            "charges": 1,
            "effect_healing": "1d8+3",
        }
        action = build_scroll_action(item)
        assert action["healing"] == "1d8+3"

    def test_scroll_with_damage_and_save(self):
        item = {
            "name": "Scroll of Fireball",
            "item_type": "scroll",
            "charges": 1,
            "effect_damage_dice": "8d6",
            "effect_damage_type": "fire",
            "effect_save_ability": "dexterity",
            "effect_save_dc": 15,
            "effect_save_damage_on_success": "half",
        }
        action = build_scroll_action(item)
        assert action["saving_throw"] is not None
        save = action["saving_throw"]
        assert save["ability"] == "dexterity"
        assert save["dc"] == 15
        assert save["damage_on_success"] == "half"
        assert len(save["damage_on_fail"]) == 1
        assert save["damage_on_fail"][0]["dice"] == "8d6"
        assert save["damage_on_fail"][0]["damage_type"] == "fire"

    def test_scroll_with_conditions(self):
        item = {
            "name": "Scroll of Hold Person",
            "item_type": "scroll",
            "charges": 1,
            "effect_save_ability": "wisdom",
            "effect_save_dc": 13,
            "effect_conditions_applied": ["paralyzed"],
        }
        action = build_scroll_action(item)
        assert "paralyzed" in action["conditions_applied"]
        save = action["saving_throw"]
        assert "paralyzed" in save["conditions_on_fail"]

    def test_scroll_with_target_and_range(self):
        item = {
            "name": "Scroll of Lightning Bolt",
            "item_type": "scroll",
            "charges": 1,
            "effect_target_type": "area_line",
            "effect_range": 100,
        }
        action = build_scroll_action(item)
        assert action["target_type"] == "area_line"
        assert action["range"] == 100


# ======================================================================
# Consumable effects on potion actions
# ======================================================================


class TestPotionEffects:
    """Test potion action generation with effects."""

    def test_potion_with_healing(self):
        item = {
            "name": "Potion of Healing",
            "item_type": "potion",
            "charges": 1,
            "effect_healing": "2d4+2",
        }
        action = build_potion_action(item)
        assert action["healing"] == "2d4+2"

    def test_potion_with_conditions_applied(self):
        item = {
            "name": "Potion of Invisibility",
            "item_type": "potion",
            "charges": 1,
            "effect_conditions_applied": ["invisible"],
        }
        action = build_potion_action(item)
        assert "invisible" in action["conditions_applied"]

    def test_potion_with_conditions_removed(self):
        item = {
            "name": "Potion of Cure Disease",
            "item_type": "potion",
            "charges": 1,
            "effect_conditions_removed": ["poisoned"],
        }
        action = build_potion_action(item)
        assert "poisoned" in action["conditions_removed"]

    def test_potion_with_save_and_damage(self):
        item = {
            "name": "Potion of Poison",
            "item_type": "potion",
            "charges": 1,
            "effect_damage_dice": "3d6",
            "effect_damage_type": "poison",
            "effect_save_ability": "constitution",
            "effect_save_dc": 13,
            "effect_save_damage_on_success": "half",
        }
        action = build_potion_action(item)
        save = action["saving_throw"]
        assert save["ability"] == "constitution"
        assert save["dc"] == 13
        assert save["damage_on_success"] == "half"
        assert save["damage_on_fail"][0]["dice"] == "3d6"

    def test_potion_with_target_override(self):
        item = {
            "name": "Potion of Dragon Breath",
            "item_type": "potion",
            "charges": 1,
            "effect_target_type": "area_cone",
            "effect_range": 30,
        }
        action = build_potion_action(item)
        assert action["target_type"] == "area_cone"
        assert action["range"] == 30

    def test_potion_no_effects_keeps_defaults(self):
        """A potion with no effects still generates a valid action."""
        item = {
            "name": "Mystery Potion",
            "item_type": "potion",
            "charges": 1,
        }
        action = build_potion_action(item)
        assert action["target_type"] == "self"
        assert action["range"] == 0
        assert "healing" not in action
        assert "saving_throw" not in action
        assert "conditions_applied" not in action

    def test_potion_damage_without_save(self):
        """Damage without a saving throw gets added to description."""
        item = {
            "name": "Acid Vial",
            "item_type": "potion",
            "charges": 1,
            "effect_damage_dice": "2d6",
            "effect_damage_type": "acid",
        }
        action = build_potion_action(item)
        assert "2d6 acid" in action["description"]
        assert "saving_throw" not in action

    def test_potion_full_effects_validate_as_pydantic(self):
        """A potion with all effects passes Pydantic validation."""
        item = {
            "name": "Greater Healing Potion",
            "item_type": "potion",
            "charges": 1,
            "potion_action_type": "bonus_action",
            "effect_healing": "4d4+4",
            "effect_conditions_removed": ["poisoned"],
        }
        action_dict = build_potion_action(item)
        action = Action.model_validate(action_dict)
        assert action.healing == "4d4+4"
        assert "poisoned" in action.conditions_removed


# ======================================================================
# Scroll category + dispatch tests
# ======================================================================


class TestScrollCategoryAndDispatch:
    """Test scroll integration with category and dispatch functions."""

    def test_scroll_default_returns_actions(self):
        assert get_action_category({"item_type": "scroll"}) == "actions"

    def test_scroll_bonus_returns_bonus_actions(self):
        item = {"item_type": "scroll", "potion_action_type": "bonus_action"}
        assert get_action_category(item) == "bonus_actions"

    def test_build_action_for_scroll(self):
        item = {"name": "Scroll", "item_type": "scroll", "charges": 1}
        result = build_action_for_item(item)
        assert result is not None
        assert result["name"] == "Use Scroll"

    def test_scroll_action_validates_as_pydantic(self):
        item = {
            "name": "Scroll of Fireball",
            "item_type": "scroll",
            "charges": 1,
            "effect_damage_dice": "8d6",
            "effect_damage_type": "fire",
            "effect_save_ability": "dexterity",
            "effect_save_dc": 15,
            "effect_save_damage_on_success": "half",
            "effect_target_type": "area_sphere",
            "effect_range": 150,
        }
        action_dict = build_scroll_action(item)
        action = Action.model_validate(action_dict)
        assert action.name == "Use Scroll of Fireball"
        assert action.source_item == "Scroll of Fireball"
        assert action.saving_throw is not None
        assert action.saving_throw.dc == 15
        assert action.target_type.value == "area_sphere"
        assert action.range == 150


# ======================================================================
# Sync with scrolls
# ======================================================================


class TestSyncWithScrolls:
    """Test sync_equipment_actions with scroll items."""

    def _make_actions_data(self):
        return {
            "actions": [],
            "bonus_actions": [],
            "reactions": [],
            "legendary_actions": [],
            "lair_actions": [],
        }

    def test_creates_action_for_scroll(self):
        equipment = [{
            "name": "Scroll of Shield", "item_type": "scroll", "charges": 1,
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1
        assert actions_data["actions"][0]["source_item"] == "Scroll of Shield"
        assert actions_data["actions"][0]["name"] == "Use Scroll of Shield"

    def test_scroll_bonus_action_goes_to_bonus_actions(self):
        equipment = [{
            "name": "Quick Scroll", "item_type": "scroll",
            "charges": 1, "potion_action_type": "bonus_action",
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["bonus_actions"]) == 1
        assert len(actions_data["actions"]) == 0

    def test_scroll_with_effects_syncs(self):
        equipment = [{
            "name": "Scroll of Fireball", "item_type": "scroll",
            "charges": 1,
            "effect_damage_dice": "8d6",
            "effect_damage_type": "fire",
            "effect_save_ability": "dexterity",
            "effect_save_dc": 15,
            "effect_save_damage_on_success": "half",
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        action = actions_data["actions"][0]
        assert action["saving_throw"]["dc"] == 15
        assert action["saving_throw"]["damage_on_fail"][0]["dice"] == "8d6"

    def test_scroll_deleted_removes_action(self):
        equipment = [{
            "name": "Scroll of Fly", "item_type": "scroll", "charges": 1,
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1

        equipment.clear()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 0

    def test_mixed_equipment_weapons_potions_scrolls(self):
        equipment = [
            {
                "name": "Longsword", "item_type": "weapon",
                "damage_dice": "1d8", "damage_type": "slashing",
                "magic_bonus": 0, "weapon_properties": [],
                "range_normal": None, "range_long": None,
            },
            {
                "name": "Healing Potion", "item_type": "potion",
                "charges": 1, "effect_healing": "2d4+2",
            },
            {
                "name": "Scroll of Fireball", "item_type": "scroll",
                "charges": 1,
                "effect_damage_dice": "8d6", "effect_damage_type": "fire",
                "effect_save_ability": "dexterity", "effect_save_dc": 15,
            },
        ]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 3
        names = [a["name"] for a in actions_data["actions"]]
        assert "Longsword Attack" in names
        assert "Use Healing Potion" in names
        assert "Use Scroll of Fireball" in names

    def test_scroll_moves_category_on_action_type_change(self):
        equipment = [{
            "name": "Magic Scroll", "item_type": "scroll",
            "charges": 1, "potion_action_type": "action",
        }]
        actions_data = self._make_actions_data()
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 1

        equipment[0]["potion_action_type"] = "bonus_action"
        sync_equipment_actions(equipment, actions_data)
        assert len(actions_data["actions"]) == 0
        assert len(actions_data["bonus_actions"]) == 1


# ======================================================================
# Item model effect fields tests
# ======================================================================


class TestItemEffectFields:
    """Test new effect fields on Item model."""

    def test_effect_fields_default_empty(self):
        item = Item(name="Test", item_type="potion")
        assert item.effect_healing is None
        assert item.effect_damage_dice is None
        assert item.effect_damage_type is None
        assert item.effect_target_type is None
        assert item.effect_range is None
        assert item.effect_save_ability is None
        assert item.effect_save_dc is None
        assert item.effect_save_damage_on_success is None
        assert item.effect_conditions_applied == []
        assert item.effect_conditions_removed == []

    def test_effect_fields_round_trip(self):
        item = Item(
            name="Potion of Healing",
            item_type="potion",
            effect_healing="2d4+2",
            effect_conditions_removed=["poisoned"],
        )
        data = item.model_dump(mode="json")
        loaded = Item.model_validate(data)
        assert loaded.effect_healing == "2d4+2"
        assert loaded.effect_conditions_removed == ["poisoned"]

    def test_scroll_effect_fields_round_trip(self):
        item = Item(
            name="Scroll of Lightning Bolt",
            item_type="scroll",
            charges=1,
            effect_damage_dice="8d6",
            effect_damage_type="lightning",
            effect_save_ability="dexterity",
            effect_save_dc=15,
            effect_save_damage_on_success="half",
            effect_target_type="area_line",
            effect_range=100,
        )
        data = item.model_dump(mode="json")
        loaded = Item.model_validate(data)
        assert loaded.effect_damage_dice == "8d6"
        assert loaded.effect_save_ability == "dexterity"
        assert loaded.effect_target_type == "area_line"
        assert loaded.effect_range == 100

    def test_old_item_without_effect_fields(self):
        """Old items without effect fields load cleanly."""
        data = {"name": "Old Potion", "item_type": "potion"}
        item = Item.model_validate(data)
        assert item.effect_healing is None
        assert item.effect_conditions_applied == []

    def test_conditions_applied_list(self):
        item = Item(
            name="Potion of Fear",
            item_type="potion",
            effect_conditions_applied=["frightened", "poisoned"],
        )
        assert len(item.effect_conditions_applied) == 2
        data = item.model_dump(mode="json")
        loaded = Item.model_validate(data)
        assert loaded.effect_conditions_applied == ["frightened", "poisoned"]
