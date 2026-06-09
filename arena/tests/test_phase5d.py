"""Tests for Phase 5d: Condition Effects on Combat."""

import pytest
from unittest.mock import patch

from arena.combat.condition_effects import (
    get_attack_advantage,
    get_save_advantage,
    is_auto_fail_save,
    can_take_actions,
    get_movement_multiplier,
    is_auto_crit,
)
from arena.combat.actions import resolve_attack, resolve_saving_throw
from arena.combat.conditions import apply_condition
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid


# ── Helpers ───────────────────────────────────────────────────────────

def _creature(name="Test", hp=20, conditions=None):
    c = Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=14, dexterity=14),
        proficiency_bonus=2,
    )
    if conditions:
        for cond in conditions:
            apply_condition(c, name.lower(), cond, "test")
    return c


def _make_grid():
    grid = HexGrid(20, 20)
    grid.place_creature(HexCoord(5, 5), "attacker")
    grid.place_creature(HexCoord(5, 6), "target")
    return grid


def _melee_action():
    return Action(
        name="Sword", description="Attack", action_type=ActionType.ACTION,
        attack=Attack(
            name="Sword", attack_type="melee_weapon", ability="strength",
            reach=5,
            damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                               ability_modifier="strength")],
        ),
    )


# ── get_attack_advantage Tests ───────────────────────────────────────

class TestGetAttackAdvantage:
    def test_no_conditions_normal(self):
        a, t = _creature(), _creature()
        assert get_attack_advantage(a, t) == 0

    def test_blinded_target_advantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.BLINDED])
        assert get_attack_advantage(a, t) == 1

    def test_blinded_attacker_disadvantage(self):
        a = _creature(conditions=[Condition.BLINDED])
        t = _creature()
        assert get_attack_advantage(a, t) == -1

    def test_blinded_both_cancel(self):
        a = _creature(conditions=[Condition.BLINDED])
        t = _creature(conditions=[Condition.BLINDED])
        # Attacker blind -> dis, target blind -> adv, cancel to 0
        assert get_attack_advantage(a, t) == 0

    def test_paralyzed_target_advantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.PARALYZED])
        assert get_attack_advantage(a, t) == 1

    def test_stunned_target_advantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.STUNNED])
        assert get_attack_advantage(a, t) == 1

    def test_unconscious_target_advantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.UNCONSCIOUS])
        assert get_attack_advantage(a, t) == 1

    def test_restrained_target_advantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.RESTRAINED])
        assert get_attack_advantage(a, t) == 1

    def test_restrained_attacker_disadvantage(self):
        a = _creature(conditions=[Condition.RESTRAINED])
        t = _creature()
        assert get_attack_advantage(a, t) == -1

    def test_prone_target_melee_advantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.PRONE])
        assert get_attack_advantage(a, t, is_melee=True) == 1

    def test_prone_target_ranged_disadvantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.PRONE])
        assert get_attack_advantage(a, t, is_melee=False) == -1

    def test_helped_attacker_advantage(self):
        a = _creature(conditions=[Condition.HELPED])
        t = _creature()
        assert get_attack_advantage(a, t) == 1

    def test_dodging_target_disadvantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.DODGING])
        assert get_attack_advantage(a, t) == -1

    def test_poisoned_attacker_disadvantage(self):
        a = _creature(conditions=[Condition.POISONED])
        t = _creature()
        assert get_attack_advantage(a, t) == -1

    def test_frightened_attacker_disadvantage(self):
        a = _creature(conditions=[Condition.FRIGHTENED])
        t = _creature()
        assert get_attack_advantage(a, t) == -1

    def test_invisible_attacker_advantage(self):
        a = _creature(conditions=[Condition.INVISIBLE])
        t = _creature()
        assert get_attack_advantage(a, t) == 1

    def test_invisible_target_disadvantage(self):
        a = _creature()
        t = _creature(conditions=[Condition.INVISIBLE])
        assert get_attack_advantage(a, t) == -1


# ── get_save_advantage Tests ────────────────────────────────────────

class TestGetSaveAdvantage:
    def test_no_conditions(self):
        c = _creature()
        assert get_save_advantage(c, "dexterity") == 0

    def test_restrained_dex_disadvantage(self):
        c = _creature(conditions=[Condition.RESTRAINED])
        assert get_save_advantage(c, "dexterity") == -1

    def test_restrained_str_no_effect(self):
        c = _creature(conditions=[Condition.RESTRAINED])
        assert get_save_advantage(c, "strength") == 0

    def test_dodging_dex_advantage(self):
        c = _creature(conditions=[Condition.DODGING])
        assert get_save_advantage(c, "dexterity") == 1

    def test_dodging_and_restrained_cancel(self):
        c = _creature(conditions=[Condition.DODGING, Condition.RESTRAINED])
        assert get_save_advantage(c, "dexterity") == 0


# ── is_auto_fail_save Tests ────────────────────────────────────────

