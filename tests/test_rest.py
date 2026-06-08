"""CS5 — rests and the resource/slot/hit-die trackers. The recovery mechanics that
work without a combat loop: a rest computes absolute StateOps, which apply the same
way live and on replay (D7)."""

from __future__ import annotations

from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.record.events import StateOp, apply_ops
from oubliette.rules.rest import long_rest_ops, short_rest_ops
from oubliette.state.models import Character, CharacterSheet
from oubliette.state.repository import InMemoryRepository

RS = load_ruleset()


def _barbarian(level=3, hp=10, hit_dice_used=3, rage_used=2) -> Character:
    return Character(
        id="pc", name="Grog", kind="pc", level=level, hp=hp, max_hp=30,
        abilities={Ability.STR: 16, Ability.DEX: 14, Ability.CON: 16,
                   Ability.INT: 8, Ability.WIS: 12, Ability.CHA: 10},
        hit_dice_used=hit_dice_used, resources_used={"Rage": rage_used},
        sheet=CharacterSheet(race="human", char_class="barbarian", background="acolyte"))


def _warlock(level=3, slots_used=None) -> Character:
    return Character(
        id="pc", name="Vex", kind="pc", level=level, hp=20, max_hp=24,
        abilities={Ability.CHA: 16, Ability.DEX: 14, Ability.CON: 14, Ability.WIS: 10},
        spell_slots_used=slots_used or {2: 2},
        sheet=CharacterSheet(race="human", char_class="warlock", background="acolyte",
                             spellcasting_ability=Ability.CHA))


def _repo(char) -> InMemoryRepository:
    return InMemoryRepository(characters=[char], items=[], pc_id="pc")


# --- long rest --------------------------------------------------------------
def test_long_rest_heals_resets_and_regains_hit_dice():
    char = _barbarian(hp=10, hit_dice_used=3, rage_used=2)
    repo = _repo(char)
    apply_ops(long_rest_ops(char, RS), repo)
    pc = repo.pc()
    assert pc.hp == 30                       # full HP
    assert pc.spell_slots_used == {}         # (no slots, but reset is recorded)
    assert pc.resources_used["Rage"] == 0    # long-recharge resource reset
    assert pc.hit_dice_used == 2             # regained max(1, level//2)=1 of the 3 spent


# --- short rest -------------------------------------------------------------
def test_short_rest_spends_hit_dice_to_heal_average():
    char = _barbarian(level=3, hp=10, hit_dice_used=0, rage_used=2)
    repo = _repo(char)
    # no rng → deterministic average: each d12 = 7, + CON 3 = 10 per die; spend 2 → +20
    apply_ops(short_rest_ops(char, RS, spend_hit_dice=2), repo)
    pc = repo.pc()
    assert pc.hp == 30                       # 10 + 20, capped at max 30
    assert pc.hit_dice_used == 2
    assert pc.resources_used["Rage"] == 2    # rage is long-recharge — a short rest leaves it


def test_short_rest_cannot_spend_more_hit_dice_than_available():
    char = _barbarian(level=3, hp=10, hit_dice_used=2)   # only 1 die left
    repo = _repo(char)
    apply_ops(short_rest_ops(char, RS, spend_hit_dice=5), repo)
    assert repo.pc().hit_dice_used == 3                  # clamped to total


def test_short_rest_restores_pact_magic_slots():
    char = _warlock(level=3, slots_used={2: 2})
    repo = _repo(char)
    apply_ops(short_rest_ops(char, RS), repo)
    assert repo.pc().spell_slots_used == {}              # pact slots recharge on a short rest


def test_short_rest_with_no_spend_is_a_noop_for_barbarian_hp():
    char = _barbarian(hp=12, hit_dice_used=1)
    repo = _repo(char)
    apply_ops(short_rest_ops(char, RS, spend_hit_dice=0), repo)
    assert repo.pc().hp == 12 and repo.pc().hit_dice_used == 1


# --- the new ops survive the wire (replay-safety) ---------------------------
def test_new_state_ops_round_trip():
    char = _barbarian()
    repo = _repo(char)
    ops = [StateOp.slots_used("pc", {1: 1, 2: 0}), StateOp.hit_dice_used("pc", 1),
           StateOp.resources_used("pc", {"Rage": 1}), StateOp.max_hp("pc", 40),
           StateOp.level("pc", 4)]
    # serialize → deserialize (what the event store does), then apply
    revived = [StateOp.model_validate(o.model_dump()) for o in ops]
    apply_ops(revived, repo)
    pc = repo.pc()
    assert pc.spell_slots_used == {1: 1, 2: 0}      # string keys coerced back to int
    assert pc.hit_dice_used == 1 and pc.resources_used == {"Rage": 1}
    assert pc.max_hp == 40 and pc.level == 4
