"""The event log and its replay applier (spec §4).

Design: only PROTECTED state is event-sourced (D-OPEN-1). Every protected
mutation decomposes into atomic, replayable `StateOp`s carried inside the event.
There is exactly ONE application path — `apply_ops` — used by both live play and
replay. Validation happens only on the live path (the dispatcher, before ops are
produced); replay TRUSTS the recorded ops and never validates, rolls, or calls a
model (spec §4.2/§4.3). State = seed(authored baseline) + replay(events).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..canon.store import CanonStore
    from ..quest.store import QuestStore
    from ..state.repository import Repository


class EventKind(str, Enum):
    SESSION_MARKER = "session_marker"
    PLAYER_MESSAGE = "player_message"
    ROLL = "roll"
    TOOL_APPLIED = "tool_applied"
    COMBAT_RESULT = "combat_result"
    CREATE_ENTITY = "create_entity"     # canon content born provisional (§7)
    CANON_PROMOTED = "canon_promoted"   # provisional -> confirmed (§11)
    EQUIP_CHANGED = "equip_changed"     # player loadout change (bounded player action)
    LOCATION_CHANGED = "location_changed"   # party travels to another Place (DM tool)
    ENVIRONMENT_CHANGED = "environment_changed"  # time-of-day / weather (DM-reported)
    QUEST_STARTED = "quest_started"     # a new quest the DM introduced
    QUEST_UPDATED = "quest_updated"     # quest status change and/or an appended note
    CONTRACT_SET = "contract_set"       # per-campaign table contract (tone + lines/veils)
    CHARACTER_CREATED = "character_created"  # chargen output: the built PC + granted SRD gear


class StateOp(BaseModel):
    """One atomic, replayable change to protected state. Deltas are commutative;
    `hp_set`/`conditions` are absolute (D7)."""

    op: Literal["gold", "item", "hp_set", "xp", "conditions", "equip"]
    char: str
    item_id: str | None = None
    delta: int | None = None
    value: int | None = None
    conditions: list[str] | None = None
    item_ids: list[str] | None = None       # for the 'equip' op (absolute loadout)

    # --- typed constructors ---------------------------------------------------
    @classmethod
    def gold(cls, char: str, delta: int) -> "StateOp":
        return cls(op="gold", char=char, delta=delta)

    @classmethod
    def item(cls, char: str, item_id: str, delta: int) -> "StateOp":
        return cls(op="item", char=char, item_id=item_id, delta=delta)

    @classmethod
    def hp_set(cls, char: str, value: int) -> "StateOp":
        return cls(op="hp_set", char=char, value=value)

    @classmethod
    def xp(cls, char: str, delta: int) -> "StateOp":
        return cls(op="xp", char=char, delta=delta)

    @classmethod
    def conditions_set(cls, char: str, conditions: list[str]) -> "StateOp":
        return cls(op="conditions", char=char, conditions=list(conditions))

    @classmethod
    def equip(cls, char: str, item_ids: list[str]) -> "StateOp":
        return cls(op="equip", char=char, item_ids=list(item_ids))

    def apply(self, repo: "Repository") -> None:
        if self.op == "gold":
            repo.adjust_gold(self.char, self.delta or 0)
        elif self.op == "item":
            d = self.delta or 0
            if d > 0:
                repo.add_item(self.char, self.item_id, d)
            elif d < 0:
                repo.remove_item(self.char, self.item_id, -d)
        elif self.op == "hp_set":
            repo.set_hp(self.char, self.value or 0)
        elif self.op == "xp":
            repo.adjust_xp(self.char, self.delta or 0)
        elif self.op == "conditions":
            repo.set_conditions(self.char, self.conditions or [])
        elif self.op == "equip":
            repo.set_equipped(self.char, self.item_ids or [])


def apply_ops(ops: list[StateOp], repo: "Repository") -> None:
    for op in ops:
        op.apply(repo)


def install_character(payload: dict, repo: "Repository") -> None:
    """Apply a CHARACTER_CREATED payload: register the granted SRD gear into the
    campaign catalog, then install the built PC (replacing the stopgap default
    party). The single apply path shared by live emit and replay — replay trusts
    the recorded character verbatim and never re-derives (D9)."""
    from ..state.models import Character, Item
    for raw in payload.get("items", []):
        repo.register_item(Item.model_validate(raw))
    repo.install_pc(Character.model_validate(payload["character"]))


class Event(BaseModel):
    """An append-only, immutable record. `seq` is the monotonic, gap-free order
    within a session (also serves as the event id in Phase 2)."""

    seq: int
    kind: str
    payload: dict = {}
    caused_by: int | None = None

    def state_ops(self) -> list[StateOp]:
        return [StateOp.model_validate(o) for o in self.payload.get("ops", [])]


def apply_event(event: Event, repo: "Repository", canon: "CanonStore | None" = None,
                quests: "QuestStore | None" = None) -> None:
    """Replay one event into state. Protected-state events carry ops; canon/quest
    events carry their record/mutation. Non-state events (player_message, roll,
    marker) are no-ops here."""
    if event.kind == EventKind.CREATE_ENTITY.value:
        if canon is not None:
            from ..canon.models import CanonRecord
            canon.add(CanonRecord.model_validate(event.payload["record"]))
        return
    if event.kind == EventKind.CANON_PROMOTED.value:
        if canon is not None:
            canon.promote(event.payload["entity_id"])
        return
    if event.kind == EventKind.QUEST_STARTED.value:
        if quests is not None:
            from ..quest.models import Quest
            quests.add(Quest.model_validate(event.payload["record"]))
        return
    if event.kind == EventKind.QUEST_UPDATED.value:
        if quests is not None:
            quests.update(event.payload["quest_id"], status=event.payload.get("status"),
                          note=event.payload.get("note"))
        return
    if event.kind == EventKind.CHARACTER_CREATED.value:
        install_character(event.payload, repo)
        return
    apply_ops(event.state_ops(), repo)


def replay(events: list[Event], repo: "Repository", canon: "CanonStore | None" = None,
           quests: "QuestStore | None" = None) -> None:
    """Rebuild authoritative state (canon + quests) by applying events in seq order.
    Never rolls, never calls a model — the byte-identical guarantee (D9)."""
    for event in sorted(events, key=lambda e: e.seq):
        apply_event(event, repo, canon, quests)
