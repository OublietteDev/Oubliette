"""Tests for the stat modifier framework (src/combat/stat_modifiers.py).

Tests cover:
- Equipment detection helpers (armor, shield, weapon lookup)
- Effective AC calculation (all 5e armor categories, shields, magic bonuses)
- Backward compatibility (empty equipment returns stored AC)
- Weapon attack bonus from magic weapons
- Stealth disadvantage from armor
- Passive equipment effects (ability scores, speed, resistances, immunities)
"""

import pytest

from arena.models.character import Creature
from arena.models.items import Item, ItemType, EquipmentSlot, Rarity
from arena.combat.stat_modifiers import (
    _get_equipped_items,
    get_equipped_armor,
    get_equipped_shield,
    get_weapon_magic_bonus,
    get_effective_armor_class,
    get_effective_ability_score,
    get_effective_ability_modifier,
    get_effective_speed,
    get_effective_damage_resistances,
    get_effective_damage_immunities,
    get_effective_condition_immunities,
    get_passive_ac_bonus,
    get_weapon_attack_bonus,
    has_stealth_disadvantage,
)


# ── Test Helpers ──────────────────────────────────────────────────────


def _make_creature(
    armor_class: int = 10,
    dexterity: int = 10,
    strength: int = 10,
    equipment: list | None = None,
    damage_resistances: list | None = None,
    damage_immunities: list | None = None,
    condition_immunities: list | None = None,
    speed: dict | None = None,
) -> Creature:
    """Create a minimal creature for testing."""
    return Creature(
        name="Test",
        max_hit_points=10,
        armor_class=armor_class,
        ability_scores={"dexterity": dexterity, "strength": strength},
        equipment=equipment or [],
        damage_resistances=damage_resistances or [],
        damage_immunities=damage_immunities or [],
        condition_immunities=condition_immunities or [],
        speed=speed or {"walk": 30},
    )


def _make_wondrous(
    name: str = "Ring of Protection",
    slot: EquipmentSlot = EquipmentSlot.RING_1,
    bonus_ac: int = 0,
    bonus_speed: int = 0,
    bonus_ability_scores: dict | None = None,
    grants_damage_resistances: list | None = None,
    grants_damage_immunities: list | None = None,
    grants_condition_immunities: list | None = None,
) -> Item:
    """Create a wondrous Item for testing passive effects."""
    return Item(
        name=name,
        item_type=ItemType.WONDROUS,
        equipment_slot=slot,
        bonus_ac=bonus_ac,
        bonus_speed=bonus_speed,
        bonus_ability_scores=bonus_ability_scores or {},
        grants_damage_resistances=grants_damage_resistances or [],
        grants_damage_immunities=grants_damage_immunities or [],
        grants_condition_immunities=grants_condition_immunities or [],
    )


def _make_armor(
    name: str = "Leather Armor",
    armor_class: int = 11,
    armor_type: str = "light",
    magic_bonus: int = 0,
    max_dex_bonus: int | None = None,
    stealth_disadvantage: bool = False,
    slot: EquipmentSlot = EquipmentSlot.ARMOR,
) -> Item:
    """Create an armor Item for testing."""
    return Item(
        name=name,
        item_type=ItemType.ARMOR,
        equipment_slot=slot,
        armor_class=armor_class,
        armor_type=armor_type,
        magic_bonus=magic_bonus,
        max_dex_bonus=max_dex_bonus,
        stealth_disadvantage=stealth_disadvantage,
    )


def _make_shield(
    name: str = "Shield",
    magic_bonus: int = 0,
    armor_class: int | None = None,
    slot: EquipmentSlot = EquipmentSlot.OFF_HAND,
) -> Item:
    """Create a shield Item for testing."""
    return Item(
        name=name,
        item_type=ItemType.SHIELD,
        equipment_slot=slot,
        magic_bonus=magic_bonus,
        armor_class=armor_class,
    )


def _make_weapon(
    name: str = "Longsword",
    magic_bonus: int = 0,
    slot: EquipmentSlot = EquipmentSlot.MAIN_HAND,
) -> Item:
    """Create a weapon Item for testing."""
    return Item(
        name=name,
        item_type=ItemType.WEAPON,
        equipment_slot=slot,
        damage_dice="1d8",
        damage_type="slashing",
        magic_bonus=magic_bonus,
    )


# ── TestGetEquippedArmor ─────────────────────────────────────────────


class TestGetEquippedArmor:
    """Tests for get_equipped_armor()."""

    def test_no_equipment_returns_none(self):
        creature = _make_creature()
        assert get_equipped_armor(creature) is None

    def test_non_armor_items_returns_none(self):
        weapon = _make_weapon()
        creature = _make_creature(equipment=[weapon])
        assert get_equipped_armor(creature) is None

    def test_finds_armor_in_armor_slot(self):
        armor = _make_armor(name="Chain Mail", armor_class=16, armor_type="heavy")
        creature = _make_creature(equipment=[armor])
        result = get_equipped_armor(creature)
        assert result is not None
        assert result.name == "Chain Mail"

    def test_ignores_armor_not_in_armor_slot(self):
        """Armor with slot=NONE (unequipped/carried) should not count."""
        armor = _make_armor(name="Spare Armor", slot=EquipmentSlot.NONE)
        creature = _make_creature(equipment=[armor])
        assert get_equipped_armor(creature) is None

    def test_finds_armor_among_mixed_equipment(self):
        weapon = _make_weapon()
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        shield = _make_shield()
        creature = _make_creature(equipment=[weapon, armor, shield])
        result = get_equipped_armor(creature)
        assert result is not None
        assert result.name == "Plate"


