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
    CHARACTER_LEVELED = "character_leveled"  # level-up output: the rebuilt PC (CS5)
    REST_TAKEN = "rest_taken"           # short/long rest: ops restoring hp/slots/hit-dice/resources
    PORTRAIT_SET = "portrait_set"       # player attached/changed a PC portrait (bounded player action)


class StateOp(BaseModel):
    """One atomic, replayable change to protected state. Deltas are commutative;
    `hp_set`/`conditions` are absolute (D7)."""

    op: Literal["gold", "item", "hp_set", "xp", "conditions", "equip",
                "slots_used", "hit_dice_used", "resources_used", "max_hp", "level",
                "portrait"]
    char: str
    item_id: str | None = None
    delta: int | None = None
    value: int | None = None
    conditions: list[str] | None = None
    item_ids: list[str] | None = None       # for the 'equip' op (absolute loadout)
    mapping: dict | None = None             # for slots_used / resources_used (absolute)
    text: str | None = None                 # for the 'portrait' op (filename; None clears it)

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

    @classmethod
    def slots_used(cls, char: str, mapping: dict) -> "StateOp":
        return cls(op="slots_used", char=char, mapping={str(k): v for k, v in mapping.items()})

    @classmethod
    def hit_dice_used(cls, char: str, value: int) -> "StateOp":
        return cls(op="hit_dice_used", char=char, value=value)

    @classmethod
    def resources_used(cls, char: str, mapping: dict) -> "StateOp":
        return cls(op="resources_used", char=char, mapping=dict(mapping))

    @classmethod
    def max_hp(cls, char: str, value: int) -> "StateOp":
        return cls(op="max_hp", char=char, value=value)

    @classmethod
    def level(cls, char: str, value: int) -> "StateOp":
        return cls(op="level", char=char, value=value)

    @classmethod
    def portrait(cls, char: str, filename: str | None) -> "StateOp":
        return cls(op="portrait", char=char, text=filename)

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
        elif self.op == "slots_used":
            repo.set_slots_used(self.char, {int(k): v for k, v in (self.mapping or {}).items()})
        elif self.op == "hit_dice_used":
            repo.set_hit_dice_used(self.char, self.value or 0)
        elif self.op == "resources_used":
            repo.set_resources_used(self.char, dict(self.mapping or {}))
        elif self.op == "max_hp":
            repo.set_max_hp(self.char, self.value or 1)
        elif self.op == "level":
            repo.set_level(self.char, self.value or 1)
        elif self.op == "portrait":
            repo.set_portrait(self.char, self.text)


def apply_ops(ops: list[StateOp], repo: "Repository", strict: bool = True) -> None:
    """Apply state ops. Live application is `strict` (an op against missing state is a
    bug — let it raise). Replay is tolerant (`strict=False`): a legacy op that targets
    a character that never existed — e.g. gold once granted to a provisional canon
    entity — is skipped with a warning rather than bricking the whole save."""
    from ..state.repository import StateError
    for op in ops:
        try:
            op.apply(repo)
        except StateError as e:
            if strict:
                raise
            print(f"[oubliette] replay: skipped {op.op!r} op on missing target "
                  f"{op.char!r} — {e}")


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
                quests: "QuestStore | None" = None, strict: bool = True) -> None:
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
    if event.kind in (EventKind.CHARACTER_CREATED.value, EventKind.CHARACTER_LEVELED.value):
        install_character(event.payload, repo)
        return
    apply_ops(event.state_ops(), repo, strict=strict)


def replay(events: list[Event], repo: "Repository", canon: "CanonStore | None" = None,
           quests: "QuestStore | None" = None) -> None:
    """Rebuild authoritative state (canon + quests) by applying events in seq order.
    Never rolls, never calls a model — the byte-identical guarantee (D9). Tolerant of
    legacy invalid ops (skips them) so a saved game always reopens."""
    for event in sorted(events, key=lambda e: e.seq):
        apply_event(event, repo, canon, quests, strict=False)
