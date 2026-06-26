"""Death saving throw mechanics for creatures at 0 HP."""

from arena.models.character import Creature
from arena.combat.events import CombatEvent, CombatEventType
from arena.util.dice import roll_die


def stabilize_creature(creature: Creature) -> None:
    """Stabilize a dying creature: clear its death saves and mark it stable so
    it stops rolling (stays at 0 HP, unconscious). Same end-state the third
    death-save success produces."""
    reset_death_saves(creature)
    if hasattr(creature, "is_stabilized"):
        creature.is_stabilized = True


def process_death_save(creature: Creature, creature_id: str) -> list[CombatEvent]:
    """Roll a death saving throw for a creature at 0 HP.

    Per 5e rules:
    - Roll a d20 (no modifiers by default).
    - >= 10: success. < 10: failure.
    - Natural 20: regain 1 HP, reset death saves.
    - Natural 1: counts as 2 failures.
    - 3 successes: stabilize (unconscious but stable).
    - 3 failures: creature dies.

    Args:
        creature: The creature making the death save.
        creature_id: Unique ID for event logging.

    Returns:
        List of events (death save result, possible stabilization/death).
    """
    events: list[CombatEvent] = []
    natural = roll_die(20)

    if natural == 20:
        # Natural 20: regain 1 HP
        creature.current_hit_points = 1
        reset_death_saves(creature)
        events.append(
            CombatEvent(
                event_type=CombatEventType.DEATH_SAVE,
                message=(
                    f"{creature.name} rolls a natural 20 on their death save! "
                    f"They regain 1 HP and regain consciousness!"
                ),
                source_id=creature_id,
                details={
                    "roll": natural,
                    "result": "nat20",
                    "successes": 0,
                    "failures": 0,
                },
            )
        )
        return events

    if natural == 1:
        # Natural 1: 2 failures
        failures = _add_failures(creature, 2)
    elif natural >= 10:
        # Success
        successes = _add_successes(creature, 1)
    else:
        # Failure
        failures = _add_failures(creature, 1)

    # Get current counts for the event
    successes = _get_successes(creature)
    failures = _get_failures(creature)

    result = "success" if natural >= 10 else "failure"
    if natural == 1:
        result = "nat1"

    events.append(
        CombatEvent(
            event_type=CombatEventType.DEATH_SAVE,
            message=(
                f"{creature.name} death save: {natural} - "
                f"{'SUCCESS' if natural >= 10 else 'FAILURE'}"
                f"{' (counts as 2 failures!)' if natural == 1 else ''}"
                f" [{successes} successes, {failures} failures]"
            ),
            source_id=creature_id,
            details={
                "roll": natural,
                "result": result,
                "successes": successes,
                "failures": failures,
            },
        )
    )

    # Check for stabilization or death
    if successes >= 3:
        reset_death_saves(creature)
        # Mark as stabilized so no more death saves are rolled
        if hasattr(creature, "is_stabilized"):
            creature.is_stabilized = True
        events.append(
            CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{creature.name} has stabilized!",
                source_id=creature_id,
                details={"stabilized": True},
            )
        )
    elif failures >= 3:
        events.append(
            CombatEvent(
                event_type=CombatEventType.CREATURE_DOWNED,
                message=f"{creature.name} has died!",
                source_id=creature_id,
                details={"died": True},
            )
        )

    return events


def apply_damage_to_dying(
    creature: Creature,
    creature_id: str,
    damage: int,
    is_critical: bool = False,
) -> list[CombatEvent]:
    """Handle damage taken by a creature already at 0 HP.

    Per 5e rules:
    - Any damage causes 1 death save failure.
    - Critical hit causes 2 death save failures.
    - Damage >= max HP from a single source: instant death.

    Args:
        creature: The creature taking damage at 0 HP.
        creature_id: Unique ID for event logging.
        damage: Amount of damage taken.
        is_critical: Whether the hit was a critical.

    Returns:
        List of events.
    """
    events: list[CombatEvent] = []

    # Massive damage = instant death
    if damage >= creature.max_hit_points:
        events.append(
            CombatEvent(
                event_type=CombatEventType.CREATURE_DOWNED,
                message=(
                    f"{creature.name} takes massive damage ({damage} >= "
                    f"{creature.max_hit_points} max HP) and dies instantly!"
                ),
                source_id=creature_id,
                details={"died": True, "massive_damage": True},
            )
        )
        return events

    # Damage breaks stabilization — creature starts dying again
    if hasattr(creature, "is_stabilized") and creature.is_stabilized:
        creature.is_stabilized = False

    # Regular damage at 0 HP
    fail_count = 2 if is_critical else 1
    _add_failures(creature, fail_count)

    failures = _get_failures(creature)
    successes = _get_successes(creature)

    crit_note = " (critical - 2 failures!)" if is_critical else ""
    events.append(
        CombatEvent(
            event_type=CombatEventType.DEATH_SAVE,
            message=(
                f"{creature.name} takes damage while dying{crit_note}! "
                f"[{successes} successes, {failures} failures]"
            ),
            source_id=creature_id,
            details={
                "result": "damage",
                "failures_added": fail_count,
                "successes": successes,
                "failures": failures,
            },
        )
    )

    if failures >= 3:
        events.append(
            CombatEvent(
                event_type=CombatEventType.CREATURE_DOWNED,
                message=f"{creature.name} has died!",
                source_id=creature_id,
                details={"died": True},
            )
        )

    return events


def reset_death_saves(creature: Creature) -> None:
    """Reset death save counters (e.g., after healing or stabilization)."""
    # Use the PlayerCharacter fields if available
    if hasattr(creature, "death_save_successes"):
        creature.death_save_successes = 0
    if hasattr(creature, "death_save_failures"):
        creature.death_save_failures = 0
    if hasattr(creature, "is_stabilized"):
        creature.is_stabilized = False


# ── Internal helpers ─────────────────────────────────────────────────

def _get_successes(creature: Creature) -> int:
    return getattr(creature, "death_save_successes", 0)


def _get_failures(creature: Creature) -> int:
    return getattr(creature, "death_save_failures", 0)


def _add_successes(creature: Creature, count: int) -> int:
    current = _get_successes(creature)
    new_val = min(3, current + count)
    if hasattr(creature, "death_save_successes"):
        creature.death_save_successes = new_val
    return new_val


def _add_failures(creature: Creature, count: int) -> int:
    current = _get_failures(creature)
    new_val = min(3, current + count)
    if hasattr(creature, "death_save_failures"):
        creature.death_save_failures = new_val
    return new_val
