"""Tests for the Equipment Tab — model enhancements, data round-trips, and tab logic."""

import json
import pytest

from arena.models.items import Item, ItemType, WeaponProperty, EquipmentSlot, Rarity
from arena.models.character import Creature, PlayerCharacter
from arena.models.monster import Monster


# ======================================================================
# Model tests — EquipmentSlot & Rarity enums
# ======================================================================


class TestEquipmentSlotEnum:
    """Verify EquipmentSlot enum has all expected values."""

    def test_hand_slots(self):
        assert EquipmentSlot.MAIN_HAND == "main_hand"
        assert EquipmentSlot.OFF_HAND == "off_hand"
        assert EquipmentSlot.BOTH_HANDS == "both_hands"

    def test_body_slots(self):
        assert EquipmentSlot.ARMOR == "armor"
        assert EquipmentSlot.HEAD == "head"
        assert EquipmentSlot.CLOAK == "cloak"
        assert EquipmentSlot.GLOVES == "gloves"
        assert EquipmentSlot.BOOTS == "boots"
        assert EquipmentSlot.BELT == "belt"

    def test_accessory_slots(self):
        assert EquipmentSlot.AMULET == "amulet"
        assert EquipmentSlot.RING_1 == "ring_1"
        assert EquipmentSlot.RING_2 == "ring_2"
        assert EquipmentSlot.RING_3 == "ring_3"

    def test_three_ring_slots(self):
        """5e allows up to 3 attuned items, so 3 ring slots."""
        ring_slots = [s for s in EquipmentSlot if s.value.startswith("ring_")]
        assert len(ring_slots) == 3

    def test_none_slot(self):
        assert EquipmentSlot.NONE == "none"

    def test_total_slot_count(self):
        assert len(EquipmentSlot) == 14


class TestRarityEnum:
    """Verify Rarity enum has all expected values."""

    def test_all_rarities(self):
        assert Rarity.COMMON == "common"
        assert Rarity.UNCOMMON == "uncommon"
        assert Rarity.RARE == "rare"
        assert Rarity.VERY_RARE == "very_rare"
        assert Rarity.LEGENDARY == "legendary"
        assert Rarity.ARTIFACT == "artifact"

    def test_total_count(self):
        assert len(Rarity) == 6


# ======================================================================
# Model tests — Item with new fields
# ======================================================================


class TestItemNewFields:
    """Verify Item model accepts new fields with backward compat."""

    def test_backward_compat_minimal_item(self):
        """Old-style item dicts without new fields should still validate."""
        item = Item(name="Dagger", item_type="weapon")
        assert item.equipment_slot == EquipmentSlot.NONE
        assert item.rarity == Rarity.COMMON
        assert item.magic_bonus == 0
        assert item.weight == 0.0
        assert item.max_dex_bonus is None

    def test_backward_compat_from_dict(self):
        """Dict without new fields validates correctly."""
        data = {
            "name": "Shield",
            "item_type": "shield",
            "armor_class": 2,
        }
        item = Item.model_validate(data)
        assert item.name == "Shield"
        assert item.equipment_slot == EquipmentSlot.NONE
        assert item.rarity == Rarity.COMMON

    def test_item_with_new_fields(self):
        """Item with all new fields validates correctly."""
        item = Item(
            name="Flame Tongue Longsword",
            item_type="weapon",
            equipment_slot="main_hand",
            rarity="rare",
            magic_bonus=1,
            is_magical=True,
            requires_attunement=True,
            weight=3.0,
            damage_dice="1d8",
            damage_type="slashing",
            versatile_dice="1d10",
            weapon_properties=["versatile"],
        )
        assert item.equipment_slot == EquipmentSlot.MAIN_HAND
        assert item.rarity == Rarity.RARE
        assert item.magic_bonus == 1
        assert item.weight == 3.0

    def test_armor_with_max_dex_bonus(self):
        """Armor item with max_dex_bonus field."""
        item = Item(
            name="Chain Mail",
            item_type="armor",
            armor_class=16,
            armor_type="heavy",
            equipment_slot="armor",
            max_dex_bonus=0,
            stealth_disadvantage=True,
            strength_requirement=13,
            weight=55.0,
        )
        assert item.max_dex_bonus == 0
        assert item.stealth_disadvantage is True
        assert item.strength_requirement == 13

    def test_magic_bonus_range(self):
        """Magic bonus must be 0-3."""
        item = Item(name="Test", item_type="weapon", magic_bonus=3)
        assert item.magic_bonus == 3

        with pytest.raises(Exception):
            Item(name="Test", item_type="weapon", magic_bonus=4)

        with pytest.raises(Exception):
            Item(name="Test", item_type="weapon", magic_bonus=-1)

    def test_weight_non_negative(self):
        """Weight must be >= 0."""
        item = Item(name="Test", item_type="gear", weight=0.0)
        assert item.weight == 0.0

        with pytest.raises(Exception):
            Item(name="Test", item_type="gear", weight=-1.0)


