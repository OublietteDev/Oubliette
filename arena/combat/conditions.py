"""Condition application, removal, duration tracking, and turn processing."""

from arena.models.character import Creature
from arena.models.conditions import Condition, AppliedCondition
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.stat_modifiers import get_effective_condition_immunities
from arena.combat.condition_immunity import is_immune_to_condition
from arena.combat.auras import get_aura_condition_immunities


def has_condition(creature: Creature, condition: Condition) -> bool:
    """Check if a creature currently has a specific condition."""
    return any(ac.condition == condition for ac in creature.active_conditions)


def apply_condition(
    creature: Creature,
    creature_id: str,
    condition: Condition,
    source: str,
    duration_type: str = "indefinite",
    duration_rounds: int | None = None,
    save_to_end: str | None = None,
    save_dc: int | None = None,
    extra_data: dict | None = None,
    combatants: dict | None = None,
    positions: dict | None = None,
    spell_level: int | None = None,
) -> CombatEvent | None:
    """Apply a condition to a creature.

    Returns None if the creature is immune to the condition.
    Does not stack: if the creature already has the same condition,
    replaces it (some conditions like exhaustion stack via level).

    Args:
        creature: Target creature.
        creature_id: Unique ID for logging.
        condition: The condition to apply.
        source: Name of effect/creature applying it.
        duration_type: "indefinite", "rounds", "end_of_turn", "start_of_turn".
        duration_rounds: Number of rounds (for "rounds" duration).
        save_to_end: Ability for save-to-end checks (e.g., "wisdom").
        save_dc: DC for save-to-end checks.
        extra_data: Additional data (e.g., frightened_of).

    Returns:
        A CONDITION_APPLIED event, or None if immune.
    """
    # Check static condition immunity (equipment, feats, features with grants_condition_immunities)
    if condition.value in [ci.lower() for ci in get_effective_condition_immunities(creature)]:
        return None

    # Check active/resource-gated condition immunity (e.g., Mindless Rage)
    if is_immune_to_condition(creature, condition.value):
        return None

    # Check aura-based condition immunity (e.g., Aura of Courage)
    if combatants is not None and positions is not None:
        aura_immunities = get_aura_condition_immunities(
            creature, creature_id, combatants, positions
        )
        if condition.value in [ci.lower() for ci in aura_immunities]:
            return None

    applied = AppliedCondition(
        condition=condition,
        source=source,
        duration_type=duration_type,
        duration_rounds=duration_rounds,
        save_to_end=save_to_end,
        save_dc=save_dc,
        extra_data=extra_data or {},
        spell_level=spell_level,
    )

    # For exhaustion, stack levels instead of replacing
    if condition == Condition.EXHAUSTION:
        existing = _find_condition(creature, condition)
        if existing:
            existing.level = min(6, existing.level + 1)
            extra = _exhaustion_side_effects(creature, existing.level)
            return CombatEvent(
                event_type=CombatEventType.CONDITION_APPLIED,
                message=(
                    f"{creature.name} gains a level of exhaustion "
                    f"(now level {existing.level}){extra}"
                ),
                source_id=creature_id,
                details={
                    "condition": condition.value,
                    "level": existing.level,
                    "source": source,
                },
            )

    # Remove existing instance of the same condition before adding new
    _remove_condition_instances(creature, condition)
    creature.active_conditions.append(applied)

    duration_text = ""
    if duration_type == "rounds" and duration_rounds is not None:
        duration_text = f" for {duration_rounds} round(s)"
    elif duration_type in ("end_of_turn", "start_of_turn"):
        duration_text = f" (save {save_to_end} DC {save_dc} to end)"

    return CombatEvent(
        event_type=CombatEventType.CONDITION_APPLIED,
        message=f"{creature.name} is now {condition.value}{duration_text}",
        source_id=creature_id,
        details={
            "condition": condition.value,
            "source": source,
            "duration_type": duration_type,
            "duration_rounds": duration_rounds,
        },
    )


def remove_condition(
    creature: Creature,
    creature_id: str,
    condition: Condition,
    source: str | None = None,
) -> CombatEvent | None:
    """Remove a condition from a creature.

    Args:
        creature: The creature to remove the condition from.
        creature_id: Unique ID for logging.
        condition: The condition to remove.
        source: If specified, only remove the instance from this source.
            If None, remove all instances of the condition.

    Returns:
        A CONDITION_REMOVED event, or None if the condition wasn't present.
    """
    if source is not None:
        removed = [
            ac for ac in creature.active_conditions
            if ac.condition == condition and ac.source == source
        ]
        creature.active_conditions = [
            ac for ac in creature.active_conditions
            if not (ac.condition == condition and ac.source == source)
        ]
    else:
        removed = [
            ac for ac in creature.active_conditions
            if ac.condition == condition
        ]
        creature.active_conditions = [
            ac for ac in creature.active_conditions
            if ac.condition != condition
        ]

    if not removed:
        return None

    return CombatEvent(
        event_type=CombatEventType.CONDITION_REMOVED,
        message=f"{creature.name} is no longer {condition.value}",
        source_id=creature_id,
        details={
            "condition": condition.value,
            "source": source,
        },
    )


