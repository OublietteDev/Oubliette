"""Companions S1 — persistent party membership: an NPC the party recruits stops
evaporating when the scene ends. They live on the party roster (counting toward
party strength), leave the scene-NPC list, and every membership change is a
player-confirmed event (COMPANION_RECRUITED / COMPANION_DISMISSED) so replay
rebuilds the roster byte-identically. The DM only ever PROPOSES — the
propose_rest pattern; POST /api/companion is the player's word.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "companions.sqlite"))
os.environ.pop("ANTHROPIC_API_KEY", None)   # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import GAME, app  # noqa: E402
from oubliette.combat.budget import budget_for  # noqa: E402
from oubliette.dm.brain import Brain  # noqa: E402
from oubliette.dm.context import build_context  # noqa: E402
from oubliette.enums import Ability  # noqa: E402
from oubliette.llm.scripted import ScriptedLLMClient  # noqa: E402
from oubliette.record.events import EventKind  # noqa: E402
from oubliette.record.rng import Rng  # noqa: E402
from oubliette.record.store import InMemoryEventStore  # noqa: E402
from oubliette.runtime.loop import TurnLoop  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402
from oubliette.state.models import Character  # noqa: E402
from oubliette.state.repository import InMemoryRepository  # noqa: E402
from oubliette.tools.dispatch import PARTY_CAP, Dispatcher, ToolApplyError  # noqa: E402
from oubliette.tools.schemas import ProposeDismiss, ProposeRecruit  # noqa: E402

client = TestClient(app)


def _pc(cid="pc", level=3):
    return Character(id=cid, name=cid.upper(), kind="pc", level=level,
                     abilities={a: 10 for a in Ability}, hp=20, max_hp=20)


def _npc(cid="roric", name="Roric", coin=30, home="somewhere"):
    return Character(id=cid, name=name, kind="npc", coin=coin, home_location=home,
                     abilities={a: 10 for a in Ability}, hp=11, max_hp=11)


def _repo(*extra):
    return InMemoryRepository(characters=[_pc(), *extra], items=[], pc_id="pc")


def _session(*extra) -> Session:
    return Session.open(InMemoryEventStore(), seed=lambda: _repo(*extra))


# --- the roster: membership, filters, purse ----------------------------------

def test_recruited_companion_joins_the_party_and_leaves_the_scene():
    s = _session(_npc())
    assert [c.id for c in s.repo.party()] == ["pc"]
    s.emit_companion_recruited(s.repo.get_character("roric"), reason="offered his sword")
    assert [c.id for c in s.repo.party()] == ["pc", "roric"]
    assert [c.id for c in s.repo.companions()] == ["roric"]
    assert s.repo.npcs() == []                       # no double-listing as a local
    roric = s.repo.get_character("roric")
    assert roric.companion and roric.companion_origin == "recruited"
    assert roric.kind == "npc"                       # a promoted NPC, not a new species


def test_dismissed_companion_returns_to_the_world():
    s = _session(_npc())
    s.emit_companion_recruited(s.repo.get_character("roric"))
    s.emit_companion_dismissed("roric", reason="stays to guard his village")
    assert [c.id for c in s.repo.party()] == ["pc"]
    assert [c.id for c in s.repo.npcs()] == ["roric"]
    assert not s.repo.get_character("roric").companion


def test_companion_pocket_coin_stays_their_own():
    """The purse pools only the HEROES' money — a recruited merchant keeps his
    pocket, and his spending draws on it, not the party's."""
    s = _session(_npc(coin=30))
    purse_before = s.repo.party_cp
    s.emit_companion_recruited(s.repo.get_character("roric"))
    assert s.repo.party_cp == purse_before
    assert s.repo.balance_cp("roric") == 30


def test_companions_count_toward_the_encounter_budget():
    s = _session(_npc())
    solo = budget_for(s.repo.party(), "standard")
    s.emit_companion_recruited(s.repo.get_character("roric"))
    accompanied = budget_for(s.repo.party(), "standard")
    assert accompanied.party_size == solo.party_size + 1
    assert accompanied.total_cap >= solo.total_cap


# --- replay: the roster survives a reload ------------------------------------

