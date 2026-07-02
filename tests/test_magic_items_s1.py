"""Module-kit Stage 1: pack items carry the full magic-item contract.

The Phase-A frozen contract (`item_type`/`rarity`/`magic_bonus`/attunement/
`consumable`/`poison`) was designed on the SRD side and is consumed by the Arena
bridge (equipped +X, drink actions) and `use_item`. S1 gives pack-authored items
the SAME fields and merges both sets into ONE mechanics catalog (pack wins on id
collision), so a Forge-authored Flametongue or healing tonic behaves exactly like
SRD gear — no special-casing anywhere downstream.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oubliette.combat.arena_bridge import consumable_actions, equipped_magic
from oubliette.content.loader import _project_mechanics, load_pack, mechanics_catalog
from oubliette.content.ruleset import load_ruleset
from oubliette.content.schemas import (ConsumableMechanics, Item as PackItem,
                                       PoisonMechanics, WeaponProfile)
from oubliette.enums import Ability
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.session import Session
from oubliette.state.models import Character, Item as StateItem, ItemStack
from oubliette.state.repository import InMemoryRepository
from oubliette.tools.dispatch import Dispatcher
from oubliette.tools.schemas import UseItem

RS = load_ruleset()


def _flametongue() -> PackItem:
    return PackItem(
        id="brightvale_flametongue", name="Brightvale Flametongue",
        category="weapon", slot="main_hand", rarity="rare",
        item_type="weapon", magic_bonus=1, requires_attunement=True,
        weapon=WeaponProfile(attack_bonus=0, damage="1d8"),
        description="A blade that remembers the forge.",
    )


def _tonic() -> PackItem:
    return PackItem(
        id="veilberry_tonic", name="Veilberry Tonic", category="consumable",
        item_type="potion", rarity="common", mechanics="structured",
        consumable=ConsumableMechanics(healing="1d4+1"),
    )


# --- schema: the contract validates (and its authoring traps trip) ------------

def test_pack_item_accepts_the_full_magic_contract():
    it = _flametongue()
    assert (it.item_type, it.rarity, it.magic_bonus, it.requires_attunement) == \
        ("weapon", "rare", 1, True)
    poison = PackItem(
        id="serpent_venom", name="Serpent Venom", category="consumable",
        item_type="poison", mechanics="structured",
        poison=PoisonMechanics(poison_type="injury", save_dc=11, damage="3d6"),
    )
    assert poison.poison.save_ability == "con"


def test_plain_legacy_items_still_validate_with_mundane_defaults():
    it = PackItem(id="boots", name="worn boots", category="gear")
    assert it.item_type == "mundane" and it.mechanics == "none"
    assert it.consumable is None and it.poison is None


def test_a_payload_requires_the_structured_flag():
    with pytest.raises(ValidationError, match="structured"):
        PackItem(id="x", name="x", category="consumable", item_type="potion",
                 consumable=ConsumableMechanics(healing="2d4+2"))


def test_the_structured_flag_requires_a_payload():
    with pytest.raises(ValidationError, match="payload"):
        PackItem(id="x", name="x", category="consumable", mechanics="structured")


def test_at_most_one_mechanics_payload():
    with pytest.raises(ValidationError, match="at most one"):
        PackItem(id="x", name="x", category="consumable", item_type="potion",
                 mechanics="structured",
                 consumable=ConsumableMechanics(healing="2d4+2"),
                 poison=PoisonMechanics(poison_type="ingested", save_dc=10))


def test_magic_bonus_needs_an_equippable_family():
    with pytest.raises(ValidationError, match="equippable"):
        PackItem(id="x", name="x", category="consumable", item_type="potion",
                 magic_bonus=1, mechanics="structured",
                 consumable=ConsumableMechanics(healing="2d4+2"))


def test_a_potion_must_be_category_consumable():
    with pytest.raises(ValidationError, match="consumable"):
        PackItem(id="x", name="x", category="gear", item_type="potion")


# --- the merged mechanics catalog ---------------------------------------------

def test_projection_carries_the_contract_field_for_field():
    entry = _project_mechanics(_flametongue())
    assert entry.id == "brightvale_flametongue"
    assert (entry.item_type, entry.rarity, entry.magic_bonus,
            entry.requires_attunement) == ("weapon", "rare", 1, True)
    assert entry.weapon.damage == "1d8"
    tonic = _project_mechanics(_tonic())
    assert tonic.mechanics == "structured" and tonic.consumable.healing == "1d4+1"


def test_catalog_merges_srd_and_pack():
    cat = mechanics_catalog(RS, [_flametongue(), _tonic()])
    assert "potion_of_healing" in cat            # the SRD set rides along whole
    assert "brightvale_flametongue" in cat       # the pack's own magic items join it
    assert len(cat) == len(RS.equipment) + 2


def test_pack_wins_on_id_collision():
    reskin = PackItem(id="potion_of_healing", name="Silverfin Dockside Remedy",
                      category="consumable", item_type="potion",
                      mechanics="structured",
                      consumable=ConsumableMechanics(healing="3d4+3"))
    cat = mechanics_catalog(RS, [reskin])
    assert cat["potion_of_healing"].name == "Silverfin Dockside Remedy"
    assert cat["potion_of_healing"].consumable.healing == "3d4+3"


def test_catalog_without_a_ruleset_is_pack_only():
    cat = mechanics_catalog(None, [_tonic()])
    assert set(cat) == {"veilberry_tonic"}


# --- use_item drinks a pack potion exactly like an SRD one ---------------------

def _repo_with_tonic(hp: int = 10) -> InMemoryRepository:
    pc = Character(
        id="pc", name="You", kind="pc", level=3,
        abilities={a: 10 for a in Ability},
        hp=hp, max_hp=24, gold=0,
        inventory=[ItemStack(item_id="veilberry_tonic", qty=2)],
    )
    items = [StateItem(id="veilberry_tonic", name="Veilberry Tonic",
                       category="consumable", base_value=20)]
    return InMemoryRepository(characters=[pc], items=items, pc_id="pc")


def test_use_item_heals_from_a_pack_potion_via_the_merged_catalog():
    repo = _repo_with_tonic(hp=10)
    disp = Dispatcher(repo, ruleset=RS, rng=Rng(7),
                      mechanics=mechanics_catalog(RS, [_tonic()]))
    rt = disp.resolve(UseItem(item_id="veilberry_tonic", reason="drinks it"))
    debit, heal = rt.ops
    assert (debit.op, debit.item_id, debit.delta) == ("item", "veilberry_tonic", -1)
    # 1d4+1 lands in [2, 5], applied as an absolute capped hp_set.
    assert heal.op == "hp_set" and 10 + 2 <= heal.value <= 10 + 5


def test_without_the_merged_catalog_a_pack_potion_is_prose_only():
    # The old behavior S1 fixes: bare SRD ruleset knows nothing about pack
    # mechanics — the tonic is consumed but heals nothing (narration-only).
    repo = _repo_with_tonic(hp=10)
    disp = Dispatcher(repo, ruleset=RS, rng=Rng(7))
    rt = disp.resolve(UseItem(item_id="veilberry_tonic", reason="drinks it"))
    assert [op.op for op in rt.ops] == ["item"]


# --- the bridge: pack +X gear and drink actions --------------------------------

def _pc(**over) -> Character:
    base = dict(id="pc", name="You", kind="pc", level=3,
                abilities={a: 10 for a in Ability}, hp=20, max_hp=20)
    base.update(over)
    return Character(**base)


def test_equipped_pack_weapon_bonus_reaches_the_bridge():
    pc = _pc(inventory=[ItemStack(item_id="brightvale_flametongue", qty=1)],
             equipped=["brightvale_flametongue"])
    cat = mechanics_catalog(RS, [_flametongue()])
    assert equipped_magic(pc, cat) == (1, 0)


def test_equipped_pack_defensive_item_raises_ac():
    ring = PackItem(id="ring_of_the_ward", name="Ring of the Ward",
                    category="gear", slot="ring_1", item_type="ring", magic_bonus=1)
    pc = _pc(inventory=[ItemStack(item_id="ring_of_the_ward", qty=1)],
             equipped=["ring_of_the_ward"])
    cat = mechanics_catalog(RS, [ring])
    assert equipped_magic(pc, cat) == (0, 1)


def test_pack_potion_becomes_an_arena_drink_action():
    pc = _pc(inventory=[ItemStack(item_id="veilberry_tonic", qty=2)])
    cat = mechanics_catalog(RS, [_tonic()])
    (drink,) = consumable_actions(pc, cat)
    assert drink.healing == "1d4+1"
    assert drink.source_item_id == "veilberry_tonic"
    assert drink.current_uses == drink.uses_per_rest == 2


# --- session wiring -------------------------------------------------------------

def test_session_open_carries_the_merged_catalog():
    session = Session.open(InMemoryEventStore())
    assert "potion_of_healing" in session.mechanics_catalog       # SRD present
    world = load_pack(session.pack_id)
    assert session.mechanics_catalog.keys() == world.mechanics_catalog.keys()
    assert len(session.mechanics_catalog) >= len(RS.equipment)
