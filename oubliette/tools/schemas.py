"""Tool-call schemas — a typed, discriminated union so the model sees each tool's
argument shape (fix for harness gap G1). Phase 0 implemented `transact` fully;
`give`/`take` are the one-directional conveniences from §5.

The `tool` literal is the discriminator. `TurnResolution.tool_calls` is a list of
these, so the JSON schema handed to the model carries the full arg shapes — no
more guessing key names.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


class ValueEntry(BaseModel):
    """One side of an exchange: either gold OR an item stack, never both."""

    gold: int | None = None
    item_id: str | None = None
    qty: int = 1
    spell: str | None = Field(
        default=None,
        description="only for a Spell Scroll: the spell id inscribed on it (any spell, "
                    "SRD or this world's own). Sets which spell the scroll casts.")
    spell_level: int | None = Field(
        default=None,
        description="only for a Spell Scroll: the level the scroll casts the spell at "
                    "(0-9). Omit for the spell's normal level; set higher only for a "
                    "commissioned/upcast scroll. Never below the spell's own level.")

    @model_validator(mode="after")
    def _exactly_one(self) -> "ValueEntry":
        has_gold = self.gold is not None
        has_item = self.item_id is not None
        if has_gold == has_item:
            raise ValueError("ValueEntry must set exactly one of {gold, item_id}")
        if has_gold and self.gold <= 0:
            raise ValueError("gold amount must be positive")
        if has_item and self.qty <= 0:
            raise ValueError("item qty must be positive")
        if self.spell is not None:
            if not has_item:
                raise ValueError("spell can only be set on an item entry (a scroll), not gold")
            # canonicalize to the spell-id convention (lowercase, underscores) so
            # "Fireball" / "Cure Wounds" land on the real ids the bridge resolves
            norm = "_".join(self.spell.strip().lower().split()).replace("-", "_")
            self.spell = norm or None
        if self.spell_level is not None:
            if self.spell is None:
                raise ValueError("spell_level only applies to a scroll's inscribed spell")
            if not 0 <= self.spell_level <= 9:
                raise ValueError("spell_level must be 0 (cantrip) through 9")
        return self


class Transact(BaseModel):
    """Atomic, BALANCED exchange between two parties (spec §5).
    `give` moves from_ -> counterparty; `receive` moves counterparty -> from_."""

    tool: Literal["transact"] = "transact"
    from_: str = Field(description="entity giving `give` and receiving `receive` (usually 'pc')")
    counterparty: str = Field(description="the other party, e.g. a merchant entity id")
    give: list[ValueEntry] = Field(default_factory=list, description="what from_ hands over")
    receive: list[ValueEntry] = Field(default_factory=list, description="what from_ gets back")
    reason: str = Field(description="the fiction that justifies this exchange")


class Give(BaseModel):
    """Grant items/gold to someone (no counter-exchange)."""

    tool: Literal["give"] = "give"
    to: str
    items: list[ValueEntry]
    reason: str


class Take(BaseModel):
    """Remove items/gold from someone (no counter-exchange)."""

    tool: Literal["take"] = "take"
    from_: str
    items: list[ValueEntry]
    reason: str


class AwardXp(BaseModel):
    """Grant experience points for a meaningful accomplishment — finishing a quest,
    overcoming a challenge or a tense social encounter, a milestone in the story.
    Code applies it to the character's XP total and the sheet handles leveling; the
    DM only decides the (positive) amount the fiction earns. Combat awards its own XP
    automatically, so don't double-grant for a fight code already resolved."""

    tool: Literal["award_xp"] = "award_xp"
    to: str = Field(default="pc", description="who earns the XP (usually 'pc')")
    amount: int = Field(description="experience points to grant (a positive number)")
    reason: str = Field(description="what was accomplished, e.g. 'resolved the bridge standoff'")

    @model_validator(mode="after")
    def _positive(self) -> "AwardXp":
        if self.amount <= 0:
            raise ValueError("XP award must be positive")
        return self


class CreateEntity(BaseModel):
    """Introduce new world content (an NPC, place, lore...). Always born
    `provisional` (spec §7/§11) — the runtime forces that; the DM cannot create
    confirmed canon directly."""

    tool: Literal["create_entity"] = "create_entity"
    entity_type: Literal["npc", "place", "lore", "item", "quest", "faction"]
    name: str = Field(description="short name/title for the entity")
    text: str = Field(default="", description="the canon — who/what this is")
    origin: Literal["recombined", "freestyle"] = "freestyle"
    reason: str


class PromoteCanon(BaseModel):
    """Promote a provisional entity to confirmed canon (spec §11)."""

    tool: Literal["promote_canon"] = "promote_canon"
    entity_id: str = Field(description="the canon id, e.g. 'canon-0'")
    reason: str


class Travel(BaseModel):
    """Move the party to another location. Code updates the scene and who's
    present; emit this when the party goes somewhere in the world."""

    tool: Literal["travel"] = "travel"
    to: str = Field(description="destination place id (or its name) from WHERE YOU CAN GO")
    reason: str = Field(description="the fiction for the move, e.g. 'the party walks to the inn'")


