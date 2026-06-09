"""Tests for Phase 5a: Advantage/Disadvantage and Action Economy Tracking."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, TurnResources
from arena.combat.actions import resolve_attack, AttackResult
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(name, hp, ac=10, strength=10, dexterity=10, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Sword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Sword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(
                            dice="1d6",
                            damage_type=DamageType.SLASHING,
                            ability_modifier="strength",
                        )
                    ],
                ),
            )
        ],
    )


def _make_grid():
    grid = HexGrid(20, 20)
    grid.place_creature(HexCoord(5, 5), "fighter")
    grid.place_creature(HexCoord(5, 6), "goblin")
    return grid


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


def _make_encounter():
    return Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="inline_player",
                creature_data=_make_creature("Fighter", hp=20, ac=15, strength=16, is_player=True),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="inline_enemy",
                creature_data=_make_creature("Goblin", hp=7, ac=13, dexterity=14, is_player=False),
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )


# ── TurnResources Tests ──────────────────────────────────────────────

class TestTurnResources:
    def test_default_state(self):
        tr = TurnResources()
        assert tr.has_used_action is False
        assert tr.has_used_bonus_action is False
        assert tr.has_used_reaction is False
        assert tr.free_actions_used == 0
        assert tr.is_disengaging is False

    def test_reset_clears_all(self):
        tr = TurnResources(
            has_used_action=True,
            has_used_bonus_action=True,
            has_used_reaction=True,
            free_actions_used=1,
            is_disengaging=True,
        )
        tr.reset_for_new_turn()
        assert tr.has_used_action is False
        assert tr.has_used_bonus_action is False
        assert tr.has_used_reaction is False
        assert tr.free_actions_used == 0
        assert tr.is_disengaging is False


class TestCombatManagerActionEconomy:
    def _start_combat(self):
        cm = CombatManager()
        cm.load_encounter(_make_encounter(), Path("."))
        cm.roll_initiative()
        cm.begin_combat()
        return cm

    def test_turn_resources_exist(self):
        cm = self._start_combat()
        assert isinstance(cm.turn_resources, TurnResources)

    def test_has_used_action_property(self):
        """Backward-compatible property delegates to turn_resources."""
        cm = self._start_combat()
        assert cm.has_used_action is False
        cm.has_used_action = True
        assert cm.turn_resources.has_used_action is True

    def test_turn_resources_reset_on_new_turn(self):
        cm = self._start_combat()
        cm.turn_resources.has_used_action = True
        cm.turn_resources.has_used_bonus_action = True
        cm.end_turn()
        # After advancing to next creature's turn, resources should reset
        assert cm.turn_resources.has_used_action is False
        assert cm.turn_resources.has_used_bonus_action is False

    def test_can_use_action_type_action(self):
        cm = self._start_combat()
        assert cm.can_use_action_type(ActionType.ACTION) is True
        cm.turn_resources.has_used_action = True
        assert cm.can_use_action_type(ActionType.ACTION) is False

    def test_can_use_action_type_bonus_action(self):
        cm = self._start_combat()
        assert cm.can_use_action_type(ActionType.BONUS_ACTION) is True
        cm.turn_resources.has_used_bonus_action = True
        assert cm.can_use_action_type(ActionType.BONUS_ACTION) is False

    def test_can_use_action_type_reaction(self):
        cm = self._start_combat()
        assert cm.can_use_action_type(ActionType.REACTION) is True
        cm.turn_resources.has_used_reaction = True
        assert cm.can_use_action_type(ActionType.REACTION) is False

    def test_can_use_action_type_free(self):
        cm = self._start_combat()
        assert cm.can_use_action_type(ActionType.FREE) is True
        cm.turn_resources.free_actions_used = 1
        assert cm.can_use_action_type(ActionType.FREE) is False

    def test_reset_clears_turn_resources(self):
        cm = self._start_combat()
        cm.turn_resources.has_used_action = True
        cm.reset()
        assert cm.turn_resources.has_used_action is False


# ── Advantage/Disadvantage Tests ─────────────────────────────────────

class TestResolveAttackAdvantage:
    @patch("arena.combat.actions.roll_with_advantage")
    @patch("arena.combat.damage.roll_expression")
    def test_advantage_rolls_twice_takes_higher(self, mock_damage, mock_adv):
        mock_adv.return_value = (18, 12, 18)  # Takes 18
        mock_damage.return_value = (5, [5])
        grid = _make_grid()
        attacker = Creature(
            name="Fighter", max_hit_points=30,
            ability_scores=AbilityScores(strength=16), proficiency_bonus=2,
        )
        target = Creature(name="Goblin", max_hit_points=10, armor_class=15)
        action = _make_melee_action()

        result = resolve_attack(
            attacker, "fighter", target, "goblin", action, grid,
            advantage=1,
        )
        mock_adv.assert_called_once()
        assert result.events[0].details["natural"] == 18
        assert result.events[0].details["advantage"] == 1
        assert "adv:" in result.events[0].message

    @patch("arena.combat.actions.roll_with_disadvantage")
    def test_disadvantage_rolls_twice_takes_lower(self, mock_dis):
        mock_dis.return_value = (5, 5, 18)  # Takes 5
        grid = _make_grid()
        attacker = Creature(
            name="Fighter", max_hit_points=30,
            ability_scores=AbilityScores(strength=16), proficiency_bonus=2,
        )
        target = Creature(name="Goblin", max_hit_points=10, armor_class=15)
        action = _make_melee_action()

        result = resolve_attack(
            attacker, "fighter", target, "goblin", action, grid,
            advantage=-1,
        )
        mock_dis.assert_called_once()
        assert result.events[0].details["natural"] == 5
        assert result.events[0].details["advantage"] == -1
        assert "dis:" in result.events[0].message

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_advantage_zero_is_normal_roll(self, mock_damage, mock_d20):
        mock_d20.return_value = 15
        mock_damage.return_value = (5, [5])
        grid = _make_grid()
        attacker = Creature(
            name="Fighter", max_hit_points=30,
            ability_scores=AbilityScores(strength=16), proficiency_bonus=2,
        )
        target = Creature(name="Goblin", max_hit_points=10, armor_class=15)
        action = _make_melee_action()

        result = resolve_attack(
            attacker, "fighter", target, "goblin", action, grid,
            advantage=0,
        )
        mock_d20.assert_called_once_with(20)
        assert result.events[0].details["advantage"] == 0
        # No [adv:] or [dis:] in message
        assert "adv:" not in result.events[0].message
        assert "dis:" not in result.events[0].message

    @patch("arena.combat.actions.roll_with_advantage")
    @patch("arena.combat.damage.roll_expression")
    def test_advantage_crit_still_works(self, mock_damage, mock_adv):
        mock_adv.return_value = (20, 15, 20)  # Nat 20 with advantage
        mock_damage.return_value = (10, [5, 5])
        grid = _make_grid()
        attacker = Creature(
            name="Fighter", max_hit_points=30,
            ability_scores=AbilityScores(strength=16), proficiency_bonus=2,
        )
        target = Creature(name="Goblin", max_hit_points=20, armor_class=25)
        action = _make_melee_action()

        result = resolve_attack(
            attacker, "fighter", target, "goblin", action, grid,
            advantage=1,
        )
        assert result.events[0].details["critical"] is True
        assert result.events[0].details["hit"] is True


# ── New Event Types Tests ────────────────────────────────────────────

class TestNewEventTypes:
    def test_saving_throw_event_type_exists(self):
        assert CombatEventType.SAVING_THROW is not None

    def test_condition_applied_event_type_exists(self):
        assert CombatEventType.CONDITION_APPLIED is not None

    def test_condition_removed_event_type_exists(self):
        assert CombatEventType.CONDITION_REMOVED is not None

    def test_death_save_event_type_exists(self):
        assert CombatEventType.DEATH_SAVE is not None

    def test_healing_event_type_exists(self):
        assert CombatEventType.HEALING is not None

    def test_reaction_event_type_exists(self):
        assert CombatEventType.REACTION is not None
