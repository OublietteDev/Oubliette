"""Tests for Phase 5k: Hide Action."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager
from arena.combat.conditions import has_condition
from arena.combat.standard_actions import execute_hide
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(name, hp=20, dexterity=14, wisdom=10, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        ability_scores=AbilityScores(strength=10, dexterity=dexterity, wisdom=wisdom),
        proficiency_bonus=2,
        speed={"walk": 30},
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Dagger",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Dagger",
                    attack_type="melee_weapon",
                    ability="dexterity",
                    reach=5,
                    damage=[
                        DamageRoll(dice="1d4", damage_type=DamageType.PIERCING,
                                   ability_modifier="dexterity")
                    ],
                    properties=["light", "finesse"],
                ),
            )
        ],
    )


def _setup_combat(player_dex=14, enemy_wis=10):
    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="rogue",
                creature_data=_make_creature("Rogue", dexterity=player_dex, is_player=True),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="guard",
                creature_data=_make_creature("Guard", dexterity=10, wisdom=enemy_wis, is_player=False),
                team="enemy",
                starting_position=(5, 5),
            ),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()
    return cm


def _skip_to_player(cm):
    for _ in range(20):
        active = cm.active_combatant
        if active and active.creature.is_player_controlled:
            return active
        cm.end_turn()
    return None


# ── HIDDEN Condition Tests ───────────────────────────────────────────

class TestHiddenCondition:
    def test_hidden_condition_exists(self):
        assert Condition.HIDDEN is not None
        assert Condition.HIDDEN.value == "hidden"


# ── execute_hide Tests ───────────────────────────────────────────────

class TestExecuteHide:
    @patch("arena.combat.standard_actions.roll_die")
    def test_hide_success_applies_condition(self, mock_d20):
        mock_d20.return_value = 18  # 18 + 2 (DEX mod) = 20 vs PP 10
        cm = _setup_combat(player_dex=14, enemy_wis=10)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        event = cm.execute_standard_action("hide")
        assert event is not None
        assert "SUCCESS" in event.message
        assert event.details["success"] is True
        assert has_condition(active.creature, Condition.HIDDEN)

    @patch("arena.combat.standard_actions.roll_die")
    def test_hide_failure_no_condition(self, mock_d20):
        mock_d20.return_value = 3  # 3 + 2 = 5 vs PP 10+WIS
        cm = _setup_combat(player_dex=14, enemy_wis=14)  # PP = 10 + 2 = 12
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        event = cm.execute_standard_action("hide")
        assert event is not None
        assert "FAILED" in event.message
        assert event.details["success"] is False
        assert not has_condition(active.creature, Condition.HIDDEN)

    @patch("arena.combat.standard_actions.roll_die")
    def test_hide_uses_action(self, mock_d20):
        mock_d20.return_value = 18
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.execute_standard_action("hide")
        assert cm.turn_resources.has_used_action is True

    @patch("arena.combat.standard_actions.roll_die")
    def test_hide_fails_if_action_used(self, mock_d20):
        mock_d20.return_value = 18
        cm = _setup_combat()
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        cm.turn_resources.has_used_action = True
        event = cm.execute_standard_action("hide")
        assert event is None

    @patch("arena.combat.standard_actions.roll_die")
    def test_hide_event_has_stealth_details(self, mock_d20):
        mock_d20.return_value = 15
        cm = _setup_combat(player_dex=14, enemy_wis=10)
        active = _skip_to_player(cm)
        if active is None:
            pytest.skip("Could not get player turn")

        event = cm.execute_standard_action("hide")
        assert event is not None
        assert "stealth_roll" in event.details
        assert "passive_perception" in event.details
        # Stealth roll = 15 + 2 (dex mod) = 17
        assert event.details["stealth_roll"] == 17
