"""Living-world W1 — keyed encounters: authored fights bound to a place that
FIRE when their conditions are met, decided by code, styled by the DM.

The contract: triggers are a pure derivation over the event log (visits from
LOCATION_CHANGED, fired-state from KEYED_ENCOUNTER_TRIGGERED, so `once` and
per-visit arming survive reload byte-for-byte); the DM gets a hard approach
directive and its improvised encounter/trade is suppressed; the engine stages
the authored enemies itself, budget-exempt; a broken ref degrades to one
anomaly, never a dead turn; the pack linter rejects refs that could not stage.
"""

from __future__ import annotations

import asyncio

from oubliette.combat import arena_launch
from oubliette.content.loader import PlaceNode, _lint_keyed_encounters, load_ruleset
from oubliette.content.schemas import (
    NPC,
    KeyedEncounter,
    KeyedEnemy,
    KeyedTrigger,
    Place,
    StatBlock,
)
from oubliette.dm.brain import Brain
from oubliette.dm.context import build_context
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.world.keyed import due_encounter


def _enc(enc_id="ambush", when="every_visit", time="any", min_level=None,
         once=True, ref="wolf", count=1):
    return KeyedEncounter(
        id=enc_id, enemies=[KeyedEnemy(ref=ref, count=count)],
        trigger=KeyedTrigger(when=when, time_of_day=time, min_party_level=min_level),
        once=once)


def _node(*encounters, place_id="mill"):
    return PlaceNode(id=place_id, name="The Old Mill", description="A ruined mill.",
                     parent=None, exits=(), encounters=tuple(encounters))


def _session() -> Session:
    s = Session.open(InMemoryEventStore())
    s.start_location = "mill"
    s.location = "mill"
    return s


def _due(s, node, time_of_day=None, level=1):
    return due_encounter(node, s.store.read_all(),
                         start_location=s.start_location,
                         time_of_day=time_of_day or s.time_of_day,
                         party_level=level)


def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(seed=99, record=session.emit_log),
                    Brain(ScriptedLLMClient()))


def _fire(s, node, enc_id):
    """Record a fired event the way the loop does."""
    s.emit_log(EventKind.KEYED_ENCOUNTER_TRIGGERED, place=node.id, encounter_id=enc_id)


# --- the trigger module (pure derivation) -------------------------------------

def test_fires_at_most_once_per_visit():
    s = _session()
    node = _node(_enc(once=False))
    got = _due(s, node)
    assert got is not None and got.id == "ambush"
    _fire(s, node, "ambush")
    assert _due(s, node) is None          # same visit: the ambush is spent


def test_returning_rearms_a_repeatable_encounter_and_once_holds():
    s = _session()
    repeat, single = _enc("wolves", once=False), _enc("guardian", once=True)
    node = _node(repeat, single)
    _fire(s, node, "wolves")
    _fire(s, node, "guardian")
    s.emit_travel("gate", "leaving")
    s.emit_travel("mill", "returning")
    got = _due(s, node)
    assert got is not None and got.id == "wolves"    # re-armed by the new visit
    _fire(s, node, "wolves")
    assert _due(s, node) is None                     # `once` guardian never re-fires


def test_first_visit_means_the_first_visit_only():
    s = _session()
    node = _node(_enc(when="first_visit", once=False))
    assert _due(s, node) is not None      # session opened here: this IS the first visit
    s.emit_travel("gate", "leaving")
    s.emit_travel("mill", "returning")
    assert _due(s, node) is None          # a return visit, even though it never fired


def test_travel_to_the_same_place_is_not_a_new_visit():
    s = _session()
    node = _node(_enc(once=False))
    _fire(s, node, "ambush")
    s.emit_travel("mill", "the DM re-emits travel in place")
    assert _due(s, node) is None


def test_time_of_day_and_level_gates():
    s = _session()
    node = _node(_enc(time="night"))
    assert _due(s, node, time_of_day="day") is None
    assert _due(s, node, time_of_day="night") is not None
    leveled = _node(_enc(min_level=5))
    assert _due(s, leveled, level=4) is None
    assert _due(s, leveled, level=5) is not None


def test_one_fires_per_turn_in_authored_order():
    s = _session()
    node = _node(_enc("first"), _enc("second"))
    assert _due(s, node).id == "first"
    _fire(s, node, "first")
    assert _due(s, node).id == "second"   # waits its turn, then gets one


# --- the loop: directive, staging, suppression ---------------------------------

def test_keyed_encounter_stages_after_the_narration():
    s = _session()
    s.places = {"mill": _node(_enc("mill_wolves", ref="wolf", count=2, once=False))}
    loop = _loop(s)
    r = asyncio.run(loop.take_turn("We poke around the ruined mill."))
    assert r.combat_pending is True
    names = [c.name_override for c in s.pending_combat.plan.encounter.combatants
             if c.team == "enemy"]
    assert len(names) == 2 and all("wolf" in n.lower() for n in names)
    fired = [e for e in s.store.read_all()
             if e.kind == EventKind.KEYED_ENCOUNTER_TRIGGERED.value]
    assert [ (e.payload["place"], e.payload["encounter_id"]) for e in fired ] \
        == [("mill", "mill_wolves")]
    # The fight is budget-exempt and visible in the dev log as such.
    staged = [e for e in loop.debug.of_kind("combat_budget")
              if e.data.get("stage") == "staged"]
    assert staged and "authored keyed encounter" in staged[-1].data["budget"]
    arena_launch.cleanup(s.pending_combat)
    s.pending_combat = None
    # Same visit, next turn: spent — an ordinary quiet turn.
    r2 = asyncio.run(loop.take_turn("We catch our breath."))
    assert r2.combat_pending is False


