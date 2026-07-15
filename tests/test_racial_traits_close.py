"""The last three story-only racial traits, made real (multiplayer pre-work
close-out): Halfling Lucky (reroll natural 1s — story rolls and Arena d20s),
Gnome Cunning (advantage on INT/WIS/CHA saves vs magic), and the tiefling's
Infernal Legacy (thaumaturgy known; Hellish Rebuke 1/day at 3rd, Darkness at
5th, CHA-cast off the racial pool — no spellcasting class required)."""

from __future__ import annotations

from unittest.mock import patch

from oubliette.combat.arena_bridge import racial_spell_actions
from oubliette.combat.feature_bridge import features_for
from oubliette.content.ruleset import load_ruleset
from oubliette.enums import Ability, Skill
from oubliette.rules import derive
from oubliette.rules.chargen import CharacterBuild, build_character
from oubliette.rules.lucky import is_lucky, lucky_reroll
from oubliette.state.models import Character, CharacterSheet, FeatureRef

RS = load_ruleset()


def _char(race: str, features: list[FeatureRef], level: int = 3,
          cha: int = 14) -> Character:
    return Character(
        id="pc", name="Hero", kind="pc", level=level,
        abilities={a: (cha if a == Ability.CHA else 10) for a in Ability},
        sheet=CharacterSheet(race=race, char_class="fighter",
                             background="acolyte", features=features),
    )


# --- Halfling Lucky -------------------------------------------------------------

def test_racial_lucky_stages_and_the_feat_name_does_not():
    racial = _char("halfling", [FeatureRef(name="Lucky", source="race")])
    staged = {f.name: f for f in features_for(racial)}
    assert staged["Lucky"].reroll_natural_ones is True
    classy = _char("human", [FeatureRef(name="Lucky", source="feat")])
    assert "Lucky" not in {f.name for f in features_for(classy)}


def test_story_lucky_rerolls_a_natural_one():
    class _Rng:
        def __init__(self):
            self.calls = []

        def roll(self, spec, purpose):
            self.calls.append(purpose)
            class O:  # the RollOutcome shape the loop consumes
                rolls, total = [12], 15
            return O()

    class _Outcome:
        rolls, total = [1], 4

    lucky = _char("halfling", [FeatureRef(name="Lucky", source="race")])
    plain = _char("human", [])
    rng = _Rng()
    out = lucky_reroll(rng, lucky, "1d20+3", "skill_check.stealth", _Outcome())
    assert out.total == 15 and "Lucky reroll" in rng.calls[0]
    assert is_lucky(lucky) and not is_lucky(plain)
    same = lucky_reroll(rng, plain, "1d20+3", "skill_check.stealth", _Outcome())
    assert same.total == 4                      # non-halfling: the 1 stands


def test_arena_lucky_rerolls_the_attack_die():
    from arena.combat.actions import resolve_attack_hit
    from arena.grid.coordinates import HexCoord
    from arena.grid.hexgrid import HexGrid
    from arena.models.abilities import AbilityScores
    from arena.models.actions import (Action, ActionType, Attack, DamageRoll,
                                      DamageType)
    from arena.models.character import Creature, Feature, PlayerCharacter

    grid = HexGrid(10, 10)
    grid.place_creature(HexCoord(5, 5), "atk")
    grid.place_creature(HexCoord(5, 6), "tgt")
    action = Action(
        name="Sword", description="melee", action_type=ActionType.ACTION,
        attack=Attack(name="Sword", attack_type="melee_weapon",
                      ability="strength", reach=5,
                      damage=[DamageRoll(dice="1d8",
                                         damage_type=DamageType.SLASHING)]))
    target = Creature(name="T", max_hit_points=10, armor_class=10)

    def _pc(lucky: bool) -> PlayerCharacter:
        feats = ([Feature(name="Lucky", description="reroll 1s",
                          reroll_natural_ones=True)] if lucky else [])
        return PlayerCharacter(name="A", character_class="Fighter",
                               max_hit_points=20, proficiency_bonus=2,
                               ability_scores=AbilityScores(strength=16),
                               features=feats)

    with patch("arena.combat.actions.roll_die", side_effect=[1, 15]):
        result = resolve_attack_hit(_pc(True), "atk", target, "tgt", action, grid)
    assert result.natural_roll == 15 and result.hit is True
    with patch("arena.combat.actions.roll_die", return_value=1):
        result = resolve_attack_hit(_pc(False), "atk", target, "tgt", action, grid)
    assert result.natural_roll == 1 and result.hit is False


