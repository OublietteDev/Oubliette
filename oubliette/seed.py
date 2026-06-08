"""A tiny hand-authored starting world for Phase 0: the player, a merchant, and
the boots at the center of the §14.1 acceptance transcript. The merchant also
carries priced stock for the trade window (spec §9)."""

from __future__ import annotations

from .enums import Ability, Skill
from .state.models import Character, Item, ItemStack
from .state.repository import InMemoryRepository

# Item catalog (original content). base_value is an advisory hint only (§11).
ITEMS = [
    Item(id="boots", name="worn leather boots", category="gear", base_value=2),
    Item(id="knife", name="a trusty knife", category="weapon", base_value=2, damage="1d4"),
    Item(id="leather_jerkin", name="leather jerkin", category="armor", base_value=10,
         armor_class=11, armor_type="light"),
    Item(id="healing_draught", name="healing draught", category="consumable", base_value=25),
    Item(id="traveling_boots", name="sturdy traveling boots", category="gear", base_value=8),
    Item(id="leather_satchel", name="leather satchel", category="gear", base_value=12),
    Item(id="sturdy_belt", name="sturdy belt", category="gear", base_value=4),
    Item(id="waterskin", name="leather waterskin", category="gear", base_value=3),
    Item(id="riding_gloves", name="riding gloves", category="gear", base_value=6),
]

# What Thom has on the table, and what he asks for each (his stock = inventory
# entries that have a price). Stock comes from the DB, not DM invention (§9).
THOM_STOCK = [
    ("traveling_boots", 2, 10),
    ("leather_satchel", 1, 15),
    ("sturdy_belt", 3, 5),
    ("waterskin", 4, 4),
    ("riding_gloves", 2, 8),
]


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
        attack_bonus=5, damage="1d8+3",                          # the knife, equipped below
        gold=15,
        inventory=[
            ItemStack(item_id="boots", qty=1),
            ItemStack(item_id="knife", qty=1),
            ItemStack(item_id="leather_jerkin", qty=1),
            ItemStack(item_id="healing_draught", qty=2),
        ],
        equipped=["knife", "leather_jerkin"],                    # wielded + worn
        description="A traveler with scuffed boots and a silver tongue.",
    )

    thom = Character(
        id="merchant_thom",
        name="Thom",
        kind="npc",
        level=1,
        abilities={a: 10 for a in Ability},
        hp=9, max_hp=9,
        gold=500,                                                # caps what he can pay
        inventory=[ItemStack(item_id=i, qty=q) for i, q, _ in THOM_STOCK],
        price_list={i: p for i, _, p in THOM_STOCK},
        description="A leather-goods merchant; cautious, but greedy when flattered.",
        disposition="cautious and shrewd; greedy when flattered, quick to suspect a hard sell",
        home_location="brightvale_market",
    )

    return InMemoryRepository(characters=[pc, thom], items=ITEMS, pc_id="pc")


# A simple opening scene for context (OPEN flavor; not event-sourced).
DEFAULT_SCENE = (
    "A crowded market square in the town of Brightvale. Thom's leather stall stands nearby, "
    "hung with belts and boots; a brazier smokes against the morning chill."
)