class TestIsAutoFailSave:
    def test_normal_creature(self):
        c = _creature()
        assert is_auto_fail_save(c, "strength") is False

    def test_stunned_str_auto_fail(self):
        c = _creature(conditions=[Condition.STUNNED])
        assert is_auto_fail_save(c, "strength") is True

    def test_stunned_dex_auto_fail(self):
        c = _creature(conditions=[Condition.STUNNED])
        assert is_auto_fail_save(c, "dexterity") is True

    def test_stunned_wis_not_auto_fail(self):
        c = _creature(conditions=[Condition.STUNNED])
        assert is_auto_fail_save(c, "wisdom") is False

    def test_paralyzed_str_auto_fail(self):
        c = _creature(conditions=[Condition.PARALYZED])
        assert is_auto_fail_save(c, "strength") is True


# ── can_take_actions Tests ──────────────────────────────────────────

class TestCanTakeActions:
    def test_normal(self):
        c = _creature()
        assert can_take_actions(c) is True

    def test_incapacitated(self):
        c = _creature(conditions=[Condition.INCAPACITATED])
        assert can_take_actions(c) is False

    def test_stunned(self):
        c = _creature(conditions=[Condition.STUNNED])
        assert can_take_actions(c) is False

    def test_paralyzed(self):
        c = _creature(conditions=[Condition.PARALYZED])
        assert can_take_actions(c) is False

    def test_petrified(self):
        c = _creature(conditions=[Condition.PETRIFIED])
        assert can_take_actions(c) is False

    def test_unconscious(self):
        c = _creature(conditions=[Condition.UNCONSCIOUS])
        assert can_take_actions(c) is False

    def test_poisoned_can_act(self):
        c = _creature(conditions=[Condition.POISONED])
        assert can_take_actions(c) is True


# ── get_movement_multiplier Tests ───────────────────────────────────

class TestGetMovementMultiplier:
    def test_normal(self):
        c = _creature()
        assert get_movement_multiplier(c) == 1.0

    def test_grappled_zero(self):
        c = _creature(conditions=[Condition.GRAPPLED])
        assert get_movement_multiplier(c) == 0.0

    def test_restrained_zero(self):
        c = _creature(conditions=[Condition.RESTRAINED])
        assert get_movement_multiplier(c) == 0.0

    def test_stunned_zero(self):
        c = _creature(conditions=[Condition.STUNNED])
        assert get_movement_multiplier(c) == 0.0

    def test_prone_half(self):
        c = _creature(conditions=[Condition.PRONE])
        assert get_movement_multiplier(c) == 0.5


# ── is_auto_crit Tests ─────────────────────────────────────────────

class TestIsAutoCrit:
    def test_normal_target(self):
        t = _creature()
        assert is_auto_crit(t) is False

    def test_paralyzed_melee(self):
        t = _creature(conditions=[Condition.PARALYZED])
        assert is_auto_crit(t, is_melee=True) is True

    def test_paralyzed_ranged(self):
        t = _creature(conditions=[Condition.PARALYZED])
        assert is_auto_crit(t, is_melee=False) is False

    def test_unconscious_melee(self):
        t = _creature(conditions=[Condition.UNCONSCIOUS])
        assert is_auto_crit(t, is_melee=True) is True


# ── Integration: resolve_attack with conditions ─────────────────────

class TestResolveAttackWithConditions:
    @patch("arena.combat.actions.roll_with_advantage")
    @patch("arena.combat.damage.roll_expression")
    def test_blinded_target_gives_advantage(self, mock_dmg, mock_adv):
        mock_adv.return_value = (15, 10, 15)
        mock_dmg.return_value = (5, [5])
        grid = _make_grid()
        attacker = _creature("Fighter")
        target = _creature("Goblin")
        apply_condition(target, "goblin", Condition.BLINDED, "spell")
        action = _melee_action()

        result = resolve_attack(attacker, "attacker", target, "target", action, grid)
        mock_adv.assert_called_once()
        assert result.events[0].details["advantage"] == 1

    @patch("arena.combat.actions.roll_with_advantage")
    @patch("arena.combat.damage.roll_expression")
    def test_paralyzed_target_auto_crit(self, mock_dmg, mock_adv):
        mock_adv.return_value = (15, 12, 15)  # Normal hit, should become crit
        mock_dmg.return_value = (5, [5])
        grid = _make_grid()
        attacker = _creature("Fighter")
        target = _creature("Goblin", hp=40)
        apply_condition(target, "goblin", Condition.PARALYZED, "spell")
        action = _melee_action()

        result = resolve_attack(attacker, "attacker", target, "target", action, grid)
        # Paralyzed gives advantage and auto-crit on melee hit
        assert result.events[0].details["critical"] is True


# ── Integration: resolve_saving_throw with conditions ───────────────

class TestResolveSavingThrowWithConditions:
    def test_stunned_auto_fail_str(self):
        creature = _creature(conditions=[Condition.STUNNED])
        success, event = resolve_saving_throw(creature, "test", "strength", dc=5)
        assert success is False
        assert event.details.get("auto_fail") is True

    def test_stunned_auto_fail_dex(self):
        creature = _creature(conditions=[Condition.STUNNED])
        success, event = resolve_saving_throw(creature, "test", "dexterity", dc=5)
        assert success is False

    @patch("arena.combat.actions.roll_die")
    def test_stunned_wis_save_normal(self, mock_d20):
        mock_d20.return_value = 15
        creature = _creature(conditions=[Condition.STUNNED])
        success, event = resolve_saving_throw(creature, "test", "wisdom", dc=15)
        # WIS is not auto-fail for stunned; 15 + 2(mod) = 17 >= 15
        assert success is True
