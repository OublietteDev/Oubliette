"""The dispatcher: validate a (typed) tool call against current state and RESOLVE
it into replayable `StateOp`s. It does NOT mutate — the session appends the event
and applies the ops (one application path for live + replay).

Because resolution is pure (read-only validation), the runtime can resolve ALL
of a turn's tool calls before applying any, so a turn is atomic: either every
tool applies or none does (no partial-application gap).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..canon.models import CanonDraft
from ..canon.store import CanonStore
from ..record.events import StateOp
from ..state.repository import Repository, StateError
from .schemas import (AwardXp, CreateEntity, EndSession, Give, PromoteCanon, StartQuest,
                      Take, ToolCall, Transact, Travel, UpdateQuest, ValueEntry)


class ToolApplyError(Exception):
    """A tool call that fails validation. Carries a message fed back to the model
    on retry (D6). Nothing is mutated."""


@dataclass
class ResolvedTool:
    """A validated tool, normalized to its effect. Exactly one of `ops` /
    `canon_create` / `canon_promote` / `travel_to` is set, per the tool's target."""

    tool: str
    reason: str
    ops: list[StateOp] = field(default_factory=list)     # protected-state tools
    canon_create: CanonDraft | None = None               # create_entity
    canon_promote: str | None = None                     # promote_canon -> entity id
    travel_to: str | None = None                         # travel -> destination place id
    end_session: bool = False                            # end_session -> close the game
    quest_start: "StartQuest | None" = None              # start_quest
    quest_update: "UpdateQuest | None" = None            # update_quest


class Dispatcher:
    def __init__(self, repo: Repository, canon: CanonStore | None = None,
                 places: dict | None = None, quests=None) -> None:
        self.repo = repo
        self.canon = canon
        self.places = places or {}       # {place_id: PlaceNode} — for travel resolution
        self.quests = quests             # QuestStore — for update_quest validation

    def resolve(self, call: ToolCall) -> ResolvedTool:
        if isinstance(call, Transact):
            return ResolvedTool(call.tool, call.reason, ops=self._resolve_transact(call))
        if isinstance(call, Give):
            self._assert_char(call.to)        # can't credit gold/items to a non-character
            return ResolvedTool(call.tool, call.reason,
                                ops=[self._credit_op(call.to, e) for e in call.items])
        if isinstance(call, Take):
            self._assert_can_cover(call.from_, call.items)
            return ResolvedTool(call.tool, call.reason,
                                ops=[self._debit_op(call.from_, e) for e in call.items])
        if isinstance(call, AwardXp):
            self._assert_char(call.to)         # XP goes to a tracked character (the party)
            return ResolvedTool(call.tool, call.reason, ops=[StateOp.xp(call.to, call.amount)])
        if isinstance(call, CreateEntity):
            draft = CanonDraft(entity_type=call.entity_type, name=call.name,
                               text=call.text, origin=call.origin)
            return ResolvedTool(call.tool, call.reason, canon_create=draft)
        if isinstance(call, PromoteCanon):
            self._assert_promotable(call.entity_id)
            return ResolvedTool(call.tool, call.reason, canon_promote=call.entity_id)
        if isinstance(call, Travel):
            return ResolvedTool(call.tool, call.reason, travel_to=self._resolve_place_id(call.to))
        if isinstance(call, EndSession):
            return ResolvedTool(call.tool, call.reason, end_session=True)
        if isinstance(call, StartQuest):
            if self.quests is not None and self.quests.active():
                raise ToolApplyError(
                    "a quest is already active — complete or fail it before starting another")
            return ResolvedTool(call.tool, call.reason, quest_start=call)
        if isinstance(call, UpdateQuest):
            if self.quests is None or self.quests.get(call.quest_id) is None:
                raise ToolApplyError(f"cannot update unknown quest {call.quest_id!r}")
            return ResolvedTool(call.tool, call.reason, quest_update=call)
        raise ToolApplyError(f"no resolver for {type(call).__name__}")  # pragma: no cover

    def _assert_promotable(self, entity_id: str) -> None:
        if self.canon is None or self.canon.get(entity_id) is None:
            raise ToolApplyError(f"cannot promote unknown canon id {entity_id!r}")

    def _resolve_place_id(self, ref: str) -> str:
        """Map a destination reference (id OR name, loosely) to a known place id —
        the DM may name a place by its prose label, mirroring item resolution."""
        if ref in self.places:
            return ref
        norm = ref.strip().lower()
        for node in self.places.values():
            if node.name.strip().lower() == norm or node.id.replace("_", " ") == norm:
                return node.id
        ref_words = set(norm.replace("_", " ").split())
        if ref_words:
            hits = [n.id for n in self.places.values()
                    if ref_words <= set(n.name.lower().split())]
            if len(hits) == 1:
                return hits[0]
        raise ToolApplyError(f"cannot travel to unknown place {ref!r}")

    # --- resolvers ------------------------------------------------------------
    def _resolve_transact(self, t: Transact) -> list[StateOp]:
        # Validate BOTH sides can cover their half (transact symmetry, §5).
        self._assert_can_cover(t.from_, t.give)
        self._assert_can_cover(t.counterparty, t.receive)
        ops: list[StateOp] = []
        for e in t.give:        # from_ -> counterparty
            ops += self._move_ops(t.from_, t.counterparty, e)
        for e in t.receive:     # counterparty -> from_
            ops += self._move_ops(t.counterparty, t.from_, e)
        return ops

    # --- helpers --------------------------------------------------------------
    def _assert_char(self, char_id: str) -> None:
        """A gold/item/XP target must be a tracked character (the party or an
        established NPC). Provisional canon entities aren't characters and can't hold
        protected state — guard here so a bad op is never recorded (it would otherwise
        crash on replay)."""
        try:
            self.repo.get_character(char_id)
        except StateError as e:
            raise ToolApplyError(
                f"{char_id!r} isn't a tracked character that can hold gold or items — "
                "only the party and established NPCs can") from e

    def _assert_can_cover(self, char_id: str, entries: list[ValueEntry]) -> None:
        try:
            char = self.repo.get_character(char_id)
        except StateError as e:
            raise ToolApplyError(str(e)) from e
        need_gold = sum(e.gold for e in entries if e.gold is not None)
        if char.gold < need_gold:
            raise ToolApplyError(f"{char.name} cannot cover {need_gold}g (has {char.gold}g)")
        for e in entries:
            if e.item_id is not None:
                item_id = self._canon_item(e.item_id)
                if char.item_qty(item_id) < e.qty:
                    raise ToolApplyError(
                        f"{char.name} lacks {e.qty}x {item_id} (has {char.item_qty(item_id)})")

    def _canon_item(self, ref: str) -> str:
        try:
            return self.repo.resolve_item_id(ref)
        except StateError as e:
            raise ToolApplyError(str(e)) from e

    def _move_ops(self, src: str, dst: str, e: ValueEntry) -> list[StateOp]:
        return [self._debit_op(src, e), self._credit_op(dst, e)]

    def _debit_op(self, char_id: str, e: ValueEntry) -> StateOp:
        if e.gold is not None:
            return StateOp.gold(char_id, -e.gold)
        return StateOp.item(char_id, self._canon_item(e.item_id), -e.qty)

    def _credit_op(self, char_id: str, e: ValueEntry) -> StateOp:
        if e.gold is not None:
            return StateOp.gold(char_id, e.gold)
        return StateOp.item(char_id, self._canon_item(e.item_id), e.qty)
