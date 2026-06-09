"""Counterspell and spell interruption mechanics.

Counterspell: reaction to interrupt a spell being cast.
- Auto-succeeds if target spell level <= slot level used
- Otherwise: ability check DC = 10 + target spell level
"""

from arena.models.actions import Action
from arena.models.character import Creature
from arena.util.dice import roll_die
from arena.combat.stat_modifiers import get_effective_ability_modifier
from arena.combat.events import CombatEvent, CombatEventType


def can_counterspell(
    counterspell_action: Action,
    target_spell: Action,
    cast_level: int | None = None,
) -> bool:
    """Check if a counterspell action can attempt to counter a target spell.

    Args:
        counterspell_action: The Counterspell action being used.
        target_spell: The spell being cast that we want to counter.
        cast_level: The slot level used for counterspell (None = base spell_level).
    """
    if not counterspell_action.is_counterspell:
        return False
    if target_spell.spell_level is None:
        return False  # Can't counter non-spells
    return True


def resolve_counterspell(
    caster: Creature,
    caster_id: str,
    counterspell_action: Action,
    target_spell: Action,
    target_spell_cast_level: int | None = None,
    counterspell_cast_level: int | None = None,
) -> tuple[bool, list[CombatEvent]]:
    """Resolve a counterspell attempt.

    Args:
        caster: The creature casting Counterspell.
        caster_id: ID of the counterspell caster.
        counterspell_action: The Counterspell action.
        target_spell: The spell being countered.
        target_spell_cast_level: Slot level of the target spell (None = base level).
        counterspell_cast_level: Slot level used for Counterspell (None = base level).

    Returns:
        (success, events) -- True if the spell is countered.
    """
    events = []

    target_level = target_spell_cast_level or target_spell.spell_level or 0
    cs_level = counterspell_cast_level or counterspell_action.spell_level or 3
    auto_level = counterspell_action.counterspell_auto_level or cs_level

    # Auto-counter if target spell level <= counterspell slot level
    if target_level <= auto_level:
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{caster.name}'s Counterspell automatically counters "
                f"{target_spell.name} (level {target_level} <= slot level {cs_level})!"
            ),
            source_id=caster_id,
            details={"counterspell_success": True, "auto": True},
        ))
        return True, events

    # Need ability check: DC = 10 + target spell level
    dc = counterspell_action.counterspell_check_dc_base + target_level

    # Ability check using spellcasting ability
    spellcasting_ability = getattr(caster, 'spellcasting_ability', None) or 'intelligence'
    ability_mod = get_effective_ability_modifier(caster, spellcasting_ability)

    natural_roll = roll_die(20)
    total = natural_roll + ability_mod

    success = total >= dc

    result_text = "SUCCESS" if success else "FAILURE"
    counter_text = "counters" if success else "fails to counter"

    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=(
            f"{caster.name} attempts to counterspell {target_spell.name} "
            f"(level {target_level}): {total} ({natural_roll}+{ability_mod}) "
            f"vs DC {dc} — {result_text}! {caster.name} {counter_text} the spell!"
        ),
        source_id=caster_id,
        details={
            "counterspell_success": success,
            "auto": False,
            "roll": total,
            "natural": natural_roll,
            "modifier": ability_mod,
            "dc": dc,
        },
    ))

    return success, events
