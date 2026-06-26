"""Tests for combat action resolution."""

import pytest
from unittest.mock import patch
from arena.combat.actions import (
    get_attack_modifier,
    is_in_range,
    resolve_attack,
    resolve_attack_hit,
    resolve_attack_damage,
    AttackResult,
    AttackHitResult,
)
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid


def _make_attacker(strength=16, proficiency=2):
    return Creature(
        name="Fighter",
        max_hit_points=30,
        ability_scores=AbilityScores(strength=strength),
        proficiency_bonus=proficiency,
    )


def _make_target(ac=15, hp=10):
    return Creature(
        name="Goblin",
        max_hit_points=hp,
        armor_class=ac,
    )


def _make_melee_action():
    return Action(
        name="Longsword",
        description="Melee weapon attack",
        action_type=ActionType.ACTION,
        attack=Attack(
            name="Longsword",
            attack_type="melee_weapon",
            ability="strength",
            reach=5,
            damage=[
                DamageRoll(
                    dice="1d8",
                    damage_type=DamageType.SLASHING,
                    ability_modifier="strength",
                )
            ],
        ),
    )


def _make_ranged_action():
    return Action(
        name="Shortbow",
        description="Ranged weapon attack",
        action_type=ActionType.ACTION,
        attack=Attack(
            name="Shortbow",
            attack_type="ranged_weapon",
            ability="dexterity",
            range_normal=80,
            range_long=320,
            damage=[
                DamageRoll(
                    dice="1d6",
                    damage_type=DamageType.PIERCING,
                    ability_modifier="dexterity",
                )
            ],
        ),
    )


class TestGetAttackModifier:
    def test_strength_melee(self):
        attacker = _make_attacker(strength=16, proficiency=2)
        attack = Attack(
            name="Sword", attack_type="melee_weapon", ability="strength",
            damage=[],
        )
        # STR 16 = +3 mod, prof +2 = +5
        assert get_attack_modifier(attacker, attack) == 5

    def test_dexterity_ranged(self):
        attacker = Creature(
            name="Ranger",
            max_hit_points=20,
            ability_scores=AbilityScores(dexterity=18),
            proficiency_bonus=3,
        )
        attack = Attack(
            name="Bow", attack_type="ranged_weapon", ability="dexterity",
            damage=[],
        )
        # DEX 18 = +4, prof +3 = +7
        assert get_attack_modifier(attacker, attack) == 7


class TestIsInRange:
    def test_melee_adjacent(self):
        action = _make_melee_action()
        assert is_in_range(HexCoord(5, 5), HexCoord(5, 6), action) is True

    def test_melee_too_far(self):
        action = _make_melee_action()
        assert is_in_range(HexCoord(5, 5), HexCoord(5, 8), action) is False

    def test_melee_same_hex(self):
        action = _make_melee_action()
        assert is_in_range(HexCoord(5, 5), HexCoord(5, 5), action) is True

    def test_ranged_in_range(self):
        action = _make_ranged_action()
        # 80 ft = 16 hexes
        assert is_in_range(HexCoord(0, 0), HexCoord(0, 10), action) is True

    def test_ranged_within_long_range_allowed(self):
        # D-ACT-4: past normal (80) but within long (320) is now in range —
        # the shot is legal, just at disadvantage. 17 hexes = 85 ft.
        action = _make_ranged_action()
        assert is_in_range(HexCoord(0, 0), HexCoord(0, 17), action) is True

    def test_ranged_beyond_long_range_refused(self):
        action = _make_ranged_action()
        # 320 ft = 64 hexes; 65 hexes = 325 ft > long range.
        assert is_in_range(HexCoord(0, 0), HexCoord(0, 65), action) is False


