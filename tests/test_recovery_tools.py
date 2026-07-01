"""HP recovery outside combat (DM-interview fix): `use_item` + `propose_rest`.

Before these tools, the DM had NO real path to heal outside combat — rest was a
player-UI action and potions could only be `take`n (removed, healing nothing) —
yet the model believed one existed and narrated recovery that never happened.
Now: `use_item` consumes one of a consumable and CODE rolls/applies its healing
(absolute hp_set, capped, replay-safe); `propose_rest` mirrors `end_session` —
a transient proposal the player confirms via the existing /api/rest, so nothing
recovers until they take the rest. The firewall holds: code owns every number.
"""

from __future__ import annotations

import asyncio

import pytest

from oubliette.content.ruleset import load_ruleset
from oubliette.dm.brain import Brain
from oubliette.enums import Ability
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng, dice_average
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.models import Character, Item, ItemStack
from oubliette.state.repository import InMemoryRepository
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.tools.schemas import ProposeRest, UseItem

RS = load_ruleset()

ITEMS = [
    Item(id="boots", name="worn leather boots", category="gear", base_value=2),
    Item(id="healing_draught", name="healing draught", category="consumable", base_value=25),
    Item(id="potion_of_healing", name="Potion of Healing", category="consumable", base_value=50),
    # in the catalog but NOBODY carries one — exercises the ownership refusal
    Item(id="potion_of_healing_greater", name="Potion of Greater Healing",
         category="consumable", base_value=400),
]


def _repo(hp: int = 10, max_hp: int = 24) -> InMemoryRepository:
    pc = Character(
        id="pc", name="You", kind="pc", level=3,
        abilities={a: 10 for a in Ability},
        hp=hp, max_hp=max_hp, gold=5,
        inventory=[
            ItemStack(item_id="potion_of_healing", qty=2),
            ItemStack(item_id="healing_draught", qty=1),
            ItemStack(item_id="boots", qty=1),
        ],
    )
    return InMemoryRepository(characters=[pc], items=ITEMS, pc_id="pc")


def _use(repo, item_id: str, rng=None):
    disp = Dispatcher(repo, ruleset=RS, rng=rng)
    return disp.resolve(UseItem(item_id=item_id, reason="drinks it down"))


# --- use_item: the potion path ------------------------------------------------

def test_use_item_consumes_one_and_heals_within_the_dice():
    repo = _repo(hp=10)
    rt = _use(repo, "potion_of_healing", rng=Rng(1))
    assert rt.tool == "use_item"
    debit, heal = rt.ops
    assert (debit.op, debit.item_id, debit.delta) == ("item", "potion_of_healing", -1)
    # Potion of Healing is 2d4+2: the rolled result lands in [4, 10], applied absolute.
    assert heal.op == "hp_set" and 10 + 4 <= heal.value <= 10 + 10


def test_use_item_healing_caps_at_max_hp():
    repo = _repo(hp=23, max_hp=24)
    rt = _use(repo, "potion_of_healing", rng=Rng(1))
    heal = rt.ops[1]
    assert heal.op == "hp_set" and heal.value == 24


def test_use_item_at_full_hp_still_consumes_but_heals_nothing():
    repo = _repo(hp=24, max_hp=24)
    rt = _use(repo, "potion_of_healing", rng=Rng(1))
    assert len(rt.ops) == 1 and rt.ops[0].delta == -1     # RAW: a potion at full HP is wasted


def test_use_item_without_rng_applies_the_dice_average():
    repo = _repo(hp=10)
    rt = _use(repo, "potion_of_healing", rng=None)
    assert rt.ops[1].value == 10 + dice_average("2d4+2")  # deterministic stand-in (7)


def test_use_item_plain_consumable_is_used_up_with_no_hp_op():
    # A pack consumable with no structured mechanics: the effect lives in narration.
    repo = _repo(hp=10)
    rt = _use(repo, "healing_draught", rng=Rng(1))
    assert len(rt.ops) == 1
    assert (rt.ops[0].item_id, rt.ops[0].delta) == ("healing_draught", -1)


def test_use_item_refuses_non_consumables():
    with pytest.raises(ToolApplyError, match="isn't a consumable"):
        _use(_repo(), "boots")


def test_use_item_refuses_when_not_owned():
    repo = _repo()
    disp = Dispatcher(repo, ruleset=RS, rng=Rng(1))
    with pytest.raises(ToolApplyError, match="has no"):
        # resolve by prose name too — but the PC carries none of these
        disp.resolve(UseItem(item_id="potion_of_healing_greater", reason="wishful"))


def test_use_item_healing_roll_is_recorded_as_a_roll_event():
    # The healing dice flow through the ONE dice source, so replay never re-rolls.
    recorded: list = []
    rng = Rng(7, record=lambda kind, **p: recorded.append((kind, p)))
    _use(_repo(hp=10), "potion_of_healing", rng=rng)
    assert len(recorded) == 1
    kind, payload = recorded[0]
    assert kind == EventKind.ROLL and payload["purpose"] == "use_item.potion_of_healing"


# --- propose_rest: offer, don't apply ------------------------------------------

def test_propose_rest_resolves_to_a_transient_proposal():
    rt = Dispatcher(None, None).resolve(ProposeRest(kind="long", reason="the party makes camp"))
    assert rt.rest_proposed == "long" and rt.ops == []


def _loop(session: Session) -> TurnLoop:
    return TurnLoop(session, Rng(1, record=session.emit_log), Brain(ScriptedLLMClient()))


def test_dm_proposes_a_rest_without_recording_recovery():
    """The proposal is a turn flag, not an event — HP/slots move only when the player
    confirms (POST /api/rest), exactly like the wrap ritual."""
    s = Session.open(InMemoryEventStore())
    report = asyncio.run(_loop(s).take_turn("We make camp for the night"))
    assert report.rest_pending == "long"
    kinds = [e.kind for e in s.store.read_all()]
    assert EventKind.REST_TAKEN.value not in kinds


def test_dm_proposes_a_short_rest_for_a_breather():
    s = Session.open(InMemoryEventStore())
    report = asyncio.run(_loop(s).take_turn("Let's take a breather here"))
    assert report.rest_pending == "short"


def test_drinking_a_consumable_through_the_loop_debits_the_stack():
    """End-to-end: the scripted DM answers a drink with use_item; the turn records ONE
    TOOL_APPLIED event and the seeded draught stack shrinks. (The seed world has no
    ruleset, so this draught heals nothing — its effect is prose; the healing path is
    covered at the dispatcher level above.)"""
    s = Session.open(InMemoryEventStore())
    before = s.repo.pc().variant_qty("healing_draught")
    report = asyncio.run(_loop(s).take_turn("I drink the healing draught"))
    assert s.repo.pc().variant_qty("healing_draught") == before - 1
    assert report.narration.strip()
    applied = [e for e in s.store.read_all() if e.kind == EventKind.TOOL_APPLIED.value]
    assert len(applied) == 1 and applied[0].payload["tool"] == "use_item"