# ── TestGetEquippedShield ────────────────────────────────────────────


class TestGetEquippedShield:
    """Tests for get_equipped_shield()."""

    def test_no_equipment_returns_none(self):
        creature = _make_creature()
        assert get_equipped_shield(creature) is None

    def test_finds_shield_in_off_hand(self):
        shield = _make_shield(name="Iron Shield")
        creature = _make_creature(equipment=[shield])
        result = get_equipped_shield(creature)
        assert result is not None
        assert result.name == "Iron Shield"

    def test_ignores_shield_not_in_off_hand(self):
        shield = _make_shield(name="Stowed Shield", slot=EquipmentSlot.NONE)
        creature = _make_creature(equipment=[shield])
        assert get_equipped_shield(creature) is None

    def test_weapon_in_off_hand_not_a_shield(self):
        """A weapon in off_hand should not be detected as a shield."""
        weapon = _make_weapon(name="Dagger", slot=EquipmentSlot.OFF_HAND)
        creature = _make_creature(equipment=[weapon])
        assert get_equipped_shield(creature) is None


# ── TestGetEffectiveArmorClass ───────────────────────────────────────


class TestGetEffectiveArmorClass:
    """Tests for get_effective_armor_class()."""

    def test_empty_equipment_returns_stored_ac(self):
        """Backward compat: no equipment → stored armor_class value."""
        creature = _make_creature(armor_class=18)
        assert get_effective_armor_class(creature) == 18

    def test_no_armor_unarmored_10_plus_dex(self):
        """Equipment present but no armor → unarmored AC = 10 + DEX mod."""
        weapon = _make_weapon()
        # DEX 14 → modifier +2 → AC = 12
        creature = _make_creature(dexterity=14, equipment=[weapon])
        assert get_effective_armor_class(creature) == 12

    def test_no_armor_negative_dex(self):
        """Unarmored with negative DEX modifier."""
        weapon = _make_weapon()
        # DEX 8 → modifier -1 → AC = 9
        creature = _make_creature(dexterity=8, equipment=[weapon])
        assert get_effective_armor_class(creature) == 9

    # ── Light Armor ──

    def test_light_armor_base_plus_dex(self):
        """Light armor: base + DEX mod."""
        # Leather: base 11, DEX 14 (+2) → AC = 13
        armor = _make_armor(name="Leather", armor_class=11, armor_type="light")
        creature = _make_creature(dexterity=14, equipment=[armor])
        assert get_effective_armor_class(creature) == 13

    def test_light_armor_studded_leather(self):
        """Studded leather: base 12, DEX 16 (+3) → AC = 15."""
        armor = _make_armor(name="Studded Leather", armor_class=12, armor_type="light")
        creature = _make_creature(dexterity=16, equipment=[armor])
        assert get_effective_armor_class(creature) == 15

    def test_light_armor_with_magic_bonus(self):
        """+1 Leather: base 11 + DEX 14 (+2) + magic 1 → AC = 14."""
        armor = _make_armor(
            name="+1 Leather", armor_class=11, armor_type="light", magic_bonus=1
        )
        creature = _make_creature(dexterity=14, equipment=[armor])
        assert get_effective_armor_class(creature) == 14

    # ── Medium Armor ──

    def test_medium_armor_caps_dex_at_2(self):
        """Medium armor: DEX mod capped at 2 (default)."""
        # Chain Shirt: base 13, DEX 18 (+4) capped to +2 → AC = 15
        armor = _make_armor(
            name="Chain Shirt", armor_class=13, armor_type="medium", max_dex_bonus=2
        )
        creature = _make_creature(dexterity=18, equipment=[armor])
        assert get_effective_armor_class(creature) == 15

    def test_medium_armor_dex_below_cap(self):
        """Medium armor: DEX below cap uses actual DEX mod."""
        # Chain Shirt: base 13, DEX 12 (+1) → AC = 14
        armor = _make_armor(
            name="Chain Shirt", armor_class=13, armor_type="medium", max_dex_bonus=2
        )
        creature = _make_creature(dexterity=12, equipment=[armor])
        assert get_effective_armor_class(creature) == 14

    def test_medium_armor_default_cap(self):
        """Medium armor with no explicit max_dex_bonus defaults to 2."""
        armor = _make_armor(
            name="Breastplate", armor_class=14, armor_type="medium", max_dex_bonus=None
        )
        creature = _make_creature(dexterity=20, equipment=[armor])
        # base 14 + min(5, 2) = 16
        assert get_effective_armor_class(creature) == 16

    def test_medium_armor_with_magic_bonus(self):
        """+1 Half Plate: base 15, DEX 14 (+2, capped at 2), magic 1 → AC = 18."""
        armor = _make_armor(
            name="+1 Half Plate",
            armor_class=15,
            armor_type="medium",
            max_dex_bonus=2,
            magic_bonus=1,
        )
        creature = _make_creature(dexterity=14, equipment=[armor])
        assert get_effective_armor_class(creature) == 18

    # ── Heavy Armor ──

    def test_heavy_armor_no_dex(self):
        """Heavy armor: no DEX mod at all."""
        # Plate: base 18, DEX 16 (ignored) → AC = 18
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        creature = _make_creature(dexterity=16, equipment=[armor])
        assert get_effective_armor_class(creature) == 18

    def test_heavy_armor_chain_mail(self):
        """Chain Mail: base 16 → AC = 16."""
        armor = _make_armor(name="Chain Mail", armor_class=16, armor_type="heavy")
        creature = _make_creature(dexterity=8, equipment=[armor])
        assert get_effective_armor_class(creature) == 16

    def test_heavy_armor_with_magic_bonus(self):
        """+2 Plate: base 18 + magic 2 → AC = 20."""
        armor = _make_armor(
            name="+2 Plate", armor_class=18, armor_type="heavy", magic_bonus=2
        )
        creature = _make_creature(dexterity=10, equipment=[armor])
        assert get_effective_armor_class(creature) == 20

    # ── Shield ──

    def test_shield_adds_2(self):
        """Shield adds 2 to unarmored AC."""
        shield = _make_shield()
        weapon = _make_weapon()
        # Unarmored: 10 + DEX 12 (+1) = 11, + shield 2 = 13
        creature = _make_creature(dexterity=12, equipment=[weapon, shield])
        assert get_effective_armor_class(creature) == 13

    def test_shield_with_magic_bonus(self):
        """+1 Shield: 2 + 1 = 3 bonus."""
        shield = _make_shield(name="+1 Shield", magic_bonus=1)
        weapon = _make_weapon()
        # Unarmored: 10 + DEX 10 (0) = 10, + shield (2+1) = 13
        creature = _make_creature(dexterity=10, equipment=[weapon, shield])
        assert get_effective_armor_class(creature) == 13

    def test_shield_with_explicit_ac(self):
        """Shield with explicit armor_class field (non-standard)."""
        shield = _make_shield(name="Tower Shield", armor_class=3)
        weapon = _make_weapon()
        # Unarmored: 10 + DEX 10 (0) = 10, + shield 3 + 0 magic = 13
        creature = _make_creature(dexterity=10, equipment=[weapon, shield])
        assert get_effective_armor_class(creature) == 13

    # ── Combinations ──

    def test_light_armor_plus_shield(self):
        """Leather (11) + DEX 14 (+2) + Shield (2) = 15."""
        armor = _make_armor(name="Leather", armor_class=11, armor_type="light")
        shield = _make_shield()
        creature = _make_creature(dexterity=14, equipment=[armor, shield])
        assert get_effective_armor_class(creature) == 15

    def test_heavy_armor_plus_shield(self):
        """Plate (18) + Shield (2) = 20."""
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        shield = _make_shield()
        creature = _make_creature(dexterity=16, equipment=[armor, shield])
        assert get_effective_armor_class(creature) == 20

    def test_magic_armor_plus_magic_shield(self):
        """+1 Plate (18+1) + +2 Shield (2+2) = 23."""
        armor = _make_armor(
            name="+1 Plate", armor_class=18, armor_type="heavy", magic_bonus=1
        )
        shield = _make_shield(name="+2 Shield", magic_bonus=2)
        creature = _make_creature(equipment=[armor, shield])
        assert get_effective_armor_class(creature) == 23

    def test_unequipped_shield_not_counted(self):
        """Shield with slot=NONE should not add to AC."""
        armor = _make_armor(name="Leather", armor_class=11, armor_type="light")
        shield = _make_shield(name="Stowed Shield", slot=EquipmentSlot.NONE)
        # Leather + DEX 10 (0) = 11, no shield
        creature = _make_creature(dexterity=10, equipment=[armor, shield])
        assert get_effective_armor_class(creature) == 11


