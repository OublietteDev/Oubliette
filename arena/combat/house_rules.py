"""The table's active house rules — process-wide for the combat engine.

The Arena runs ONE fight per process (launched per encounter), so the rules
ride in the encounter file and are set once at load. Combat math that a house
rule can bend (crit range, crit dice, flanking) reads them here rather than
threading a parameter through every attack-resolution call chain. A fresh
`CombatManager` resets to by-the-book, so tests and headless runs start clean.
"""

from arena.models.encounter import HouseRules

_ACTIVE = HouseRules()


def set_active(rules: HouseRules | None) -> None:
    global _ACTIVE
    _ACTIVE = rules if rules is not None else HouseRules()


def active() -> HouseRules:
    return _ACTIVE


def reset() -> None:
    set_active(None)
