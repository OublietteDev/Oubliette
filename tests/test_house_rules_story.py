"""House rules per world — story side: the manifest block, the pack→session
plumbing, the bridge's encounter-file carriage, the potion action-economy
override, and the player-facing read-only labels."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oubliette.combat.arena_bridge import build_encounter, consumable_actions
from oubliette.combat.schemas import TerrainSpec
from oubliette.content.loader import DEFAULT_PACK, load_pack
from oubliette.content.ruleset import load_ruleset
from oubliette.content.schemas import HouseRules, PackManifest
from oubliette.enums import Ability
from oubliette.state.models import Character, ItemStack

RS = load_ruleset()

_MANIFEST = {
    "id": "testworld", "schema_version": 1, "name": "Test World",
    "version": "1.0.0", "entry_scenario": "intro",
}


def _pc(**over) -> Character:
    base = dict(id="pc", name="You", kind="pc", level=3,
                abilities={a: 10 for a in Ability}, hp=20, max_hp=20)
    base.update(over)
    return Character(**base)


# --- the manifest block -------------------------------------------------------

def test_manifest_without_house_rules_plays_by_the_book():
    m = PackManifest.model_validate(_MANIFEST)
    assert m.house_rules.initiative == "standard"
    assert m.house_rules.flanking is False
    assert m.house_rules.potions_bonus_action is False


def test_manifest_house_rules_parse_and_validate():
    m = PackManifest.model_validate({
        **_MANIFEST,
        "house_rules": {"initiative": "side", "flanking": True,
                        "crit_range_19": True, "brutal_crits": True,
                        "potions_bonus_action": True},
    })
    assert m.house_rules.initiative == "side"
    assert m.house_rules.brutal_crits is True
    with pytest.raises(ValidationError):        # only the three known variants
        PackManifest.model_validate({**_MANIFEST,
                                     "house_rules": {"initiative": "popcorn"}})


def test_default_pack_ships_book_rules():
    world = load_pack(DEFAULT_PACK)
    assert world.house_rules is not None
    assert world.house_rules.initiative == "standard"
    assert world.house_rules.flanking is False


# --- the bridge: rules ride the encounter file ---------------------------------

def test_build_encounter_carries_the_house_rules():
    from oubliette.combat.arena_bridge import enemy_from_statblock
    enemies = [enemy_from_statblock(RS.bestiary["bandit"])]
    rules = HouseRules(initiative="side", flanking=True, crit_range_19=True,
                       brutal_crits=True, potions_bonus_action=True)
    plan = build_encounter([_pc()], enemies, TerrainSpec(kind="open"),
                           house_rules=rules)
    enc = plan.encounter.house_rules
    assert enc.initiative == "side" and enc.flanking is True
    assert enc.crit_range_19 is True and enc.brutal_crits is True
    # No rules given (custom seeds / tests) → the encounter plays by the book
    plain = build_encounter([_pc()], enemies, TerrainSpec(kind="open"))
    assert plain.encounter.house_rules.initiative == "standard"
    assert plain.encounter.house_rules.flanking is False


def test_potions_bonus_action_overrides_the_drink_cost():
    from arena.models.actions import ActionType
    pc = _pc(inventory=[ItemStack(item_id="potion_of_healing", qty=1)])
    (book,) = consumable_actions(pc, RS.equipment)
    assert book.action_type == ActionType.ACTION           # SRD: an action
    (house,) = consumable_actions(pc, RS.equipment, True)  # the house rule
    assert house.action_type == ActionType.BONUS_ACTION


# --- the player-facing labels ---------------------------------------------------

def test_state_snapshot_lists_no_rules_for_a_book_world():
    import os
    import tempfile
    os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "hr.sqlite")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from fastapi.testclient import TestClient
    from oubliette.app import server
    client = TestClient(server.app)
    client.post("/api/new")
    state = client.get("/api/state").json()["state"]
    assert state["house_rules"] == []                      # brightvale = by the book

    # Flip the session's rules live: the labels speak every active variant.
    server.GAME.session.house_rules = HouseRules(
        initiative="reroll", flanking=True, potions_bonus_action=True)
    labels = client.get("/api/state").json()["state"]["house_rules"]
    assert len(labels) == 3
    assert any("re-rolled" in t for t in labels)
    assert any("Flanking" in t for t in labels)
    assert any("bonus action" in t for t in labels)
