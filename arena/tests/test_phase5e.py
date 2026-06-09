"""Tests for Phase 5e: Death Saving Throws."""

import pytest
from unittest.mock import patch

from arena.combat.death_saves import (
    process_death_save,
    apply_damage_to_dying,
    reset_death_saves,
)
from arena.combat.events import CombatEventType
from arena.models.abilities import AbilityScores
from arena.models.character import PlayerCharacter


# ── Helpers ───────────────────────────────────────────────────────────

def _make_dying_pc():
    """Create a PlayerCharacter at 0 HP (dying)."""
    pc = PlayerCharacter(
        name="Hero",
        max_hit_points=20,
        character_class="Fighter",
        ability_scores=AbilityScores(constitution=14),
        proficiency_bonus=2,
    )
    pc.current_hit_points = 0
    return pc


# ── process_death_save Tests ────────────────────────────────────────

class TestProcessDeathSave:
    @patch("arena.combat.death_saves.roll_die")
    def test_success(self, mock_d20):
        mock_d20.return_value = 15
        pc = _make_dying_pc()
        events = process_death_save(pc, "hero")
        assert pc.death_save_successes == 1
        assert pc.death_save_failures == 0
        assert events[0].details["result"] == "success"

    @patch("arena.combat.death_saves.roll_die")
    def test_failure(self, mock_d20):
        mock_d20.return_value = 5
        pc = _make_dying_pc()
        events = process_death_save(pc, "hero")
        assert pc.death_save_successes == 0
        assert pc.death_save_failures == 1
        assert events[0].details["result"] == "failure"

    @patch("arena.combat.death_saves.roll_die")
    def test_natural_20_regains_consciousness(self, mock_d20):
        mock_d20.return_value = 20
        pc = _make_dying_pc()
        events = process_death_save(pc, "hero")
        assert pc.current_hit_points == 1
        assert pc.death_save_successes == 0  # Reset
        assert pc.death_save_failures == 0  # Reset
        assert events[0].details["result"] == "nat20"
        assert "regain" in events[0].message.lower()

    @patch("arena.combat.death_saves.roll_die")
    def test_natural_1_counts_as_two_failures(self, mock_d20):
        mock_d20.return_value = 1
        pc = _make_dying_pc()
        events = process_death_save(pc, "hero")
        assert pc.death_save_failures == 2
        assert events[0].details["result"] == "nat1"
        assert "2 failures" in events[0].message

    @patch("arena.combat.death_saves.roll_die")
    def test_three_successes_stabilize(self, mock_d20):
        mock_d20.return_value = 12
        pc = _make_dying_pc()
        pc.death_save_successes = 2
        events = process_death_save(pc, "hero")
        # 2 + 1 = 3 successes -> stabilize
        assert any("stabilized" in e.message for e in events)
        # Death saves reset after stabilization
        assert pc.death_save_successes == 0
        assert pc.death_save_failures == 0

    @patch("arena.combat.death_saves.roll_die")
    def test_three_failures_death(self, mock_d20):
        mock_d20.return_value = 5
        pc = _make_dying_pc()
        pc.death_save_failures = 2
        events = process_death_save(pc, "hero")
        # 2 + 1 = 3 failures -> death
        assert any("died" in e.message.lower() for e in events)

    @patch("arena.combat.death_saves.roll_die")
    def test_nat1_can_cause_death(self, mock_d20):
        mock_d20.return_value = 1
        pc = _make_dying_pc()
        pc.death_save_failures = 1
        events = process_death_save(pc, "hero")
        # 1 + 2 = 3 failures -> death
        assert pc.death_save_failures == 3
        assert any("died" in e.message.lower() for e in events)

    @patch("arena.combat.death_saves.roll_die")
    def test_exactly_10_is_success(self, mock_d20):
        mock_d20.return_value = 10
        pc = _make_dying_pc()
        events = process_death_save(pc, "hero")
        assert pc.death_save_successes == 1


# ── apply_damage_to_dying Tests ─────────────────────────────────────

class TestApplyDamageToDying:
    def test_normal_damage_adds_failure(self):
        pc = _make_dying_pc()
        events = apply_damage_to_dying(pc, "hero", damage=5)
        assert pc.death_save_failures == 1

    def test_critical_adds_two_failures(self):
        pc = _make_dying_pc()
        events = apply_damage_to_dying(pc, "hero", damage=5, is_critical=True)
        assert pc.death_save_failures == 2
        assert "critical" in events[0].message.lower()

    def test_massive_damage_instant_death(self):
        pc = _make_dying_pc()  # max HP = 20
        events = apply_damage_to_dying(pc, "hero", damage=20)
        assert any(e.details.get("massive_damage") for e in events)
        assert any("dies instantly" in e.message for e in events)

    def test_damage_causes_death_at_three_failures(self):
        pc = _make_dying_pc()
        pc.death_save_failures = 2
        events = apply_damage_to_dying(pc, "hero", damage=5)
        assert pc.death_save_failures == 3
        assert any("died" in e.message.lower() for e in events)


# ── reset_death_saves Tests ─────────────────────────────────────────

class TestResetDeathSaves:
    def test_resets_counters(self):
        pc = _make_dying_pc()
        pc.death_save_successes = 2
        pc.death_save_failures = 1
        reset_death_saves(pc)
        assert pc.death_save_successes == 0
        assert pc.death_save_failures == 0