# ── TestGetWeaponMagicBonus ──────────────────────────────────────────


class TestGetWeaponMagicBonus:
    """Tests for get_weapon_magic_bonus()."""

    def test_no_equipment_returns_0(self):
        creature = _make_creature()
        assert get_weapon_magic_bonus(creature, "Longsword") == 0

    def test_matching_weapon_returns_bonus(self):
        weapon = _make_weapon(name="Longsword", magic_bonus=2)
        creature = _make_creature(equipment=[weapon])
        assert get_weapon_magic_bonus(creature, "Longsword") == 2

    def test_no_matching_name_returns_0(self):
        weapon = _make_weapon(name="Longsword", magic_bonus=2)
        creature = _make_creature(equipment=[weapon])
        assert get_weapon_magic_bonus(creature, "Greatsword") == 0

    def test_non_weapon_same_name_returns_0(self):
        """A non-weapon item with the same name should not match."""
        potion = Item(name="Longsword", item_type=ItemType.POTION)
        creature = _make_creature(equipment=[potion])
        assert get_weapon_magic_bonus(creature, "Longsword") == 0

    def test_non_magic_weapon_returns_0(self):
        weapon = _make_weapon(name="Shortsword", magic_bonus=0)
        creature = _make_creature(equipment=[weapon])
        assert get_weapon_magic_bonus(creature, "Shortsword") == 0


# ── TestGetWeaponAttackBonus ─────────────────────────────────────────


