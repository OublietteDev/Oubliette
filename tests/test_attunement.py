"""Attunement enforcement (multiplayer pre-work): the SRD's three-item bond.

An item flagged `requires_attunement` is INERT until its bearer attunes to it;
a hero holds at most three bonds; the ritual happens when the party rests
(attune ops ride REST_TAKEN, replay-safe); and a bond breaks when the item
leaves its bearer's hands. Enforced below the firewall: the bond list lives on
the character, the Arena bridge gates item benefits on it, and the choice
surfaces in the rest popup and the DM's character card.
"""

from __future__ import annotations

import pytest

from oubliette.combat.arena_bridge import equipped_magic, equipped_wards
from oubliette.content.loader import mechanics_catalog
from oubliette.content.ruleset import load_ruleset
from oubliette.content.schemas import Item as PackItem
from oubliette.dm.context import build_context
from oubliette.enums import Ability
from oubliette.record.events import EventKind, StateOp, replay
from oubliette.record.store import SqliteEventStore
from oubliette.rules.attune import MAX_ATTUNED, active_attuned, validate_attunement
from oubliette.runtime.session import Session
from oubliette.seed import seed_world
from oubliette.state.models import Character, CharacterSheet, Item as StateItem, ItemStack
from oubliette.state.repository import InMemoryRepository, StateError

RS = load_ruleset()


def _band(n: int) -> PackItem:
    return PackItem(id=f"band_{n}", name=f"Band {n}", category="gear",
                    slot="ring_1", item_type="ring", magic_bonus=1,
                    requires_attunement=True)


def _plain_ring() -> PackItem:
    return PackItem(id="plain_ring", name="Plain Ring", category="gear",
                    slot="ring_1", item_type="ring", magic_bonus=1)


def _pc(**over) -> Character:
    base = dict(id="pc", name="You", kind="pc", level=3,
                abilities={a: 10 for a in Ability}, hp=20, max_hp=20)
    base.update(over)
    return Character(**base)


# --- validation (the live path, before any op is produced) --------------------

def test_validate_normalizes_and_enforces_the_cap():
    pc = _pc(inventory=[ItemStack(item_id=f"band_{n}", qty=1) for n in range(4)])
    cat = mechanics_catalog(None, [_band(n) for n in range(4)])
    # dedupe, order kept
    assert validate_attunement(pc, cat, ["band_0", "band_1", "band_0"]) == \
        ["band_0", "band_1"]
    # the cap is MAX_ATTUNED, no more
    with pytest.raises(StateError, match="at most"):
        validate_attunement(pc, cat, [f"band_{n}" for n in range(MAX_ATTUNED + 1)])


def test_validate_rejects_uncarried_and_non_attunement_items():
    pc = _pc(inventory=[ItemStack(item_id="band_0", qty=1),
                        ItemStack(item_id="plain_ring", qty=1)])
    cat = mechanics_catalog(None, [_band(0), _plain_ring()])
    with pytest.raises(StateError, match="not carrying"):
        validate_attunement(pc, cat, ["band_1"])
    with pytest.raises(StateError, match="does not require"):
        validate_attunement(pc, cat, ["plain_ring"])


def test_active_attuned_drops_items_no_longer_held():
    # the recorded bond outlives the item only as dead weight, never a benefit
    pc = _pc(inventory=[ItemStack(item_id="band_0", qty=1)],
             attuned=["band_0", "band_1"])
    assert active_attuned(pc) == ["band_0"]


# --- the op records and replays (event-sourced like equip) --------------------

