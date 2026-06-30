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
from oubliette.record.events import EventKind, StateOp
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


def test_iconic_monster_fights_with_its_full_generated_kit():
    """An enemy resolves to the generated full-fidelity Arena monster — a
    save-for-half breath weapon and a multi-type bite — not a flat basic attack.
    Reward stays Oubliette's bestiary XP."""
    from oubliette.combat.arena_bridge import enemy_from_statblock

    s = _session()
    sb = (getattr(s.ruleset, "bestiary", None) or {})["young_red_dragon"]
    mon = enemy_from_statblock(sb).creature

    assert any(a.saving_throw is not None for a in mon.actions)        # Fire Breath
    bite = next((a for a in mon.actions
                 if a.attack and len({dr.damage_type for dr in a.attack.damage}) > 1), None)
    assert bite is not None                                            # multi-type bite
    assert mon.experience_points == sb.xp                              # reward = bestiary


def test_missing_generated_file_falls_back_to_basic_mapping():
    """The basic mapping is still the safety net for ids with no generated file
    (templates, synthetic foes): a single basic attack, no rich actions."""
    from oubliette.combat.arena_bridge import arena_monster_file, enemy_from_statblock
    from oubliette.content.schemas import StatBlock

    assert arena_monster_file("no_such_generated_monster") is None
    sb = StatBlock(id="no_such_generated_monster", name="Gribbly", hp=12,
                   armor_class=12, attack_bonus=3, damage="1d8+1", xp=25)
    mon = enemy_from_statblock(sb).creature
    assert all(a.saving_throw is None for a in mon.actions)
    assert len(mon.actions) == 1


def test_every_generated_monster_file_is_a_valid_arena_monster():
    """Structural gate (like the bestiary linter): the whole generated set loads
    cleanly as Arena Monsters."""
    from arena.models.monster import Monster

    from oubliette.combat.arena_bridge import DATA_DIR

    srd = DATA_DIR / "monsters" / "srd"
    files = list(srd.glob("*.json"))
    assert len(files) > 300                       # the full SRD set
    for f in files:
        Monster.model_validate(json.loads(f.read_text(encoding="utf-8")))


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


def test_monster_multiattack_is_live():
    """The engine enable: a generated multiattacker's extra-attack count is now
    read off its special_abilities, so monster multiattack actually fires."""
    from arena.combat.stat_modifiers import get_extra_attack_count

    from oubliette.combat.arena_bridge import arena_monster_file

    assert get_extra_attack_count(arena_monster_file("young_red_dragon")) == 3  # bite + 2 claws
    assert get_extra_attack_count(arena_monster_file("goblin")) == 1            # no multiattack


def test_legendary_actions_are_generated_and_survive_staging():
    """C2: legendary entries with their own mechanics map directly (Wing Attack:
    save + damage + prone, costs 2); reference entries ("makes a tail attack")
    resolve against the action list; non-mechanizable ones (Detect) are skipped."""
    from oubliette.combat.arena_bridge import arena_monster_file

    dragon = arena_monster_file("adult_red_dragon")
    assert dragon.legendary_action_count == 3
    names = {a.name: a for a in dragon.legendary_actions}
    assert "Detect" not in names
    tail = names["Tail Attack"]
    assert tail.attack is not None and tail.legendary_action_cost == 1
    assert tail.action_type.value == "legendary"
    wing = names["Wing Attack (Costs 2 Actions)"]
    assert wing.legendary_action_cost == 2
    assert wing.saving_throw.dc == 22
    assert wing.saving_throw.conditions_on_fail == ["prone"]
    assert wing.target_type.value == "area_sphere" and wing.area_size == 10