class TestGetWeaponAttackBonus:
    """Tests for get_weapon_attack_bonus()."""

    def test_none_source_returns_0(self):
        creature = _make_creature()
        assert get_weapon_attack_bonus(creature, None) == 0

    def test_matching_magic_weapon(self):
        weapon = _make_weapon(name="Flame Tongue", magic_bonus=1)
        creature = _make_creature(equipment=[weapon])
        assert get_weapon_attack_bonus(creature, "Flame Tongue") == 1

    def test_no_match_returns_0(self):
        weapon = _make_weapon(name="Longsword", magic_bonus=2)
        creature = _make_creature(equipment=[weapon])
        assert get_weapon_attack_bonus(creature, "Mace") == 0

    def test_plus_3_weapon(self):
        weapon = _make_weapon(name="+3 Longsword", magic_bonus=3)
        creature = _make_creature(equipment=[weapon])
        assert get_weapon_attack_bonus(creature, "+3 Longsword") == 3


# ── TestHasStealthDisadvantage ───────────────────────────────────────


class TestHasStealthDisadvantage:
    """Tests for has_stealth_disadvantage()."""

    def test_no_armor_returns_false(self):
        creature = _make_creature()
        assert has_stealth_disadvantage(creature) is False

    def test_light_armor_no_disadvantage(self):
        armor = _make_armor(
            name="Leather", armor_type="light", stealth_disadvantage=False
        )
        creature = _make_creature(equipment=[armor])
        assert has_stealth_disadvantage(creature) is False

    def test_chain_mail_has_disadvantage(self):
        armor = _make_armor(
            name="Chain Mail",
            armor_class=16,
            armor_type="heavy",
            stealth_disadvantage=True,
        )
        creature = _make_creature(equipment=[armor])
        assert has_stealth_disadvantage(creature) is True

    def test_half_plate_has_disadvantage(self):
        armor = _make_armor(
            name="Half Plate",
            armor_class=15,
            armor_type="medium",
            stealth_disadvantage=True,
        )
        creature = _make_creature(equipment=[armor])
        assert has_stealth_disadvantage(creature) is True

    def test_unequipped_armor_no_disadvantage(self):
        """Armor in inventory but not equipped should not cause disadvantage."""
        armor = _make_armor(
            name="Chain Mail",
            armor_class=16,
            armor_type="heavy",
            stealth_disadvantage=True,
            slot=EquipmentSlot.NONE,
        )
        creature = _make_creature(equipment=[armor])
        assert has_stealth_disadvantage(creature) is False


# ── TestGetEquippedItems ───────────────────────────────────────────


class TestGetEquippedItems:
    """Tests for _get_equipped_items()."""

    def test_empty_equipment_returns_empty(self):
        creature = _make_creature()
        assert _get_equipped_items(creature) == []

    def test_none_slot_excluded(self):
        item = _make_wondrous(name="Trinket", slot=EquipmentSlot.NONE)
        creature = _make_creature(equipment=[item])
        assert _get_equipped_items(creature) == []

    def test_non_none_slot_included(self):
        ring = _make_wondrous(name="Ring", slot=EquipmentSlot.RING_1)
        creature = _make_creature(equipment=[ring])
        result = _get_equipped_items(creature)
        assert len(result) == 1
        assert result[0].name == "Ring"

    def test_mixed_equipped_and_carried(self):
        ring = _make_wondrous(name="Ring", slot=EquipmentSlot.RING_1)
        trinket = _make_wondrous(name="Trinket", slot=EquipmentSlot.NONE)
        weapon = _make_weapon(name="Sword")
        creature = _make_creature(equipment=[ring, trinket, weapon])
        result = _get_equipped_items(creature)
        assert len(result) == 2
        names = {i.name for i in result}
        assert names == {"Ring", "Sword"}


# ── TestGetEffectiveAbilityScore ───────────────────────────────────


class TestGetEffectiveAbilityScore:
    """Tests for get_effective_ability_score()."""

    def test_no_equipment_returns_base(self):
        creature = _make_creature(strength=14)
        assert get_effective_ability_score(creature, "strength") == 14

    def test_single_item_bonus(self):
        gauntlets = _make_wondrous(
            name="Gauntlets of Ogre Power",
            slot=EquipmentSlot.GLOVES,
            bonus_ability_scores={"strength": 4},
        )
        creature = _make_creature(strength=12, equipment=[gauntlets])
        assert get_effective_ability_score(creature, "strength") == 16

    def test_multiple_items_stack(self):
        belt = _make_wondrous(
            name="Belt of Giant Strength",
            slot=EquipmentSlot.BELT,
            bonus_ability_scores={"strength": 2},
        )
        ring = _make_wondrous(
            name="Ring of Might",
            slot=EquipmentSlot.RING_1,
            bonus_ability_scores={"strength": 1},
        )
        creature = _make_creature(strength=14, equipment=[belt, ring])
        assert get_effective_ability_score(creature, "strength") == 17

    def test_caps_at_30(self):
        belt = _make_wondrous(
            name="Belt of Storm Giant Strength",
            slot=EquipmentSlot.BELT,
            bonus_ability_scores={"strength": 10},
        )
        creature = _make_creature(strength=25, equipment=[belt])
        assert get_effective_ability_score(creature, "strength") == 30

    def test_unequipped_item_not_counted(self):
        gauntlets = _make_wondrous(
            name="Gauntlets",
            slot=EquipmentSlot.NONE,
            bonus_ability_scores={"strength": 4},
        )
        creature = _make_creature(strength=10, equipment=[gauntlets])
        assert get_effective_ability_score(creature, "strength") == 10

    def test_different_ability_not_affected(self):
        """STR bonus should not affect DEX."""
        gauntlets = _make_wondrous(
            name="Gauntlets",
            slot=EquipmentSlot.GLOVES,
            bonus_ability_scores={"strength": 4},
        )
        creature = _make_creature(dexterity=14, equipment=[gauntlets])
        assert get_effective_ability_score(creature, "dexterity") == 14


