"""Session lifecycle: the durable event store + the materialized authoritative
state (character repo + canon store), kept in agreement.

`Session.open` rebuilds everything by seeding the authored baseline and replaying
the log. During play, `emit_state`/`emit_create_entity`/`emit_promote` are the
record-then-apply points: append the event FIRST (durable), then apply. So a
reload always reproduces the live state — protected state AND canon — byte-for-
byte (D9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..canon.models import CanonDraft, CanonRecord
from ..canon.store import CanonStore
from ..content.loader import DEFAULT_PACK, load_pack
from ..quest.models import Quest, QuestStatus
from ..quest.store import QuestStore
from ..record.events import (Event, EventKind, StateOp, apply_ops,
                             install_character, relevel_character, replay)
from ..record.store import EventStore
from ..rules.chargen import build_character
from ..seed import DEFAULT_SCENE
from ..state.models import Character
from ..state.repository import Repository
from ..table import DEFAULT_TABLE, TableContract, normalize_contract

if TYPE_CHECKING:
    from ..rules.chargen import CharacterBuild


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
        self.pack_name: str = ""            # the pack's display name (bestiary source label)
        self.statblocks: tuple = ()         # the pack's authored StatBlocks (this-world bestiary)
        self.ai_profiles: tuple = ()        # the pack's Forge-authored monster personalities (AiProfile)
        self.npc_statblocks: dict = {}      # {npc id -> StatBlock id} for the combat bridge (Phase 4a)
        self.world_map: str | None = None   # top-level map background image filename (pack)
        self.bestiary_gate = None           # per-world bestiary knowledge cutoff (manifest)
        self.force_ended: bool = False      # the DM terminally closed the game (force_end_session tool);
                                            # distinct from an ordinary session wrap-up, which continues play
        # A staged-but-unresolved tactical fight awaiting "⚔ Enter the Arena"
        # (combat Stage 3). Transient runtime state — set while a fight is pending,
        # cleared when the Arena returns; never event-sourced. While set, the turn
        # endpoints reject normal input (the D-COMBAT-3 hard lock).
        self.pending_combat = None          # combat.arena_launch.PendingCombat | None
        self.table: TableContract = DEFAULT_TABLE   # campaign's tone + content boundaries
        self.ruleset = None                  # the global SRD ruleset (chargen/sheet/derivation)
        self.authored_quests: dict = {}      # {id: AuthoredQuest} the pack ships (offered in play,
                                             # not canon); deterministic baseline, re-seeded on open

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
            ruleset = world.ruleset
            pack_name = world.pack_name
            statblocks = world.statblocks
            ai_profiles = world.ai_profiles
            npc_statblocks = world.npc_statblocks
            bestiary_gate = world.bestiary_gate
            authored_quests = {q.id: q for q in world.quests}
            marker = {"pack_id": world.pack_id, "pack_version": world.pack_version}
        else:
            repo = seed()
            authored_canon = []
            places = {}
            start_location = None
            start_scene = DEFAULT_SCENE
            world_map = None
            ruleset = None
            pack_name = ""
            statblocks = ()
            ai_profiles = ()
            npc_statblocks = {}
            bestiary_gate = None
            authored_quests = {}
            marker = {}
        canon = CanonStore()
        quests = QuestStore()
        # Seed authored canon (slug ids) BEFORE replay so runtime 'canon-N' records
        # layer on top without colliding; it's part of the deterministic baseline,
        # not the event log, so reload re-seeds it identically.
        for rec in authored_canon:
            canon.add(rec)
        # Attach the global SRD equipment catalog as the repo's fallback tier so the DM
        # can `give`/reference ANY SRD item (potions, scrolls, magic gear, poisons), not
        # just the handful a pack ships or chargen granted. It's a SECOND-tier lookup —
        # the lean campaign catalog keeps precedence — so the rich SRD set never makes a
        # pack-specific abbreviation ambiguous. Deterministic content, re-attached on every
        # open (not event-sourced), like authored canon.
        if ruleset is not None:
            from ..rules.chargen import _project_srd_item
            repo.set_fallback_catalog(
                {i.id: _project_srd_item(i) for i in ruleset.equipment.values()})
        # The current location is the start, with every LOCATION_CHANGED folded over
        # it — so reload lands the party exactly where they last travelled to.
        location = start_location
        time_of_day, weather = "day", "clear"
        table = DEFAULT_TABLE
        force_ended = False
        for event in sorted(events, key=lambda e: e.seq):
            if event.kind == EventKind.LOCATION_CHANGED.value:
                location = event.payload.get("to", location)
            elif event.kind == EventKind.ENVIRONMENT_CHANGED.value:
                time_of_day = event.payload.get("time_of_day", time_of_day)
                weather = event.payload.get("weather", weather)
            elif event.kind == EventKind.CONTRACT_SET.value:
                table = TableContract.model_validate(event.payload["table"])
            elif event.kind == EventKind.SESSION_MARKER.value and event.payload.get("marker") == "end":
                force_ended = True

        session = cls(store, repo, canon, quests)
        session.places = places
        session.start_location = start_location
        session.start_scene = start_scene
        session.location = location
        session.scene = session._scene_for(location)
        session.time_of_day = time_of_day
        session.weather = weather
        session.pack_id = chosen_pack
        session.pack_name = pack_name
        session.statblocks = statblocks
        session.ai_profiles = ai_profiles
        session.npc_statblocks = npc_statblocks
        session.world_map = world_map
        session.bestiary_gate = bestiary_gate
        session.force_ended = force_ended
        session.table = table
        session.ruleset = ruleset
        session.authored_quests = authored_quests
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

    def emit_wrap(self, player_facing: str, dm_private: str,
                  reason: str = "session wrapped") -> None:
        """Wrap up the current session (the DM's `end_session` tool / the player's Wrap
        button). Records a SESSION_MARKER{marker:"wrap"} carrying the two-faced notes: this
        seals the session (the segmentation boundary transcript.py keys on) and makes the
        notes durable cross-session memory — dm_private feeds the DM's context, player_facing
        the player's chronicle. Inert on replay (notes are prose, never state). Does NOT end
        the game: play resumes as a fresh session, carrying the notes forward."""
        self.store.append(EventKind.SESSION_MARKER,
                          {"marker": "wrap", "player_facing": player_facing,
                           "dm_private": dm_private, "reason": reason})

    def emit_force_end(self, reason: str) -> None:
        """Terminally close the game (the DM's `force_end_session` tool). Records an end
        marker with the reason and flags the game force-ended (persists across reload).
        The persisted marker string stays "end" for save compatibility; the concept is the
        protective force-end, NOT the ordinary session wrap-up (which continues play)."""
        self.store.append(EventKind.SESSION_MARKER, {"marker": "end", "reason": reason})
        self.force_ended = True

    def emit_quest_start(self, title: str, text: str, reason: str,
                         authored_id: str | None = None) -> Quest:
        """Record a new quest (the DM's `start_quest`, or `accept_quest` for an authored
        one). The id is assigned now and recorded, so replay reproduces it exactly. When
        `authored_id` is set, it rides inside the record so reload knows which authored
        quest this runtime quest came from (drives chain progress)."""
        quest = Quest(id=self.quests.next_id(), title=title, text=text, status="active",
                      authored_id=authored_id)
        self.store.append(EventKind.QUEST_STARTED, {"record": quest.model_dump(), "reason": reason})
        self.quests.add(quest)
        return quest

    def emit_quest_accept(self, authored, reason: str) -> Quest:
        """Activate a pre-authored quest (the DM's `accept_quest` tool) as the single
        active quest, seeded from the authored definition (title + player-facing hook).
        Links it back to the authored id so completing it can advance the chain."""
        return self.emit_quest_start(authored.title, authored.hook, reason,
                                     authored_id=authored.id)

    def emit_quest_update(self, quest_id: str, status: QuestStatus | None = None,
                          note: str | None = None, outcome: str | None = None,
                          reward_settled: bool | None = None, reason: str = "") -> None:
        """Advance a quest (the DM's `update_quest` tool): change its status, append a
        note, and/or mark its reward settled. `outcome` is recorded for authored-quest
        chain routing but is NOT applied to quest state — it's read back from the log by
        quest.offers, so replay stays byte-identical without it touching the QuestStore.
        `reward_settled` IS quest state (clears the REWARDS PENDING reminder)."""
        self.store.append(EventKind.QUEST_UPDATED,
                          {"quest_id": quest_id, "status": status, "note": note,
                           "outcome": outcome, "reward_settled": reward_settled,
                           "reason": reason})
        self.quests.update(quest_id, status=status, note=note,
                           reward_settled=reward_settled)

    def emit_party_created(self, builds: list["CharacterBuild"],
                           reason: str = "party created") -> list[Character]:
        """Run chargen (design §6) for each build, then record-then-apply ONE
        CHARACTER_CREATED event carrying the whole built party + the SRD gear its
        members were granted. The first build becomes the lead PC (`repo.pc()`); ids
        are pc, pc2, pc3, … Replaces the scenario's default-party stopgap; replay
        re-registers the gear and re-installs the party. Raises `ChargenError` if any
        build breaks the rules."""
        if self.ruleset is None:
            raise RuntimeError("this campaign has no ruleset loaded; cannot create characters")
        chars: list[Character] = []
        items: list = []
        for i, build in enumerate(builds):
            char, granted = build_character(build, self.ruleset, "pc" if i == 0 else f"pc{i + 1}")
            chars.append(char)
            items.extend(granted)
        # Party gold is a shared purse (one shop, one driver). Pool every hero's chargen
        # starting gold onto the lead so none is stranded on a member the shop can't spend.
        if len(chars) > 1:
            chars[0].gold = sum(c.gold for c in chars)
            for c in chars[1:]:
                c.gold = 0
        payload = {
            "characters": [c.model_dump(mode="json") for c in chars],
            "items": [it.model_dump(mode="json") for it in items],
            "reason": reason,
        }
        self.store.append(EventKind.CHARACTER_CREATED, payload)
        install_character(payload, self.repo)
        return chars

    def emit_character_created(self, build: "CharacterBuild",
                               reason: str = "character created") -> Character:
        """Single-character convenience wrapper over `emit_party_created` (a party of
        one) — back-compat for callers/tests that build a lone PC."""
        return self.emit_party_created([build], reason=reason)[0]

    def emit_character_leveled(self, char: Character, reason: str = "level up") -> Character:
        """Record-then-apply a CHARACTER_LEVELED event carrying the rebuilt PC (CS5).
        The character is already built by `rules.levelup` (the server rolls HP via the
        RNG and supplies equipped items); here we just persist + reinstall it, so replay
        reproduces it exactly."""
        payload = {"character": char.model_dump(mode="json"), "items": [], "reason": reason}
        self.store.append(EventKind.CHARACTER_LEVELED, payload)
        relevel_character(payload, self.repo)
        return char

    def emit_log(self, kind: "str | EventKind", **payload) -> Event:
        """Append a non-state event (player message, roll, marker). No ops."""
        return self.store.append(kind, payload)

    def emit_narration(self, narration: str, beat: str,
                       caused_by: int | None = None) -> Event:
        """Record the DM's narration for a completed turn, verbatim (W2). Carries the
        full narration (rebuilds the player transcript) and the compact continuity beat
        (rehydrates the DM's short-term memory on reload). Non-deterministic model
        OUTPUT, so — like PLAYER_MESSAGE — it is stored as inert prose and is a no-op on
        replay: durable memory, never an authority the model can use to assert protected
        state. `caused_by` links it to the PLAYER_MESSAGE that prompted it (None when the
        turn had no player message, e.g. entering the Arena)."""
        return self.store.append(
            EventKind.NARRATION_RECORDED,
            {"narration": narration, "beat": beat},
            caused_by=caused_by,
        )

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