def test_replay_reproduces_the_companion_roster():
    store = InMemoryEventStore()
    seed = lambda: _repo(_npc(), _npc("pup", "Wolf Pup", coin=0))  # noqa: E731
    s = Session.open(store, seed=seed)
    s.emit_companion_recruited(s.repo.get_character("roric"))
    s.emit_companion_recruited(s.repo.get_character("pup"), origin="purchased")
    s.emit_companion_dismissed("roric")
    reloaded = Session.open(store, seed=seed)
    assert [c.id for c in reloaded.repo.party()] == ["pc", "pup"]
    assert reloaded.repo.get_character("pup").companion_origin == "purchased"
    assert not reloaded.repo.get_character("roric").companion


def test_replay_tolerates_a_dismissal_of_a_missing_character():
    """A hand-edited or legacy log must never brick the save: dismissing someone
    who never existed is skipped with a warning, not raised."""
    store = InMemoryEventStore()
    s = Session.open(store, seed=_repo)
    s.store.append(EventKind.COMPANION_DISMISSED, {"char_id": "nobody", "reason": "?"})
    reloaded = Session.open(store, seed=_repo)          # must not raise
    assert [c.id for c in reloaded.repo.party()] == ["pc"]


# --- the dispatcher: propose-only, validated ---------------------------------

def test_propose_recruit_resolves_by_id_and_by_name():
    repo = _repo(_npc())
    disp = Dispatcher(repo)
    assert disp.resolve(ProposeRecruit(char="roric", reason="x")).recruit_proposed == "roric"
    assert disp.resolve(ProposeRecruit(char="Roric", reason="x")).recruit_proposed == "roric"


def test_propose_recruit_is_an_offer_not_an_act():
    rt = Dispatcher(_repo(_npc())).resolve(ProposeRecruit(char="roric", reason="x"))
    assert rt.ops == [] and rt.recruit_proposed == "roric"


def test_propose_recruit_refuses_unknowns_heroes_and_repeats():
    repo = _repo(_npc())
    disp = Dispatcher(repo)
    with pytest.raises(ToolApplyError, match="isn't a tracked character"):
        disp.resolve(ProposeRecruit(char="a stranger", reason="x"))
    with pytest.raises(ToolApplyError, match="already one of the heroes"):
        disp.resolve(ProposeRecruit(char="pc", reason="x"))
    repo.adopt_companion(repo.get_character("roric").model_copy(update={"companion": True}))
    with pytest.raises(ToolApplyError, match="already travels"):
        disp.resolve(ProposeRecruit(char="roric", reason="x"))


def test_propose_recruit_enforces_the_party_cap():
    extras = [_npc(f"n{i}", f"Extra{i}") for i in range(PARTY_CAP)]
    repo = _repo(*extras)
    for e in extras[:PARTY_CAP - 1]:                    # fill to the cap (1 pc + 5)
        repo.adopt_companion(repo.get_character(e.id).model_copy(update={"companion": True}))
    with pytest.raises(ToolApplyError, match="party is full"):
        Dispatcher(repo).resolve(ProposeRecruit(char=f"n{PARTY_CAP - 1}", reason="x"))


def test_propose_dismiss_only_parts_with_actual_companions():
    repo = _repo(_npc())
    disp = Dispatcher(repo)
    with pytest.raises(ToolApplyError, match="isn't a companion"):
        disp.resolve(ProposeDismiss(char="roric", reason="x"))
    repo.adopt_companion(repo.get_character("roric").model_copy(update={"companion": True}))
    assert disp.resolve(ProposeDismiss(char="roric", reason="x")).dismiss_proposed == "roric"


# --- the loop: proposal -> pending -> expiry ----------------------------------

def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))


def test_dm_proposes_a_recruit_without_recording_membership():
    """The scripted DM answers 'join us' with propose_recruit for the present NPC
    (Thom, in brightvale) — a turn flag only; the roster moves at /api/companion."""
    s = Session.open(InMemoryEventStore())              # brightvale: Thom is present
    report = asyncio.run(_loop(s).take_turn("Thom, will you join us on the road?"))
    assert report.companion_pending == {
        "action": "recruit", "char_id": "merchant_thom", "name": "Thom",
        "kind": "creature", "origin": "recruited",
        "reason": "The party asked them to join."}
    assert s.pending_companion is not None
    kinds = [e.kind for e in s.store.read_all()]
    assert EventKind.COMPANION_RECRUITED.value not in kinds
    assert [c.id for c in s.repo.party()] == ["pc"]