# ── TestGetEffectiveAbilityModifier ────────────────────────────────


class TestGetEffectiveAbilityModifier:
    """Tests for get_effective_ability_modifier()."""

    def test_no_equipment_standard_modifier(self):
        creature = _make_creature(strength=14)
        # 14 → mod +2
        assert get_effective_ability_modifier(creature, "strength") == 2

    def test_with_bonus_changes_modifier(self):
        ring = _make_wondrous(
            name="Ring of STR",
            slot=EquipmentSlot.RING_1,
            bonus_ability_scores={"strength": 2},
        )
        creature = _make_creature(strength=14, equipment=[ring])
        # 14 + 2 = 16 → mod +3
        assert get_effective_ability_modifier(creature, "strength") == 3

    def test_odd_score_rounds_down(self):
        ring = _make_wondrous(
            name="Ring of STR",
            slot=EquipmentSlot.RING_1,
            bonus_ability_scores={"strength": 1},
        )
        creature = _make_creature(strength=14, equipment=[ring])
        # 14 + 1 = 15 → mod +2 (rounds down)
        assert get_effective_ability_modifier(creature, "strength") == 2


# ── TestGetEffectiveSpeed ──────────────────────────────────────────


class TestGetEffectiveSpeed:
    """Tests for get_effective_speed()."""

    def test_no_equipment_returns_base(self):
        creature = _make_creature(speed={"walk": 30})
        assert get_effective_speed(creature) == 30

    def test_single_item_bonus(self):
        boots = _make_wondrous(
            name="Boots of Speed",
            slot=EquipmentSlot.BOOTS,
            bonus_speed=10,
        )
        creature = _make_creature(speed={"walk": 30}, equipment=[boots])
        assert get_effective_speed(creature) == 40

    def test_multiple_items_stack(self):
        boots = _make_wondrous(
            name="Boots of Speed",
            slot=EquipmentSlot.BOOTS,
            bonus_speed=10,
        )
        cloak = _make_wondrous(
            name="Cloak of Swiftness",
            slot=EquipmentSlot.CLOAK,
            bonus_speed=5,
        )
        creature = _make_creature(speed={"walk": 30}, equipment=[boots, cloak])
        assert get_effective_speed(creature) == 45

    def test_minimum_zero(self):
        cursed = _make_wondrous(
            name="Cursed Boots",
            slot=EquipmentSlot.BOOTS,
            bonus_speed=-50,
        )
        creature = _make_creature(speed={"walk": 30}, equipment=[cursed])
        assert get_effective_speed(creature) == 0

    def test_unequipped_item_not_counted(self):
        boots = _make_wondrous(
            name="Boots of Speed",
            slot=EquipmentSlot.NONE,
            bonus_speed=10,
        )
        creature = _make_creature(speed={"walk": 30}, equipment=[boots])
        assert get_effective_speed(creature) == 30


# ── TestGetEffectiveDamageResistances ──────────────────────────────


class TestGetEffectiveDamageResistances:
    """Tests for get_effective_damage_resistances()."""

    def test_no_equipment_returns_base(self):
        creature = _make_creature(damage_resistances=["fire"])
        assert get_effective_damage_resistances(creature) == ["fire"]

    def test_equipment_adds_resistances(self):
        ring = _make_wondrous(
            name="Ring of Fire Resistance",
            slot=EquipmentSlot.RING_1,
            grants_damage_resistances=["fire"],
        )
        creature = _make_creature(equipment=[ring])
        assert get_effective_damage_resistances(creature) == ["fire"]

    def test_deduplication(self):
        ring = _make_wondrous(
            name="Ring of Fire Resistance",
            slot=EquipmentSlot.RING_1,
            grants_damage_resistances=["fire"],
        )
        creature = _make_creature(
            damage_resistances=["fire"],
            equipment=[ring],
        )
        result = get_effective_damage_resistances(creature)
        assert result == ["fire"]

    def test_multiple_items_different_types(self):
        ring1 = _make_wondrous(
            name="Ring of Fire Res",
            slot=EquipmentSlot.RING_1,
            grants_damage_resistances=["fire"],
        )
        ring2 = _make_wondrous(
            name="Ring of Cold Res",
            slot=EquipmentSlot.RING_2,
            grants_damage_resistances=["cold"],
        )
        creature = _make_creature(equipment=[ring1, ring2])
        result = get_effective_damage_resistances(creature)
        assert "fire" in result
        assert "cold" in result
        assert len(result) == 2

    def test_unequipped_item_not_counted(self):
        ring = _make_wondrous(
            name="Ring of Fire Res",
            slot=EquipmentSlot.NONE,
            grants_damage_resistances=["fire"],
        )
        creature = _make_creature(equipment=[ring])
        assert get_effective_damage_resistances(creature) == []


# ── TestGetEffectiveDamageImmunities ───────────────────────────────