# ======================================================================
# Model tests — equipment on Creature base class
# ======================================================================


class TestEquipmentOnCreature:
    """Verify equipment field is on Creature base, inherited by all types."""

    def test_creature_has_equipment(self):
        """Base Creature class should have equipment field."""
        creature = Creature(name="Test", max_hit_points=10)
        assert hasattr(creature, "equipment")
        assert creature.equipment == []

    def test_creature_with_equipment(self):
        """Creature can be created with equipment list."""
        sword = Item(name="Longsword", item_type="weapon", damage_dice="1d8")
        creature = Creature(
            name="Armed Creature",
            max_hit_points=20,
            equipment=[sword],
        )
        assert len(creature.equipment) == 1
        assert creature.equipment[0].name == "Longsword"

    def test_player_character_inherits_equipment(self):
        """PlayerCharacter should inherit equipment from Creature."""
        pc = PlayerCharacter(
            name="Thorin",
            max_hit_points=30,
            character_class="Fighter",
            equipment=[
                Item(name="Battleaxe", item_type="weapon"),
                Item(name="Chain Mail", item_type="armor", armor_class=16),
            ],
        )
        assert len(pc.equipment) == 2
        assert pc.equipment[0].name == "Battleaxe"
        assert pc.equipment[1].name == "Chain Mail"

    def test_monster_inherits_equipment(self):
        """Monster should inherit equipment from Creature."""
        mon = Monster(
            name="Goblin Boss",
            max_hit_points=21,
            equipment=[
                Item(name="Scimitar", item_type="weapon", damage_dice="1d6"),
            ],
        )
        assert len(mon.equipment) == 1
        assert mon.equipment[0].name == "Scimitar"


# ======================================================================
# Round-trip tests — save/load via JSON
# ======================================================================


class TestEquipmentRoundTrip:
    """Verify equipment survives JSON serialization round-trips."""

    def test_character_equipment_round_trip(self):
        """Character with equipment -> JSON -> load back."""
        pc = PlayerCharacter(
            name="Elara",
            max_hit_points=28,
            character_class="Wizard",
            equipment=[
                Item(
                    name="Staff of Power",
                    item_type="weapon",
                    equipment_slot="both_hands",
                    rarity="very_rare",
                    magic_bonus=2,
                    is_magical=True,
                    requires_attunement=True,
                    damage_dice="1d6",
                    damage_type="bludgeoning",
                    weight=4.0,
                ),
                Item(
                    name="Robe of the Archmagi",
                    item_type="armor",
                    equipment_slot="armor",
                    rarity="legendary",
                    is_magical=True,
                    requires_attunement=True,
                    armor_class=15,
                    max_dex_bonus=None,
                ),
            ],
        )

        # Serialize
        data = pc.model_dump(mode="json")
        json_str = json.dumps(data)

        # Deserialize
        loaded_data = json.loads(json_str)
        loaded_pc = PlayerCharacter.model_validate(loaded_data)

        assert len(loaded_pc.equipment) == 2
        staff = loaded_pc.equipment[0]
        assert staff.name == "Staff of Power"
        assert staff.equipment_slot == EquipmentSlot.BOTH_HANDS
        assert staff.rarity == Rarity.VERY_RARE
        assert staff.magic_bonus == 2
        assert staff.weight == 4.0

        robe = loaded_pc.equipment[1]
        assert robe.name == "Robe of the Archmagi"
        assert robe.rarity == Rarity.LEGENDARY
        assert robe.armor_class == 15

    def test_monster_equipment_round_trip(self):
        """Monster with equipment -> JSON -> load back."""
        mon = Monster(
            name="Hobgoblin Captain",
            max_hit_points=39,
            equipment=[
                Item(
                    name="Greatsword",
                    item_type="weapon",
                    equipment_slot="both_hands",
                    damage_dice="2d6",
                    damage_type="slashing",
                    weapon_properties=["heavy", "two_handed"],
                    weight=6.0,
                ),
                Item(
                    name="Half Plate",
                    item_type="armor",
                    equipment_slot="armor",
                    armor_class=15,
                    armor_type="medium",
                    max_dex_bonus=2,
                    weight=40.0,
                ),
            ],
        )

        data = mon.model_dump(mode="json")
        json_str = json.dumps(data)
        loaded = Monster.model_validate(json.loads(json_str))

        assert len(loaded.equipment) == 2
        assert loaded.equipment[0].name == "Greatsword"
        assert loaded.equipment[0].weapon_properties == [
            WeaponProperty.HEAVY, WeaponProperty.TWO_HANDED,
        ]
        assert loaded.equipment[1].max_dex_bonus == 2

    def test_no_equipment_backward_compat(self):
        """Creature dict without equipment key should load without error."""
        data = {
            "name": "Old Creature",
            "max_hit_points": 10,
        }
        creature = Creature.model_validate(data)
        assert creature.equipment == []

    def test_character_no_equipment_backward_compat(self):
        """Old character JSON without equipment loads cleanly."""
        data = {
            "name": "Old Char",
            "max_hit_points": 20,
            "character_class": "Rogue",
        }
        pc = PlayerCharacter.model_validate(data)
        assert pc.equipment == []

    def test_monster_no_equipment_backward_compat(self):
        """Old monster JSON without equipment loads cleanly."""
        data = {
            "name": "Old Monster",
            "max_hit_points": 15,
        }
        mon = Monster.model_validate(data)
        assert mon.equipment == []