def test_condition_riders_un_inert_the_signature_abilities():
    """C2: Gorgon petrifying breath restrains (deliberate first-stage approx),
    Frightful Presence frightens in a 120-ft burst, Ghoul claws carry a
    save-gated paralysis rider, Aboleth's "magically charmed" parses."""
    from oubliette.combat.arena_bridge import arena_monster_file

    gorgon = arena_monster_file("gorgon")
    breath = next(a for a in gorgon.actions if "Breath" in a.name)
    assert breath.saving_throw.conditions_on_fail == ["restrained"]
    # D-MON-2: a real recharge ability — one charge, refreshed by the d6 roll.
    assert breath.recharge_min == 5
    assert breath.uses_per_rest == 1 and breath.current_uses == 1

    dragon = arena_monster_file("adult_red_dragon")
    fp = next(a for a in dragon.actions if "Frightful" in a.name)
    assert fp.saving_throw.conditions_on_fail == ["frightened"]
    assert fp.target_type.value == "area_sphere" and fp.area_size == 120

    ghoul = arena_monster_file("ghoul")
    claws = next(a for a in ghoul.actions if a.name == "Claws")
    assert claws.conditions_applied == ["paralyzed"]
    assert claws.condition_save_to_end == "constitution"
    assert claws.condition_save_to_end_dc == 10

    enslave = next(a for a in arena_monster_file("aboleth").actions
                   if a.name == "Enslave")
    assert enslave.saving_throw.conditions_on_fail == ["charmed"]


def test_ghoul_paralysis_flows_through_attack_resolution():
    """C2 engine slice: the generated rider data drives the real attack path —
    a claw hit applies paralyzed with the CON 10 save-to-end."""
    from arena.combat.actions import resolve_attack
    from arena.grid.coordinates import HexCoord
    from arena.grid.hexgrid import HexGrid
    from arena.models.character import PlayerCharacter

    from oubliette.combat.arena_bridge import arena_monster_file

    ghoul = arena_monster_file("ghoul")
    claws = next(a for a in ghoul.actions if a.name == "Claws")
    target = PlayerCharacter(name="Dummy", character_class="Fighter",
                             max_hit_points=30, armor_class=1)
    grid = HexGrid(5, 5)
    grid.place_creature(HexCoord(1, 1), "ghoul")
    grid.place_creature(HexCoord(2, 1), "dummy")
    for _ in range(30):                                # AC 1: only nat 1 misses
        resolve_attack(ghoul, "ghoul", target, "dummy", claws, grid)
        if target.active_conditions:
            break
    conds = {c.condition.value: c for c in target.active_conditions}
    assert "paralyzed" in conds
    assert conds["paralyzed"].save_to_end == "constitution"
    assert conds["paralyzed"].save_dc == 10


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


def test_potion_drunk_in_the_arena_is_gone_from_inventory(monkeypatch):
    """The B1 vertical slice, headless: a Potion of Healing in story inventory is
    staged into the Arena as a drink action (uses = stack qty, catalog id stamped);
    the canned v2 result reports one drunk; the story-side stack decrements; and
    the debit — an ordinary item op inside the COMBAT_RESULT event — replays."""
    s = _session()
    loop = _loop(s)
    pc = s.repo.pc()
    # Grant through the event log (as the DM's `give` does) so the replay holds.
    s.emit_state(EventKind.TOOL_APPLIED, [StateOp.item(pc.id, "potion_of_healing", 2)],
                 tool="give", reason="test grant")

    def canned_with_potion(pending) -> dict:
        result = _canned_victory(pending)
        result["schema"] = 2
        for c in result["combatants"]:
            if c["is_pc"]:
                c["consumables_used"] = [
                    {"item_id": "potion_of_healing", "name": "Potion of Healing", "used": 1}]
        return result

    monkeypatch.setattr(arena_launch, "run_arena", canned_with_potion)
    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))

    # OUT: the staged PC carries the drink action under the entry invariant
    staged_pc = next(c.creature_data for c in s.pending_combat.plan.encounter.combatants
                     if c.team == "player")
    drink = next(a for a in staged_pc.actions if a.source_item)
    assert drink.healing == "2d4+2"
    assert drink.uses_per_rest == 2 and drink.current_uses == 2
    assert drink.source_item_id == "potion_of_healing"

    # BACK: consumption lands in the result and the inventory stack decrements
    report = asyncio.run(loop.enter_combat())
    assert [(i.char, i.item_id, i.qty) for i in report.combat_result.items_consumed] \
        == [(pc.id, "potion_of_healing", 1)]
    assert pc.item_qty("potion_of_healing") == 1

    # and the debit replays: a fresh session over the same store agrees
    s2 = Session.open(s.store)
    assert s2.repo.pc().item_qty("potion_of_healing") == 1