def test_keyed_outranks_the_dms_improvised_encounter():
    """'I attack' makes the scripted DM improvise a road-bandit fight — but with
    a keyed encounter armed, the authored wolves stage instead."""
    s = _session()
    s.places = {"mill": _node(_enc("mill_wolves", ref="wolf", once=False))}
    loop = _loop(s)
    r = asyncio.run(loop.take_turn("I draw my knife and attack the raiders."))
    assert r.combat_pending is True
    names = [c.name_override for c in s.pending_combat.plan.encounter.combatants
             if c.team == "enemy"]
    assert all("wolf" in n.lower() for n in names)
    arena_launch.cleanup(s.pending_combat)
    s.pending_combat = None


def test_ooc_turns_never_fire_a_keyed_encounter():
    s = _session()
    s.places = {"mill": _node(_enc(once=False))}
    loop = _loop(s)
    r = asyncio.run(loop.take_turn("What does my sheet say?", ooc=True))
    assert r.combat_pending is False
    assert not [e for e in s.store.read_all()
                if e.kind == EventKind.KEYED_ENCOUNTER_TRIGGERED.value]


def test_a_broken_ref_degrades_to_one_anomaly_and_play_continues():
    s = _session()
    s.places = {"mill": _node(_enc(ref="no_such_beast", once=False))}
    loop = _loop(s)
    r = asyncio.run(loop.take_turn("We poke around."))
    assert r.combat_pending is False and r.narration    # the turn survived
    assert not [e for e in s.store.read_all()
                if e.kind == EventKind.KEYED_ENCOUNTER_TRIGGERED.value]
    asyncio.run(loop.take_turn("We keep looking."))     # suppressed, not re-attempted
    anomalies = [e for e in loop.debug.of_kind("anomaly")
                 if e.data.get("stage") == "keyed_encounter"]
    assert len(anomalies) == 1


def test_fired_state_survives_reload():
    """Replay: a spent `once` encounter stays spent in a reopened session."""
    store = InMemoryEventStore()
    s = Session.open(store)
    s.start_location = "mill"
    s.location = "mill"
    node = _node(_enc("guardian", once=True))
    _fire(s, node, "guardian")
    s2 = Session.open(store)                 # replays the same log
    s2.start_location = "mill"
    s2.location = "mill"
    assert due_encounter(node, s2.store.read_all(), start_location="mill",
                         time_of_day="day", party_level=1) is None


def test_context_carries_the_hard_directive():
    s = _session()
    ctx = build_context(s.repo, scene="the mill", time_of_day="day",
                        keyed_directive={"names": "2 x Wolf",
                                         "briefing": "They pour from the undercroft."})
    assert "AUTHORED ENCOUNTER — IT FIRES NOW" in ctx
    assert "2 x Wolf" in ctx and "undercroft" in ctx
    assert "NARRATES THE APPROACH ONLY" in ctx


# --- the pack linter ------------------------------------------------------------

def _lint(places, statblocks=(), npcs=()):
    errors: list[str] = []
    _lint_keyed_encounters(list(places), list(statblocks), list(npcs),
                           load_ruleset(), errors)
    return errors


def _place(*encounters):
    return Place(id="mill", name="Mill", description="d",
                 encounters=list(encounters))


def test_lint_accepts_srd_pack_and_npc_refs():
    sb = StatBlock(id="lean_wolf", name="Lean Wolf", hp=11, armor_class=12, cr=0.25)
    npc = NPC(id="seraphel", name="Seraphel", combat_kind="creature",
              stat_block="lean_wolf")
    errors = _lint([_place(
        _enc("a", ref="Dire Wolf"),                 # SRD, by name
        _enc("b", ref="lean_wolf", count=3),        # pack stat block, by id
        _enc("c", ref="seraphel"),                  # pack NPC, by id
    )], statblocks=[sb], npcs=[npc])
    assert errors == []


def test_lint_rejects_unknown_refs_npc_counts_and_duplicate_ids():
    npc = NPC(id="seraphel", name="Seraphel")
    errors = _lint([_place(
        _enc("a", ref="no such beast"),
        _enc("a", ref="wolf"),                      # duplicate id in this place
        _enc("b", ref="seraphel", count=2),         # an NPC is always ONE
    )], npcs=[npc])
    assert any("no such beast" in e for e in errors)
    assert any("duplicate encounter id" in e for e in errors)
    assert any("always one" in e for e in errors)


def test_brightvale_testbed_pack_still_lints():
    from oubliette.content.loader import load_pack
    world = load_pack("brightvale")
    mill = world.places["brightvale_old_mill"]
    assert [e.id for e in mill.encounters] == ["mill_wolves", "mill_toughs"]
