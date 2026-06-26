"""Death prevention mechanics — Relentless Rage, Relentless Endurance, etc.

When a creature would drop to 0 HP, these features can prevent it.
"""

from arena.models.character import Creature, Feature
from arena.util.dice import roll_die
from arena.combat.stat_modifiers import get_effective_ability_modifier
from arena.combat.events import CombatEvent, CombatEventType


def get_death_prevention_features(creature: Creature) -> list[Feature]:
    """Get all features that can prevent dropping to 0 HP — across both PC
    `features` and monster `special_abilities` (e.g. a Relentless Endurance foe)."""
    feats = list(getattr(creature, 'features', []) or [])
    feats += list(getattr(creature, 'special_abilities', []) or [])
    return [f for f in feats if f.death_prevention]


def check_undead_fortitude(
    creature: Creature,
    creature_id: str,
    damage_taken: int,
    took_radiant: bool,
    is_critical: bool,
) -> tuple[bool, list[CombatEvent]]:
    """Undead Fortitude (D-MON-4b): a zombie reduced to 0 HP makes a CON save
    (DC 5 + damage taken); on a success it drops to 1 HP instead. The trait does
    not apply when the killing damage was radiant or from a critical hit."""
    if took_radiant or is_critical:
        reason = "radiant damage" if took_radiant else "a critical hit"
        return False, [CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{creature.name}'s Undead Fortitude fails — {reason} destroys it!",
            source_id=creature_id,
            details={"undead_fortitude": True, "negated": reason},
        )]
    dc = 5 + max(0, damage_taken)
    mod = get_effective_ability_modifier(creature, "constitution")
    natural_roll = roll_die(20)
    total = natural_roll + mod
    success = total >= dc
    if success:
        creature.current_hit_points = 1
        msg = (f"{creature.name}'s Undead Fortitude: CON save {total} "
               f"({natural_roll}+{mod}) vs DC {dc} — SUCCESS! It lurches back up at 1 HP!")
    else:
        msg = (f"{creature.name}'s Undead Fortitude: CON save {total} "
               f"({natural_roll}+{mod}) vs DC {dc} — FAILURE! It finally falls.")
    return success, [CombatEvent(
        event_type=CombatEventType.INFO,
        message=msg,
        source_id=creature_id,
        details={"undead_fortitude": True, "success": success, "roll": total, "dc": dc},
    )]


def can_use_death_prevention(creature: Creature, feature: Feature) -> bool:
    """Check if a death prevention feature can be used.

    Checks: feature has death_prevention enabled, and any
    required resource is available.
    """
    if not feature.death_prevention:
        return False

    # Check resource cost if any
    if feature.death_prevention_resource:
        class_resources = getattr(creature, 'class_resources', {})
        if class_resources.get(feature.death_prevention_resource, 0) <= 0:
            return False

    return True


def resolve_death_prevention(
    creature: Creature,
    creature_id: str,
    feature: Feature,
    use_count: int = 0,
) -> tuple[bool, list[CombatEvent]]:
    """Attempt to use a death prevention feature.

    Args:
        creature: The creature at 0 HP.
        creature_id: Creature's ID.
        feature: The death prevention feature to use.
        use_count: How many times this feature has been used this combat
            (for escalating DC like Relentless Rage).

    Returns:
        (success, events) — True if the creature stays up at 1 HP.
    """
    events = []

    if feature.death_prevention_save_ability is None:
        # Auto-succeed (Relentless Endurance, Half-Orc)
        creature.current_hit_points = feature.death_prevention_hp

        # Deduct resource if needed
        if feature.death_prevention_resource:
            class_resources = getattr(creature, 'class_resources', {})
            res = feature.death_prevention_resource
            if res in class_resources:
                class_resources[res] = max(0, class_resources[res] - 1)

        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{creature.name} uses {feature.name}! "
                f"Instead of falling, {creature.name} drops to "
                f"{feature.death_prevention_hp} HP!"
            ),
            source_id=creature_id,
            details={"death_prevention": True, "new_hp": feature.death_prevention_hp},
        ))
        return True, events

    # Requires a saving throw (Relentless Rage)
    dc = feature.death_prevention_save_dc + (use_count * feature.death_prevention_dc_increment)
    ability = feature.death_prevention_save_ability
    ability_mod = get_effective_ability_modifier(creature, ability)

    natural_roll = roll_die(20)
    total = natural_roll + ability_mod
    success = total >= dc

    if success:
        creature.current_hit_points = feature.death_prevention_hp

        if feature.death_prevention_resource:
            class_resources = getattr(creature, 'class_resources', {})
            res = feature.death_prevention_resource
            if res in class_resources:
                class_resources[res] = max(0, class_resources[res] - 1)

        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{creature.name}'s {feature.name}: {ability.upper()} save "
                f"{total} ({natural_roll}+{ability_mod}) vs DC {dc} — SUCCESS! "
                f"{creature.name} stays up at {feature.death_prevention_hp} HP!"
            ),
            source_id=creature_id,
            details={
                "death_prevention": True,
                "success": True,
                "roll": total,
                "dc": dc,
                "new_hp": feature.death_prevention_hp,
            },
        ))
    else:
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{creature.name}'s {feature.name}: {ability.upper()} save "
                f"{total} ({natural_roll}+{ability_mod}) vs DC {dc} — FAILURE! "
                f"{creature.name} falls unconscious!"
            ),
            source_id=creature_id,
            details={
                "death_prevention": True,
                "success": False,
                "roll": total,
                "dc": dc,
            },
        ))

    return success, events
