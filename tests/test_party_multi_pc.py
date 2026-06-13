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

from oubliette.app.server import app  # noqa: E402
from oubliette.dm.brain import Brain  # noqa: E402
from oubliette.enums import Ability, Skill  # noqa: E402
from oubliette.llm.scripted import ScriptedLLMClient  # noqa: E402
from oubliette.record.events import install_character, relevel_character  # noqa: E402
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
