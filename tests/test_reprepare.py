"""C5 — re-preparing spells on a long rest.

A prepared caster may swap which spells it has ready, but only inside the window
that opens on a long rest and closes once the party acts. The pool follows the
faithful split: cleric/druid/paladin draw from their WHOLE class list, a wizard
only from its spellbook (spells_known). The new prepared list is event-sourced
(SPELLS_PREPARED) so it survives reload byte-identically.
"""

from __future__ import annotations

from types import SimpleNamespace

from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability
from oubliette.record.events import EventKind, Event, StateOp, apply_ops, replay
from oubliette.rules import derive
from oubliette.rules.rest import reprepare_window_open
from oubliette.state.models import Character, CharacterSheet
from oubliette.state.repository import InMemoryRepository, StateError

RS = load_ruleset()


def _cleric(level=1, prepared=None):
    return Character(
        id="pc", name="Piety", kind="pc", level=level, hp=10, max_hp=10,
        abilities={Ability.WIS: 16, Ability.CON: 14, Ability.DEX: 12, Ability.STR: 10},
        sheet=CharacterSheet(race="human", char_class="cleric", background="acolyte",
                             spellcasting_ability=Ability.WIS,
                             spells_known=["cure_wounds", "bless"],
                             spells_prepared=list(prepared or ["cure_wounds", "bless"])))


def _wizard(level=1, known=None, prepared=None):
    known = known or ["magic_missile", "shield", "mage_armor"]
    return Character(
        id="pc", name="Sage", kind="pc", level=level, hp=8, max_hp=8,
        abilities={Ability.INT: 16, Ability.CON: 14, Ability.DEX: 14},
        sheet=CharacterSheet(race="human", char_class="wizard", background="sage",
                             spellcasting_ability=Ability.INT,
                             spells_known=list(known),
                             spells_prepared=list(prepared or known[:2])))


def _paladin(level=1):
    return Character(
        id="pc", name="Oath", kind="pc", level=level, hp=12, max_hp=12,
        abilities={Ability.CHA: 14, Ability.STR: 16, Ability.CON: 14},
        sheet=CharacterSheet(race="human", char_class="paladin", background="soldier",
                             spellcasting_ability=Ability.CHA))


def _warlock(level=1):
    return Character(
        id="pc", name="Pact", kind="pc", level=level, hp=9, max_hp=9,
        abilities={Ability.CHA: 16},
        sheet=CharacterSheet(race="human", char_class="warlock", background="charlatan",
                             spellcasting_ability=Ability.CHA,
                             spells_known=["eldritch_blast"]))


def _repo(char):
    return InMemoryRepository(characters=[char], items=[], pc_id="pc")


# ── the prepare pool (faithful split) ────────────────────────────────────────

class TestPreparePool:
    def test_cleric_draws_from_whole_class_list(self):
        pool = derive.prepare_pool(_cleric(), RS)
        # The pool is the full cleric L1 list — far bigger than its two "known".
        assert "cure_wounds" in pool and "bless" in pool
        assert "command" in pool  # a cleric spell it never explicitly picked
        assert all(RS.spells[s].level == 1 for s in pool)  # only castable levels
        assert len(pool) > 2

    def test_wizard_limited_to_spellbook(self):
        pool = derive.prepare_pool(_wizard(), RS)
        assert sorted(pool) == sorted(["magic_missile", "shield", "mage_armor"])
        # burning_hands is a wizard L1 spell, but not in this wizard's spellbook.
        assert "burning_hands" not in pool

    def test_known_caster_has_no_pool(self):
        assert derive.prepare_pool(_warlock(), RS) is None

    def test_paladin_without_slots_has_empty_pool(self):
        # A level-1 paladin has no spell slots yet → nothing to prepare.
        assert derive.prepared_spell_count(_paladin(), RS) == 0
        assert derive.prepare_pool(_paladin(), RS) == []


# ── validation (the firewall) ────────────────────────────────────────────────

class TestValidate:
    def _count(self, char):
        return derive.prepared_spell_count(char, RS)

    def test_valid_choice_passes(self):
        char = _cleric()
        n = self._count(char)
        pick = derive.prepare_pool(char, RS)[:n]
        assert derive.validate_prepared_choice(char, RS, pick) is None

    def test_wrong_count_rejected(self):
        char = _cleric()
        pick = derive.prepare_pool(char, RS)[: self._count(char) + 1]
        assert "exactly" in derive.validate_prepared_choice(char, RS, pick)

    def test_duplicates_rejected(self):
        char = _cleric()
        n = self._count(char)
        pick = ["cure_wounds"] * n
        assert "duplicate" in derive.validate_prepared_choice(char, RS, pick)

    def test_out_of_pool_rejected(self):
        char = _wizard()
        n = self._count(char)
        # burning_hands isn't in the spellbook → not allowed.
        pick = (["burning_hands"] + ["magic_missile", "shield", "mage_armor"])[:n]
        assert "not available" in derive.validate_prepared_choice(char, RS, pick)


# ── the SPELLS_PREPARED op is event-sourced ──────────────────────────────────

class TestEventSourced:
    def test_op_sets_prepared_list(self):
        char = _cleric()
        repo = _repo(char)
        apply_ops([StateOp.spells_prepared("pc", ["bless", "command"])], repo)
        assert repo.pc().sheet.spells_prepared == ["bless", "command"]

    def test_op_rejects_sheetless_character(self):
        npc = Character(id="pc", name="Mob", kind="pc")  # no sheet
        repo = _repo(npc)
        try:
            apply_ops([StateOp.spells_prepared("pc", ["bless"])], repo)
            assert False, "expected StateError"
        except StateError:
            pass

    def test_replay_reproduces_the_list(self):
        events = [Event(seq=1, kind=EventKind.SPELLS_PREPARED.value,
                        payload={"char_id": "pc",
                                 "ops": [StateOp.spells_prepared(
                                     "pc", ["bless", "guiding_bolt"]).model_dump()]})]
        repo = _repo(_cleric())
        replay(events, repo)
        assert repo.pc().sheet.spells_prepared == ["bless", "guiding_bolt"]


# ── the post-long-rest window ────────────────────────────────────────────────

def _ev(seq, kind, **payload):
    return SimpleNamespace(seq=seq, kind=kind, payload=payload)

LONG = EventKind.REST_TAKEN.value
MSG = EventKind.PLAYER_MESSAGE.value


class TestWindow:
    def test_open_right_after_long_rest(self):
        assert reprepare_window_open([_ev(1, MSG), _ev(2, LONG, rest="long")]) is True

    def test_closes_once_party_acts(self):
        assert reprepare_window_open(
            [_ev(2, LONG, rest="long"), _ev(3, MSG)]) is False

    def test_short_rest_does_not_open(self):
        assert reprepare_window_open([_ev(1, LONG, rest="short")]) is False

    def test_no_events_closed(self):
        assert reprepare_window_open([]) is False
