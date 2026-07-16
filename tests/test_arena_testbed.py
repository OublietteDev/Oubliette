"""The Arena test bed, T1 — the proving ground (Forge v2.0).

The benchmark party is generated data (tools/gen_benchmark_party.py drove the
real chargen + level-up engines once); these tests pin that the snapshots
stay loadable and honest, that the sandbox stager builds faithful encounters
(teams, watch mode, authored battlefields, creature allies), and that the
creator endpoint runs the whole loop with the Arena subprocess canned.
"""

from __future__ import annotations

import json
import shutil

import pytest

from oubliette.combat.boundary import CombatError
from oubliette.combat.testbed import (MAX_BENCH_LEVEL, benchmark_party,
                                      benchmark_roster, stage_test_fight)
from oubliette.content.loader import _PACKS_ROOT, load_pack
from oubliette.content.ruleset import load_ruleset

RS = load_ruleset()


# --- the benchmark party -------------------------------------------------------

def test_roster_is_the_classic_four():
    assert benchmark_roster() == ["fighter", "cleric", "rogue", "wizard"]


def test_every_snapshot_loads_and_levels_honestly():
    for level in range(1, MAX_BENCH_LEVEL + 1):
        chars, items = benchmark_party(level, 4)
        assert [c.sheet.char_class for c in chars] == benchmark_roster()
        for c in chars:
            assert c.level == level and c.hp == c.max_hp > 0
            assert c.equipped, f"{c.id} L{level} has no loadout"
    assert {i.id for i in items} >= {"chain_mail", "rapier", "quarterstaff"}


def test_casters_carry_castable_spells():
    chars, _ = benchmark_party(5, 4)
    by_class = {c.sheet.char_class: c for c in chars}
    assert "cure_wounds" in by_class["cleric"].sheet.spells_known
    assert "fireball" in benchmark_party(9, 4)[0][3].sheet.spells_known
    assert by_class["wizard"].sheet.cantrips_known  # fire_bolt et al.


def test_party_of_n_takes_the_first_n():
    chars, _ = benchmark_party(3, 2)
    assert [c.sheet.char_class for c in chars] == ["fighter", "cleric"]


def test_bounds_are_enforced():
    with pytest.raises(CombatError):
        benchmark_party(0, 4)
    with pytest.raises(CombatError):
        benchmark_party(3, 5)


# --- the sandbox stager ----------------------------------------------------------

@pytest.fixture(scope="module")
def world():
    return load_pack("brightvale")


def _stage(world, **kw):
    kw.setdefault("enemies", [("wolf", 2)])
    kw.setdefault("party_level", 3)
    kw.setdefault("party_size", 4)
    p = stage_test_fight(world, _PACKS_ROOT / "brightvale", **kw)
    enc = json.loads(p.encounter_path.read_text(encoding="utf-8"))
    shutil.rmtree(p.scratch_dir, ignore_errors=True)
    return enc


def test_stage_builds_party_vs_enemies(world):
    enc = _stage(world)
    teams = [(c["team"], c["name_override"]) for c in enc["combatants"]]
    assert teams[:4] == [("player", "Bram"), ("player", "Mirelle"),
                         ("player", "Vex"), ("player", "Aldous")]
    assert [t for t, _ in teams].count("enemy") == 2
    assert enc["use_ai_for_allies"] is False       # the author fights by default


def test_watch_mode_hands_the_party_to_the_ai(world):
    assert _stage(world, watch=True)["use_ai_for_allies"] is True


def test_unknown_creature_fails_loudly(world):
    with pytest.raises(CombatError):
        _stage(world, enemies=[("definitely_not_a_monster", 1)])


def test_a_place_without_a_battle_map_is_refused(world):
    some_place = next(iter(world.places))
    node = world.places[some_place]
    if getattr(node, "battle", None) is None:
        with pytest.raises(CombatError):
            _stage(world, place_id=some_place)


def test_creature_allies_join_the_player_side(world):
    enc = _stage(world, allies=["wolf"])
    players = [c for c in enc["combatants"] if c["team"] == "player"]
    assert len(players) == 5                        # the four + the wolf
    assert any(c["name_override"] == "Wolf" for c in players)


