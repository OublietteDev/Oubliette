"""C5 — re-prepare spells through the live app (HTTP path + long-rest gating).

Drives the FastAPI server with the scripted DM: build a prepared caster, take a
long rest to open the window, swap the readied list, and confirm the firewall
rejects bad picks. The breadth of the cleric/wizard *pool* is unit-tested in
test_reprepare; here we prove the endpoint, the window gate, and the event path.
"""

from __future__ import annotations

import os
import tempfile

os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "reprepare-api.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)   # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import app  # noqa: E402
from oubliette.enums import Ability, Skill  # noqa: E402
from oubliette.rules.chargen import CharacterBuild  # noqa: E402

client = TestClient(app)


def _wizard() -> dict:
    return CharacterBuild(
        name="Mira", race="human", char_class="wizard", background="acolyte",
        ability_method="standard_array",
        base_abilities={Ability.INT: 15, Ability.DEX: 14, Ability.CON: 13,
                        Ability.WIS: 12, Ability.STR: 10, Ability.CHA: 8},
        skills=[Skill.ARCANA, Skill.INVESTIGATION],
        languages=["Draconic", "Celestial"], race_languages=["Orc"],
        cantrips=["fire_bolt", "mage_hand", "light"],
        spells=["magic_missile", "shield", "burning_hands", "detect_magic"],
        equipment_choices=[[1]],
    ).model_dump(mode="json")


def _sc():
    return client.get("/api/sheet").json()["party"][0]["spellcasting"]


def _new_story_game(**extra) -> dict:
    """A Story-table game: long rests stay one-click here (the S3 gate has its
    own test file); these tests are about the re-prepare window."""
    return client.post("/api/new",
                       json={"difficulty": {"preset": "story"}, **extra}).json()


def test_reprepare_flow_through_the_app():
    assert _new_story_game(builds=[_wizard()])["ok"]

    # Before any long rest the window is shut.
    sc = _sc()
    assert sc["preparation"] == "prepared"
    assert sc["reprepare_window_open"] is False
    assert sc["can_reprepare"] is False
    pool_ids = [s["id"] for s in sc["prepare_pool"]]
    assert sorted(pool_ids) == ["burning_hands", "detect_magic", "magic_missile", "shield"]

    # A long rest opens the window.
    assert client.post("/api/rest", json={"kind": "long"}).json()["ok"]
    sc = _sc()
    assert sc["reprepare_window_open"] is True
    assert sc["can_reprepare"] is True
    count = sc["prepared_count"]

    # A valid re-preparation (reordered, exactly `count`) is accepted and sticks.
    pick = list(reversed(pool_ids))[:count]
    r = client.post("/api/prepare_spells", json={"char_id": "pc", "spells": pick})
    assert r.json()["ok"] is True
    after = _sc()
    assert set(after["prepared_ids"]) == set(pick)
    assert {s["id"] for s in after["spells"]} == set(pick)


def test_firewall_rejects_bad_picks():
    assert _new_story_game(builds=[_wizard()])["ok"]
    client.post("/api/rest", json={"kind": "long"})
    count = _sc()["prepared_count"]

    # Wrong count.
    r = client.post("/api/prepare_spells",
                    json={"char_id": "pc", "spells": ["shield"]})
    assert r.json()["ok"] is False and "exactly" in r.json()["error"]

    # Out of the spellbook (fly is a wizard spell, but not in this book).
    bad = (["fly"] + ["magic_missile", "shield", "detect_burning", "burning_hands"])[:count]
    r = client.post("/api/prepare_spells", json={"char_id": "pc", "spells": bad})
    assert r.json()["ok"] is False and "not available" in r.json()["error"]


def test_window_shut_rejects_without_long_rest():
    assert _new_story_game(builds=[_wizard()])["ok"]
    # No long rest taken → endpoint refuses regardless of a valid pick.
    pool = [s["id"] for s in _sc()["prepare_pool"]]
    count = _sc()["prepared_count"]
    r = client.post("/api/prepare_spells", json={"char_id": "pc", "spells": pool[:count]})
    assert r.json()["ok"] is False and "long rest" in r.json()["error"]
