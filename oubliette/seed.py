"""A tiny hand-authored starting world for Phase 0: the player, a merchant, and
the boots at the center of the §14.1 acceptance transcript."""

from __future__ import annotations

from .enums import Ability, Skill
from .state.models import Character, Item
from .state.repository import InMemoryRepository

BOOTS = Item(id="boots", name="worn leather boots", tags=["apparel"], base_value=2)


def seed_world() -> InMemoryRepository:
    pc = Character(
        id="pc",
        name="You",
        kind="pc",
        level=3,
        abilities={
            Ability.STR: 10, Ability.DEX: 12, Ability.CON: 12,
            Ability.INT: 10, Ability.WIS: 11, Ability.CHA: 14,   # +2 CHA
        },
        skill_proficiencies={Skill.DECEPTION},                   # +2 proficiency
        hp=24, max_hp=24,
        armor_class=14,                                          # worn leather + DEX
        attack_bonus=5, damage="1d8+3",                          # a trusty knife (placeholder)
        gold=15,
        inventory=[],
        description="A traveler with scuffed boots and a silver tongue.",
    )
    # Boots start on the PC's feet, ready to be 'reappraised'.
    from .state.models import ItemStack
    pc.inventory.append(ItemStack(item_id="boots", qty=1))

    thom = Character(
        id="merchant_thom",
        name="Thom",
        kind="npc",
        level=1,
        abilities={a: 10 for a in Ability},
        hp=9, max_hp=9,
        gold=500,                                                # caps what he can pay
        description="A leather-goods merchant; cautious, but greedy when flattered.",
    )

    return InMemoryRepository(characters=[pc, thom], items=[BOOTS], pc_id="pc")