# --- the creator endpoint ---------------------------------------------------------

def _canned_handoff(pending):
    return {"schema": 1, "winner": "player", "outcome": "victory", "rounds": 4,
            "combatants": [
                {"id": "Bram", "name": "Bram", "team": "player", "is_pc": True,
                 "hp": 21, "max_hp": 28, "temp_hp": 0, "conditions": [],
                 "is_conscious": True, "xp": 0},
                {"id": "Wolf", "name": "Wolf", "team": "enemy", "is_pc": False,
                 "hp": 0, "max_hp": 11, "temp_hp": 0, "conditions": [],
                 "is_conscious": False, "xp": 50},
            ]}


def test_endpoint_runs_the_loop_and_summarizes(monkeypatch):
    from fastapi.testclient import TestClient
    import oubliette.combat.arena_launch as arena_launch
    from oubliette.creator.server import app
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(_PACKS_ROOT))
    monkeypatch.setattr(arena_launch, "run_arena", _canned_handoff)
    client = TestClient(app)
    r = client.post("/api/pack/brightvale/test-fight",
                    json={"enemies": [{"ref": "wolf", "count": 2}],
                          "party_level": 3, "party_size": 4, "watch": False})
    d = r.json()
    assert r.status_code == 200, d
    assert d["ok"] is True and d["outcome"] == "victory" and d["rounds"] == 4
    assert d["party"] == [{"name": "Bram", "hp": 21, "max_hp": 28, "conscious": True}]


def test_endpoint_refuses_an_unknown_creature(monkeypatch):
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(_PACKS_ROOT))
    client = TestClient(app)
    r = client.post("/api/pack/brightvale/test-fight",
                    json={"enemies": [{"ref": "nonsense_beast"}]})
    assert r.status_code == 400
    assert "nonsense_beast" in r.json()["error"]


def test_endpoint_404s_an_unknown_pack(monkeypatch):
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(_PACKS_ROOT))
    client = TestClient(app)
    r = client.post("/api/pack/nope/test-fight", json={"enemies": [{"ref": "wolf"}]})
    assert r.status_code == 404


# --- T2: the spell range / attack previews ------------------------------------

def test_spell_preview_stages_the_lone_caster(world):
    from oubliette.combat.testbed import stage_spell_preview
    p = stage_spell_preview(world, _PACKS_ROOT / "brightvale", spell_id="fireball")
    enc = json.loads(p.encounter_path.read_text(encoding="utf-8"))
    teams = [(c["team"], c["name_override"]) for c in enc["combatants"]]
    assert teams[0] == ("player", "Aldous")
    assert [t for t, _ in teams].count("enemy") == 2      # the dummies
    caster = json.loads(open([c for c in enc["combatants"]
                              if c["team"] == "player"][0]["creature_id"],
                             encoding="utf-8").read())
    names = [a["name"] for a in caster.get("actions", [])]
    assert "Fireball" in names and "Magic Missile" not in names   # ONLY the previewed spell
    shutil.rmtree(p.scratch_dir, ignore_errors=True)


def test_spell_preview_takes_an_unsaved_inline_spell(world):
    from oubliette.combat.testbed import stage_spell_preview
    inline = {"id": "test_zap", "name": "Test Zap", "level": 1,
              "school": "evocation", "classes": ["wizard"],
              "chassis": {"kind": "bolt", "range_ft": 60,
                          "damage": "2d8", "damage_type": "lightning"},
              "description": "An unsaved zap."}
    p = stage_spell_preview(world, _PACKS_ROOT / "brightvale", spell=inline)
    enc = json.loads(p.encounter_path.read_text(encoding="utf-8"))
    assert enc["name"] == "Spell Range — Test Zap"
    shutil.rmtree(p.scratch_dir, ignore_errors=True)


