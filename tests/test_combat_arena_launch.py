"""Combat Stage 3 — "flip the switch": the Arena launch coordinator
(`oubliette.combat.arena_launch`) wired into the live loop.

The Arena subprocess (a pygame window) is the one impure step; every test
monkeypatches `arena_launch.run_arena` with a canned result so the full wiring —
enemy resolution, encounter staging, the two-step Enter-the-Arena flow, map-back,
and the single COMBAT_RESULT event — is exercised headlessly.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from arena.models.encounter import Encounter

from oubliette.combat import arena_launch
from oubliette.combat.arena_launch import stage_combat
from oubliette.combat.boundary import CombatError
from oubliette.combat.schemas import EncounterRequest, EnemyRef, ExitKind, TerrainSpec
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.repository import StateError


def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _loop(session: Session) -> TurnLoop:
    rng = Rng(seed=1234, record=session.emit_log)
    return TurnLoop(session, rng, Brain(ScriptedLLMClient()))


def _canned_victory(pending) -> dict:
    """A handoff result dict shaped from the staged plan: every enemy fallen,
    the party left standing (lightly wounded). Names match `name_override` so the
    bridge maps the result back."""
    combatants = []
    for c in pending.plan.encounter.combatants:
        cd = c.creature_data
        enemy = c.team == "enemy"
        combatants.append({
            "id": c.name_override, "name": c.name_override, "team": c.team,
            "is_pc": c.team == "player",
            "hp": 0 if enemy else max(1, cd.max_hit_points - 3),
            "max_hp": cd.max_hit_points, "temp_hp": 0, "conditions": [],
            "is_conscious": not enemy,
            "xp": int(getattr(cd, "experience_points", 0) or 0),
        })
    return {"schema": 1, "winner": "player", "outcome": "victory",
            "rounds": 2, "combatants": combatants}


# --- staging (enemy resolution + encounter file) -------------------------

def test_stage_resolves_a_bestiary_monster_into_a_loadable_encounter():
    s = _session()
    req = EncounterRequest(kind="ambush", enemies=[EnemyRef(ref="goblin", count=2)],
                           terrain=TerrainSpec(kind="chokepoint"))
    outcome = stage_combat(req, s.repo, s)

    assert outcome.result is None and outcome.pending is not None
    pending = outcome.pending
    assert pending.encounter_path.is_file()

    # the produced file loads through the Arena's OWN encounter model
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    assert isinstance(enc, Encounter)
    assert len(enc.combatants) == 3  # party (1) + 2 goblins
    enemy_names = [c.name_override for c in enc.combatants if c.team == "enemy"]
    assert len(enemy_names) == 2 and len(set(enemy_names)) == 2  # counts uniquified
    assert len(enc.terrain) > 0  # chokepoint laid down a wall line

    arena_launch.cleanup(pending)
    assert not pending.scratch_dir.exists()


def test_generated_encounter_loads_into_a_real_combat_manager():
    """The strongest headless check short of live play: a bridge-built encounter
    isn't just a valid `Encounter` — it deserializes through the Arena's OWN
    `CombatManager.load_encounter` (inline creature_data → creatures, grid
    placement, teams) without the GUI."""
    from pathlib import Path

    from arena.combat.manager import CombatManager

    s = _session()
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="goblin", count=2)],
                           terrain=TerrainSpec())
    pending = stage_combat(req, s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))

    cm = CombatManager()
    cm.load_encounter(enc, Path("."))  # data_dir unused: every combatant is inline

    teams = sorted(c.team for c in cm.combatants.values())
    assert teams.count("player") == 1 and teams.count("enemy") == 2
    for c in cm.combatants.values():
        assert c.creature.current_hit_points >= 1     # HP initialized
        assert c.position is not None                 # placed on the grid
    arena_launch.cleanup(pending)


def test_unknown_enemy_ref_is_a_combat_error():
    s = _session()
    req = EncounterRequest(enemies=[EnemyRef(ref="nonesuch_beast")])
    with pytest.raises(CombatError):
        stage_combat(req, s.repo, s)


def test_chosen_exit_resolves_immediately_without_an_arena():
    s = _session()
    req = EncounterRequest(enemies=[EnemyRef(ref="goblin")],
                           allow_exits=[ExitKind.PARLEY], chosen_exit=ExitKind.PARLEY)
    outcome = stage_combat(req, s.repo, s)
    assert outcome.pending is None
    assert outcome.result is not None and outcome.result.outcome == "parley"


# --- the two-step flow through the loop ----------------------------------

def test_triggering_combat_stages_a_pending_fight_and_does_not_resolve_yet():
    s = _session()
    loop = _loop(s)
    pc = s.repo.pc()

    r = asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))

    assert r.combat_pending is True and r.combat_result is None
    assert s.pending_combat is not None
    # nothing resolved yet: no event recorded, PC untouched
    assert len(s.store.of_kind(EventKind.COMBAT_RESULT)) == 0
    assert pc.xp == 0 and pc.gold == 15


def test_entering_the_arena_resolves_the_fight_as_one_event(monkeypatch):
    s = _session()
    loop = _loop(s)
    pc = s.repo.pc()
    monkeypatch.setattr(arena_launch, "run_arena", _canned_victory)

    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))
    report = asyncio.run(loop.enter_combat())

    assert report.combat_result is not None
    assert report.combat_result.outcome == "victory"
    assert s.pending_combat is None                     # lock cleared
    assert pc.xp == 25                                   # road-bandit XP
    assert pc.gold == 15 + 8                             # road-bandit loot (8g)
    assert 0 < pc.hp <= pc.max_hp                        # PC HP written back
    assert len(s.store.of_kind(EventKind.COMBAT_RESULT)) == 1


def test_enter_combat_without_a_staged_fight_raises():
    s = _session()
    loop = _loop(s)
    with pytest.raises(CombatError):
        asyncio.run(loop.enter_combat())


def test_ephemeral_arena_enemy_never_becomes_a_persistent_entity(monkeypatch):
    s = _session()
    loop = _loop(s)
    monkeypatch.setattr(arena_launch, "run_arena", _canned_victory)

    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))
    asyncio.run(loop.enter_combat())

    # the template bandit fought and fell, but no entity row was ever created
    for ref in ("bandit", "road bandit", "road bandit#1"):
        with pytest.raises(StateError):
            s.repo.get_character(ref)