# --- Gnome Cunning ----------------------------------------------------------------

def test_gnome_cunning_gives_advantage_on_mental_saves_vs_magic_only():
    from arena.combat.condition_effects import get_trait_save_advantage
    from arena.models.abilities import AbilityScores
    from arena.models.character import Feature, PlayerCharacter

    gnome = PlayerCharacter(
        name="G", character_class="Wizard", max_hit_points=10,
        ability_scores=AbilityScores(), proficiency_bonus=2,
        features=[Feature(name="Gnome Cunning",
                          description="mental saves vs magic",
                          save_advantage_abilities_vs_magic=[
                              "intelligence", "wisdom", "charisma"])])
    assert get_trait_save_advantage(gnome, is_spell_save=True,
                                    ability="wisdom") == (1, "Gnome Cunning")
    assert get_trait_save_advantage(gnome, is_spell_save=True,
                                    ability="strength")[0] == 0
    assert get_trait_save_advantage(gnome, is_spell_save=False,
                                    ability="wisdom")[0] == 0   # mundane fear etc.


def test_gnome_cunning_stages_from_the_sheet():
    gnome = _char("gnome", [FeatureRef(name="Gnome Cunning", source="race")])
    staged = {f.name: f for f in features_for(gnome)}
    assert staged["Gnome Cunning"].save_advantage_abilities_vs_magic == [
        "intelligence", "wisdom", "charisma"]


# --- Infernal Legacy -----------------------------------------------------------------

def _tiefling(level: int) -> Character:
    return _char("tiefling", [FeatureRef(name="Infernal Legacy", source="race")],
                 level=level, cha=16)


def test_infernal_legacy_actions_arrive_at_the_right_levels():
    assert racial_spell_actions(_tiefling(1), RS) == []
    at3 = {a.name.lower(): a for a in racial_spell_actions(_tiefling(3), RS)}
    assert len(at3) == 1
    rebuke = next(iter(at3.values()))
    assert rebuke.resource_cost == {"hellish_rebuke": 1}
    assert rebuke.action_type.value == "reaction"
    assert rebuke.fixed_cast_level == 2                        # SRD: cast at 2nd
    assert rebuke.saving_throw is not None
    assert rebuke.saving_throw.dc == 8 + 2 + 3                 # prof 2, CHA +3
    at5 = racial_spell_actions(_tiefling(5), RS)
    assert len(at5) == 2
    assert {a.resource_cost and next(iter(a.resource_cost)) for a in at5} == {
        "hellish_rebuke", "darkness"}


def test_the_racial_pools_appear_with_their_levels_and_recharge_long():
    res3 = derive.class_resources(_tiefling(3), RS)
    assert res3["Hellish Rebuke"]["max"] == 1
    assert res3["Hellish Rebuke"]["recharge"] == "long"
    assert "Darkness" not in res3
    res5 = derive.class_resources(_tiefling(5), RS)
    assert res5["Darkness"]["max"] == 1
    assert res5["Darkness"]["recharge"] == "long"


def test_chargen_grants_thaumaturgy_to_every_tiefling():
    build = CharacterBuild(
        name="Vex", race="tiefling", char_class="fighter", background="acolyte",
        ability_method="standard_array",
        base_abilities={Ability.STR: 15, Ability.DEX: 13, Ability.CON: 14,
                        Ability.INT: 10, Ability.WIS: 8, Ability.CHA: 12},
        skills=[Skill.PERCEPTION, Skill.SURVIVAL],
        languages=["Draconic", "Celestial"],
        equipment_choices=[[0], [0], [0]],
    )
    char, _ = build_character(build, RS)
    assert "thaumaturgy" in char.sheet.cantrips_known
