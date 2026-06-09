"""Tests for dice rolling utilities."""

import pytest
from arena.util.dice import (
    roll_die,
    roll_dice,
    parse_dice_expression,
    roll_expression,
    roll_with_advantage,
    roll_with_disadvantage,
)


class TestRollDie:
    """Tests for single die rolling."""

    def test_d20_range(self):
        """d20 should roll between 1 and 20."""
        for _ in range(100):
            result = roll_die(20)
            assert 1 <= result <= 20

    def test_d6_range(self):
        """d6 should roll between 1 and 6."""
        for _ in range(100):
            result = roll_die(6)
            assert 1 <= result <= 6

    def test_d1(self):
        """d1 should always be 1."""
        for _ in range(10):
            assert roll_die(1) == 1


class TestRollDice:
    """Tests for multiple dice rolling."""

    def test_multiple_dice_count(self):
        """Should return correct number of results."""
        results = roll_dice(4, 6)
        assert len(results) == 4

    def test_multiple_dice_range(self):
        """All results should be in valid range."""
        results = roll_dice(10, 8)
        for r in results:
            assert 1 <= r <= 8


class TestParseDiceExpression:
    """Tests for dice expression parsing."""

    def test_simple_expression(self):
        """Parse simple dice expression."""
        count, sides, mod = parse_dice_expression("2d6")
        assert count == 2
        assert sides == 6
        assert mod == 0

    def test_expression_with_positive_modifier(self):
        """Parse expression with positive modifier."""
        count, sides, mod = parse_dice_expression("1d20+5")
        assert count == 1
        assert sides == 20
        assert mod == 5

    def test_expression_with_negative_modifier(self):
        """Parse expression with negative modifier."""
        count, sides, mod = parse_dice_expression("3d6-2")
        assert count == 3
        assert sides == 6
        assert mod == -2

    def test_expression_no_count(self):
        """Parse expression without explicit count (assumes 1)."""
        count, sides, mod = parse_dice_expression("d20")
        assert count == 1
        assert sides == 20

    def test_expression_with_spaces(self):
        """Parse expression with spaces."""
        count, sides, mod = parse_dice_expression("2d6 + 3")
        assert count == 2
        assert sides == 6
        assert mod == 3

    def test_case_insensitive(self):
        """Parse expression regardless of case."""
        count, sides, mod = parse_dice_expression("2D6+3")
        assert count == 2
        assert sides == 6
        assert mod == 3

    def test_flat_number(self):
        """Parse a flat number with no dice (e.g., '10' for Lay on Hands)."""
        count, sides, mod = parse_dice_expression("10")
        assert count == 0
        assert sides == 0
        assert mod == 10

    def test_flat_zero(self):
        """Parse zero as a flat number."""
        count, sides, mod = parse_dice_expression("0")
        assert count == 0
        assert sides == 0
        assert mod == 0

    def test_flat_large_number(self):
        """Parse a larger flat number."""
        count, sides, mod = parse_dice_expression("25")
        assert count == 0
        assert sides == 0
        assert mod == 25

    def test_invalid_expression(self):
        """Invalid expression should raise ValueError."""
        with pytest.raises(ValueError):
            parse_dice_expression("invalid")


class TestRollExpression:
    """Tests for rolling dice expressions."""

    def test_roll_expression_returns_tuple(self):
        """Should return (total, individual_rolls)."""
        total, rolls = roll_expression("3d6")
        assert isinstance(total, int)
        assert isinstance(rolls, list)
        assert len(rolls) == 3

    def test_roll_expression_total(self):
        """Total should equal sum of rolls plus modifier."""
        total, rolls = roll_expression("2d6+5")
        assert total == sum(rolls) + 5

    def test_roll_expression_range(self):
        """Results should be in valid range."""
        for _ in range(50):
            total, rolls = roll_expression("4d6")
            assert 4 <= total <= 24
            assert all(1 <= r <= 6 for r in rolls)

    def test_flat_number_expression(self):
        """Flat number like '10' should return (10, []) with no dice."""
        total, rolls = roll_expression("10")
        assert total == 10
        assert rolls == []

    def test_flat_zero_expression(self):
        """Flat zero should return (0, [])."""
        total, rolls = roll_expression("0")
        assert total == 0
        assert rolls == []

    def test_flat_25_expression(self):
        """Flat 25 should return (25, [])."""
        total, rolls = roll_expression("25")
        assert total == 25
        assert rolls == []


class TestAdvantageDisadvantage:
    """Tests for advantage and disadvantage rolling."""

    def test_advantage_returns_three_values(self):
        """Advantage should return (result, roll1, roll2)."""
        result, r1, r2 = roll_with_advantage()
        assert isinstance(result, int)
        assert isinstance(r1, int)
        assert isinstance(r2, int)

    def test_advantage_takes_higher(self):
        """Advantage should take the higher roll."""
        for _ in range(50):
            result, r1, r2 = roll_with_advantage()
            assert result == max(r1, r2)

    def test_disadvantage_takes_lower(self):
        """Disadvantage should take the lower roll."""
        for _ in range(50):
            result, r1, r2 = roll_with_disadvantage()
            assert result == min(r1, r2)

    def test_advantage_range(self):
        """Advantage results should be in valid range."""
        for _ in range(50):
            result, r1, r2 = roll_with_advantage()
            assert 1 <= result <= 20
            assert 1 <= r1 <= 20
            assert 1 <= r2 <= 20

    def test_custom_die_size(self):
        """Should work with custom die sizes."""
        result, r1, r2 = roll_with_advantage(sides=6)
        assert 1 <= result <= 6
