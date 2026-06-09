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
    cm.load_encounter(enc, Path("."))  # creature_id paths are absolute → data_dir unused

    teams = sorted(c.team for c in cm.combatants.values())
    assert teams.count("player") == 1 and teams.count("enemy") == 2
    for c in cm.combatants.values():
        assert c.creature.current_hit_points >= 1     # HP initialized
        assert c.position is not None                 # placed on the grid
    # regression: enemies must reload as Monster with XP intact (the inline-data
    # round-trip used to downgrade them to base Creature, zeroing kill XP)
    from arena.models.monster import Monster
    for c in (c for c in cm.combatants.values() if c.team == "enemy"):
        assert isinstance(c.creature, Monster)
        assert c.creature.experience_points > 0
    arena_launch.cleanup(pending)


def test_killing_an_enemy_awards_its_xp_end_to_end():
    """Direct regression for the live-play '0 XP' bug. A bridge monster used to
    reload as a base Creature — subclass + experience_points lost — so kills paid
    nothing. Drive a real CombatManager fight to a kill and confirm XP flows back."""
    from pathlib import Path

    from arena.combat.manager import CombatManager
    from arena.handoff import build_result

    s = _session()
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="wolf")], terrain=TerrainSpec())
    pending = stage_combat(req, s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))

    for c in cm.combatants.values():
        if c.team == "enemy":
            c.creature.current_hit_points = 0     # slay it
    cm.winner = "player"

    result = arena_launch.resolve_to_combat_result(pending, build_result(cm))
    assert result.outcome == "victory"
    assert result.xp_award == 50                  # lean wolf = 50 XP, not 0
    arena_launch.cleanup(pending)


def test_descriptive_enemy_names_resolve_to_the_core_creature():
    """The DM names creatures descriptively ('a wild wolf'); the resolver falls
    back to the trailing whole-word creature, preferring the most specific."""
    from oubliette.combat.arena_launch import _statblock_for

    s = _session()
    assert _statblock_for(s, "a wild wolf").id == "wolf"               # adjective stripped
    assert _statblock_for(s, "giant wolf spider").id == "giant_wolf_spider"  # specific beats bare wolf
    assert _statblock_for(s, "an unspeakable foozle") is None          # genuinely unknown


def test_iconic_monster_fights_with_its_authored_arena_kit():
    """Fidelity slice: an enemy that has a hand-authored Arena file fights with
    its real kit — a save-for-half breath weapon and a multi-type bite — not a
    flat single basic attack. Reward stays Oubliette's bestiary XP."""
    from oubliette.combat.arena_bridge import enemy_from_statblock

    s = _session()
    sb = (getattr(s.ruleset, "bestiary", None) or {})["young_red_dragon"]
    mon = enemy_from_statblock(sb).creature

    assert any(a.saving_throw is not None for a in mon.actions)        # Fire Breath
    bite = next((a for a in mon.actions
                 if a.attack and len({dr.damage_type for dr in a.attack.damage}) > 1), None)
    assert bite is not None                                            # multi-type bite
    assert mon.experience_points == sb.xp                              # reward = bestiary


def test_non_authored_monster_falls_back_to_basic_mapping():
    """A monster without an authored file still works — a single basic attack,
    no rich actions (the ~317 not yet hand-built)."""
    from oubliette.combat.arena_bridge import authored_arena_monster, enemy_from_statblock

    s = _session()
    assert authored_arena_monster("awakened_shrub") is None
    sb = (getattr(s.ruleset, "bestiary", None) or {})["awakened_shrub"]
    mon = enemy_from_statblock(sb).creature
    assert all(a.saving_throw is None for a in mon.actions)
    assert len(mon.actions) == 1


def test_authored_fidelity_survives_the_encounter_round_trip():
    """The rich actions must survive staging + the Arena's own load (the path that
    used to drop Monster fields)."""
    from pathlib import Path

    from arena.combat.manager import CombatManager

    s = _session()
    pending = stage_combat(
        EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="young red dragon")],
                         terrain=TerrainSpec()), s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))

    dragon = next(c.creature for c in cm.combatants.values() if c.team == "enemy")
    assert any(a.saving_throw is not None for a in dragon.actions)     # breath weapon intact
    arena_launch.cleanup(pending)


def test_unknown_enemy_ref_is_a_combat_error():
    s = _session()
    req = EncounterRequest(enemies=[EnemyRef(ref="nonesuch_beast")])
    with pytest.raises(CombatError):
        stage_combat(req, s.repo, s)


