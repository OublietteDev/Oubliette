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
    """One side of an exchange: either money OR an item stack, never both.
    Money is any mix of the coin fields (1 pp = 10 gp, 1 gp = 10 sp = 100 cp) —
    '1 gp 5 sp' is {gold: 1, silver: 5}."""

    gold: int | None = None
    silver: int | None = Field(default=None, description="silver pieces (10 sp = 1 gp)")
    copper: int | None = Field(default=None, description="copper pieces (100 cp = 1 gp)")
    platinum: int | None = Field(default=None, description="platinum pieces (1 pp = 10 gp)")
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

    def money_cp(self) -> int:
        """The entry's money side in copper (0 for an item entry)."""
        return ((self.platinum or 0) * 1000 + (self.gold or 0) * 100
                + (self.silver or 0) * 10 + (self.copper or 0))

    @classmethod
    def from_cp(cls, cp: int) -> "ValueEntry":
        """A money entry decomposed into gp/sp/cp (no pp promotion — tables think
        in gold). `cp` must be positive."""
        g, s, c = cp // 100, (cp % 100) // 10, cp % 10
        return cls(gold=g or None, silver=s or None, copper=c or None)

    @model_validator(mode="after")
    def _exactly_one(self) -> "ValueEntry":
        coins = [c for c in (self.platinum, self.gold, self.silver, self.copper)
                 if c is not None]
        has_money = bool(coins)
        has_item = self.item_id is not None
        if has_money == has_item:
            raise ValueError(
                "ValueEntry must set exactly one of {money (gold/silver/copper/platinum), item_id}")
        if has_money and (any(c < 0 for c in coins) or self.money_cp() <= 0):
            raise ValueError("money amount must be positive")
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


class UseItem(BaseModel):
    """Use up ONE consumable from a character's inventory (drink a potion, quaff a
    draught) and let CODE apply its effect. For a healing item, code rolls the healing
    dice and raises the character's HP — you never pick or assert the number. The item
    is removed from the stack. Non-consumable gear (a sword, a rope) is USED in the
    fiction but not used UP — just narrate that; this tool will refuse it."""

    tool: Literal["use_item"] = "use_item"
    char: str = Field(default="pc", description="who uses it (usually 'pc')")
    item_id: str = Field(description="the consumable's item id from the inventory context")
    reason: str = Field(description="the fiction, e.g. 'downs the potion after the ambush'")


class ProposeRest(BaseModel):
    """PROPOSE that the party take a rest — a short breather or a long night's sleep.
    Like end_session, this is an offer, not an act: it surfaces a rest prompt to the
    player, and THEY confirm it. Only when they accept does code apply the recovery
    (HP, spell slots, hit dice — a rest is the ONLY way those come back outside a
    potion). So never narrate the party already rested and restored in the same turn
    you propose: narrate settling in, and let the player take the rest."""

    tool: Literal["propose_rest"] = "propose_rest"
    kind: Literal["short", "long"] = Field(description="'short' for a breather (an hour), "
                                           "'long' for a full night's sleep")
    reason: str = Field(description="the in-fiction moment that invites the rest, "
                        "e.g. 'the party makes camp beneath the overhang'")


class ProposeRecruit(BaseModel):
    """PROPOSE that a present NPC join the party as a standing COMPANION — from then
    on they travel with the party, appear in every fight under the player's control,
    and count toward the party's strength when code sizes up encounters. Like
    propose_rest, this is an offer, not an act: it surfaces a prompt and THE PLAYER
    confirms. Emit it only when the fiction has truly arrived there — the NPC offered,
    or agreed when the party asked; never press-gang someone into the roster. The
    party holds at most 6 members including companions. Never narrate them as already
    a member in the same turn you propose: narrate the offer, and let the player
    welcome them. A BOUGHT creature (a kennel's wolf pup, a stable's horse) composes
    naturally: settle the payment with `transact` in this same turn, then propose the
    animal here — code records it as purchased."""

    tool: Literal["propose_recruit"] = "propose_recruit"
    char: str = Field(description="the joining NPC's id (or exact name) from PRESENT")
    reason: str = Field(description="the in-fiction moment, e.g. 'the wolf pup has "
                        "chosen them' or 'Roric offers his sword to the cause'")


class ProposeDismiss(BaseModel):
    """PROPOSE that a companion LEAVE the party — a parting of ways the player must
    confirm. Emit it only when the player has said goodbye, asked them to go, or the
    story has clearly closed their road together; never dismiss a companion on your
    own initiative. Narrate the farewell after the player confirms, and decide in the
    fiction where they go — the world keeps them as an NPC."""

    tool: Literal["propose_dismiss"] = "propose_dismiss"
    char: str = Field(description="the departing companion's id from COMPANIONS")
    reason: str = Field(description="the in-fiction parting, e.g. 'Roric stays to "
                        "guard his village'")


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


class AdjustStanding(BaseModel):
    """Nudge the party's STANDING with a faction when the fiction just earned it —
    they helped a member in front of witnesses, insulted a captain, were seen working
    with the faction's enemy. Small bounded moves only (±5; a full tier is 20 points):
    the big swings belong to authored quests, not to you. Standing is code-owned —
    never claim a tier changed unless FACTION STANDING says so.
    delta 0 is the REVEAL: the party has just LEARNED this faction exists (it appears
    on their Factions page). Use it the moment a hidden faction steps into the light —
    named by an NPC, its sigil recognized, its hand revealed."""

    tool: Literal["adjust_standing"] = "adjust_standing"
    faction: str = Field(description="the faction id from FACTION STANDING")
    delta: int = Field(ge=-5, le=5,
                       description="-5..+5 standing points (0 = reveal the faction, no change)")
    reason: str = Field(description="the fiction that earned the shift")


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
    Union[Transact, Give, Take, UseItem, AwardXp, CreateEntity, PromoteCanon, Travel,
          EndSession, ForceEndSession, StartQuest, UpdateQuest, AcceptQuest,
          SetEnvironment, DmNote, ProposeRest, ProposeRecruit, ProposeDismiss,
          AdjustStanding],
    Field(discriminator="tool"),
]

# The candidate tools handed to the model on a resolve turn (W6). Order is the order
# the model sees them; each is registered by its `tool` literal via `act()`. This is
# the single list to extend when adding a resolve-time tool (also add a dispatch branch).
TOOL_MODELS: tuple[type[BaseModel], ...] = (
    Transact, Give, Take, UseItem, AwardXp, CreateEntity, PromoteCanon, Travel,
    EndSession, ForceEndSession, StartQuest, UpdateQuest, AcceptQuest,
    SetEnvironment, DmNote, ProposeRest, ProposeRecruit, ProposeDismiss,
    AdjustStanding,
)
