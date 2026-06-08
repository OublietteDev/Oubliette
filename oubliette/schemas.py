"""Typed structured-output schemas the model fills in.

These are the contracts the DM brain (§9) returns. In Phase 0 we collapse
parser + router + DM into two calls per turn (assess, then resolve), which the
spec explicitly permits for the skeleton (§14). The schemas stay faithful so
Phase 2+ can split them back out without changing shapes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .combat.schemas import EncounterRequest
from .enums import Ability, Skill, Tier, Verb
from .tools.schemas import ToolCall
from .trade.schemas import TradeRequest


class Intent(BaseModel):
    """The parser's typed reading of one player message (spec §6)."""

    raw_text: str
    verb: Verb
    skill: Skill | None = None          # only meaningful when verb == skill_check
    targets: list[str] = Field(default_factory=list)
    args: dict = Field(default_factory=dict)
    ooc: bool = False                   # the meta / table-talk channel
    confidence: float = 1.0


class RollRequest(BaseModel):
    """A roll the DM has called for. The DM sets the DC (model-set, D8); code
    supplies the bonus from the sheet (state-owned). `spec` here is the *base*
    die only — the runtime appends the sheet-derived modifier."""

    base: str = "1d20"
    skill: Skill | None = None
    ability: Ability | None = None
    dc: int
    purpose: str                        # e.g. "skill_check.deception"


class TurnAssessment(BaseModel):
    """First model call of a turn: classify and decide whether a roll is needed."""

    intent: Intent
    tier: Tier
    resolution_hint: str = ""
    requires_roll: bool = False
    roll: RollRequest | None = None
    # When the narrator detects hostility it emits a declarative encounter (§8).
    # If set, the runtime summons combat instead of the normal resolve path (§12).
    encounter: EncounterRequest | None = None
    # When the player wants to browse a merchant's wares, the DM summons the trade
    # window (§9). Set `trade` with the merchant id.
    trade: TradeRequest | None = None


class TurnResolution(BaseModel):
    """Second model call of a turn: narrate the outcome and emit 0+ tool calls.
    `tool_calls` is the typed discriminated union from tools/schemas (gap G1), so
    the model sees each tool's argument shape."""

    narration: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # The DM reports the CURRENT environment each turn (engine-owned state, audio mixer §5).
    # Carry the prior values forward unchanged unless the story has just turned them.
    time_of_day: Literal["day", "night"] | None = None
    weather: Literal["clear", "rain", "storm", "wind"] | None = None
