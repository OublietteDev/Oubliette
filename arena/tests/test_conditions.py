"""Tests for condition models."""

import pytest
from arena.models.conditions import Condition, AppliedCondition


class TestCondition:
    """Tests for the Condition enum."""

    def test_standard_conditions(self):
        """All standard 5e conditions should be available."""
        standard_conditions = [
            "blinded", "charmed", "deafened", "exhaustion", "frightened",
            "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
            "poisoned", "prone", "restrained", "stunned", "unconscious",
        ]
        for cond in standard_conditions:
            assert Condition(cond) is not None

    def test_combat_pseudo_conditions(self):
        """Combat-specific pseudo-conditions should be available."""
        assert Condition.CONCENTRATING.value == "concentrating"
        assert Condition.DODGING.value == "dodging"
        assert Condition.HELPED.value == "helped"


class TestAppliedCondition:
    """Tests for the AppliedCondition model."""

    def test_basic_condition(self):
        """Basic condition application."""
        cond = AppliedCondition(
            condition=Condition.POISONED,
            source="Giant Spider",
        )
        assert cond.condition == Condition.POISONED
        assert cond.source == "Giant Spider"
        assert cond.duration_type == "indefinite"

    def test_condition_with_duration(self):
        """Condition with round-based duration."""
        cond = AppliedCondition(
            condition=Condition.FRIGHTENED,
            source="Dragon Fear",
            duration_type="rounds",
            duration_rounds=10,
        )
        assert cond.duration_type == "rounds"
        assert cond.duration_rounds == 10

    def test_condition_with_save(self):
        """Condition that can be ended with a save."""
        cond = AppliedCondition(
            condition=Condition.PARALYZED,
            source="Hold Person",
            duration_type="end_of_turn",
            save_to_end="wisdom",
            save_dc=15,
        )
        assert cond.save_to_end == "wisdom"
        assert cond.save_dc == 15

    def test_exhaustion_levels(self):
        """Exhaustion should track levels."""
        cond = AppliedCondition(
            condition=Condition.EXHAUSTION,
            source="Forced March",
            level=2,
        )
        assert cond.level == 2

    def test_condition_extra_data(self):
        """Conditions can have extra data."""
        cond = AppliedCondition(
            condition=Condition.FRIGHTENED,
            source="Adult Red Dragon",
            extra_data={"frightened_of": "Adult Red Dragon"},
        )
        assert cond.extra_data["frightened_of"] == "Adult Red Dragon"

    def test_concentration_condition(self):
        """Concentration tracking as a condition."""
        cond = AppliedCondition(
            condition=Condition.CONCENTRATING,
            source="Bless",
            extra_data={"spell": "Bless", "targets": ["Fighter", "Rogue"]},
        )
        assert cond.condition == Condition.CONCENTRATING
        assert cond.extra_data["spell"] == "Bless"