def test_spell_preview_refuses_what_the_caster_cannot_slot(world):
    from oubliette.combat.testbed import stage_spell_preview
    with pytest.raises(CombatError):                       # 9th-level spell, L9 caster
        stage_spell_preview(world, _PACKS_ROOT / "brightvale", spell_id="power_word_kill")


def test_attack_preview_puts_the_creature_against_dummies(world):
    from oubliette.combat.testbed import stage_attack_preview
    sb = world.statblocks[0].model_dump(mode="json")
    p = stage_attack_preview(world, _PACKS_ROOT / "brightvale", statblock=sb)
    enc = json.loads(p.encounter_path.read_text(encoding="utf-8"))
    players = [c for c in enc["combatants"] if c["team"] == "player"]
    assert len(players) == 2 and all("Dummy" in c["name_override"] for c in players)
    assert enc["use_ai_for_allies"] is True                # dummies pass their turns
    shutil.rmtree(p.scratch_dir, ignore_errors=True)


# --- T3: the war room --------------------------------------------------------------

def test_sim_batch_is_deterministic_and_honest(world):
    from arena.sim import run_batch
    p = stage_test_fight(world, _PACKS_ROOT / "brightvale",
                         enemies=[("wolf", 1)], party_level=3, party_size=2, watch=True)
    a = run_batch(p.encounter_path, 3, seed=7, round_cap=30)
    b = run_batch(p.encounter_path, 3, seed=7, round_cap=30)
    shutil.rmtree(p.scratch_dir, ignore_errors=True)
    assert a == b                                          # same seed, same story
    assert a["iterations"] == 3
    assert sum(a["wins"].values()) == 3
    assert {q["name"] for q in a["party"]} == {"Bram", "Mirelle"}
    assert "floor" in a["caveat"]


def test_a_stomped_party_is_an_enemy_win_not_a_draw(world):
    """Found live by Chris: 92 'draws' against a dragon that had downed the
    whole party — stabilized-at-0 heroes counted as still fighting, and the
    enemy had no conscious target left to finish. The sim now arms the same
    solo_defeat_when_downed rule the handoff sets: fully downed = defeat."""
    from arena.sim import run_batch
    p = stage_test_fight(world, _PACKS_ROOT / "brightvale",
                         enemies=[("ogre", 2)], party_level=1, party_size=1,
                         watch=True)
    r = run_batch(p.encounter_path, 5, seed=11, round_cap=30)
    shutil.rmtree(p.scratch_dir, ignore_errors=True)
    assert r["wins"]["enemy"] >= 4                 # two ogres vs a lone level-1
    assert r["wins"]["draw"] == 0                  # a stomp is never a draw


def test_round_cap_reports_a_draw(world):
    from arena.sim import run_batch
    p = stage_test_fight(world, _PACKS_ROOT / "brightvale",
                         enemies=[("wolf", 1)], party_level=3, party_size=2, watch=True)
    r = run_batch(p.encounter_path, 1, seed=7, round_cap=0)   # capped before round 1 ends
    shutil.rmtree(p.scratch_dir, ignore_errors=True)
    assert r["wins"]["draw"] == 1 and r["win_pct"] == 0.0


def test_simulate_endpoint_runs_the_real_headless_batch(monkeypatch):
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(_PACKS_ROOT))
    client = TestClient(app)
    r = client.post("/api/pack/brightvale/simulate",
                    json={"enemies": [{"ref": "wolf", "count": 1}],
                          "party_level": 3, "party_size": 2, "iterations": 2})
    d = r.json()
    assert r.status_code == 200, d
    assert d["ok"] is True and d["iterations"] == 2
    assert 0.0 <= d["win_pct"] <= 100.0 and d["party"]


def test_preview_endpoints_gate_like_the_game(monkeypatch):
    from fastapi.testclient import TestClient
    from oubliette.creator.server import app
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(_PACKS_ROOT))
    client = TestClient(app)
    r = client.post("/api/pack/brightvale/preview-spell", json={"spell_id": "not_a_spell"})
    assert r.status_code == 400
    r = client.post("/api/pack/nope/preview-attack", json={"statblock": {}})
    assert r.status_code == 404
