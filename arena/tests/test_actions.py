"""Tests for action models."""

import pytest
from arena.models.actions import (
    Action,
    ActionType,
    TargetType,
    DamageType,
    DamageRoll,
    Attack,
    SavingThrowEffect,
)


class TestDamageRoll:
    """Tests for the DamageRoll model."""

    def test_basic_damage_roll(self):
        """Basic damage roll creation."""
        dmg = DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)
        assert dmg.dice == "1d8"
        assert dmg.damage_type == DamageType.SLASHING
        assert dmg.bonus == 0
        assert dmg.ability_modifier is None

    def test_damage_roll_with_modifier(self):
        """Damage roll with ability modifier."""
        dmg = DamageRoll(
            dice="2d6",
            damage_type=DamageType.FIRE,
            ability_modifier="dexterity",
        )
        assert dmg.ability_modifier == "dexterity"

    def test_damage_roll_with_bonus(self):
        """Damage roll with flat bonus."""
        dmg = DamageRoll(
            dice="1d6",
            damage_type=DamageType.PIERCING,
            bonus=2,
        )
        assert dmg.bonus == 2


class TestAttack:
    """Tests for the Attack model."""

    def test_melee_attack(self):
        """Melee weapon attack creation."""
        attack = Attack(
            name="Longsword",
            attack_type="melee_weapon",
            ability="strength",
            reach=5,
            damage=[
                DamageRoll(dice="1d8", damage_type=DamageType.SLASHING, ability_modifier="strength")
            ],
        )
        assert attack.name == "Longsword"
        assert attack.attack_type == "melee_weapon"
        assert attack.reach == 5
        assert len(attack.damage) == 1

    def test_ranged_attack(self):
        """Ranged weapon attack creation."""
        attack = Attack(
            name="Longbow",
            attack_type="ranged_weapon",
            ability="dexterity",
            range_normal=150,
            range_long=600,
            damage=[
                DamageRoll(dice="1d8", damage_type=DamageType.PIERCING, ability_modifier="dexterity")
            ],
        )
        assert attack.range_normal == 150
        assert attack.range_long == 600

    def test_attack_with_extra_effects(self):
        """Attack with additional effects."""
        attack = Attack(
            name="Poisoned Dagger",
            attack_type="melee_weapon",
            ability="dexterity",
            damage=[DamageRoll(dice="1d4", damage_type=DamageType.PIERCING)],
            extra_effects=["Target must make DC 13 CON save or take 2d6 poison damage"],
        )
        assert len(attack.extra_effects) == 1


class TestSavingThrowEffect:
    """Tests for the SavingThrowEffect model."""

    def test_basic_save_effect(self):
        """Basic saving throw effect."""
        effect = SavingThrowEffect(
            ability="dexterity",
            dc=15,
            damage_on_fail=[DamageRoll(dice="8d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        )
        assert effect.ability == "dexterity"
        assert effect.dc == 15
        assert effect.damage_on_success == "half"

    def test_save_with_conditions(self):
        """Saving throw that applies conditions."""
        effect = SavingThrowEffect(
            ability="wisdom",
            dc=14,
            conditions_on_fail=["frightened"],
        )
        assert "frightened" in effect.conditions_on_fail


class TestAction:
    """Tests for the Action model."""

    def test_basic_action(self):
        """Basic action creation."""
        action = Action(
            name="Attack",
            description="Make a melee weapon attack",
            action_type=ActionType.ACTION,
        )
        assert action.name == "Attack"
        assert action.action_type == ActionType.ACTION

    def test_action_with_attack(self):
        """Action containing an attack."""
        action = Action(
            name="Longsword",
            description="Melee weapon attack",
            attack=Attack(
                name="Longsword",
                attack_type="melee_weapon",
                ability="strength",
                damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING)],
            ),
        )
        assert action.attack is not None
        assert action.attack.name == "Longsword"

    def test_bonus_action(self):
        """Bonus action creation."""
        action = Action(
            name="Cunning Action",
            description="Dash, Disengage, or Hide as bonus action",
            action_type=ActionType.BONUS_ACTION,
        )
        assert action.action_type == ActionType.BONUS_ACTION

    def test_reaction(self):
        """Reaction creation."""
        action = Action(
            name="Opportunity Attack",
            description="Attack when enemy leaves reach",
            action_type=ActionType.REACTION,
        )
        assert action.action_type == ActionType.REACTION

    def test_limited_use_action(self):
        """Action with limited uses."""
        action = Action(
            name="Second Wind",
            description="Regain HP",
            uses_per_rest=1,
            rest_type="short",
            healing="1d10+5",
        )
        assert action.uses_per_rest == 1
        assert action.rest_type == "short"
        assert action.healing == "1d10+5"

    def test_action_with_resource_cost(self):
        """Action that costs resources."""
        action = Action(
            name="Flurry of Blows",
            description="Make two unarmed strikes as bonus action",
            action_type=ActionType.BONUS_ACTION,
            resource_cost={"ki_points": 1},
        )
        assert action.resource_cost["ki_points"] == 1

    def test_concentration_action(self):
        """Action requiring concentration."""
        action = Action(
            name="Hold Person",
            description="Paralyze a humanoid",
            requires_concentration=True,
        )
        assert action.requires_concentration is True

    def test_area_action(self):
        """Area of effect action."""
        action = Action(
            name="Fireball",
            description="20-foot radius explosion",
            target_type=TargetType.AREA_SPHERE,
            range=150,
            area_size=20,
        )
        assert action.target_type == TargetType.AREA_SPHERE
        assert action.area_size == 20

    def test_ai_hints(self):
        """AI priority and conditions."""
        action = Action(
            name="Healing Word",
            description="Heal an ally",
            ai_priority=9,
            ai_use_condition="ally.hp_percent < 25",
        )
        assert action.ai_priority == 9
        assert action.ai_use_condition == "ally.hp_percent < 25"


class TestDamageType:
    """Tests for DamageType enum."""

    def test_all_damage_types(self):
        """All 13 damage types should be available."""
        damage_types = [
            "acid", "bludgeoning", "cold", "fire", "force",
            "lightning", "necrotic", "piercing", "poison",
            "psychic", "radiant", "slashing", "thunder",
        ]
        for dt in damage_types:
            assert DamageType(dt) is not None


class TestActionType:
    """Tests for ActionType enum."""

    def test_all_action_types(self):
        """All action types should be available."""
        assert ActionType.ACTION.value == "action"
        assert ActionType.BONUS_ACTION.value == "bonus_action"
        assert ActionType.REACTION.value == "reaction"
        assert ActionType.LEGENDARY.value == "legendary"
        assert ActionType.LAIR.value == "lair"
        assert ActionType.FREE.value == "free"
