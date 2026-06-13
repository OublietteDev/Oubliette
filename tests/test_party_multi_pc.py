"""Multi-character party (game start with N PCs).

Pins the foundation: a party of built PCs is seeded at game start, survives replay,
level-up swaps one member in place (without wiping the others), legacy single-PC saves
still load, and skill checks use the most capable member ("best member rolls").
"""

from __future__ import annotations

import os
import tempfile

os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "party-test.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import GAME, app  # noqa: E402
from oubliette.dm.brain import Brain  # noqa: E402
from oubliette.enums import Ability, Skill  # noqa: E402
from oubliette.llm.scripted import ScriptedLLMClient  # noqa: E402
from oubliette.record.events import StateOp, install_character, relevel_character  # noqa: E402
from oubliette.record.rng import Rng  # noqa: E402
from oubliette.record.store import InMemoryEventStore  # noqa: E402
from oubliette.rules.chargen import CharacterBuild  # noqa: E402
from oubliette.runtime.loop import TurnLoop  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402
from oubliette.schemas import RollRequest  # noqa: E402
from oubliette.state.repository import InMemoryRepository  # noqa: E402

client = TestClient(app)

_STD = {Ability.STR: 15, Ability.DEX: 14, Ability.CON: 13,
        Ability.INT: 12, Ability.WIS: 10, Ability.CHA: 8}
# A valid standard-array permutation with CHA highest (the face of the party).
_HIGH_CHA = {Ability.STR: 13, Ability.DEX: 14, Ability.CON: 12,
             Ability.INT: 10, Ability.WIS: 8, Ability.CHA: 15}


def _fighter(name: str, abilities=None) -> CharacterBuild:
    return CharacterBuild(
        name=name, race="human", char_class="fighter", background="acolyte",
        ability_method="standard_array", base_abilities=abilities or dict(_STD),
        skills=[Skill.PERCEPTION, Skill.SURVIVAL],
        languages=["Draconic", "Celestial"], race_languages=["Orc"],
        equipment_choices=[[0], [0], [0]],
    )


def _session() -> Session:
    return Session.open(InMemoryEventStore())


# --- seeding + replay -------------------------------------------------------

def test_party_created_seeds_all_members_with_unique_ids():
    s = _session()
    chars = s.emit_party_created([_fighter("Bron"), _fighter("Sera"), _fighter("Kael")])
    assert [c.name for c in chars] == ["Bron", "Sera", "Kael"]
    party = s.repo.party()
    assert len(party) == 3
    assert {c.id for c in party} == {"pc", "pc2", "pc3"}    # lead is "pc"
    assert s.repo.pc().name == "Bron"                       # first build = lead PC


def test_party_survives_replay():
    store = InMemoryEventStore()
    Session.open(store).emit_party_created([_fighter("Bron"), _fighter("Sera")])
    reopened = Session.open(store)                          # replays the event log
    assert sorted(c.name for c in reopened.repo.party()) == ["Bron", "Sera"]
    assert reopened.repo.pc().name == "Bron"


def test_legacy_single_character_payload_still_loads_as_party_of_one():
    # Saves predating multi-PC carry a single `character`, not a `characters` list.
    s = _session()
    one = s.emit_party_created([_fighter("Solo")])[0]
    repo = InMemoryRepository(characters=[], items=[], pc_id="pc")
    install_character({"character": one.model_dump(mode="json"), "items": []}, repo)
    assert [c.name for c in repo.party()] == ["Solo"]
    assert repo.pc().name == "Solo"


# --- level-up must NOT wipe the rest of the party ---------------------------

def test_level_up_replaces_one_member_in_place():
    s = _session()
    s.emit_party_created([_fighter("Bron"), _fighter("Sera")])
    sera = next(c for c in s.repo.party() if c.name == "Sera")
    leveled = sera.model_copy(update={"level": 2})
    relevel_character({"character": leveled.model_dump(mode="json"), "items": []}, s.repo)
    party = {c.name: c for c in s.repo.party()}
    assert set(party) == {"Bron", "Sera"}                  # Bron NOT wiped
    assert party["Sera"].level == 2 and party["Bron"].level == 1
    assert s.repo.pc().name == "Bron"                      # lead pointer preserved


# --- best member rolls ------------------------------------------------------

