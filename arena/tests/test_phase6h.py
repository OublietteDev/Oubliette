"""Tests for Phase 6h: Turn Executor."""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.ai.controller import (
    AIController,
    TurnPlan,
    TurnStep,
    TurnStepType,
)
from arena.ai.executor import execute_step, execute_full_plan
from arena.combat.manager import CombatManager, CombatState, TurnPhase
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


# ── Helpers ─────────────────────────────────────────────────────────


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


def _make_encounter(player_pos=(2, 2), enemy_pos=(3, 2)):
    return Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="inline_player",
                creature_data=_make_creature("Fighter", hp=20, ac=15, strength=16,
                                             is_player=True),
                team="player",
                starting_position=player_pos,
            ),
            CombatantEntry(
                creature_id="inline_enemy",
                creature_data=_make_creature("Goblin", hp=7, ac=13, dexterity=14,
                                             is_player=False),
                team="enemy",
                starting_position=enemy_pos,
            ),
        ],
    )


def _start_combat_enemy_first():
    """Start combat with the enemy going first."""
    cm = CombatManager()
    cm.load_encounter(_make_encounter(), Path("."))

    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()

    # Force enemy first
    entries = cm.initiative.entries
    for e in entries:
        if cm.combatants[e.creature_id].team == "enemy":
            e.initiative_roll = 20
        else:
            e.initiative_roll = 5
    cm.initiative.entries.sort(
        key=lambda x: (-x.initiative_roll, -x.dexterity)
    )

    cm.begin_combat()
    return cm


# ── execute_step ────────────────────────────────────────────────────


class TestExecuteStep:
    def test_end_turn_advances(self):
        cm = _start_combat_enemy_first()
        active_before = cm.active_combatant.creature_id
        step = TurnStep(step_type=TurnStepType.END_TURN)
        execute_step(step, cm)
        active_after = cm.active_combatant.creature_id
        assert active_before != active_after

    def test_log_thinking_adds_event(self):
        cm = _start_combat_enemy_first()
        event_count_before = len(cm.log.events)
        step = TurnStep(
            step_type=TurnStepType.LOG_THINKING,
            message="Considering targets...",
        )
        result = execute_step(step, cm)
        assert result is not None
        assert "[AI]" in result.message
        assert result.event_type == CombatEventType.AI_THINKING
        assert len(cm.log.events) > event_count_before

    def test_select_action_sets_phase(self):
        cm = _start_combat_enemy_first()
        step = TurnStep(
            step_type=TurnStepType.SELECT_ACTION,
            action_name="Sword",
        )
        execute_step(step, cm)
        assert cm.turn_phase == TurnPhase.SELECTING_TARGET
        assert cm.selected_action is not None

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_execute_attack_uses_action(self, mock_damage, mock_d20):
        mock_d20.return_value = 18
        mock_damage.return_value = (5, [5])

        cm = _start_combat_enemy_first()
        active = cm.active_combatant

        # Find target
        target_id = None
        for cid in cm.combatants:
            if cid != active.creature_id:
                target_id = cid
                break

        # Select action first
        cm.select_action(active.creature.actions[0])

        # Execute attack
        step = TurnStep(
            step_type=TurnStepType.EXECUTE_ATTACK,
            target_id=target_id,
        )
        execute_step(step, cm)
        assert cm.has_used_action is True

    def test_standard_action_dash(self):
        cm = _start_combat_enemy_first()
        step = TurnStep(
            step_type=TurnStepType.STANDARD_ACTION,
            action_name="dash",
        )
        result = execute_step(step, cm)
        assert result is not None
        assert cm.has_used_action is True

    def test_standard_action_dodge(self):
        cm = _start_combat_enemy_first()
        step = TurnStep(
            step_type=TurnStepType.STANDARD_ACTION,
            action_name="dodge",
        )
        result = execute_step(step, cm)
        assert result is not None
        assert cm.has_used_action is True

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_move_changes_position(self, mock_damage, mock_d20):
        # Mock roll to 1 so any opportunity attack misses
        mock_d20.return_value = 1
        mock_damage.return_value = (0, [0])

        cm = _start_combat_enemy_first()
        active = cm.active_combatant
        old_pos = active.position
        assert old_pos is not None

        # Find an empty adjacent hex
        target_hex = None
        for neighbor in old_pos.neighbors():
            if cm.grid.is_valid(neighbor) and not cm.grid.is_occupied(neighbor):
                target_hex = neighbor
                break

        assert target_hex is not None
        step = TurnStep(
            step_type=TurnStepType.MOVE,
            target_hex=(target_hex.q, target_hex.r),
        )
        execute_step(step, cm)
        assert active.position == target_hex


# ── execute_full_plan ───────────────────────────────────────────────


class TestExecuteFullPlan:
    def test_executes_all_steps(self):
        cm = _start_combat_enemy_first()
        active_before = cm.active_combatant.creature_id

        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.LOG_THINKING, message="Planning..."),
            TurnStep(step_type=TurnStepType.STANDARD_ACTION, action_name="dodge"),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        events = execute_full_plan(plan, cm)
        # Should have at least the thinking and dodge events
        assert len(events) >= 2

        active_after = cm.active_combatant.creature_id
        assert active_before != active_after

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_full_attack_plan(self, mock_damage, mock_d20):
        """Execute a plan with select_action -> execute_attack -> end_turn."""
        mock_d20.return_value = 18
        mock_damage.return_value = (3, [3])

        cm = _start_combat_enemy_first()
        active = cm.active_combatant

        # Find target
        target_id = None
        for cid in cm.combatants:
            if cid != active.creature_id:
                target_id = cid
                break

        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.SELECT_ACTION, action_name="Sword"),
            TurnStep(step_type=TurnStepType.EXECUTE_ATTACK, target_id=target_id),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        events = execute_full_plan(plan, cm)
        assert len(events) >= 1  # At least the attack event

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_controller_plan_executes_successfully(self, mock_damage, mock_d20):
        """Integration: AIController.plan_turn() + execute_full_plan()."""
        mock_d20.return_value = 15
        mock_damage.return_value = (3, [3])

        cm = _start_combat_enemy_first()
        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)

        # Plan should be valid
        assert len(plan.steps) > 0
        assert plan.steps[-1].step_type == TurnStepType.END_TURN

        # Execute it
        events = execute_full_plan(plan, cm)
        # Turn should have advanced
        # (active combatant should now be the player)
        active = cm.active_combatant
        assert active is not None
        assert active.team == "player"

    def test_empty_plan_does_nothing(self):
        cm = _start_combat_enemy_first()
        active_before = cm.active_combatant.creature_id
        plan = TurnPlan(steps=[])
        events = execute_full_plan(plan, cm)
        assert events == []
        # Turn should not have advanced
        assert cm.active_combatant.creature_id == active_before
