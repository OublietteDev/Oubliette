"""Pure ability/skill math and check resolution."""

from __future__ import annotations

from typing import Literal

CheckOutcome = Literal["success", "failure"]


def ability_modifier(score: int) -> int:
    """SRD ability modifier: floor((score - 10) / 2)."""
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    """SRD proficiency bonus by level (+2 at 1-4, +3 at 5-8, ...)."""
    return 2 + (max(1, level) - 1) // 4


def resolve_check(total: int, dc: int) -> CheckOutcome:
    """A check meets-or-beats its DC to succeed. Pure: total in, verdict out."""
    return "success" if total >= dc else "failure"
