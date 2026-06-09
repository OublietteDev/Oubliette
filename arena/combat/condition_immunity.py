"""Condition immunity checks for active features.

Handles Mindless Rage (immune to charmed/frightened while raging),
and similar conditional immunity features.
"""

from arena.models.character import Creature, Feature


def get_active_condition_immunities(creature: Creature) -> list[str]:
    """Get all condition immunities from active features.

    For passive features (active_condition_resource=None), always active.
    For resource-gated features (e.g., rage), checks if the resource is
    currently active (resource count > 0 in class_resources).

    Note: This is a simplified check. For rage specifically, the combat
    manager should track "is_raging" state. For now, we check if the
    resource exists and is > 0, or if it's a passive (always-on) feature.
    """
    if not hasattr(creature, 'features'):
        return []

    immunities: list[str] = []
    class_resources = getattr(creature, 'class_resources', {})

    for feature in creature.features:
        if not feature.active_condition_immunities:
            continue

        if feature.active_condition_resource is None:
            # Passive feature — always active
            immunities.extend(feature.active_condition_immunities)
        else:
            # Resource-gated — check if resource is available
            # Convention: resource > 0 means the feature is "active"
            resource_val = class_resources.get(feature.active_condition_resource, 0)
            if resource_val > 0:
                immunities.extend(feature.active_condition_immunities)

    return immunities


def is_immune_to_condition(creature: Creature, condition_name: str) -> bool:
    """Check if a creature is currently immune to a specific condition.

    Checks both static condition_immunities and active feature immunities.
    """
    # Static immunities (from creature model)
    if condition_name.lower() in [c.lower() for c in creature.condition_immunities]:
        return True

    # Active feature immunities
    active_immunities = get_active_condition_immunities(creature)
    if condition_name.lower() in [c.lower() for c in active_immunities]:
        return True

    return False