def test_real_engine_drink_heals_and_flows_back_to_inventory(monkeypatch):
    """The strongest headless slice: no canned consumption dict anywhere. Stage →
    load into a REAL CombatManager → the PC drinks through the engine's own
    `resolve_effect` (heals + decrements uses) → the GENUINE `build_result` v2
    reports it → the live loop debits the story inventory."""
    from pathlib import Path

    from arena.combat.actions import resolve_effect
    from arena.combat.manager import CombatManager
    from arena.handoff import build_result

    s = _session()
    loop = _loop(s)
    pc = s.repo.pc()
    s.emit_state(EventKind.TOOL_APPLIED, [StateOp.item(pc.id, "potion_of_healing", 2)],
                 tool="give", reason="test grant")

    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))
    pending = s.pending_combat
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))

    pc_cid, pc_combatant = next((cid, c) for cid, c in cm.combatants.items()
                                if c.team == "player")
    creature = pc_combatant.creature
    creature.current_hit_points = max(1, creature.max_hit_points - 6)   # wounded
    drink = next(a for a in creature.actions if a.source_item)

    res = resolve_effect(creature, pc_cid, creature, pc_cid, drink, cm.grid)
    assert res.success
    # 2d4+2 heals at least 4 of the 6 missing HP
    assert creature.current_hit_points >= creature.max_hit_points - 2
    assert drink.current_uses == 1                                       # one drunk

    for c in cm.combatants.values():                                     # win the fight
        if c.team == "enemy":
            c.creature.current_hit_points = 0
    cm.winner = "player"

    monkeypatch.setattr(arena_launch, "run_arena", lambda _pending: build_result(cm))
    report = asyncio.run(loop.enter_combat())

    assert [(i.item_id, i.qty) for i in report.combat_result.items_consumed] \
        == [("potion_of_healing", 1)]
    assert pc.item_qty("potion_of_healing") == 1
    assert pc.hp == creature.current_hit_points                          # heal stuck


def test_scroll_cast_in_the_arena_consumes_the_exact_variant(monkeypatch):
    """The C5 scroll slice, headless with the REAL engine: a 2nd-level Cure
    Wounds scroll in story inventory stages as a no-slot cast action carrying
    the variant riders; the PC reads it through the engine's own resolve_effect
    at the inscribed level (upcast dice, use decremented); the genuine v2
    result names the variant; and the boundary debits the exact
    (item, spell, level) stack — with the replay agreeing."""
    from pathlib import Path

    from arena.combat.actions import resolve_effect
    from arena.combat.manager import CombatManager
    from arena.handoff import build_result

    s = _session()
    loop = _loop(s)
    pc = s.repo.pc()
    s.emit_state(EventKind.TOOL_APPLIED,
                 [StateOp.item(pc.id, "spell_scroll", 1, spell="cure_wounds",
                               spell_level=2)],
                 tool="give", reason="test grant")

    asyncio.run(loop.take_turn("I draw my knife and attack the bandit."))
    pending = s.pending_combat
    enc = Encounter.model_validate(json.loads(pending.encounter_path.read_text("utf-8")))
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))

    pc_cid, pc_combatant = next((cid, c) for cid, c in cm.combatants.items()
                                if c.team == "player")
    creature = pc_combatant.creature
    creature.current_hit_points = 1                                   # badly hurt
    scroll = next(a for a in creature.actions
                  if getattr(a, "source_item_spell", None) == "cure_wounds")
    assert scroll.resource_cost == {}             # the scroll, not a slot
    assert scroll.fixed_cast_level == 2           # inscribed level rides in

    res = resolve_effect(creature, pc_cid, creature, pc_cid, scroll, cm.grid,
                         cast_level=scroll.fixed_cast_level)
    assert res.success
    assert creature.current_hit_points >= 3       # 2d8 (1d8 base + upcast 1d8)
    assert scroll.current_uses == 0               # the scroll is spent

    for c in cm.combatants.values():                                  # win
        if c.team == "enemy":
            c.creature.current_hit_points = 0
    cm.winner = "player"

    monkeypatch.setattr(arena_launch, "run_arena", lambda _p: build_result(cm))
    report = asyncio.run(loop.enter_combat())

    assert [(i.item_id, i.spell, i.spell_level, i.qty)
            for i in report.combat_result.items_consumed] \
        == [("spell_scroll", "cure_wounds", 2, 1)]
    assert pc.item_qty("spell_scroll") == 0       # the exact variant debited

    s2 = Session.open(s.store)                    # and the debit replays
    assert s2.repo.pc().item_qty("spell_scroll") == 0


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


