"""Session lifecycle: the durable event store + the materialized authoritative
state (character repo + canon store), kept in agreement.

`Session.open` rebuilds everything by seeding the authored baseline and replaying
the log. During play, `emit_state`/`emit_create_entity`/`emit_promote` are the
record-then-apply points: append the event FIRST (durable), then apply. So a
reload always reproduces the live state — protected state AND canon — byte-for-
byte (D9).
"""

from __future__ import annotations

from typing import Callable

from ..canon.models import CanonDraft, CanonRecord
from ..canon.store import CanonStore
from ..content.loader import DEFAULT_PACK, load_pack
from ..quest.models import Quest, QuestStatus
from ..quest.store import QuestStore
from ..record.events import Event, EventKind, StateOp, apply_ops, replay
from ..record.store import EventStore
from ..seed import DEFAULT_SCENE
from ..state.repository import Repository
from ..table import DEFAULT_TABLE, TableContract, normalize_contract


class Session:
    def __init__(self, store: EventStore, repo: Repository, canon: CanonStore,
                 quests: QuestStore | None = None) -> None:
        self.store = store
        self.repo = repo
        self.canon = canon
        self.quests = quests if quests is not None else QuestStore()
        # Location/scene state — set up by `open` from the pack + the event log.
        self.places: dict = {}              # {place_id: PlaceNode}
        self.start_location: str | None = None
        self.start_scene: str = DEFAULT_SCENE
        self.location: str | None = None    # party's current Place id (scopes present NPCs)
        self.scene: str = DEFAULT_SCENE     # current location's prose
        self.time_of_day: str = "day"       # engine-owned environment (DM-reported); drives
        self.weather: str = "clear"         # narration tone + the soundscape (audio mixer §5)
        self.pack_id: str | None = None     # which content pack this campaign is playing
        self.world_map: str | None = None   # top-level map background image filename (pack)
        self.ended: bool = False            # the DM closed this session (end_session tool)
        self.table: TableContract = DEFAULT_TABLE   # campaign's tone + content boundaries

    def _scene_for(self, location: str | None) -> str:
        """The prose for a location — the pack's opening text at the start spot
        (which may be a scenario scene_override), else the place's own description."""
        if location is None or location == self.start_location:
            return self.start_scene
        node = self.places.get(location)
        return node.description if node is not None else self.start_scene

    @classmethod
    def open(cls, store: EventStore, seed: Callable[[], Repository] | None = None,
             pack_id: str = DEFAULT_PACK) -> "Session":
        # `pack_id` chooses the world for a NEW game; an EXISTING save pins its own
        # pack in the start marker, which wins on reload. A custom `seed` (tests)
        # bypasses the pack entirely.
        events = store.read_all()
        chosen_pack: str | None = None
        if seed is None:
            chosen_pack = _start_marker_pack(events) or pack_id
            world = load_pack(chosen_pack)
            repo: Repository = world.repository
            authored_canon = world.canon
            places = world.places
            start_location = world.location
            start_scene = world.scene
            chosen_pack = world.pack_id
            world_map = world.world_map
            marker = {"pack_id": world.pack_id, "pack_version": world.pack_version}
        else:
            repo = seed()
            authored_canon = []
            places = {}
            start_location = None
            start_scene = DEFAULT_SCENE
            world_map = None
            marker = {}
        canon = CanonStore()
        quests = QuestStore()
        # Seed authored canon (slug ids) BEFORE replay so runtime 'canon-N' records
        # layer on top without colliding; it's part of the deterministic baseline,
        # not the event log, so reload re-seeds it identically.
        for rec in authored_canon:
            canon.add(rec)
        # The current location is the start, with every LOCATION_CHANGED folded over
        # it — so reload lands the party exactly where they last travelled to.
        location = start_location
        time_of_day, weather = "day", "clear"
        table = DEFAULT_TABLE
        ended = False
        for event in sorted(events, key=lambda e: e.seq):
            if event.kind == EventKind.LOCATION_CHANGED.value:
                location = event.payload.get("to", location)
            elif event.kind == EventKind.ENVIRONMENT_CHANGED.value:
                time_of_day = event.payload.get("time_of_day", time_of_day)
                weather = event.payload.get("weather", weather)
            elif event.kind == EventKind.CONTRACT_SET.value:
                table = TableContract.model_validate(event.payload["table"])
            elif event.kind == EventKind.SESSION_MARKER.value and event.payload.get("marker") == "end":
                ended = True

        session = cls(store, repo, canon, quests)
        session.places = places
        session.start_location = start_location
        session.start_scene = start_scene
        session.location = location
        session.scene = session._scene_for(location)
        session.time_of_day = time_of_day
        session.weather = weather
        session.pack_id = chosen_pack
        session.world_map = world_map
        session.ended = ended
        session.table = table
        if events:
            replay(events, repo, canon, quests)   # existing session: rebuild to current
        else:
            session.emit_log(EventKind.SESSION_MARKER, marker="start", **marker)
        return session

    def emit_travel(self, to: str, reason: str) -> None:
        """Move the party to another Place (the DM's `travel` tool). Records a
        LOCATION_CHANGED event, then updates the current location + scene."""
        self.store.append(EventKind.LOCATION_CHANGED, {"to": to, "reason": reason})
        self.location = to
        self.scene = self._scene_for(to)

    def emit_environment(self, time_of_day: str | None = None,
                         weather: str | None = None, reason: str = "") -> None:
        """Update the engine-owned environment (the DM's per-turn report). Records an
        ENVIRONMENT_CHANGED event so reload reproduces the soundscape + tone, then applies
        the new value(s); a None field leaves that aspect unchanged."""
        if time_of_day is None and weather is None:
            return
        if time_of_day is not None:
            self.time_of_day = time_of_day
        if weather is not None:
            self.weather = weather
        self.store.append(EventKind.ENVIRONMENT_CHANGED,
                          {"time_of_day": self.time_of_day, "weather": self.weather, "reason": reason})

    def emit_contract(self, table: TableContract, reason: str = "table set") -> TableContract:
        """Set this campaign's table contract (tone + content boundaries). Records a
        CONTRACT_SET event (folded last-write-wins on reload) and applies it. Returns
        the normalized contract actually stored."""
        normalized = normalize_contract(table)
        self.store.append(EventKind.CONTRACT_SET, {"table": normalized.model_dump(), "reason": reason})
        self.table = normalized
        return normalized

    def emit_end(self, reason: str) -> None:
        """Close the session (the DM's `end_session` tool). Records an end marker
        with the reason and flags the session ended (persists across reload)."""
        self.store.append(EventKind.SESSION_MARKER, {"marker": "end", "reason": reason})
        self.ended = True

    def emit_quest_start(self, title: str, text: str, reason: str) -> Quest:
        """Record a new quest (the DM's `start_quest` tool). The id is assigned now
        and recorded, so replay reproduces it exactly."""
        quest = Quest(id=self.quests.next_id(), title=title, text=text, status="active")
        self.store.append(EventKind.QUEST_STARTED, {"record": quest.model_dump(), "reason": reason})
        self.quests.add(quest)
        return quest

    def emit_quest_update(self, quest_id: str, status: QuestStatus | None = None,
                          note: str | None = None, reason: str = "") -> None:
        """Advance a quest (the DM's `update_quest` tool): change its status and/or
        append a note."""
        self.store.append(EventKind.QUEST_UPDATED,
                          {"quest_id": quest_id, "status": status, "note": note, "reason": reason})
        self.quests.update(quest_id, status=status, note=note)

    def emit_log(self, kind: "str | EventKind", **payload) -> Event:
        """Append a non-state event (player message, roll, marker). No ops."""
        return self.store.append(kind, payload)

    def emit_state(self, kind: "str | EventKind", ops: list[StateOp], **payload) -> Event:
        """Append a protected-state event carrying its replayable ops, THEN apply
        them to the materialized repo (append-then-commit, spec §5)."""
        full = {**payload, "ops": [op.model_dump() for op in ops]}
        event = self.store.append(kind, full)
        apply_ops(ops, self.repo)
        return event

    def emit_create_entity(self, draft: CanonDraft, reason: str) -> CanonRecord:
        """Create provisional canon (spec §7/§11). The id + creating-event seq are
        assigned now and recorded, so replay reproduces them exactly (§4.4)."""
        record = CanonRecord(
            id=self.canon.next_id(),
            entity_type=draft.entity_type, name=draft.name, text=draft.text,
            origin=draft.origin, status="provisional",
            created_by_event=self.store.peek_seq(), load_bearing=False,
        )
        self.store.append(EventKind.CREATE_ENTITY, {"record": record.model_dump(), "reason": reason})
        self.canon.add(record)
        return record

    def emit_promote(self, entity_id: str, reason: str) -> None:
        """Promote provisional → confirmed canon (spec §11)."""
        self.store.append(EventKind.CANON_PROMOTED, {"entity_id": entity_id, "reason": reason})
        self.canon.promote(entity_id)


def _start_marker_pack(events: list[Event]) -> str | None:
    """The pack id pinned on a save's session-start marker (None if absent)."""
    for event in sorted(events, key=lambda e: e.seq):
        if event.kind == EventKind.SESSION_MARKER.value and event.payload.get("marker") == "start":
            return event.payload.get("pack_id")
    return None