class TestGetEffectiveDamageImmunities:
    """Tests for get_effective_damage_immunities()."""

    def test_no_equipment_returns_base(self):
        creature = _make_creature(damage_immunities=["poison"])
        assert get_effective_damage_immunities(creature) == ["poison"]

    def test_equipment_adds_immunities(self):
        amulet = _make_wondrous(
            name="Amulet of Poison Immunity",
            slot=EquipmentSlot.AMULET,
            grants_damage_immunities=["poison"],
        )
        creature = _make_creature(equipment=[amulet])
        assert get_effective_damage_immunities(creature) == ["poison"]

    def test_deduplication(self):
        amulet = _make_wondrous(
            name="Amulet of Poison Immunity",
            slot=EquipmentSlot.AMULET,
            grants_damage_immunities=["poison"],
        )
        creature = _make_creature(
            damage_immunities=["poison"],
            equipment=[amulet],
        )
        result = get_effective_damage_immunities(creature)
        assert result == ["poison"]

    def test_unequipped_item_not_counted(self):
        amulet = _make_wondrous(
            name="Amulet",
            slot=EquipmentSlot.NONE,
            grants_damage_immunities=["poison"],
        )
        creature = _make_creature(equipment=[amulet])
        assert get_effective_damage_immunities(creature) == []


# ── TestGetEffectiveConditionImmunities ────────────────────────────


class TestGetEffectiveConditionImmunities:
    """Tests for get_effective_condition_immunities()."""

    def test_no_equipment_returns_base(self):
        creature = _make_creature(condition_immunities=["poisoned"])
        assert get_effective_condition_immunities(creature) == ["poisoned"]

    def test_equipment_adds_condition_immunity(self):
        ring = _make_wondrous(
            name="Ring of Free Action",
            slot=EquipmentSlot.RING_1,
            grants_condition_immunities=["paralyzed"],
        )
        creature = _make_creature(equipment=[ring])
        assert get_effective_condition_immunities(creature) == ["paralyzed"]

    def test_deduplication(self):
        ring = _make_wondrous(
            name="Ring of Free Action",
            slot=EquipmentSlot.RING_1,
            grants_condition_immunities=["poisoned"],
        )
        creature = _make_creature(
            condition_immunities=["poisoned"],
            equipment=[ring],
        )
        result = get_effective_condition_immunities(creature)
        assert result == ["poisoned"]

    def test_multiple_items_stack(self):
        ring = _make_wondrous(
            name="Ring of Free Action",
            slot=EquipmentSlot.RING_1,
            grants_condition_immunities=["paralyzed"],
        )
        cloak = _make_wondrous(
            name="Cloak of Purity",
            slot=EquipmentSlot.CLOAK,
            grants_condition_immunities=["poisoned"],
        )
        creature = _make_creature(equipment=[ring, cloak])
        result = get_effective_condition_immunities(creature)
        assert "paralyzed" in result
        assert "poisoned" in result
        assert len(result) == 2

    def test_unequipped_item_not_counted(self):
        ring = _make_wondrous(
            name="Ring",
            slot=EquipmentSlot.NONE,
            grants_condition_immunities=["poisoned"],
        )
        creature = _make_creature(equipment=[ring])
        assert get_effective_condition_immunities(creature) == []


# ── TestGetPassiveAcBonus ──────────────────────────────────────────


class TestGetPassiveAcBonus:
    """Tests for get_passive_ac_bonus()."""

    def test_no_equipment_returns_0(self):
        creature = _make_creature()
        assert get_passive_ac_bonus(creature) == 0

    def test_single_item(self):
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=1,
        )
        creature = _make_creature(equipment=[ring])
        assert get_passive_ac_bonus(creature) == 1

    def test_multiple_items_stack(self):
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=1,
        )
        cloak = _make_wondrous(
            name="Cloak of Protection",
            slot=EquipmentSlot.CLOAK,
            bonus_ac=1,
        )
        creature = _make_creature(equipment=[ring, cloak])
        assert get_passive_ac_bonus(creature) == 2

    def test_unequipped_item_not_counted(self):
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.NONE,
            bonus_ac=1,
        )
        creature = _make_creature(equipment=[ring])
        assert get_passive_ac_bonus(creature) == 0


# ── TestEffectiveArmorClassWithPassiveBonus ────────────────────────


class TestEffectiveArmorClassWithPassiveBonus:
    """Tests that passive AC bonus integrates with armor AC calculation."""

    def test_light_armor_plus_ring_of_protection(self):
        armor = _make_armor(name="Leather", armor_class=11, armor_type="light")
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=1,
        )
        # Leather (11) + DEX 14 (+2) + Ring (+1) = 14
        creature = _make_creature(dexterity=14, equipment=[armor, ring])
        assert get_effective_armor_class(creature) == 14

    def test_heavy_armor_shield_plus_cloak(self):
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        shield = _make_shield()
        cloak = _make_wondrous(
            name="Cloak of Protection",
            slot=EquipmentSlot.CLOAK,
            bonus_ac=1,
        )
        # Plate (18) + Shield (2) + Cloak (+1) = 21
        creature = _make_creature(equipment=[armor, shield, cloak])
        assert get_effective_armor_class(creature) == 21

    def test_backward_compat_no_equipment(self):
        """Empty equipment still returns stored AC (no passive bonus)."""
        creature = _make_creature(armor_class=15)
        assert get_effective_armor_class(creature) == 15

    def test_dex_bonus_from_equipped_item_affects_ac(self):
        """An item granting DEX bonus should affect unarmored AC."""
        ring = _make_wondrous(
            name="Ring of Dexterity",
            slot=EquipmentSlot.RING_1,
            bonus_ability_scores={"dexterity": 4},
        )
        # Base DEX 10 (+0), item gives +4 → effective DEX 14 (+2)
        # Unarmored: 10 + 2 = 12
        creature = _make_creature(dexterity=10, equipment=[ring])
        assert get_effective_armor_class(creature) == 12


