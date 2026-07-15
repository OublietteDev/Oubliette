"""Surprise rounds (SRD gap-fill): the side caught off guard loses its first
turn and takes no reactions until that turn has passed; Alert-style immunity
(grants_condition_immunities=["surprised"]) shrugs it off."""

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat import house_rules as hr
from arena.combat.conditions import has_condition
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, Feature, PlayerCharacter
from arena.models.conditions import Condition
from arena.models.encounter import CombatantEntry, Encounter


@pytest.fixture(autouse=True)
def _clean_rules():
    hr.reset()
    yield
    hr.reset()


def _creature(name: str, player: bool = False, dex: int = 10,
              features: list | None = None) -> Creature:
    cls = PlayerCharacter if player else Creature
    kwargs = dict(name=name, max_hit_points=10, armor_class=10,
                  ability_scores=AbilityScores(dexterity=dex),
                  is_player_controlled=player, features=features or [])
    if player:
        kwargs.update(character_class="Fighter", proficiency_bonus=2)
    return cls(**kwargs)


def _manager(surprised_side: str | None, hero_features: list | None = None,
             hero_dex: int = 18) -> CombatManager:
    enc = Encounter(
        name="t", surprised_side=surprised_side,
        combatants=[
            CombatantEntry(creature_id="inline", team="player",
                           creature_data=_creature("Hero", player=True,
                                                   dex=hero_dex,
                                                   features=hero_features)),
            CombatantEntry(creature_id="inline", team="enemy",
                           creature_data=_creature("Foe", dex=1)),
        ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    return cm


def _by_name(cm: CombatManager, name: str):
    return next((cid, c) for cid, c in cm.combatants.items()
                if c.creature.name == name)


def test_old_encounter_files_have_no_surprise():
    enc = Encounter.model_validate({"name": "legacy"})
    assert enc.surprised_side is None


def test_the_surprised_side_is_marked_and_the_other_is_not():
    cm = _manager("player")
    cm.roll_initiative()
    _, hero = _by_name(cm, "Hero")
    _, foe = _by_name(cm, "Foe")
    assert has_condition(hero.creature, Condition.SURPRISED)
    assert not has_condition(foe.creature, Condition.SURPRISED)


def test_alert_style_immunity_shrugs_off_surprise():
    alert = Feature(name="Alert", description="can't be surprised",
                    grants_condition_immunities=["surprised"])
    cm = _manager("player", hero_features=[alert])
    cm.roll_initiative()
    _, hero = _by_name(cm, "Hero")
    assert not has_condition(hero.creature, Condition.SURPRISED)
    assert any("cannot be surprised" in ev.message for ev in cm.log.events)


def test_a_surprised_creature_loses_its_first_turn_and_recovers():
    # High-DEX surprised hero acts first: their turn is skipped, the condition
    # ends with it, and the foe's turn follows. The d20 is pinned so the
    # hero's +4 DEX vs the foe's -5 decides the order deterministically.
    cm = _manager("player", hero_dex=18)
    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()
    hero_id, hero = _by_name(cm, "Hero")
    assert cm.initiative.entries[0].creature_id == hero_id
    assert cm._reaction_blocked(hero_id) is True     # no reactions while surprised
    cm._start_current_turn()                         # skips, ends, advances
    assert not has_condition(hero.creature, Condition.SURPRISED)
    assert cm._reaction_blocked(hero_id) is False    # their slot passed
    assert any("surprised" in ev.message.lower() and "lose" in ev.message.lower()
               for ev in cm.log.events)
    # the round moved on to the foe
    assert cm.initiative.current_entry.creature_id == _by_name(cm, "Foe")[0]


def test_unsurprised_fights_play_exactly_as_before():
    cm = _manager(None)
    cm.roll_initiative()
    for cid, c in cm.combatants.items():
        assert not has_condition(c.creature, Condition.SURPRISED)
        assert cm._reaction_blocked(cid) is False
