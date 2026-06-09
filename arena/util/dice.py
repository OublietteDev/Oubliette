"""Dice rolling utilities."""

import random
import re


def roll_die(sides: int) -> int:
    """Roll a single die with the given number of sides."""
    return random.randint(1, sides)


def roll_dice(count: int, sides: int) -> list[int]:
    """Roll multiple dice and return individual results."""
    return [roll_die(sides) for _ in range(count)]


def parse_dice_expression(expression: str) -> tuple[int, int, int]:
    """
    Parse a dice expression like '2d6+3' or '1d20-1'.

    Also supports flat numbers like '10' (treated as 0d0+10).

    Returns:
        Tuple of (count, sides, modifier)
    """
    expression = expression.lower().replace(" ", "")

    # Match patterns like 2d6, 2d6+3, 2d6-2, d20, etc.
    match = re.match(r"(\d*)d(\d+)([+-]\d+)?", expression)
    if match:
        count = int(match.group(1)) if match.group(1) else 1
        sides = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0
        return count, sides, modifier

    # Flat number (e.g., "10", "-5", "+3")
    flat_match = re.match(r"^([+-]?\d+)$", expression)
    if flat_match:
        return 0, 0, int(flat_match.group(1))

    raise ValueError(f"Invalid dice expression: {expression}")


def roll_expression(expression: str) -> tuple[int, list[int]]:
    """
    Roll a dice expression and return total and individual rolls.

    Args:
        expression: A dice expression like '2d6+3' or a flat number like '10'

    Returns:
        Tuple of (total, individual_rolls)
    """
    count, sides, modifier = parse_dice_expression(expression)
    if count == 0:
        # Flat number — no dice to roll
        return modifier, []
    rolls = roll_dice(count, sides)
    total = sum(rolls) + modifier
    return total, rolls


def roll_with_advantage(sides: int = 20) -> tuple[int, int, int]:
    """
    Roll with advantage (roll twice, take higher).

    Returns:
        Tuple of (result, roll1, roll2)
    """
    roll1 = roll_die(sides)
    roll2 = roll_die(sides)
    return max(roll1, roll2), roll1, roll2


def roll_with_disadvantage(sides: int = 20) -> tuple[int, int, int]:
    """
    Roll with disadvantage (roll twice, take lower).

    Returns:
        Tuple of (result, roll1, roll2)
    """
    roll1 = roll_die(sides)
    roll2 = roll_die(sides)
    return min(roll1, roll2), roll1, roll2
