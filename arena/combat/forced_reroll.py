"""Forced reroll mechanics for Indomitable, Lucky, Diamond Soul.

These features allow rerolling failed saving throws (or other d20 rolls).
"""

from arena.models.character import Creature, Feature


def get_forced_reroll_features(creature: Creature) -> list[Feature]:
    """Get all features that can force a saving throw reroll."""
    if not hasattr(creature, 'features'):
        return []
    return [f for f in creature.features if f.forced_reroll_saves]


def can_afford_reroll(creature: Creature, feature: Feature) -> bool:
    """Check if the creature can afford to use a reroll feature.

    Some rerolls cost resources (Diamond Soul costs 1 ki).
    Indomitable costs a use of the feature itself (uses_per_rest, not class_resources).
    """
    if feature.forced_reroll_resource is None:
        return True  # Free reroll (or tracked by uses_per_rest on the feature)

    class_resources = getattr(creature, 'class_resources', {})
    available = class_resources.get(feature.forced_reroll_resource, 0)
    return available >= feature.forced_reroll_resource_cost


def deduct_reroll_cost(creature: Creature, feature: Feature) -> None:
    """Deduct the resource cost for using a reroll."""
    if feature.forced_reroll_resource is None:
        return

    class_resources = getattr(creature, 'class_resources', {})
    resource = feature.forced_reroll_resource
    if resource in class_resources:
        class_resources[resource] = max(
            0, class_resources[resource] - feature.forced_reroll_resource_cost
        )