# ======================================================================
# Equipment tab logic tests
# ======================================================================


class TestEquipmentTabLogic:
    """Test equipment tab helper functions and data flow (no Pygame needed)."""

    def test_default_item_structure(self):
        """Default new item dict should have expected keys."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import _default_item

        item = _default_item()
        assert item["name"] == "New Item"
        assert item["item_type"] == "weapon"
        assert item["equipment_slot"] == "main_hand"
        assert item["rarity"] == "common"
        assert item["magic_bonus"] == 0
        assert item["requires_attunement"] is False
        assert item["is_magical"] is False
        assert item["weight"] == 0.0
        assert item["weapon_properties"] == []

    def test_type_to_slot_mapping(self):
        """Auto-slot mapping should give sensible defaults."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import _TYPE_TO_DEFAULT_SLOT

        assert _TYPE_TO_DEFAULT_SLOT["weapon"] == "main_hand"
        assert _TYPE_TO_DEFAULT_SLOT["armor"] == "armor"
        assert _TYPE_TO_DEFAULT_SLOT["shield"] == "off_hand"
        assert _TYPE_TO_DEFAULT_SLOT["potion"] == "none"
        assert _TYPE_TO_DEFAULT_SLOT["wondrous"] == "none"
        assert _TYPE_TO_DEFAULT_SLOT["tool"] == "none"
        assert _TYPE_TO_DEFAULT_SLOT["gear"] == "none"

    def test_default_item_validates_as_pydantic(self):
        """Default item dict should pass Pydantic validation."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import _default_item

        item_dict = _default_item()
        # Remove None values that Pydantic doesn't need
        clean = {k: v for k, v in item_dict.items() if v is not None}
        item = Item.model_validate(clean)
        assert item.name == "New Item"
        assert item.item_type == ItemType.WEAPON

    def test_add_item_to_equipment_data(self):
        """Simulating add item appends to equipment_data list."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import _default_item

        equipment_data: list[dict] = []
        equipment_data.append(_default_item())
        assert len(equipment_data) == 1

        equipment_data.append(_default_item())
        assert len(equipment_data) == 2

    def test_remove_item_from_equipment_data(self):
        """Simulating remove item removes from list."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import _default_item

        equipment_data = [_default_item(), _default_item(), _default_item()]
        equipment_data[0]["name"] = "Sword"
        equipment_data[1]["name"] = "Shield"
        equipment_data[2]["name"] = "Potion"

        # Remove middle item
        equipment_data.pop(1)
        assert len(equipment_data) == 2
        assert equipment_data[0]["name"] == "Sword"
        assert equipment_data[1]["name"] == "Potion"

    def test_item_type_options_match_enum(self):
        """Dropdown options should match ItemType enum values."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import ITEM_TYPE_OPTIONS

        enum_values = [e.value for e in ItemType]
        assert ITEM_TYPE_OPTIONS == enum_values

    def test_equipment_slot_options_match_enum(self):
        """Dropdown options should match EquipmentSlot enum values."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import EQUIPMENT_SLOT_OPTIONS

        enum_values = [e.value for e in EquipmentSlot]
        assert EQUIPMENT_SLOT_OPTIONS == enum_values

    def test_rarity_options_match_enum(self):
        """Dropdown options should match Rarity enum values."""
        from arena.gui.screens.creature_builder_tabs.equipment_tab import RARITY_OPTIONS

        enum_values = [e.value for e in Rarity]
        assert RARITY_OPTIONS == enum_values