def test_creature_npc_enemy_fights_its_statblock_kit_as_a_persistent_foe():
    """Forge 4a-2: a recurring creature-NPC (Seraphel) resolves to her full stat
    block kit — proven by the block's HP (99) overriding the NPC's flat Character
    HP (10) — while keeping persistent-entity semantics (HP write-back via
    entity_id, a single instance, no loot) and her OWN name, not the species label.
    """
    from types import SimpleNamespace

    from oubliette.combat.arena_launch import _resolve_enemies
    from oubliette.content.schemas import StatBlock
    from oubliette.state.models import Character

    sb = StatBlock(id="seraphel_kit", name="Ancient Blue Dragon", hp=99, armor_class=18)
    npc = Character(id="seraphel", name="Seraphel", kind="npc", hp=10, max_hp=10, xp=5000)

    class _Repo:
        def get_character(self, ref):
            if ref == "seraphel":
                return npc
            raise StateError(f"no entity {ref!r}")

    session = SimpleNamespace(
        statblocks=(sb,), npc_statblocks={"seraphel": "seraphel_kit"},
        ai_profiles=(), pack_id=None, ruleset=None,
    )
    req = EncounterRequest(kind="ambush", enemies=[EnemyRef(ref="seraphel", count=3)],
                           terrain=TerrainSpec(kind="chokepoint"))

    insts = _resolve_enemies(req, _Repo(), session)

    assert len(insts) == 1                       # persistent ⇒ a single Seraphel
    inst = insts[0]
    assert inst.entity_id == "seraphel"          # her final HP writes back
    assert inst.loot == []                        # a recurring foe drops no loot
    assert inst.creature.name == "Seraphel"      # her name, not "Ancient Blue Dragon"
    assert inst.creature.max_hit_points == 99    # the stat-block kit, not the flat 10


def test_persistent_npc_without_a_statblock_still_resolves_flat():
    """An NPC with no stat block keeps the existing flat mapping (entity semantics,
    its own Character HP) — the 4a-2 reorder must not regress the no-block path."""
    from types import SimpleNamespace

    from oubliette.combat.arena_launch import _resolve_enemies
    from oubliette.state.models import Character

    npc = Character(id="thug", name="Sour Ned", kind="npc", hp=17, max_hp=17)

    class _Repo:
        def get_character(self, ref):
            if ref == "thug":
                return npc
            raise StateError(f"no entity {ref!r}")

    session = SimpleNamespace(statblocks=(), npc_statblocks={}, ai_profiles=(),
                              pack_id=None, ruleset=None)
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="thug")],
                           terrain=TerrainSpec())

    insts = _resolve_enemies(req, _Repo(), session)
    assert len(insts) == 1
    assert insts[0].entity_id == "thug"
    assert insts[0].creature.name == "Sour Ned"
    assert insts[0].creature.max_hit_points == 17


def test_person_npc_adversary_fights_with_its_honest_snapshot_numbers():
    """Forge 4b-5: a person-NPC enemy (a Fighter 3 built via chargen, with a real
    sheet) has no stat block, so it resolves through the flat `enemy_from_character`
    path — but that path reads the SNAPSHOT, so the foe arrives with honest
    AC/HP/XP/abilities (≈28 HP / AC 16), not the 10/10/+2/1d4 placeholder. Guards
    the bridge contract that the WHOLE built sheet's combat numbers reach the Arena,
    not just HP."""
    from types import SimpleNamespace

    from oubliette.combat.arena_launch import _resolve_enemies
    from oubliette.state.models import Character, CharacterSheet

    aldric = Character(
        id="capt_aldric", name="Captain Aldric", kind="npc", level=3,
        abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 11, "cha": 13},
        hp=28, max_hp=28, armor_class=16, attack_bonus=5, damage="1d8+3", xp=900,
        sheet=CharacterSheet(race="Human", char_class="Fighter",
                             background="Soldier", size="Medium"),
    )

    class _Repo:
        def get_character(self, ref):
            if ref == "capt_aldric":
                return aldric
            raise StateError(f"no entity {ref!r}")

    session = SimpleNamespace(statblocks=(), npc_statblocks={}, ai_profiles=(),
                              pack_id=None, ruleset=None)
    req = EncounterRequest(kind="brawl", enemies=[EnemyRef(ref="capt_aldric")],
                           terrain=TerrainSpec())

    insts = _resolve_enemies(req, _Repo(), session)
    assert len(insts) == 1
    inst = insts[0]
    assert inst.entity_id == "capt_aldric"          # persistent ⇒ HP writes back
    mon = inst.creature
    assert mon.name == "Captain Aldric"
    assert mon.armor_class == 16                     # the built AC, not 10
    assert mon.max_hit_points == 28                  # the built HP, not 10
    assert mon.experience_points == 900
    assert mon.ability_scores.strength == 16         # the whole snapshot, not just HP
    assert mon.is_player_controlled is False         # an adversary, AI-run