def process_start_of_turn(
    creature: Creature, creature_id: str
) -> list[CombatEvent]:
    """Process condition effects at the start of a creature's turn.

    - Conditions with duration_type "start_of_turn" trigger save-to-end.
    - Conditions with duration_type "rounds" decrement on start of turn.

    Returns list of events produced.
    """
    events: list[CombatEvent] = []

    # Process save-to-end conditions (start of turn saves)
    to_remove: list[Condition] = []
    for ac in list(creature.active_conditions):
        if ac.duration_type == "start_of_turn" and ac.save_to_end and ac.save_dc:
            from arena.combat.actions import resolve_saving_throw

            success, save_event = resolve_saving_throw(
                creature, creature_id, ac.save_to_end, ac.save_dc,
                is_spell_save=ac.spell_level is not None,
                imposes_conditions=[ac.condition.value],
            )
            events.append(save_event)
            if success:
                to_remove.append(ac.condition)

    for cond in to_remove:
        remove_event = remove_condition(creature, creature_id, cond)
        if remove_event:
            events.append(remove_event)

    # Decrement round-based durations
    for ac in list(creature.active_conditions):
        if ac.duration_type == "rounds" and ac.duration_rounds is not None:
            ac.duration_rounds -= 1
            if ac.duration_rounds <= 0:
                remove_event = remove_condition(
                    creature, creature_id, ac.condition, source=ac.source
                )
                if remove_event:
                    events.append(remove_event)

    return events


def process_end_of_turn(
    creature: Creature, creature_id: str
) -> list[CombatEvent]:
    """Process condition effects at the end of a creature's turn.

    - Conditions with duration_type "end_of_turn" trigger save-to-end.

    Returns list of events produced.
    """
    events: list[CombatEvent] = []

    # Process save-to-end conditions (end of turn saves)
    to_remove: list[Condition] = []
    for ac in list(creature.active_conditions):
        if ac.duration_type == "end_of_turn" and ac.save_to_end and ac.save_dc:
            from arena.combat.actions import resolve_saving_throw

            success, save_event = resolve_saving_throw(
                creature, creature_id, ac.save_to_end, ac.save_dc,
                is_spell_save=ac.spell_level is not None,
                imposes_conditions=[ac.condition.value],
            )
            events.append(save_event)
            if success:
                to_remove.append(ac.condition)

    for cond in to_remove:
        remove_event = remove_condition(creature, creature_id, cond)
        if remove_event:
            events.append(remove_event)

    return events


# ── Internal helpers ─────────────────────────────────────────────────

def _exhaustion_side_effects(creature: Creature, level: int) -> str:
    """Apply the HP consequences of crossing an exhaustion tier (D-COND-2) and
    return a message suffix. Levels 1-3 (ability-check / speed / attack-save
    penalties) are pure queries handled in condition_effects; only the HP-side
    tiers mutate state here.

    - Level 4: hit-point maximum is halved, so current HP is capped to it.
    - Level 6: death. The Arena renders this as dropping to 0 HP — a monster is
      then defeated; a downed PC stays under the engine's usual 0-HP mercy
      (consistent with Phase D leaving downed-PC RAW out of scope).
    """
    if level >= 6:
        creature.current_hit_points = 0
        return " — level 6 exhaustion: it collapses!"
    if level >= 4:
        from arena.combat.condition_effects import effective_max_hp
        cap = effective_max_hp(creature)
        cur = creature.current_hit_points if creature.current_hit_points is not None else 0
        if cur > cap:
            creature.current_hit_points = cap
        return f" — its hit-point maximum is halved (now {cap})"
    return ""


def _find_condition(
    creature: Creature, condition: Condition
) -> AppliedCondition | None:
    """Find the first instance of a condition on a creature."""
    for ac in creature.active_conditions:
        if ac.condition == condition:
            return ac
    return None


def _remove_condition_instances(creature: Creature, condition: Condition) -> None:
    """Remove all instances of a condition from a creature (internal)."""
    creature.active_conditions = [
        ac for ac in creature.active_conditions if ac.condition != condition
    ]
