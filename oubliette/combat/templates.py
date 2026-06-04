"""Enemy stat templates. Ephemeral combatants are spawned from these (D5) so dead
mooks never touch the entity table. All-original content (no SRD Product Identity)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..tools.schemas import ValueEntry


class CombatantTemplate(BaseModel):
    name: str
    hp: int
    armor_class: int
    attack_bonus: int
    damage: str
    xp: int = 0
    loot: list[ValueEntry] = Field(default_factory=list)


ENEMY_TEMPLATES: dict[str, CombatantTemplate] = {
    "bandit": CombatantTemplate(
        name="road bandit", hp=11, armor_class=12, attack_bonus=3, damage="1d6+1",
        xp=25, loot=[ValueEntry(gold=8)],
    ),
    "wolf": CombatantTemplate(
        name="lean wolf", hp=9, armor_class=13, attack_bonus=4, damage="2d4",
        xp=50, loot=[],
    ),
}