# ── Feature Integration Tests ────────────────────────────────────────

from arena.models.character import PlayerCharacter, Feature
from arena.combat.stat_modifiers import (
    get_initiative_bonus,
    get_effective_saving_throw_proficiencies,
    get_ac_breakdown,
    get_speed_breakdown,
    get_ability_score_breakdown,
)


def _make_pc(
    armor_class: int = 10,
    dexterity: int = 10,
    wisdom: int = 10,
    constitution: int = 10,
    strength: int = 10,
    equipment: list | None = None,
    features: list | None = None,
    feats: list | None = None,
    speed: dict | None = None,
) -> PlayerCharacter:
    """Create a minimal PlayerCharacter for feature testing."""
    return PlayerCharacter(
        name="TestPC",
        max_hit_points=10,
        armor_class=armor_class,
        ability_scores={
            "dexterity": dexterity,
            "wisdom": wisdom,
            "constitution": constitution,
            "strength": strength,
        },
        equipment=equipment or [],
        features=features or [],
        feats=feats or [],
        speed=speed or {"walk": 30},
        character_class="Fighter",
        level=5,
    )


class TestFeatureAC:
    """Tests for Feature passive AC bonus integration."""

    def test_feature_bonus_ac(self):
        """Feature with bonus_ac should add to AC."""
        feat = Feature(
            name="Fighting Style: Defense",
            description="+1 AC",
            bonus_ac=1,
        )
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        pc = _make_pc(equipment=[armor], features=[feat])
        # Plate (18) + feature (+1) = 19
        assert get_effective_armor_class(pc) == 19

    def test_feature_bonus_ac_stacks_with_equipment(self):
        """Feature AC bonus stacks with equipment passive AC bonus."""
        feat = Feature(name="Defense", description="", bonus_ac=1)
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=2,
        )
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        pc = _make_pc(equipment=[armor, ring], features=[feat])
        # Plate (18) + Ring (+2) + Feature (+1) = 21
        assert get_effective_armor_class(pc) == 21


class TestUnarmoredDefense:
    """Tests for Unarmored Defense via Feature model."""

    def test_monk_unarmored_defense(self):
        """Monk: 10 + DEX + WIS."""
        feat = Feature(
            name="Unarmored Defense",
            description="",
            unarmored_defense="monk",
        )
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=2,
        )
        # DEX 18 (+4), WIS 16 (+3) → 10 + 4 + 3 = 17 + 2 ring = 19
        pc = _make_pc(
            dexterity=18, wisdom=16,
            equipment=[ring], features=[feat],
        )
        assert get_effective_armor_class(pc) == 19

    def test_barbarian_unarmored_defense(self):
        """Barbarian: 10 + DEX + CON."""
        feat = Feature(
            name="Unarmored Defense",
            description="",
            unarmored_defense="barbarian",
        )
        # Need some equipment to avoid backward compat path
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=0,
        )
        # DEX 14 (+2), CON 16 (+3) → 10 + 2 + 3 = 15
        pc = _make_pc(
            dexterity=14, constitution=16,
            equipment=[ring], features=[feat],
        )
        assert get_effective_armor_class(pc) == 15

    def test_unarmored_defense_ignored_when_wearing_armor(self):
        """Unarmored Defense doesn't apply when armor is equipped."""
        feat = Feature(
            name="Unarmored Defense",
            description="",
            unarmored_defense="monk",
        )
        armor = _make_armor(name="Leather", armor_class=11, armor_type="light")
        # DEX 18 (+4), WIS 16 (+3)
        # Leather with armor: 11 + DEX(4) = 15 (not 10+4+3=17)
        pc = _make_pc(
            dexterity=18, wisdom=16,
            equipment=[armor], features=[feat],
        )
        assert get_effective_armor_class(pc) == 15

    def test_no_unarmored_defense_standard_calc(self):
        """Without Unarmored Defense feature, standard unarmored calc."""
        ring = _make_wondrous(
            name="Ring",
            slot=EquipmentSlot.RING_1,
            bonus_ac=0,
        )
        # DEX 14 (+2) → 10 + 2 = 12
        pc = _make_pc(dexterity=14, equipment=[ring])
        assert get_effective_armor_class(pc) == 12


class TestFeatureSpeed:
    """Tests for Feature speed bonus integration."""

    def test_feature_bonus_speed(self):
        """Feature with bonus_speed should add to speed."""
        feat = Feature(
            name="Unarmored Movement",
            description="",
            bonus_speed=10,
        )
        pc = _make_pc(speed={"walk": 30}, features=[feat])
        assert get_effective_speed(pc) == 40

    def test_feature_speed_stacks_with_equipment(self):
        """Feature speed bonus stacks with equipment speed bonus."""
        feat = Feature(
            name="Unarmored Movement",
            description="",
            bonus_speed=10,
        )
        boots = _make_wondrous(
            name="Boots of Speed",
            slot=EquipmentSlot.BOOTS,
            bonus_speed=10,
        )
        pc = _make_pc(
            speed={"walk": 30},
            equipment=[boots], features=[feat],
        )
        assert get_effective_speed(pc) == 50