# --- recruited allies (4b-ally) ------------------------------------------

def _ally_repo(chars):
    """A tiny repo over a {id -> Character} map, raising like the real one."""
    class _Repo:
        def get_character(self, ref):
            try:
                return chars[ref]
            except KeyError:
                raise StateError(f"no entity {ref!r}")
    return _Repo()


def _person(cid, name, kind="npc", **over):
    from oubliette.state.models import Character, CharacterSheet
    base = dict(
        id=cid, name=name, kind=kind, level=3, hp=28, max_hp=28,
        armor_class=16, attack_bonus=5, damage="1d8+3",
        abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 11, "cha": 13},
        sheet=CharacterSheet(race="Human", char_class="Fighter",
                             background="Soldier", size="Medium"),
    )
    base.update(over)
    return Character(**base)


def test_named_ally_joins_the_player_party_player_controlled():
    """Forge 4b-ally: an entity named in `encounter.allies` is appended to the party,
    so `build_encounter` team-tags it 'player' and `character_to_player` makes it
    player-controlled — a recruited captain fights at the PC's side, his HP written
    back like any party member."""
    from oubliette.combat.arena_bridge import build_encounter
    from oubliette.combat.arena_launch import _resolve_allies

    pc = _person("pc", "Hero", kind="pc", hp=20, max_hp=20)
    aldric = _person("capt_aldric", "Captain Aldric")
    repo = _ally_repo({"pc": pc, "capt_aldric": aldric})

    req = EncounterRequest(enemies=[EnemyRef(ref="bandit")], allies=["capt_aldric"])
    party = _resolve_allies(req, repo, [pc])
    assert [c.id for c in party] == ["pc", "capt_aldric"]

    plan = build_encounter(party, [], TerrainSpec())
    slot = next(c for c in plan.encounter.combatants
                if c.name_override == "Captain Aldric")
    assert slot.team == "player"
    assert slot.creature_data.is_player_controlled is True
    assert plan.persistent_ids["Captain Aldric"] == "capt_aldric"  # HP writes back


def test_unknown_ally_id_is_skipped_not_fatal():
    """An ally is additive: a stray/hallucinated ally id is dropped silently rather
    than aborting the fight (the opposite of an unknown ENEMY ref, which raises)."""
    from oubliette.combat.arena_launch import _resolve_allies

    pc = _person("pc", "Hero", kind="pc")
    repo = _ally_repo({"pc": pc})

    req = EncounterRequest(enemies=[EnemyRef(ref="bandit")],
                           allies=["ghost_who_isnt_here"])
    party = _resolve_allies(req, repo, [pc])
    assert [c.id for c in party] == ["pc"]


def test_ally_already_in_party_is_not_doubled():
    """Naming the PC (or an already-present party member) as an ally is a no-op —
    deduped by id so no combatant appears twice."""
    from oubliette.combat.arena_launch import _resolve_allies

    pc = _person("pc", "Hero", kind="pc")
    repo = _ally_repo({"pc": pc})

    req = EncounterRequest(enemies=[EnemyRef(ref="bandit")], allies=["pc"])
    party = _resolve_allies(req, repo, [pc])
    assert [c.id for c in party] == ["pc"]
