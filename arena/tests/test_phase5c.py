"""Tests for Phase 5c: Condition Engine."""

import pytest
from unittest.mock import patch

from arena.combat.conditions import (
    apply_condition,
    remove_condition,
    has_condition,
    process_start_of_turn,
    process_end_of_turn,
)
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.conditions import Condition, AppliedCondition


# ── Helpers ───────────────────────────────────────────────────────────

def _make_creature(condition_immunities=None, wisdom=10):
    return Creature(
        name="Test",
        max_hit_points=20,
        ability_scores=AbilityScores(wisdom=wisdom),
        proficiency_bonus=2,
        condition_immunities=condition_immunities or [],
    )


# ── has_condition Tests ──────────────────────────────────────────────

class TestHasCondition:
    def test_no_conditions(self):
        creature = _make_creature()
        assert has_condition(creature, Condition.POISONED) is False

    def test_has_condition(self):
        creature = _make_creature()
        creature.active_conditions.append(
            AppliedCondition(condition=Condition.POISONED, source="trap")
        )
        assert has_condition(creature, Condition.POISONED) is True

    def test_different_condition(self):
        creature = _make_creature()
        creature.active_conditions.append(
            AppliedCondition(condition=Condition.POISONED, source="trap")
        )
        assert has_condition(creature, Condition.BLINDED) is False


# ── apply_condition Tests ────────────────────────────────────────────

class TestApplyCondition:
    def test_basic_apply(self):
        creature = _make_creature()
        event = apply_condition(creature, "test", Condition.POISONED, "venom")
        assert event is not None
        assert event.event_type == CombatEventType.CONDITION_APPLIED
        assert has_condition(creature, Condition.POISONED)
        assert "poisoned" in event.message

    def test_immune_returns_none(self):
        creature = _make_creature(condition_immunities=["poisoned"])
        event = apply_condition(creature, "test", Condition.POISONED, "venom")
        assert event is None
        assert not has_condition(creature, Condition.POISONED)

    def test_replaces_existing_same_condition(self):
        creature = _make_creature()
        apply_condition(creature, "test", Condition.POISONED, "source_a")
        apply_condition(creature, "test", Condition.POISONED, "source_b")
        # Should have exactly one POISONED condition, from source_b
        poisoned = [
            ac for ac in creature.active_conditions
            if ac.condition == Condition.POISONED
        ]
        assert len(poisoned) == 1
        assert poisoned[0].source == "source_b"

    def test_exhaustion_stacks_levels(self):
        creature = _make_creature()
        apply_condition(creature, "test", Condition.EXHAUSTION, "march")
        event = apply_condition(creature, "test", Condition.EXHAUSTION, "starvation")
        # Should still be one exhaustion, but at level 2
        exhaustion = [
            ac for ac in creature.active_conditions
            if ac.condition == Condition.EXHAUSTION
        ]
        assert len(exhaustion) == 1
        assert exhaustion[0].level == 2
        assert event.details["level"] == 2

    def test_exhaustion_caps_at_6(self):
        creature = _make_creature()
        for _ in range(7):
            apply_condition(creature, "test", Condition.EXHAUSTION, "forced_march")
        exhaustion = [
            ac for ac in creature.active_conditions
            if ac.condition == Condition.EXHAUSTION
        ]
        assert exhaustion[0].level == 6  # Capped

    def test_duration_rounds(self):
        creature = _make_creature()
        event = apply_condition(
            creature, "test", Condition.BLINDED, "spell",
            duration_type="rounds", duration_rounds=3,
        )
        assert "3 round(s)" in event.message
        ac = creature.active_conditions[0]
        assert ac.duration_type == "rounds"
        assert ac.duration_rounds == 3

    def test_save_to_end(self):
        creature = _make_creature()
        event = apply_condition(
            creature, "test", Condition.STUNNED, "dragon",
            duration_type="end_of_turn",
            save_to_end="wisdom",
            save_dc=15,
        )
        ac = creature.active_conditions[0]
        assert ac.save_to_end == "wisdom"
        assert ac.save_dc == 15

    def test_extra_data(self):
        creature = _make_creature()
        apply_condition(
            creature, "test", Condition.FRIGHTENED, "dragon",
            extra_data={"frightened_of": "dragon"},
        )
        ac = creature.active_conditions[0]
        assert ac.extra_data["frightened_of"] == "dragon"


# ── remove_condition Tests ───────────────────────────────────────────