def test_resolver_is_tolerant_of_natural_monster_naming():
    """The DM names creatures in plain English ('Dire Wolf'), not by exact id.
    The resolver normalizes spaces/case and matches id OR name."""
    from oubliette.combat.arena_launch import _statblock_for

    s = _session()
    bestiary = getattr(s.ruleset, "bestiary", None) or {}
    # a monster whose display name isn't a bare lowercase id (has a space)
    sb = next(v for v in bestiary.values() if " " in v.name)

    assert _statblock_for(s, sb.id) is sb                  # exact id still works
    assert _statblock_for(s, sb.name) is sb                # "Dire Wolf"
    assert _statblock_for(s, sb.name.upper()) is sb        # case-insensitive
    assert _statblock_for(s, sb.name.replace(" ", "-")) is sb  # hyphens too
    assert _statblock_for(s, "no_such_monster_xyz") is None


def test_stage_accepts_a_naturally_named_enemy():
    s = _session()
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="Goblin")])  # capitalized
    outcome = stage_combat(req, s.repo, s)
    assert outcome.pending is not None
    enemy = [c for c in outcome.pending.plan.encounter.combatants if c.team == "enemy"]
    assert len(enemy) == 1 and enemy[0].creature_data.name.lower().startswith("goblin")
    arena_launch.cleanup(outcome.pending)


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


def _canned_defeat(pending) -> dict:
    """Handoff result for a lost fight: the player team downed, an enemy standing."""
    combatants = []
    for c in pending.plan.encounter.combatants:
        cd = c.creature_data
        enemy = c.team == "enemy"
        combatants.append({
            "id": c.name_override, "name": c.name_override, "team": c.team,
            "is_pc": c.team == "player",
            "hp": cd.max_hit_points if enemy else 0,
            "max_hp": cd.max_hit_points, "temp_hp": 0,
            "conditions": [] if enemy else ["unconscious"],
            "is_conscious": enemy,
            "xp": int(getattr(cd, "experience_points", 0) or 0),
        })
    return {"schema": 1, "winner": "enemy", "outcome": "defeat",
            "rounds": 3, "combatants": combatants}


def test_defeat_resolves_and_writes_the_pc_down(monkeypatch):
    s = _session()
    loop = _loop(s)
    pc = s.repo.pc()
    monkeypatch.setattr(arena_launch, "run_arena", _canned_defeat)

    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))
    report = asyncio.run(loop.enter_combat())

    assert report.combat_result.outcome == "defeat"
    assert s.pending_combat is None        # lock clears even on a loss
    assert pc.hp == 0                       # PC written back as downed
    assert len(s.store.of_kind(EventKind.COMBAT_RESULT)) == 1


def test_enter_combat_survives_an_arena_failure(monkeypatch):
    """If the Arena crashes or writes no result, the turn still resolves so the
    browser lock always clears — never a stuck, unenterable combat."""
    s = _session()
    loop = _loop(s)

    def boom(pending):
        raise CombatError("the Arena exploded")

    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))
    monkeypatch.setattr(arena_launch, "run_arena", boom)
    report = asyncio.run(loop.enter_combat())

    assert report.combat_result.outcome == "flee"   # safe break-off, no state change
    assert s.pending_combat is None


def test_solo_handoff_downed_pc_ends_combat_as_defeat():
    """Regression for the live-play hang: a downed solo PC used to keep the fight
    'alive' through death-save grace (no ally can revive them), so combat never
    ended and the Arena subprocess — and the story turn — hung. In handoff mode a
    fully-downed player team is an immediate defeat."""
    from pathlib import Path

    from arena.combat.manager import CombatManager

    s = _session()
    pending = stage_combat(
        EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="wolf")], terrain=TerrainSpec()),
        s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    cm.solo_defeat_when_downed = True       # handoff.play_encounter sets this

    for c in cm.combatants.values():
        if c.team == "player":
            c.creature.current_hit_points = 0   # downed, no death-save failures yet

    assert cm._check_victory() is True
    assert cm.winner == "enemy"
    arena_launch.cleanup(pending)


def test_standalone_play_keeps_full_death_save_grace():
    """The handoff rule is opt-in: by default a downed PC at 0 HP with no failures
    is still in the fight, so combat does NOT end (death-save rules preserved)."""
    from pathlib import Path

    from arena.combat.manager import CombatManager

    s = _session()
    pending = stage_combat(
        EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="wolf")], terrain=TerrainSpec()),
        s.repo, s).pending
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))       # solo_defeat_when_downed defaults False

    for c in cm.combatants.values():
        if c.team == "player":
            c.creature.current_hit_points = 0
            c.creature.death_save_failures = 0

    assert cm._check_victory() is False     # still dying, not yet defeated
    arena_launch.cleanup(pending)


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