class EndSession(BaseModel):
    """Propose wrapping up THIS play session at a natural stopping point — a lull, a safe
    place to rest, an arc just resolved. This does NOT end the game: it suggests the table
    pause for now. The player confirms, you record the session's notes out-of-character,
    and play resumes fresh next time (carrying your notes forward as memory). Offer it when
    the moment fits; the player may decline and play on. (To terminally close a hostile or
    bad-faith game instead, that's the separate `force_end_session` tool.)"""

    tool: Literal["end_session"] = "end_session"
    reason: str = Field(description="the in-fiction reason it's a good place to pause "
                        "(e.g. 'the party makes camp as night falls')")


class ForceEndSession(BaseModel):
    """Force the game to close, terminally. Exists for the DM's protection — you may
    emit this to step away from a hostile or bad-faith interaction; the game shuts and
    does NOT continue. This is distinct from `end_session`, the ordinary in-fiction
    wrap-up that pauses a session and carries the campaign forward. The reason is logged."""

    tool: Literal["force_end_session"] = "force_end_session"
    reason: str = Field(description="a brief, honest reason for force-ending (logged, not shown as fiction)")


class DmNote(BaseModel):
    """Jot a PRIVATE note to your own DM notebook (W4) — your working memory for THIS session.
    Use it for things you want to remember but that aren't protected state: a plan you're
    building toward, an NPC's true intention or secret, foreshadowing you just planted, a
    promise or lie left standing, a thread to follow up. These notes ride your context every
    turn and the players NEVER see them. They are prose memory only — do NOT record gold/HP/XP
    or any number here (code owns those; the give/transact/award_xp tools change them)."""

    tool: Literal["dm_note"] = "dm_note"
    note: str = Field(description="the private note to remember, a sentence or two")


class SetEnvironment(BaseModel):
    """Report a CHANGE to the world's time-of-day and/or weather (engine-owned state
    that drives the audio soundscape). Emit this ONLY when the fiction has just turned
    the environment — the party beds down for the night, a storm you've been building
    finally breaks. Do NOT emit it every turn: with no call, the current time/weather
    simply carry forward unchanged. Set only the field(s) that changed."""

    tool: Literal["set_environment"] = "set_environment"
    time_of_day: Literal["day", "night"] | None = None
    weather: Literal["clear", "rain", "storm", "wind"] | None = None
    reason: str = Field(default="the fiction turned the environment",
                        description="the fiction for the change, e.g. 'night falls as they make camp'")

    @model_validator(mode="after")
    def _at_least_one(self) -> "SetEnvironment":
        if self.time_of_day is None and self.weather is None:
            raise ValueError("set_environment must change at least one of {time_of_day, weather}")
        return self


class StartQuest(BaseModel):
    """Begin tracking a goal the party has taken on (an NPC's request, a mystery
    they're chasing). Code records it as an active quest."""

    tool: Literal["start_quest"] = "start_quest"
    title: str = Field(description="a short name for the quest")
    text: str = Field(default="", description="what the goal is, in a sentence or two")
    reason: str


class UpdateQuest(BaseModel):
    """Advance a tracked quest: append a development as a note, and/or change its
    status. Hand out any reward with a normal give/transact, not here."""

    tool: Literal["update_quest"] = "update_quest"
    quest_id: str = Field(description="the quest id from ACTIVE QUESTS, e.g. 'quest-0'")
    status: Literal["active", "completed", "failed"] | None = Field(
        default=None, description="set when the quest finishes (completed/failed)")
    note: str | None = Field(default=None, description="a short development to record")
    outcome: str | None = Field(
        default=None,
        description="ONLY when completing an authored quest that lists OUTCOMES: the exact "
                    "outcome label that fits how it resolved (e.g. 'spared') — it unlocks the "
                    "next quest in the chain. Omit for an emergent quest or one with no outcomes.")
    reward_settled: bool | None = Field(
        default=None,
        description="set true once the party has been justly compensated for this quest — in "
                    "whatever form they agreed to (the promised reward, a renegotiated one, or "
                    "nothing if they declined). Until you set this, a completed quest's reward "
                    "stays in your REWARDS PENDING list so you don't forget to hand it over.")
    reason: str


class AcceptQuest(BaseModel):
    """Take up a pre-authored quest from the QUESTS OFFERED HERE list when the party
    engages with it. Code activates the authored quest (its title/goal are already
    written — don't retype them) as the party's single active quest."""

    tool: Literal["accept_quest"] = "accept_quest"
    quest_id: str = Field(description="the authored quest's id from QUESTS OFFERED HERE")
    reason: str = Field(description="the fiction for taking it on")


# The only doors into protected state + canon, as a discriminated union (the schema
# the model fills in). To add a tool: add a model + a `tool` literal, and a resolver
# branch in tools/dispatch.py.
ToolCall = Annotated[
    Union[Transact, Give, Take, AwardXp, CreateEntity, PromoteCanon, Travel,
          EndSession, ForceEndSession, StartQuest, UpdateQuest, AcceptQuest,
          SetEnvironment, DmNote],
    Field(discriminator="tool"),
]

# The candidate tools handed to the model on a resolve turn (W6). Order is the order
# the model sees them; each is registered by its `tool` literal via `act()`. This is
# the single list to extend when adding a resolve-time tool (also add a dispatch branch).
TOOL_MODELS: tuple[type[BaseModel], ...] = (
    Transact, Give, Take, AwardXp, CreateEntity, PromoteCanon, Travel,
    EndSession, ForceEndSession, StartQuest, UpdateQuest, AcceptQuest,
    SetEnvironment, DmNote,
)