class TestFeatureAbilityScore:
    """Tests for Feature ability score bonus integration."""

    def test_feature_bonus_ability(self):
        """Feature with bonus_ability_scores should add to score."""
        feat = Feature(
            name="ASI",
            description="",
            bonus_ability_scores={"strength": 2},
        )
        pc = _make_pc(strength=16, features=[feat])
        assert get_effective_ability_score(pc, "strength") == 18

    def test_feature_ability_stacks_with_equipment(self):
        """Feature ability bonus stacks with equipment ability bonus."""
        feat = Feature(
            name="ASI",
            description="",
            bonus_ability_scores={"strength": 2},
        )
        gauntlets = _make_wondrous(
            name="Gauntlets",
            slot=EquipmentSlot.GLOVES,
            bonus_ability_scores={"strength": 2},
        )
        pc = _make_pc(strength=14, equipment=[gauntlets], features=[feat])
        # 14 + 2 + 2 = 18
        assert get_effective_ability_score(pc, "strength") == 18


class TestFeatureConditionImmunities:
    """Tests for Feature condition immunity integration."""

    def test_feature_grants_condition_immunity(self):
        """Feature granting condition immunity should appear in effective list."""
        feat = Feature(
            name="Divine Health",
            description="",
            grants_condition_immunities=["diseased"],
        )
        pc = _make_pc(features=[feat])
        result = get_effective_condition_immunities(pc)
        assert "diseased" in result


class TestFeatureInitiative:
    """Tests for Feature initiative bonus integration."""

    def test_feature_bonus_initiative(self):
        """Feature with bonus_initiative should add to initiative."""
        feat = Feature(
            name="Custom Init",
            description="",
            bonus_initiative=3,
        )
        pc = _make_pc(features=[feat])
        assert get_initiative_bonus(pc) == 3


class TestFeatureSavingThrows:
    """Tests for Feature saving throw proficiency integration."""

    def test_feature_grants_saving_throw(self):
        feat = Feature(
            name="Resilient",
            description="",
            grants_saving_throw_proficiencies=["constitution"],
        )
        pc = _make_pc(features=[feat])
        result = get_effective_saving_throw_proficiencies(pc)
        assert "constitution" in result


# ── Breakdown Function Tests ──────────────────────────────────────────


class TestACBreakdown:
    """Tests for get_ac_breakdown()."""

    def test_no_equipment_shows_stored(self):
        creature = _make_creature(armor_class=15)
        breakdown = get_ac_breakdown(creature)
        assert len(breakdown) == 1
        assert breakdown[0] == ("Stored AC", "15")

    def test_heavy_armor_breakdown(self):
        armor = _make_armor(name="Plate", armor_class=18, armor_type="heavy")
        shield = _make_shield()
        creature = _make_creature(equipment=[armor, shield])
        breakdown = get_ac_breakdown(creature)
        labels = [label for label, _ in breakdown]
        assert "Plate" in labels
        assert "Shield" in labels
        assert "Total" in labels
        # Total should be 18 + 2 = 20
        total_line = [v for l, v in breakdown if l == "Total"][0]
        assert total_line == "20"

    def test_monk_unarmored_breakdown(self):
        feat = Feature(
            name="Unarmored Defense",
            description="",
            unarmored_defense="monk",
        )
        ring = _make_wondrous(
            name="Ring of Protection",
            slot=EquipmentSlot.RING_1,
            bonus_ac=2,
        )
        pc = _make_pc(dexterity=18, wisdom=16, equipment=[ring], features=[feat])
        breakdown = get_ac_breakdown(pc)
        labels = [label for label, _ in breakdown]
        assert any("Monk" in l for l in labels)
        assert "Ring of Protection" in labels
        total_line = [v for l, v in breakdown if l == "Total"][0]
        assert total_line == "19"


class TestSpeedBreakdown:
    """Tests for get_speed_breakdown()."""

    def test_base_speed_only(self):
        creature = _make_creature(speed={"walk": 30})
        breakdown = get_speed_breakdown(creature)
        assert breakdown[0] == ("Base", "30 ft")
        assert breakdown[-1] == ("Total", "30 ft")

    def test_speed_with_feature(self):
        feat = Feature(
            name="Unarmored Movement",
            description="",
            bonus_speed=10,
        )
        pc = _make_pc(speed={"walk": 30}, features=[feat])
        breakdown = get_speed_breakdown(pc)
        labels = [label for label, _ in breakdown]
        assert "Unarmored Movement" in labels
        total_line = [v for l, v in breakdown if l == "Total"][0]
        assert total_line == "40 ft"


class TestAbilityScoreBreakdown:
    """Tests for get_ability_score_breakdown()."""

    def test_base_only(self):
        creature = _make_creature(strength=16)
        breakdown = get_ability_score_breakdown(creature, "strength")
        assert breakdown[0] == ("Base", "16")
        assert breakdown[-1] == ("Total", "16 (+3)")

    def test_with_feature_bonus(self):
        feat = Feature(
            name="ASI",
            description="",
            bonus_ability_scores={"strength": 2},
        )
        pc = _make_pc(strength=16, features=[feat])
        breakdown = get_ability_score_breakdown(pc, "strength")
        labels = [label for label, _ in breakdown]
        assert "ASI" in labels
        assert breakdown[-1] == ("Total", "18 (+4)")
