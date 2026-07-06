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
    DIFFICULTY_SET = "difficulty_set"   # per-campaign difficulty settings (preset + dials);
                                        # folded last-write-wins on reload, like the contract
    CHARACTER_CREATED = "character_created"  # chargen output: the built PC + granted SRD gear
    CHARACTER_LEVELED = "character_leveled"  # level-up output: the rebuilt PC (CS5)
    REST_TAKEN = "rest_taken"           # short/long rest: ops restoring hp/slots/hit-dice/resources
    PORTRAIT_SET = "portrait_set"       # player attached/changed a PC portrait (bounded player action)
    SPELLS_PREPARED = "spells_prepared" # prepared caster re-prepared its spells after a long rest (CS5/C5)
    NARRATION_RECORDED = "narration_recorded"  # DM narration + continuity beat, stored verbatim; inert on
                                        # replay (like player_message). Model OUTPUT made durable — prose, not
                                        # authority: the firewall holds, code still owns every number (W2).
    NOTEBOOK_NOTE = "notebook_note"     # DM's private working note (the dm_note tool, W4): plans, NPC true
                                        # intentions, foreshadowing. Durable prose, inert on replay; feeds the
                                        # DM's context (never the player's), never a source of protected state.
    CAMPAIGN_ENDED = "campaign_ended"   # the campaign is truly over (hardcore TPK, S4): carries the
                                        # ending narration; folded to a permanent lock on reload. Distinct
                                        # from force_end (hostile-table close) and wrap (an ordinary pause).


class StateOp(BaseModel):
    """One atomic, replayable change to protected state. Deltas are commutative;
    `hp_set`/`conditions` are absolute (D7)."""

    op: Literal["coin", "gold", "item", "hp_set", "xp", "conditions", "equip",
                "slots_used", "hit_dice_used", "resources_used", "max_hp", "level",
                "portrait", "spells_prepared"]
    char: str
    item_id: str | None = None
    delta: int | None = None
    value: int | None = None
    conditions: list[str] | None = None
    item_ids: list[str] | None = None       # for the 'equip' op (absolute loadout)
    mapping: dict | None = None             # for slots_used / resources_used (absolute)
    text: str | None = None                 # for the 'portrait' op (filename; None clears it)
    spell: str | None = None                # for the 'item' op: a scroll's inscribed spell (rider)
    spell_level: int | None = None          # for the 'item' op: a scroll's cast level (upcast rider)
    spells: list[str] | None = None         # for the 'spells_prepared' op (absolute prepared list)

    # --- typed constructors ---------------------------------------------------
    @classmethod
    def coin(cls, char: str, delta_cp: int) -> "StateOp":
        """Money delta in COPPER. (The legacy 'gold' op — deltas in gp from
        pre-coin saves — is still applied on replay, scaled ×100; new events
        always record 'coin'.)"""
        return cls(op="coin", char=char, delta=delta_cp)

    @classmethod
    def item(cls, char: str, item_id: str, delta: int, spell: str | None = None,
             spell_level: int | None = None) -> "StateOp":
        return cls(op="item", char=char, item_id=item_id, delta=delta,
                   spell=spell, spell_level=spell_level)

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

    @classmethod
    def spells_prepared(cls, char: str, spells: list[str]) -> "StateOp":
        return cls(op="spells_prepared", char=char, spells=list(spells))

    def apply(self, repo: "Repository") -> None:
        if self.op == "coin":
            repo.adjust_coin(self.char, self.delta or 0)
        elif self.op == "gold":     # legacy op (pre-coin saves): delta is GOLD pieces
            repo.adjust_coin(self.char, (self.delta or 0) * 100)
        elif self.op == "item":
            d = self.delta or 0
            if d > 0:
                repo.add_item(self.char, self.item_id, d, spell=self.spell, spell_level=self.spell_level)
            elif d < 0:
                repo.remove_item(self.char, self.item_id, -d, spell=self.spell, spell_level=self.spell_level)
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
        elif self.op == "spells_prepared":
            repo.set_spells_prepared(self.char, self.spells or [])


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
    campaign catalog, then install the built party (replacing the stopgap default
    party). The payload carries either a `characters` list (a built party) or a single
    legacy `character` (single-PC saves) — both install via `install_party`. The single
    apply path shared by live emit and replay — replay trusts the recorded characters
    verbatim and never re-derives (D9)."""
    from ..state.models import Character, Item
    for raw in payload.get("items", []):
        repo.register_item(Item.model_validate(raw))
    raws = payload.get("characters")
    if raws is None:
        raws = [payload["character"]]          # legacy single-PC payload
    repo.install_party([Character.model_validate(r) for r in raws])


def relevel_character(payload: dict, repo: "Repository") -> None:
    """Apply a CHARACTER_LEVELED payload: register any gear, then swap the rebuilt PC
    in place — preserving the rest of the party (create replaces the party; level-up
    must not). Replay-safe; the rebuilt character is stored whole, never re-derived (D9)."""
    from ..state.models import Character, Item
    for raw in payload.get("items", []):
        repo.register_item(Item.model_validate(raw))
    repo.replace_character(Character.model_validate(payload["character"]))


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
    marker, narration_recorded) carry no ops and are no-ops here — narration is
    durable prose, never an authority the model can use to assert state (W2)."""
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
                          note=event.payload.get("note"),
                          reward_settled=event.payload.get("reward_settled"))
        return
    if event.kind == EventKind.CHARACTER_CREATED.value:
        install_character(event.payload, repo)
        return
    if event.kind == EventKind.CHARACTER_LEVELED.value:
        relevel_character(event.payload, repo)
        return
    apply_ops(event.state_ops(), repo, strict=strict)


def replay(events: list[Event], repo: "Repository", canon: "CanonStore | None" = None,
           quests: "QuestStore | None" = None) -> None:
    """Rebuild authoritative state (canon + quests) by applying events in seq order.
    Never rolls, never calls a model — the byte-identical guarantee (D9). Tolerant of
    legacy invalid ops (skips them) so a saved game always reopens."""
    for event in sorted(events, key=lambda e: e.seq):
        apply_event(event, repo, canon, quests, strict=False)
