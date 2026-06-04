"""Domain models. PROTECTED fields (gold, inventory, hp, ...) are mutated only via
the repository, which is only called by the tools dispatcher (spec §3.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..enums import Ability, Skill
from ..rules.checks import ability_modifier, proficiency_bonus


class Item(BaseModel):
    id: str
    name: str
    tags: list[str] = Field(default_factory=list)
    base_value: int | None = None       # advisory hint only; never enforced (spec §11)


class ItemStack(BaseModel):
    item_id: str
    qty: int = 1


class Character(BaseModel):
    id: str
    name: str
    kind: Literal["pc", "npc"] = "npc"
    level: int = 1
    abilities: dict[Ability, int] = Field(default_factory=dict)
    skill_proficiencies: set[Skill] = Field(default_factory=set)
    # PROTECTED ---------------------------------------------------------------
    hp: int = 10
    max_hp: int = 10
    armor_class: int = 10
    # Phase-1 placeholder combat profile (real equipment/derivation lands later).
    attack_bonus: int = 2
    damage: str = "1d4"
    xp: int = 0
    conditions: list[str] = Field(default_factory=list)
    gold: int = 0
    inventory: list[ItemStack] = Field(default_factory=list)
    # OPEN (flavor; not event-sourced — D-OPEN-1) -----------------------------
    description: str = ""
    disposition: str = ""    # NPC demeanor — context for the DM's DC-setting (D8)
    price_list: dict[str, int] = Field(default_factory=dict)  # merchant asking prices (soft, §11)

    @property
    def proficiency_bonus(self) -> int:
        return proficiency_bonus(self.level)

    def ability_mod(self, ability: Ability) -> int:
        return ability_modifier(self.abilities.get(ability, 10))

    def item_qty(self, item_id: str) -> int:
        return sum(s.qty for s in self.inventory if s.item_id == item_id)
