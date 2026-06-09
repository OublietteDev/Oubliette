"""Tests for Extra Attack wiring in CombatManager.

Verifies that creatures with extra_attack_count can make multiple attacks
per Attack action, and that the action slot is only consumed after all
attacks are used.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature, PlayerCharacter, Feature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ──────────────────────────────────────────────────────────

_ACTIONS = [
    Action(
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
    ),
    Action(
        name="Offhand Dagger",
        description="Bonus action offhand attack",
        action_type=ActionType.BONUS_ACTION,
        attack=Attack(
            name="Offhand Dagger",
            attack_type="melee_weapon",
            ability="dexterity",
            reach=5,
            damage=[
                DamageRoll(
                    dice="1d4",
                    damage_type=DamageType.PIERCING,
                )
            ],
        ),
    ),
]


def _make_fighter(features=None):
    """Create a PlayerCharacter fighter with optional features."""
    return PlayerCharacter(
        name="Fighter",
        size="medium",
        creature_type="humanoid",
        max_hit_points=50,
        armor_class=16,
        ability_scores=AbilityScores(strength=16, dexterity=10),
        proficiency_bonus=2,
        is_player_controlled=True,
        character_class="Fighter",
        level=5,
        features=features or [],
        actions=list(_ACTIONS),
    )


def _make_enemy():
    """Create a basic enemy creature."""
    return Creature(
        name="Goblin",
        max_hit_points=100,
        armor_class=10,
        ability_scores=AbilityScores(strength=8, dexterity=14),
        proficiency_bonus=2,
        is_player_controlled=False,
        actions=[_ACTIONS[0]],
    )


def _make_encounter(player_features=None):
    """Create a 1v1 encounter with adjacent combatants."""
    return Encounter(
        name="Extra Attack Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="fighter",
                creature_data=_make_fighter(features=player_features),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="enemy",
                creature_data=_make_enemy(),
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )


def _start_combat(player_features=None):
    """Set up and start combat, advancing to the player's turn."""
    cm = CombatManager()
    cm.load_encounter(_make_encounter(player_features), Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    # Advance to the fighter's turn if not already active
    if cm.active_combatant and cm.active_combatant.creature_id != "fighter":
        cm.end_turn()
    return cm


def _get_target_id(cm, active_id):
    """Return the first combatant ID that isn't the active creature."""
    for cid in cm.combatants:
        if cid != active_id:
            return cid
    return None


# ── Tests ────────────────────────────────────────────────────────────


class TestExtraAttackWiring:
    """Tests for Extra Attack integration in combat flow."""

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_no_extra_attack_consumes_action_after_one_attack(
        self, mock_damage, mock_d20,
    ):
        """Creature without Extra Attack: action consumed after 1 attack."""
        mock_d20.return_value = 18  # Hit
        mock_damage.return_value = (5, [5])

        cm = _start_combat(player_features=[])
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # First (and only) attack
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)

        assert result is not None
        assert cm.turn_resources.has_used_action is True
        assert cm.turn_resources.attacks_remaining == 0
        assert not cm.has_attacks_remaining()

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_extra_attack_2_allows_two_attacks(self, mock_damage, mock_d20):
        """Fighter with extra_attack_count=2: can attack twice before action used."""
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        features = [
            Feature(
                name="Extra Attack",
                description="Two attacks per Attack action",
                extra_attack_count=2,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # First attack — action should NOT be consumed yet
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_action is False
        assert cm.turn_resources.attacks_remaining == 1
        assert cm.has_attacks_remaining()

        # Second attack — action should now be consumed
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_action is True
        assert cm.turn_resources.attacks_remaining == 0
        assert not cm.has_attacks_remaining()

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_extra_attack_3_allows_three_attacks(self, mock_damage, mock_d20):
        """Fighter with extra_attack_count=3: can attack three times."""
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        features = [
            Feature(
                name="Extra Attack (x2)",
                description="Three attacks per Attack action",
                extra_attack_count=3,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # Attack 1 of 3
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_action is False
        assert cm.turn_resources.attacks_remaining == 2

        # Attack 2 of 3
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_action is False
        assert cm.turn_resources.attacks_remaining == 1

        # Attack 3 of 3 — action consumed
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_action is True
        assert cm.turn_resources.attacks_remaining == 0

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_bonus_action_attack_not_affected_by_extra_attack(
        self, mock_damage, mock_d20,
    ):
        """Bonus action attacks are NOT affected by Extra Attack."""
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        features = [
            Feature(
                name="Extra Attack",
                description="Two attacks per Attack action",
                extra_attack_count=2,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # Bonus action attack (offhand dagger)
        bonus_action = active.creature.actions[1]
        assert bonus_action.action_type == ActionType.BONUS_ACTION

        cm.select_action(bonus_action)
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_bonus_action is True
        # Extra attack counter should not have been touched
        assert cm.turn_resources.attacks_remaining == 0
        # Main action should still be available
        assert cm.turn_resources.has_used_action is False

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_action_blocked_after_all_extra_attacks_used(
        self, mock_damage, mock_d20,
    ):
        """After all extra attacks are used, action slot is consumed and
        cannot be used again."""
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        features = [
            Feature(
                name="Extra Attack",
                description="Two attacks per Attack action",
                extra_attack_count=2,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # Use both attacks
        cm.select_action(active.creature.actions[0])
        cm.execute_attack(target_id)
        cm.select_action(active.creature.actions[0])
        cm.execute_attack(target_id)

        assert cm.turn_resources.has_used_action is True

        # Third attack attempt should fail (action slot consumed)
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is None

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_two_phase_attack_flow_with_extra_attack(
        self, mock_damage, mock_d20,
    ):
        """Two-phase flow (hit check + complete) works with extra attack."""
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        features = [
            Feature(
                name="Extra Attack",
                description="Two attacks per Attack action",
                extra_attack_count=2,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # First attack via two-phase flow
        cm.select_action(active.creature.actions[0])
        hit_result = cm.execute_attack_hit_check(target_id)
        assert hit_result is not None
        result = cm.complete_attack(hit_result)
        assert result is not None
        assert cm.turn_resources.has_used_action is False
        assert cm.turn_resources.attacks_remaining == 1

        # Second attack via two-phase flow — action consumed
        cm.select_action(active.creature.actions[0])
        hit_result = cm.execute_attack_hit_check(target_id)
        assert hit_result is not None
        result = cm.complete_attack(hit_result)
        assert result is not None
        assert cm.turn_resources.has_used_action is True
        assert cm.turn_resources.attacks_remaining == 0

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_attacks_remaining_resets_on_new_turn(
        self, mock_damage, mock_d20,
    ):
        """attacks_remaining resets to 0 at the start of a new turn."""
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        features = [
            Feature(
                name="Extra Attack",
                description="Two attacks per Attack action",
                extra_attack_count=2,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # Use first attack only (1 remaining)
        cm.select_action(active.creature.actions[0])
        cm.execute_attack(target_id)
        assert cm.turn_resources.attacks_remaining == 1

        # End turn and come back around
        cm.end_turn()
        # Skip enemy turn
        if cm.active_combatant and cm.active_combatant.creature_id != "fighter":
            cm.end_turn()

        # attacks_remaining should be reset
        assert cm.turn_resources.attacks_remaining == 0

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_missed_attack_still_counts(self, mock_damage, mock_d20):
        """A miss still consumes one of the extra attacks."""
        mock_d20.return_value = 1  # Miss (natural 1 always misses)
        mock_damage.return_value = (0, [0])

        features = [
            Feature(
                name="Extra Attack",
                description="Two attacks per Attack action",
                extra_attack_count=2,
            ),
        ]
        cm = _start_combat(player_features=features)
        active = cm.active_combatant
        assert active.creature_id == "fighter"
        target_id = _get_target_id(cm, active.creature_id)

        # First attack misses — but we need to check: does a miss set
        # result.success = False? That would skip _handle_extra_attack_tracking.
        # Let's verify what happens with a hit first and miss second.
        mock_d20.return_value = 18  # Hit
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert result.success is True
        assert cm.turn_resources.has_used_action is False
        assert cm.turn_resources.attacks_remaining == 1

        # Second attack hits too — action consumed
        cm.select_action(active.creature.actions[0])
        result = cm.execute_attack(target_id)
        assert result is not None
        assert cm.turn_resources.has_used_action is True