class TestRemoveCondition:
    def test_basic_remove(self):
        creature = _make_creature()
        apply_condition(creature, "test", Condition.POISONED, "trap")
        event = remove_condition(creature, "test", Condition.POISONED)
        assert event is not None
        assert event.event_type == CombatEventType.CONDITION_REMOVED
        assert not has_condition(creature, Condition.POISONED)

    def test_remove_not_present(self):
        creature = _make_creature()
        event = remove_condition(creature, "test", Condition.POISONED)
        assert event is None

    def test_remove_by_source(self):
        creature = _make_creature()
        apply_condition(creature, "test", Condition.FRIGHTENED, "dragon")
        # Try removing with wrong source
        event = remove_condition(
            creature, "test", Condition.FRIGHTENED, source="spider"
        )
        assert event is None
        assert has_condition(creature, Condition.FRIGHTENED)

        # Remove with correct source
        event = remove_condition(
            creature, "test", Condition.FRIGHTENED, source="dragon"
        )
        assert event is not None
        assert not has_condition(creature, Condition.FRIGHTENED)


# ── Turn Processing Tests ────────────────────────────────────────────

class TestProcessStartOfTurn:
    @patch("arena.combat.actions.roll_die")
    def test_start_of_turn_save_success(self, mock_d20):
        mock_d20.return_value = 18  # High roll = success
        creature = _make_creature(wisdom=14)  # +2 mod
        apply_condition(
            creature, "test", Condition.STUNNED, "dragon",
            duration_type="start_of_turn",
            save_to_end="wisdom", save_dc=13,
        )
        events = process_start_of_turn(creature, "test")
        # Should have a save event + removal event
        event_types = [e.event_type for e in events]
        assert CombatEventType.SAVING_THROW in event_types
        assert CombatEventType.CONDITION_REMOVED in event_types
        assert not has_condition(creature, Condition.STUNNED)

    @patch("arena.combat.actions.roll_die")
    def test_start_of_turn_save_failure(self, mock_d20):
        mock_d20.return_value = 3  # Low roll = failure
        creature = _make_creature(wisdom=10)
        apply_condition(
            creature, "test", Condition.STUNNED, "dragon",
            duration_type="start_of_turn",
            save_to_end="wisdom", save_dc=15,
        )
        events = process_start_of_turn(creature, "test")
        event_types = [e.event_type for e in events]
        assert CombatEventType.SAVING_THROW in event_types
        assert CombatEventType.CONDITION_REMOVED not in event_types
        assert has_condition(creature, Condition.STUNNED)

    def test_round_duration_decrements(self):
        creature = _make_creature()
        apply_condition(
            creature, "test", Condition.BLINDED, "spell",
            duration_type="rounds", duration_rounds=2,
        )
        events = process_start_of_turn(creature, "test")
        # Duration decremented from 2 to 1, not yet removed
        assert has_condition(creature, Condition.BLINDED)
        ac = creature.active_conditions[0]
        assert ac.duration_rounds == 1

    def test_round_duration_expires(self):
        creature = _make_creature()
        apply_condition(
            creature, "test", Condition.BLINDED, "spell",
            duration_type="rounds", duration_rounds=1,
        )
        events = process_start_of_turn(creature, "test")
        # Duration decremented from 1 to 0, should be removed
        assert not has_condition(creature, Condition.BLINDED)
        event_types = [e.event_type for e in events]
        assert CombatEventType.CONDITION_REMOVED in event_types

    def test_indefinite_not_affected(self):
        creature = _make_creature()
        apply_condition(creature, "test", Condition.POISONED, "curse")
        events = process_start_of_turn(creature, "test")
        assert has_condition(creature, Condition.POISONED)
        assert len(events) == 0


class TestProcessEndOfTurn:
    @patch("arena.combat.actions.roll_die")
    def test_end_of_turn_save_success(self, mock_d20):
        mock_d20.return_value = 18
        creature = _make_creature(wisdom=14)
        apply_condition(
            creature, "test", Condition.CHARMED, "vampire",
            duration_type="end_of_turn",
            save_to_end="wisdom", save_dc=13,
        )
        events = process_end_of_turn(creature, "test")
        event_types = [e.event_type for e in events]
        assert CombatEventType.SAVING_THROW in event_types
        assert CombatEventType.CONDITION_REMOVED in event_types
        assert not has_condition(creature, Condition.CHARMED)

    @patch("arena.combat.actions.roll_die")
    def test_end_of_turn_save_failure(self, mock_d20):
        mock_d20.return_value = 3
        creature = _make_creature(wisdom=10)
        apply_condition(
            creature, "test", Condition.CHARMED, "vampire",
            duration_type="end_of_turn",
            save_to_end="wisdom", save_dc=15,
        )
        events = process_end_of_turn(creature, "test")
        assert has_condition(creature, Condition.CHARMED)
