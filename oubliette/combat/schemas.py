"""Combat boundary schemas (spec §8). The two edges — EncounterRequest in,
CombatResult out — plus the ephemeral runtime Combatant in between."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from ..tools.schemas import ValueEntry


class ExitKind(str, Enum):
    FLEE = "flee"
    PARLEY = "parley"
    SURRENDER = "surrender"
    BRIBE = "bribe"


Outcome = Literal["victory", "defeat", "flee", "parley", "surrender", "bribe"]


class TerrainSpec(BaseModel):
    kind: str = "open"          # "open", "ambush_cover", "chokepoint", ...
    notes: str = ""


class EnemyRef(BaseModel):
    """A reference the boundary resolves to EITHER a template (→ ephemeral) or an
    existing persistent entity (→ used directly, written back)."""

    ref: str                    # template slug OR existing entity id
    count: int = 1              # only meaningful for templates


class EncounterRequest(BaseModel):
    """Emitted by the narrator when it detects hostility (declarative, §8)."""

    kind: str = "brawl"         # "ambush", "standoff", "brawl", ...
    enemies: list[EnemyRef] = Field(default_factory=list)
    terrain: TerrainSpec = Field(default_factory=TerrainSpec)
    allow_exits: list[ExitKind] = Field(default_factory=list)
    # Phase 1 placeholder: real combat picks exits interactively across turns.
    # Here the narrator may pre-declare the player's chosen non-combat exit.
    chosen_exit: ExitKind | None = None


class Combatant(BaseModel):
    """Ephemeral runtime fighter. Persisted ONLY if it came from a persistent
    entity; template-spawned ones are discarded when the instance closes (D5)."""

    id: str                     # runtime id, e.g. "bandit#1"
    name: str
    source: Literal["template", "entity"]
    entity_id: str | None = None    # set iff source == "entity"
    is_pc: bool = False
    hp: int
    max_hp: int
    armor_class: int
    attack_bonus: int
    damage: str                 # dice spec, e.g. "1d6+1"
    xp: int = 0                 # awarded to the victor if this one falls
    loot: list[ValueEntry] = Field(default_factory=list)


class ConsumedItem(BaseModel):
    """One inventory debit reported by the Arena (handoff-v2 `consumables_used`):
    `char` — a persistent entity id — used up `qty` of catalog item `item_id`
    during the fight. Applied regardless of outcome: a potion drunk before
    fleeing is still gone."""

    char: str
    item_id: str
    qty: int = 1


class CombatResult(BaseModel):
    """The truth object the subsystem returns (§8). Absolute values, not deltas
    (D7). hp_final/conditions_final key ONLY persistent entities — ephemeral
    combatants never appear here, they live and die in the digest."""

    outcome: Outcome
    hp_final: dict[str, int] = Field(default_factory=dict)
    conditions_final: dict[str, list[str]] = Field(default_factory=dict)
    loot: list[ValueEntry] = Field(default_factory=list)
    xp_award: int = 0
    narrative_digest: str = ""
    # Phase-1 transparency: which ephemeral combatants survived (promotion
    # candidates per D5). Not applied to state; surfaced for the boundary's hook.
    ephemeral_survivors: list[str] = Field(default_factory=list)
    # Consumables spent in the Arena (B1) — decremented from inventory on apply.
    items_consumed: list[ConsumedItem] = Field(default_factory=list)
    # Slot/resource state after the fight (B2): absolute USED mappings per
    # persistent entity, the CS5 op shape (`slots_used` / `resources_used`).
    # Keyed only for PCs whose resources were staged in; empty dicts never appear.
    slots_used_final: dict[str, dict[int, int]] = Field(default_factory=dict)
    resources_used_final: dict[str, dict[str, int]] = Field(default_factory=dict)
