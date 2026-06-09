"""Tests for ability scores."""

import pytest
from arena.models.abilities import AbilityScores


class TestAbilityScores:
    """Tests for the AbilityScores model."""

    def test_default_scores(self):
        """Default scores should all be 10."""
        scores = AbilityScores()
        assert scores.strength == 10
        assert scores.dexterity == 10
        assert scores.constitution == 10
        assert scores.intelligence == 10
        assert scores.wisdom == 10
        assert scores.charisma == 10

    def test_custom_scores(self):
        """Custom scores should be stored correctly."""
        scores = AbilityScores(
            strength=18,
            dexterity=14,
            constitution=16,
            intelligence=8,
            wisdom=12,
            charisma=10,
        )
        assert scores.strength == 18
        assert scores.dexterity == 14
        assert scores.constitution == 16
        assert scores.intelligence == 8
        assert scores.wisdom == 12
        assert scores.charisma == 10

    def test_modifier_calculation(self):
        """Modifiers should be calculated correctly."""
        scores = AbilityScores(
            strength=1,    # -5
            dexterity=6,   # -2
            constitution=10,  # 0
            intelligence=14,  # +2
            wisdom=18,     # +4
            charisma=20,   # +5
        )
        assert scores.get_modifier("strength") == -5
        assert scores.get_modifier("dexterity") == -2
        assert scores.get_modifier("constitution") == 0
        assert scores.get_modifier("intelligence") == 2
        assert scores.get_modifier("wisdom") == 4
        assert scores.get_modifier("charisma") == 5

    def test_modifier_edge_cases(self):
        """Test modifier calculation at boundary values."""
        # Score of 10-11 should give +0
        scores = AbilityScores(strength=10, dexterity=11)
        assert scores.get_modifier("strength") == 0
        assert scores.get_modifier("dexterity") == 0

        # Score of 12-13 should give +1
        scores = AbilityScores(strength=12, dexterity=13)
        assert scores.get_modifier("strength") == 1
        assert scores.get_modifier("dexterity") == 1

    def test_get_score(self):
        """get_score should return the raw ability score."""
        scores = AbilityScores(strength=15)
        assert scores.get_score("strength") == 15
        assert scores.get_score("STRENGTH") == 15  # Case insensitive

    def test_score_validation_min(self):
        """Scores below 1 should be rejected."""
        with pytest.raises(ValueError):
            AbilityScores(strength=0)

    def test_score_validation_max(self):
        """Scores above 30 should be rejected."""
        with pytest.raises(ValueError):
            AbilityScores(strength=31)

    def test_valid_extreme_scores(self):
        """Scores of 1 and 30 should be valid."""
        scores = AbilityScores(strength=1, charisma=30)
        assert scores.strength == 1
        assert scores.charisma == 30
        assert scores.get_modifier("strength") == -5
        assert scores.get_modifier("charisma") == 10