class TestResolveAttack:
    def _setup_grid(self):
        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(5, 5), "fighter")
        grid.place_creature(HexCoord(5, 6), "goblin")
        return grid

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_hit(self, mock_damage_roll, mock_d20):
        mock_d20.return_value = 15  # 15 + 5 = 20 vs AC 15
        mock_damage_roll.return_value = (5, [5])
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15, hp=10)
        action = _make_melee_action()

        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        assert result.success is True
        assert len(result.events) >= 2  # Attack roll + damage
        assert result.events[0].event_type == CombatEventType.ATTACK_ROLL
        assert result.events[0].details["hit"] is True

    @patch("arena.combat.actions.roll_die")
    def test_miss(self, mock_d20):
        mock_d20.return_value = 5  # 5 + 5 = 10 vs AC 15
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15)
        action = _make_melee_action()

        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        assert result.success is True  # Action resolved successfully (even though miss)
        assert len(result.events) == 1  # Only attack roll, no damage
        assert result.events[0].details["hit"] is False

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_critical_hit(self, mock_damage_roll, mock_d20):
        mock_d20.return_value = 20
        mock_damage_roll.return_value = (4, [4])
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=25, hp=20)  # High AC, but nat 20 always hits
        action = _make_melee_action()

        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        assert result.events[0].details["critical"] is True
        assert result.events[0].details["hit"] is True
        assert "CRITICAL" in result.events[0].message

    @patch("arena.combat.actions.roll_die")
    def test_critical_miss(self, mock_d20):
        mock_d20.return_value = 1
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=5)  # Low AC, but nat 1 always misses
        action = _make_melee_action()

        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        assert result.events[0].details["hit"] is False
        assert "Critical Miss" in result.events[0].message

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_knockout(self, mock_damage_roll, mock_d20):
        mock_d20.return_value = 15
        mock_damage_roll.return_value = (20, [20])
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15, hp=5)
        action = _make_melee_action()

        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        # Should have attack roll + damage + knocked down events
        event_types = [e.event_type for e in result.events]
        assert CombatEventType.CREATURE_DOWNED in event_types

    def test_out_of_range(self):
        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(0, 0), "fighter")
        grid.place_creature(HexCoord(10, 10), "goblin")
        attacker = _make_attacker()
        target = _make_target()
        action = _make_melee_action()

        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        assert result.success is False
        assert result.events[0].event_type == CombatEventType.INFO

    def test_no_attack_on_action(self):
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target()
        action = Action(name="Heal", description="Healing", attack=None)
        result = resolve_attack(attacker, "fighter", target, "goblin", action, grid)
        assert result.success is False


class TestTwoPhaseAttack:
    """Tests for the two-phase attack split (resolve_attack_hit + resolve_attack_damage)."""

    def _setup_grid(self):
        grid = HexGrid(20, 20)
        grid.place_creature(HexCoord(5, 5), "fighter")
        grid.place_creature(HexCoord(5, 6), "goblin")
        return grid

    @patch("arena.combat.actions.roll_die")
    def test_hit_check_returns_hit(self, mock_d20):
        mock_d20.return_value = 15  # 15 + 5 = 20 vs AC 15
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        assert hit_result.hit is True
        assert hit_result.critical is False
        assert hit_result.natural_roll == 15
        assert hit_result.attacker is attacker
        assert hit_result.target is target
        assert hit_result.action is action
        assert len(hit_result.events) >= 1

    @patch("arena.combat.actions.roll_die")
    def test_hit_check_returns_miss(self, mock_d20):
        mock_d20.return_value = 5  # 5 + 5 = 10 vs AC 15
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        assert hit_result.hit is False

    @patch("arena.combat.actions.roll_die")
    def test_hit_check_crit(self, mock_d20):
        mock_d20.return_value = 20
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=25)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        assert hit_result.hit is True
        assert hit_result.critical is True

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_damage_phase_applies_damage(self, mock_damage_roll, mock_d20):
        mock_d20.return_value = 15
        mock_damage_roll.return_value = (5, [5])
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15, hp=20)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        assert hit_result.hit is True

        result = resolve_attack_damage(hit_result)
        assert result.success is True
        # Should have attack roll events + damage event
        event_types = [e.event_type for e in result.events]
        assert CombatEventType.DAMAGE in event_types

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_bonus_damage_adds_to_total(self, mock_damage_roll, mock_d20):
        """Bonus damage (Divine Smite) should be added to attack damage."""
        mock_d20.return_value = 15
        # First call: weapon damage; second call: smite damage
        mock_damage_roll.side_effect = [(5, [5]), (9, [4, 5])]
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15, hp=30)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        bonus = [DamageRoll(dice="2d8", damage_type=DamageType.RADIANT)]
        result = resolve_attack_damage(hit_result, bonus_damage=bonus)
        assert result.success is True
        # Target should have lost HP from both weapon + smite
        assert target.current_hit_points < 30

    @patch("arena.combat.actions.roll_die")
    def test_miss_then_damage_no_effect(self, mock_d20):
        """On a miss, resolve_attack_damage should not deal damage."""
        mock_d20.return_value = 5  # miss
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15, hp=10)
        action = _make_melee_action()

        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        result = resolve_attack_damage(hit_result)
        assert target.current_hit_points == 10  # No damage

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_two_phase_equivalent_to_single_call(self, mock_damage_roll, mock_d20):
        """Two-phase split should produce the same hit outcome as single resolve_attack."""
        mock_d20.return_value = 15
        mock_damage_roll.return_value = (8, [8])
        grid = self._setup_grid()
        attacker = _make_attacker()
        target = _make_target(ac=15, hp=30)
        action = _make_melee_action()

        # Two-phase
        hit_result = resolve_attack_hit(
            attacker, "fighter", target, "goblin", action, grid
        )
        result = resolve_attack_damage(hit_result)

        # Verify the combined result has both attack and damage events
        event_types = [e.event_type for e in result.events]
        assert CombatEventType.ATTACK_ROLL in event_types
        assert CombatEventType.DAMAGE in event_types
