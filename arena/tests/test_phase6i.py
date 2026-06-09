"""Tests for Phase 6i: GUI Integration — AITurnRunner.

These tests exercise the AITurnRunner class without a Pygame display
by mocking pygame.time.get_ticks().
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from arena.ai.controller import TurnPlan, TurnStep, TurnStepType
from arena.combat.manager import CombatManager, CombatState
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry

# We need to import AITurnRunner, but it requires pygame.
# Mock pygame before importing.
import sys

# Create a mock for pygame if not available in test environment
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

if PYGAME_AVAILABLE:
    from arena.gui.screens.combat import AITurnRunner
    from arena.util.settings import get_settings

    # Read default delay values from settings (matching what AITurnRunner uses)
    AI_STEP_DELAY = get_settings().gameplay.ai_step_delay
    AI_THINKING_DELAY = get_settings().gameplay.ai_thinking_delay


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


def _make_encounter():
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
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="inline_enemy",
                creature_data=_make_creature("Goblin", hp=7, ac=13, dexterity=14,
                                             is_player=False),
                team="enemy",
                starting_position=(3, 2),
            ),
        ],
    )


def _start_combat_enemy_first():
    cm = CombatManager()
    cm.load_encounter(_make_encounter(), Path("."))

    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()

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


# ── AITurnRunner ────────────────────────────────────────────────────


@pytest.mark.skipif(not PYGAME_AVAILABLE, reason="pygame not available")
class TestAITurnRunner:
    def test_not_active_initially(self):
        runner = AITurnRunner()
        assert runner.is_active is False

    def test_becomes_active_after_start(self):
        runner = AITurnRunner()
        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        with patch("pygame.time.get_ticks", return_value=0):
            runner.start(plan)
        assert runner.is_active is True

    def test_update_before_delay_does_nothing(self):
        runner = AITurnRunner()
        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.STANDARD_ACTION, action_name="dodge"),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        with patch("pygame.time.get_ticks", return_value=1000):
            runner.start(plan)

        cm = _start_combat_enemy_first()
        # Try to update before delay elapses
        finished = runner.update(cm, 1000 + 100)  # Only 100ms elapsed
        assert finished is False
        assert runner.is_active is True

    def test_update_after_delay_executes_step(self):
        runner = AITurnRunner()
        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.STANDARD_ACTION, action_name="dodge"),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        with patch("pygame.time.get_ticks", return_value=0):
            runner.start(plan)

        cm = _start_combat_enemy_first()
        # First step after delay
        finished = runner.update(cm, AI_THINKING_DELAY + 1)
        assert finished is False
        assert cm.has_used_action is True  # Dodge uses action

    def test_end_turn_completes_plan(self):
        runner = AITurnRunner()
        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        with patch("pygame.time.get_ticks", return_value=0):
            runner.start(plan)

        cm = _start_combat_enemy_first()
        active_before = cm.active_combatant.creature_id

        finished = runner.update(cm, AI_THINKING_DELAY + 1)
        assert finished is True
        assert runner.is_active is False

    def test_thinking_step_uses_short_delay(self):
        runner = AITurnRunner()
        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.LOG_THINKING, message="Thinking..."),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])
        with patch("pygame.time.get_ticks", return_value=0):
            runner.start(plan)

        cm = _start_combat_enemy_first()

        # Execute thinking step
        runner.update(cm, AI_THINKING_DELAY + 1)
        assert runner.is_active is True  # Not finished yet

        # Execute end turn after thinking delay
        runner.update(cm, AI_THINKING_DELAY + AI_THINKING_DELAY + 2)
        assert runner.is_active is False

    def test_update_when_not_active_returns_false(self):
        runner = AITurnRunner()
        cm = _start_combat_enemy_first()
        assert runner.update(cm, 0) is False

    @patch("arena.combat.actions.roll_die")
    @patch("arena.combat.damage.roll_expression")
    def test_multi_step_execution(self, mock_damage, mock_d20):
        """Execute a multi-step plan with delays."""
        mock_d20.return_value = 18
        mock_damage.return_value = (3, [3])

        runner = AITurnRunner()
        cm = _start_combat_enemy_first()
        active = cm.active_combatant

        # Find target
        target_id = None
        for cid in cm.combatants:
            if cid != active.creature_id:
                target_id = cid
                break

        plan = TurnPlan(steps=[
            TurnStep(step_type=TurnStepType.LOG_THINKING, message="Attack!"),
            TurnStep(step_type=TurnStepType.SELECT_ACTION, action_name="Sword"),
            TurnStep(step_type=TurnStepType.EXECUTE_ATTACK, target_id=target_id),
            TurnStep(step_type=TurnStepType.END_TURN),
        ])

        with patch("pygame.time.get_ticks", return_value=0):
            runner.start(plan)

        t = AI_THINKING_DELAY + 1
        # Step 1: thinking
        runner.update(cm, t)
        assert runner.is_active is True

        t += AI_THINKING_DELAY + 1
        # Step 2: select action
        runner.update(cm, t)
        assert runner.is_active is True

        t += AI_STEP_DELAY + 1
        # Step 3: execute attack
        runner.update(cm, t)
        assert cm.has_used_action is True

        t += AI_STEP_DELAY + 1
        # Step 4: end turn
        runner.update(cm, t)
        assert runner.is_active is False