def test_the_proposal_expires_on_the_next_in_character_turn():
    s = Session.open(InMemoryEventStore())
    loop = _loop(s)
    asyncio.run(loop.take_turn("Thom, will you join us on the road?"))
    assert s.pending_companion is not None
    asyncio.run(loop.take_turn("I look around the market"))
    assert s.pending_companion is None


def test_dm_proposes_a_parting_for_a_companion():
    s = Session.open(InMemoryEventStore())
    s.emit_companion_recruited(s.repo.get_character("merchant_thom"))
    report = asyncio.run(_loop(s).take_turn("It's time we part ways with Thom."))
    assert report.companion_pending["action"] == "dismiss"
    assert report.companion_pending["char_id"] == "merchant_thom"
    assert s.repo.get_character("merchant_thom").companion    # still aboard until confirmed


# --- the Arena: companions are staged on the player team, and persist --------

def test_companions_are_staged_player_side_with_writeback():
    """A companion needs no `allies` listing — being on the party roster stages
    them on the player team, with their id in the write-back map so wounds
    persist (the recurring-entity policy the ally path already follows)."""
    import json

    from arena.models.encounter import Encounter

    from oubliette.combat.arena_launch import stage_combat
    from oubliette.combat.schemas import EncounterRequest, EnemyRef, TerrainSpec

    s = Session.open(InMemoryEventStore())              # brightvale
    s.emit_companion_recruited(s.repo.get_character("merchant_thom"))
    req = EncounterRequest(kind="ambush", enemies=[EnemyRef(ref="road bandit", count=1)],
                           terrain=TerrainSpec(kind="open"))
    pending = stage_combat(req, s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    players = [c.name_override for c in enc.combatants if c.team == "player"]
    assert any("Thom" in n for n in players)
    assert "merchant_thom" in pending.plan.persistent_ids.values()


# --- the DM's context: COMPANIONS block, no double-listing -------------------

def test_context_lists_companions_and_unlists_them_as_locals():
    s = Session.open(InMemoryEventStore())
    before = build_context(s.repo, s.scene, [], [], location=s.location,
                           places=s.places, time_of_day="day", weather="clear")
    assert "COMPANIONS" not in before and "Thom (id: merchant_thom)" in before
    s.emit_companion_recruited(s.repo.get_character("merchant_thom"))
    after = build_context(s.repo, s.scene, [], [], location=s.location,
                          places=s.places, time_of_day="day", weather="clear")
    assert "COMPANIONS" in after
    # He travels now: gone from the PRESENT locals (Scrap the pup remains one).
    present = after[after.index("PRESENT"):] if "PRESENT" in after else ""
    assert "merchant_thom" not in present


# --- growth (S2): creatures climb authored tiers, people level ----------------
# Brightvale ships the testbed chain: Scrap the stray pup (stat block wolf_pup,
# CR 0) grows into a lean_wolf when the heroes reach level 2.

def test_growth_waits_for_the_authored_threshold():
    s = Session.open(InMemoryEventStore())
    s.repo.set_level("pc", 1)                     # below the pup's level-2 threshold
    s.emit_companion_recruited(s.repo.get_character("stray_pup"))
    report = asyncio.run(_loop(s).take_turn("I scratch the pup behind the ears"))
    assert report.growth == []
    assert s.repo.get_character("stray_pup").damage == "1d3"      # still a pup


def test_growth_fires_the_turn_the_heroes_cross_the_threshold():
    s = Session.open(InMemoryEventStore())
    s.repo.set_level("pc", 1)
    s.emit_companion_recruited(s.repo.get_character("stray_pup"))
    s.repo.set_level("pc", 2)
    report = asyncio.run(_loop(s).take_turn("We set out for the gate"))
    assert report.growth == [{"char_id": "stray_pup", "name": "Scrap",
                              "from": "wolf pup", "to": "lean wolf"}]
    scrap = s.repo.get_character("stray_pup")
    assert (scrap.hp, scrap.max_hp, scrap.damage) == (9, 9, "2d4")  # the wolf's numbers
    assert scrap.name == "Scrap"                                    # still THEIR pup
    assert s.npc_statblocks["stray_pup"] == "lean_wolf"             # fights as the new form
    kinds = [e.kind for e in s.store.read_all()]
    assert EventKind.COMPANION_EVOLVED.value in kinds
    # The moment is once: the next turn reports no growth (no further stages).
    report2 = asyncio.run(_loop(s).take_turn("Onward"))
    assert report2.growth == []


def test_growth_survives_a_reload():
    store = InMemoryEventStore()
    s = Session.open(store)
    s.emit_companion_recruited(s.repo.get_character("stray_pup"))
    s.repo.set_level("pc", 2)                     # not event-sourced — but the evolve is
    asyncio.run(_loop(s).take_turn("We set out"))
    reloaded = Session.open(store)
    scrap = reloaded.repo.get_character("stray_pup")
    assert scrap.companion and scrap.max_hp == 9 and scrap.damage == "2d4"
    assert reloaded.npc_statblocks["stray_pup"] == "lean_wolf"


def test_growth_context_tells_the_dm_to_narrate_the_moment():
    s = Session.open(InMemoryEventStore())
    ctx = build_context(s.repo, s.scene, [], [],
                        companion_growth=[{"char_id": "x", "name": "Scrap",
                                           "from": "wolf pup", "to": "lean wolf"}])
    assert "THIS TURN — GROWTH" in ctx and "Scrap" in ctx and "lean wolf" in ctx


def test_creature_companions_never_dilute_the_xp_split():
    """Person companions share combat XP at exact parity; a creature can't spend
    XP, so it draws no share (keeping a pet must not tax the party's leveling)."""
    s = Session.open(InMemoryEventStore())
    s.emit_companion_recruited(s.repo.get_character("stray_pup"))
    loop = _loop(s)
    from oubliette.record.events import StateOp
    ops = loop._split_combat_xp([StateOp.xp("pc", 100)], 100)
    assert [(o.char, o.delta) for o in ops if o.op == "xp"] == [("pc", 100)]


# --- the player's word: POST /api/companion -----------------------------------

def _propose(action="recruit", char_id="merchant_thom", name="Thom"):
    GAME.session.pending_companion = {
        "action": action, "char_id": char_id, "name": name,
        "kind": "creature", "origin": "recruited", "reason": "test proposal"}


def test_accepting_a_recruit_records_the_event_and_updates_the_hud():
    assert client.post("/api/new", json={}).json()["ok"]
    _propose()
    d = client.post("/api/companion", json={"accept": True}).json()
    assert d["ok"] and d["accepted"] and d["action"] == "recruit"
    party = d["state"]["party"]
    assert [m["id"] for m in party] == ["pc", "merchant_thom"]
    assert party[1]["companion"] is True
    kinds = [e.kind for e in GAME.session.store.read_all()]
    assert EventKind.COMPANION_RECRUITED.value in kinds
    assert GAME.session.pending_companion is None       # the offer is spent


def test_declining_leaves_the_roster_untouched():
    assert client.post("/api/new", json={}).json()["ok"]
    _propose()
    d = client.post("/api/companion", json={"accept": False}).json()
    assert d["ok"] and d["accepted"] is False
    assert [m["id"] for m in d["state"]["party"]] == ["pc"]
    kinds = [e.kind for e in GAME.session.store.read_all()]
    assert EventKind.COMPANION_RECRUITED.value not in kinds


def test_confirming_without_a_standing_proposal_is_refused():
    assert client.post("/api/new", json={}).json()["ok"]
    r = client.post("/api/companion", json={"accept": True})
    assert r.status_code == 409


def test_accepting_a_dismissal_returns_the_companion_to_the_world():
    assert client.post("/api/new", json={}).json()["ok"]
    GAME.session.emit_companion_recruited(
        GAME.session.repo.get_character("merchant_thom"))
    _propose(action="dismiss")
    d = client.post("/api/companion", json={"accept": True}).json()
    assert d["ok"] and d["action"] == "dismiss"
    assert [m["id"] for m in d["state"]["party"]] == ["pc"]
    assert any(n["id"] == "merchant_thom" for n in d["state"]["npcs"])