def test_best_member_rolls_the_relevant_check():
    s = _session()
    s.emit_party_created([_fighter("Bron"), _fighter("Sera", _HIGH_CHA)])
    loop = TurnLoop(s, Rng(seed=1, record=s.emit_log), Brain(ScriptedLLMClient()))
    sera = next(c for c in s.repo.party() if c.name == "Sera")
    bron = s.repo.pc()
    # CHA-based check -> the high-CHA member (Sera) rolls
    cha_roller, cha_mod = loop._best_roller(RollRequest(skill=Skill.PERSUASION, dc=10, purpose="persuade"))
    assert cha_roller.id == sera.id and cha_mod == sera.ability_mod(Ability.CHA)
    # STR-based check -> the high-STR member (Bron, the lead) rolls instead
    str_roller, str_mod = loop._best_roller(RollRequest(ability=Ability.STR, dc=10, purpose="shove"))
    assert str_roller.id == bron.id and str_mod == bron.ability_mod(Ability.STR)


# --- the API party path -----------------------------------------------------

def test_api_new_with_builds_creates_a_full_party():
    builds = [_fighter("Bron").model_dump(mode="json"),
              _fighter("Sera", _HIGH_CHA).model_dump(mode="json")]
    r = client.post("/api/new", json={"builds": builds})
    assert r.status_code == 200 and r.json()["ok"] is True
    party = client.get("/api/sheet").json()["party"]
    assert sorted(m["name"] for m in party) == ["Bron", "Sera"]


def _start_party():
    client.post("/api/new", json={"builds": [
        _fighter("Bron").model_dump(mode="json"),
        _fighter("Sera", _HIGH_CHA).model_dump(mode="json")]})
    for c in GAME.session.repo.party():   # wound everyone so recovery is observable
        c.hp = 1


def test_long_rest_restores_the_whole_party():
    _start_party()
    r = client.post("/api/rest", json={"kind": "long", "char_id": "pc"}).json()
    assert r["ok"] is True
    assert all(m["hp"] == m["max_hp"] for m in r["party"])   # every member healed, not just the lead


def test_short_rest_spends_hit_dice_only_for_the_named_member():
    _start_party()
    # spend a hit die as pc2 (Sera); the rest of the party still rests but heals no HP
    r = client.post("/api/rest", json={"kind": "short", "char_id": "pc2", "hit_dice": 1}).json()
    party = {m["name"]: m for m in r["party"]}
    assert party["Sera"]["hp"] > 1            # Sera spent a hit die and healed
    assert party["Bron"]["hp"] == 1           # Bron took the short rest but spent no dice


def test_short_rest_hit_dice_by_member_map():
    _start_party()                            # Bron=pc, Sera=pc2, both at hp 1
    # the party popup sends a per-member spend: Bron spends 1, Sera spends 0
    r = client.post("/api/rest", json={"kind": "short", "hit_dice_by": {"pc": 1, "pc2": 0}}).json()
    party = {m["name"]: m for m in r["party"]}
    assert party["Bron"]["hp"] > 1
    assert party["Sera"]["hp"] == 1


# --- combat XP is shared across the party (RAW) -----------------------------

def _party_loop(*names):
    s = _session()
    s.emit_party_created([_fighter(n) for n in names])
    return TurnLoop(s, Rng(seed=1, record=s.emit_log), Brain(ScriptedLLMClient()))


def test_combat_xp_splits_evenly_across_the_party():
    loop = _party_loop("A", "B", "C")
    ops = loop._split_combat_xp([StateOp.xp("pc", 100)], 100)
    xp = {op.char: op.delta for op in ops if op.op == "xp"}
    assert sum(xp.values()) == 100                 # no XP lost
    assert set(xp) == {"pc", "pc2", "pc3"}         # every member shares
    assert sorted(xp.values()) == [33, 33, 34]     # remainder spread one per member


def test_combat_xp_solo_party_keeps_the_full_award():
    loop = _party_loop("Solo")
    ops = loop._split_combat_xp([StateOp.xp("pc", 100)], 100)
    xp = {op.char: op.delta for op in ops if op.op == "xp"}
    assert xp == {"pc": 100}                       # solo: the lead keeps it all


# --- Phase 2: party-aware narration + HUD -----------------------------------

def test_dm_context_lists_the_whole_party_by_id():
    from oubliette.dm.context import build_context
    s = _session()
    s.emit_party_created([_fighter("Bron"), _fighter("Sera", _HIGH_CHA)])
    ctx = build_context(s.repo, scene="a tavern")
    assert "PARTY" in ctx
    # each hero appears with their id so the DM can call checks / award XP per member
    assert "Bron (id: pc)" in ctx and "Sera (id: pc2)" in ctx


def test_state_snapshot_includes_the_whole_party():
    builds = [_fighter("Bron").model_dump(mode="json"),
              _fighter("Sera", _HIGH_CHA).model_dump(mode="json")]
    client.post("/api/new", json={"builds": builds})
    state = client.get("/api/state").json()["state"]
    assert [m["name"] for m in state["party"]] == ["Bron", "Sera"]
    assert state["pc"]["name"] == "Bron"           # lead still present (back-compat)