def test_attune_op_sets_bonds_and_replays(tmp_path):
    db = str(tmp_path / "attune.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    # replay trusts recorded ops (validation is live-path only), so the seed
    # world's knife serves fine as the bonded id here
    session.emit_state(EventKind.ATTUNEMENT_CHANGED,
                       [StateOp.attune("pc", ["knife"])], reason="x")
    assert session.repo.pc().attuned == ["knife"]
    store.close()

    store2 = SqliteEventStore(db)
    reloaded = Session.open(store2)
    assert reloaded.repo.pc().attuned == ["knife"]
    repo3 = seed_world()
    replay(store2.read_all(), repo3)
    assert repo3.pc().attuned == ["knife"]
    store2.close()


# --- the bridge gate: an unattuned item grants nothing -------------------------

def test_unattuned_wards_grant_nothing():
    ward = PackItem(id="ember_band", name="Ember Band", category="gear",
                    slot="ring_1", item_type="ring", requires_attunement=True,
                    grants_resistances=["fire"])
    cat = mechanics_catalog(None, [ward])
    worn = _pc(inventory=[ItemStack(item_id="ember_band", qty=1)],
               equipped=["ember_band"])
    bonded = _pc(inventory=[ItemStack(item_id="ember_band", qty=1)],
                 equipped=["ember_band"], attuned=["ember_band"])
    assert equipped_wards(worn, cat) == ([], [])
    assert equipped_wards(bonded, cat) == (["fire"], [])


def test_unattuned_magic_bonus_is_inert_but_bonded_counts():
    cat = mechanics_catalog(None, [_band(0)])
    worn = _pc(inventory=[ItemStack(item_id="band_0", qty=1)], equipped=["band_0"])
    bonded = _pc(inventory=[ItemStack(item_id="band_0", qty=1)],
                 equipped=["band_0"], attuned=["band_0"])
    assert equipped_magic(worn, cat) == (0, 0)
    assert equipped_magic(bonded, cat) == (0, 1)


# --- the DM's card: live bonds + dormant carried items -------------------------

def test_dm_card_shows_bonds_and_dormant_items():
    pc = _pc(
        inventory=[ItemStack(item_id="band_0", qty=1),
                   ItemStack(item_id="band_1", qty=1)],
        attuned=["band_0"],
        sheet=CharacterSheet(race="human", char_class="rogue",
                             background="criminal"),
    )
    items = [StateItem(id="band_0", name="Band 0", category="gear"),
             StateItem(id="band_1", name="Band 1", category="gear")]
    repo = InMemoryRepository([pc], items, "pc")
    mech = mechanics_catalog(None, [_band(0), _band(1)])
    ctx = build_context(repo, "a scene", ruleset=RS, mechanics=mech)
    assert f"Attuned (1/{MAX_ATTUNED}): Band 0" in ctx
    assert "NOT attuned" in ctx and "Band 1" in ctx


def test_dm_card_stays_silent_without_attunement_items():
    pc = _pc(inventory=[ItemStack(item_id="plain_ring", qty=1)],
             sheet=CharacterSheet(race="human", char_class="rogue",
                                  background="criminal"))
    repo = InMemoryRepository(
        [pc], [StateItem(id="plain_ring", name="Plain Ring", category="gear")], "pc")
    ctx = build_context(repo, "a scene", ruleset=RS,
                        mechanics=mechanics_catalog(None, [_plain_ring()]))
    assert "Attuned" not in ctx


# --- the rest endpoint runs the ritual ------------------------------------------

def test_rest_endpoint_attunes_and_unattunes():
    import os
    import tempfile
    os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "attune.sqlite")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from fastapi.testclient import TestClient
    from oubliette.app import server
    client = TestClient(server.app)
    client.post("/api/new")

    # the party finds a Ring of Protection (SRD: requires attunement)
    server.GAME.session.repo.add_item("pc", "ring_of_protection", 1)

    # the sheet offers the choice
    sheet = client.get("/api/sheet").json()["party"][0]
    assert sheet["attunement"]["max"] == MAX_ATTUNED
    assert sheet["attunement"]["attunable"] == [
        {"item_id": "ring_of_protection", "name": "Ring of Protection", "attuned": False}]

    # attuning rides a short rest
    r = client.post("/api/rest", json={
        "kind": "short", "attune_by": {"pc": ["ring_of_protection"]}}).json()
    assert r["ok"] is True
    member = next(m for m in r["party"] if m["id"] == "pc")
    assert member["attunement"]["attuned"] == ["ring_of_protection"]
    row = next(i for i in client.get("/api/inventory").json()["party"][0]["items"]
               if i["item_id"] == "ring_of_protection")
    assert row["attuned"] is True and row["requires_attunement"] is True

    # bad choices abort the rest before anything is spent
    bad = client.post("/api/rest", json={
        "kind": "short", "attune_by": {"pc": ["knife"]}})
    assert bad.status_code == 400 and bad.json()["error"] == "attune"
    bad2 = client.post("/api/rest", json={
        "kind": "short", "attune_by": {"pc": ["amulet_of_health"]}})
    assert bad2.status_code == 400

    # ending the bond is the same ritual with an empty list
    r2 = client.post("/api/rest", json={"kind": "short", "attune_by": {"pc": []}}).json()
    assert r2["ok"] is True
    member2 = next(m for m in r2["party"] if m["id"] == "pc")
    assert member2["attunement"]["attuned"] == []


def test_handover_breaks_the_givers_bond():
    """An attuned item that leaves its bearer's hands ends the bond (recorded as
    ATTUNEMENT_CHANGED via the prune) — the receiver starts unbonded."""
    import os
    import tempfile
    os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "prune.sqlite")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    from fastapi.testclient import TestClient
    from oubliette.app import server
    client = TestClient(server.app)
    client.post("/api/new")

    repo = server.GAME.session.repo
    repo.install_party([repo.pc(), Character(
        id="buddy", name="Buddy", kind="pc", level=1,
        abilities={a: 10 for a in Ability}, hp=8, max_hp=8)])
    repo.add_item("pc", "ring_of_protection", 1)
    r = client.post("/api/rest", json={
        "kind": "short", "attune_by": {"pc": ["ring_of_protection"]}}).json()
    assert r["ok"] is True

    h = client.post("/api/handover", json={
        "from_id": "pc", "to_id": "buddy", "item_id": "ring_of_protection"}).json()
    assert h["ok"] is True
    assert repo.get_character("pc").attuned == []          # the bond broke
    assert repo.get_character("buddy").attuned == []       # and didn't transfer
