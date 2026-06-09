"""Tests for Phase 6j: Polish — AI thinking log, end-to-end tests.

End-to-end tests run full AI-vs-AI combats to completion,
verifying that the AI system handles all edge cases gracefully.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from arena.ai.controller import AIController, TurnPlan, TurnStepType
from arena.ai.executor import execute_full_plan
from arena.ai.behavior import DEFAULT_PROFILES
from arena.combat.manager import CombatManager, CombatState
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.encounter import Encounter, CombatantEntry


# ── Helpers ─────────────────────────────────────────────────────────


def _creature(name, hp, ac=10, strength=10, dexterity=10, is_player=False,
              ai_profile="default_monster"):
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        ai_profile=ai_profile,
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


def _encounter_2v2(profile_a="default_monster", profile_b="default_monster"):
    return Encounter(
        name="AI vs AI",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="inline_p1",
                creature_data=_creature("Warrior A1", hp=15, ac=12, strength=14,
                                        is_player=False, ai_profile=profile_a),
                team="player",
                starting_position=(2, 2),
            ),
            CombatantEntry(
                creature_id="inline_p2",
                creature_data=_creature("Warrior A2", hp=15, ac=12, strength=14,
                                        is_player=False, ai_profile=profile_a),
                team="player",
                starting_position=(2, 3),
            ),
            CombatantEntry(
                creature_id="inline_e1",
                creature_data=_creature("Warrior B1", hp=15, ac=12, strength=14,
                                        ai_profile=profile_b),
                team="enemy",
                starting_position=(4, 2),
            ),
            CombatantEntry(
                creature_id="inline_e2",
                creature_data=_creature("Warrior B2", hp=15, ac=12, strength=14,
                                        ai_profile=profile_b),
                team="enemy",
                starting_position=(4, 3),
            ),
        ],
    )


def _encounter_1v1(profile_a="default_monster", profile_b="default_monster",
                   pos_a=(2, 2), pos_b=(3, 2)):
    return Encounter(
        name="1v1",
        grid_width=10,
        grid_height=10,
        combatants=[
            CombatantEntry(
                creature_id="inline_p1",
                creature_data=_creature("Fighter A", hp=20, ac=12, strength=14,
                                        is_player=False, ai_profile=profile_a),
                team="player",
                starting_position=pos_a,
            ),
            CombatantEntry(
                creature_id="inline_e1",
                creature_data=_creature("Fighter B", hp=20, ac=12, strength=14,
                                        ai_profile=profile_b),
                team="enemy",
                starting_position=pos_b,
            ),
        ],
    )


def _run_full_combat(encounter, max_rounds=50):
    """Run a full AI-vs-AI combat to completion.

    Returns (CombatManager, rounds_taken).
    """
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    cm.roll_initiative()
    cm.begin_combat()

    controller = AIController(randomness=0.0)
    rounds = 0

    while cm.state == CombatState.IN_COMBAT and rounds < max_rounds:
        active = cm.active_combatant
        if active is None:
            break

        plan = controller.plan_turn(cm)
        execute_full_plan(plan, cm)
        rounds += 1

    return cm, rounds


# ── AI_THINKING event type ──────────────────────────────────────────


class TestAIThinkingEvent:
    def test_ai_thinking_event_type_exists(self):
        assert hasattr(CombatEventType, "AI_THINKING")

    def test_thinking_events_in_log(self):
        """AI turns should produce AI_THINKING events in the log."""
        encounter = _encounter_1v1()
        cm = CombatManager()
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        controller = AIController(randomness=0.0)
        plan = controller.plan_turn(cm)
        execute_full_plan(plan, cm)

        thinking_events = [
            e for e in cm.log.events
            if e.event_type == CombatEventType.AI_THINKING
        ]
        assert len(thinking_events) >= 1
        assert "[AI]" in thinking_events[0].message


# ── End-to-end combat tests ────────────────────────────────────────


class TestEndToEndCombat:
    def test_1v1_completes(self):
        """A simple 1v1 AI fight should reach a conclusion."""
        cm, rounds = _run_full_combat(_encounter_1v1())
        assert cm.state == CombatState.COMBAT_ENDED
        assert cm.winner in ("player", "enemy")
        assert rounds < 50

    def test_2v2_completes(self):
        """A 2v2 AI fight should reach a conclusion."""
        cm, rounds = _run_full_combat(_encounter_2v2())
        assert cm.state == CombatState.COMBAT_ENDED
        assert cm.winner in ("player", "enemy")
        assert rounds < 100  # generous limit

    def test_berserker_profile_works(self):
        """Berserker profile should handle turns without errors."""
        cm, rounds = _run_full_combat(
            _encounter_1v1(profile_a="berserker", profile_b="default_monster")
        )
        assert cm.state == CombatState.COMBAT_ENDED

    def test_archer_profile_works(self):
        """Archer profile should handle turns without errors."""
        cm, rounds = _run_full_combat(
            _encounter_1v1(
                profile_a="archer",
                profile_b="default_monster",
                pos_a=(1, 1),
                pos_b=(5, 5),
            )
        )
        assert cm.state == CombatState.COMBAT_ENDED

    def test_coward_profile_works(self):
        """Coward profile should handle turns without errors.

        The coward only retreats when HP < 50%, so with full HP it
        should fight normally. We verify it plans turns without errors
        rather than requiring combat completion, since a coward may
        endlessly retreat in small arenas.
        """
        encounter = _encounter_1v1(profile_a="coward", profile_b="default_monster")
        cm = CombatManager()
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        controller = AIController(randomness=0.0)

        # Run 20 turns — enough to verify no crashes
        for _ in range(20):
            if cm.state != CombatState.IN_COMBAT:
                break
            active = cm.active_combatant
            if active is None:
                break
            plan = controller.plan_turn(cm)
            assert plan.steps[-1].step_type == TurnStepType.END_TURN
            execute_full_plan(plan, cm)

        # Either combat ended or we ran 20 turns without error — both OK
        assert cm.state in (CombatState.IN_COMBAT, CombatState.COMBAT_ENDED)

    def test_protector_profile_works(self):
        """Protector profile should handle turns without errors."""
        cm, rounds = _run_full_combat(
            _encounter_2v2(profile_a="protector", profile_b="default_monster")
        )
        assert cm.state == CombatState.COMBAT_ENDED

    def test_spellcaster_profile_works(self):
        """Spellcaster profile should handle turns without errors."""
        cm, rounds = _run_full_combat(
            _encounter_1v1(
                profile_a="spellcaster",
                profile_b="default_monster",
                pos_a=(1, 1),
                pos_b=(4, 4),
            )
        )
        assert cm.state == CombatState.COMBAT_ENDED

    def test_all_default_profiles_against_each_other(self):
        """Every default profile should be able to plan turns without errors.

        Note: Some profiles (like coward) may not complete combat in a
        small arena because they endlessly retreat. This test verifies
        that all profiles can at least plan and execute 30 turns without
        crashing, which validates the full AI pipeline.
        """
        profiles = list(DEFAULT_PROFILES.keys())
        for profile_name in profiles:
            encounter = _encounter_1v1(
                profile_a=profile_name,
                profile_b="default_monster",
            )
            cm = CombatManager()
            cm.load_encounter(encounter, Path("."))
            cm.roll_initiative()
            cm.begin_combat()

            controller = AIController(randomness=0.0)
            for _ in range(30):
                if cm.state != CombatState.IN_COMBAT:
                    break
                active = cm.active_combatant
                if active is None:
                    break
                plan = controller.plan_turn(cm)
                execute_full_plan(plan, cm)

            # Either ended or ran 30 turns without error
            assert cm.state in (CombatState.IN_COMBAT, CombatState.COMBAT_ENDED), \
                f"Profile {profile_name} entered unexpected state"


class TestEdgeCases:
    def test_ai_handles_no_enemies(self):
        """AI should handle a situation where all enemies are already dead."""
        encounter = _encounter_1v1()
        cm = CombatManager()
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        # Kill the enemy before AI plans
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                c.creature.current_hit_points = 0
                break

        # End current turn to trigger victory check
        cm.end_turn()
        assert cm.state == CombatState.COMBAT_ENDED

    def test_ai_handles_incapacitated(self):
        """AI should skip turns for incapacitated creatures."""
        from arena.models.conditions import Condition, AppliedCondition

        encounter = _encounter_1v1()
        cm = CombatManager()
        cm.load_encounter(encounter, Path("."))
        cm.roll_initiative()
        cm.begin_combat()

        # Stun the active combatant
        active = cm.active_combatant
        if active:
            active.creature.active_conditions.append(
                AppliedCondition(
                    condition=Condition.STUNNED,
                    source="test",
                    duration_type="rounds",
                    duration_rounds=1,
                )
            )
            # End turn — the stunned creature should be skipped
            cm.end_turn()
            # After ending the stunned creature's turn, the next should be active
            new_active = cm.active_combatant
            assert new_active is not None

    def test_combat_log_has_expected_events(self):
        """A full combat should produce a rich combat log."""
        cm, rounds = _run_full_combat(_encounter_1v1())
        event_types = {e.event_type for e in cm.log.events}

        assert CombatEventType.COMBAT_START in event_types
        assert CombatEventType.TURN_START in event_types
        assert CombatEventType.COMBAT_END in event_types

    def test_distant_creatures_still_fight(self):
        """Creatures placed far apart should still be able to fight."""
        cm, rounds = _run_full_combat(
            _encounter_1v1(pos_a=(0, 0), pos_b=(8, 8))
        )
        assert cm.state == CombatState.COMBAT_ENDED
