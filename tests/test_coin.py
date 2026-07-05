"""Coinage (the copper migration): parse/format helpers, mixed-coin tool
entries, party-purse routing, and — most importantly — that PRE-COIN saves
replay to the right purse (legacy `gold` fields and ops mean GOLD pieces and
scale ×100 exactly once)."""

from __future__ import annotations

import pytest

from oubliette.coin import authored_to_cp, format_cp, parse_coin, split_cp
from oubliette.record.events import Event, EventKind, StateOp, apply_event, replay
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from oubliette.state.models import Character, Item
from oubliette.state.repository import InMemoryRepository, StateError
from oubliette.tools.schemas import ValueEntry


# --- helpers -------------------------------------------------------------------
def test_parse_coin_units_and_mixes():
    assert parse_coin("5 sp") == 50
    assert parse_coin("3 cp") == 3
    assert parse_coin("2 pp") == 2000
    assert parse_coin("1 gp 5 sp") == 150
    assert parse_coin("10 gold") == 1000
    assert parse_coin("1,200 gp") == 120000
    assert parse_coin("15") == 1500                    # bare number: default gp
    assert parse_coin("15", default_unit="sp") == 150
    for bad in ("", "gold", "5 groats", "5 sp and change"):
        with pytest.raises(ValueError):
            parse_coin(bad)


def test_authored_values_keep_gold_semantics_for_ints():
    assert authored_to_cp(10) == 1000                  # every existing pack stays right
    assert authored_to_cp("5 sp") == 50
    assert authored_to_cp(None) is None


def test_format_cp_reads_like_a_table_talks():
    assert format_cp(235) == "2 gp 3 sp 5 cp"
    assert format_cp(1500) == "15 gp"
    assert format_cp(50) == "5 sp"
    assert format_cp(3) == "3 cp"
    assert format_cp(0) == "0 gp"
    assert format_cp(-150) == "-1 gp 5 sp"
    assert format_cp(250000) == "2,500 gp"             # no platinum promotion
    assert split_cp(235) == (2, 3, 5)


# --- ValueEntry money ------------------------------------------------------------
def test_value_entry_mixes_coins():
    e = ValueEntry(gold=1, silver=5)
    assert e.money_cp() == 150
    assert ValueEntry(platinum=1).money_cp() == 1000
    assert ValueEntry.from_cp(235).money_cp() == 235
    with pytest.raises(Exception):
        ValueEntry(gold=1, item_id="boots")            # money XOR item
    with pytest.raises(Exception):
        ValueEntry(silver=0)                           # zero money is no entry
    with pytest.raises(Exception):
        ValueEntry(gold=1, copper=-5)                  # no negative coins


# --- purse routing ----------------------------------------------------------------
def _repo():
    pc = Character(id="pc", name="Hero", kind="pc", gold=15)          # legacy gp kwarg
    npc = Character(id="npc", name="Til", kind="npc", coin=500)
    return InMemoryRepository(characters=[pc, npc], items=[], pc_id="pc")


def test_pc_coin_sweeps_to_purse_and_ops_route_there():
    repo = _repo()
    assert repo.party_cp == 1500                       # 15 gp swept in as copper
    assert repo.pc().coin == 0
    repo.adjust_coin("pc", -500)                       # spending routes to the purse
    assert repo.party_cp == 1000
    repo.adjust_coin("npc", 250)                       # NPCs keep their own pocket
    assert repo.get_character("npc").coin == 750
    assert repo.balance_cp("pc") == 1000 and repo.balance_cp("npc") == 750
    with pytest.raises(StateError):
        repo.adjust_coin("pc", -99999)                 # the purse can't go negative


# --- legacy save migration ----------------------------------------------------------
def test_legacy_gold_ops_replay_scaled_once():
    """A pre-coin save: CHARACTER payload holds `gold` (gp) and TOOL_APPLIED ops say
    op='gold' with gp deltas. Replay lands the same totals ×100, in the purse."""
    pc = Character(id="pc", name="Hero", kind="pc", gold=15)
    npc = Character(id="npc", name="Til", kind="npc", gold=500)        # legacy gp pocket
    repo = InMemoryRepository(characters=[pc, npc], items=[], pc_id="pc")
    legacy = Event(seq=10, kind=EventKind.TOOL_APPLIED.value,
                   payload={"ops": [
                       {"op": "gold", "char": "pc", "delta": 250},     # sold the boots
                       {"op": "gold", "char": "npc", "delta": -250},   # merchant paid
                   ]})
    replay([legacy], repo)
    assert repo.party_cp == (15 + 250) * 100
    assert repo.get_character("npc").coin == (500 - 250) * 100


def test_legacy_character_created_payload_pools_into_purse():
    """An old save's CHARACTER_CREATED pooled all gold onto the lead (gp). The
    install sweep turns that into the same-sized purse."""
    repo = _repo()
    ev = Event(seq=1, kind=EventKind.CHARACTER_CREATED.value, payload={
        "characters": [
            {"id": "pc", "name": "A", "kind": "pc", "gold": 45},       # pooled lead
            {"id": "pc2", "name": "B", "kind": "pc", "gold": 0},
        ],
        "items": [],
    })
    apply_event(ev, repo)
    assert repo.party_cp == 4500
    assert all(c.coin == 0 for c in repo.party())


def test_legacy_levelup_snapshot_does_not_double_the_purse():
    """Regression: an old CHARACTER_LEVELED payload carries the lead's then-pooled
    gold. That money is already in the purse via the op history — the snapshot's
    coin must be discarded, not added again."""
    repo = _repo()                                      # purse 1500
    ev = Event(seq=5, kind=EventKind.CHARACTER_LEVELED.value, payload={
        "character": {"id": "pc", "name": "Hero", "kind": "pc", "gold": 15, "level": 2},
        "items": [],
    })
    apply_event(ev, repo)
    assert repo.party_cp == 1500                        # unchanged — no doubling
    assert repo.pc().level == 2 and repo.pc().coin == 0


def test_legacy_item_base_value_becomes_value_cp():
    it = Item.model_validate({"id": "boots", "name": "boots", "base_value": 2})
    assert it.value_cp == 200
    assert Item(id="x", name="x", value_cp=35).value_cp == 35


def test_srd_catalog_carries_real_coin_prices():
    """S3: the equipment catalog's re-imported SRD prices survive projection —
    a candle really costs 1 cp, a club 1 sp, plate armor 1,500 gp."""
    from oubliette.content.ruleset import load_ruleset
    from oubliette.rules.chargen import _project_srd_item
    rs = load_ruleset()
    worth = {k: _project_srd_item(rs.equipment[k]).value_cp
             for k in ("candle", "club", "longsword", "plate_armor")}
    assert worth == {"candle": 1, "club": 10, "longsword": 1500, "plate_armor": 150000}


def test_new_session_end_to_end_purse():
    """The seeded world (authored gp) opens with a copper purse and merchant pocket."""
    s = Session.open(InMemoryEventStore())
    assert s.repo.party_cp == 1500
    assert s.repo.get_character("merchant_thom").coin == 50000
    assert s.repo.get_character("merchant_thom").price_list["waterskin"] == 400
