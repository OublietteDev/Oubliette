"""D-MON-4a: monster trait primitives wired into combat hooks.

Covers the four trait families whose inert flags the Session-1 plumbing already
stamped onto monster ``special_abilities``:

- Magic Resistance (``save_advantage_vs_spells``) → advantage on saves vs spells.
- Brave / Dark Devotion / Fey Ancestry (``save_advantage_vs_conditions``) →
  advantage on a save that would impose the named condition.
- Pack Tactics (``attack_advantage_when_ally_adjacent``) → advantage when an
  ally flanks the target.
- Magic Weapons (``attacks_are_magical``) → attacks overcome nonmagical defenses.
"""

from arena.combat.actions import resolve_saving_throw, resolve_attack_hit
from arena.combat.damage import attack_is_magical
from arena.combat.manager import Combatant
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType
from arena.models.character import Creature, Feature
from arena.models.conditions import Condition
from arena.models.monster import Monster


def _feat(name, **flags):
    return Feature(name=name, description="x", **flags)


# ── Magic Resistance (advantage on saves vs spells) ──────────────────────────

def _resistant(name="Rakshasa"):
    return Monster(name=name, max_hit_points=110, ability_scores=AbilityScores(),
                   special_abilities=[_feat("Magic Resistance", save_advantage_vs_spells=True)])


def test_magic_resistance_grants_advantage_on_spell_save():
    m = _resistant()
    _, event = resolve_saving_throw(m, "m1", "wisdom", 15, is_spell_save=True)
    assert event.details["advantage"] == 1
    assert event.details["trait_advantage"] == "Magic Resistance"


def test_magic_resistance_inert_on_nonspell_save():
    m = _resistant()
    _, event = resolve_saving_throw(m, "m1", "dexterity", 15, is_spell_save=False)
    assert event.details["advantage"] == 0
    assert event.details["trait_advantage"] is None


def test_plain_monster_no_spell_save_advantage():
    m = Monster(name="Commoner", max_hit_points=4, ability_scores=AbilityScores())
    _, event = resolve_saving_throw(m, "c1", "wisdom", 15, is_spell_save=True)
    assert event.details["advantage"] == 0


# ── Brave / Dark Devotion / Fey Ancestry (advantage vs a condition) ──────────

def test_brave_grants_advantage_vs_frightened():
    m = Monster(name="Veteran", max_hit_points=58, ability_scores=AbilityScores(),
                special_abilities=[_feat("Brave", save_advantage_vs_conditions=["frightened"])])
    _, event = resolve_saving_throw(m, "m1", "wisdom", 15, imposes_conditions=["frightened"])
    assert event.details["advantage"] == 1
    assert event.details["trait_advantage"] == "Brave"


def test_brave_inert_vs_unrelated_condition():
    m = Monster(name="Veteran", max_hit_points=58, ability_scores=AbilityScores(),
                special_abilities=[_feat("Brave", save_advantage_vs_conditions=["frightened"])])
    _, event = resolve_saving_throw(m, "m1", "constitution", 15, imposes_conditions=["poisoned"])
    assert event.details["advantage"] == 0
    assert event.details["trait_advantage"] is None


def test_fey_ancestry_grants_advantage_vs_charmed():
    m = Monster(name="Drow", max_hit_points=13, ability_scores=AbilityScores(),
                special_abilities=[_feat("Fey Ancestry", save_advantage_vs_conditions=["charmed"])])
    _, event = resolve_saving_throw(m, "m1", "wisdom", 15, imposes_conditions=["charmed"])
    assert event.details["advantage"] == 1
    assert event.details["trait_advantage"] == "Fey Ancestry"


# ── Magic Resistance / traits on RECURRING saves (not just the opening one) ──

def _spell_condition(cond, dc=15, spell_level=2):
    from arena.models.conditions import AppliedCondition
    return AppliedCondition(condition=cond, source="Hold Person",
                            duration_type="end_of_turn", save_to_end="wisdom",
                            save_dc=dc, spell_level=spell_level)


def _resave_event(creature, dc):
    from arena.combat.conditions import process_end_of_turn
    events = process_end_of_turn(creature, "m1")
    return next(e for e in events if e.details.get("dc") == dc)


def test_magic_resistance_applies_to_recurring_condition_resave():
    m = _resistant()
    m.active_conditions.append(_spell_condition(Condition.PARALYZED))
    ev = _resave_event(m, 15)
    assert ev.details["advantage"] == 1
    assert ev.details["trait_advantage"] == "Magic Resistance"


def test_no_magic_resistance_on_nonspell_condition_resave():
    m = _resistant()
    m.active_conditions.append(_spell_condition(Condition.PARALYZED, spell_level=None))
    ev = _resave_event(m, 15)
    assert ev.details["advantage"] == 0
    assert ev.details["trait_advantage"] is None


def test_brave_applies_to_recurring_frightened_resave():
    m = Monster(name="Knight", max_hit_points=52, ability_scores=AbilityScores(),
                special_abilities=[_feat("Brave", save_advantage_vs_conditions=["frightened"])])
    ac = _spell_condition(Condition.FRIGHTENED, dc=14, spell_level=3)
    ac.source = "Fear"
    m.active_conditions.append(ac)
    ev = _resave_event(m, 14)
    assert ev.details["advantage"] == 1
    assert ev.details["trait_advantage"] == "Brave"


# ── Pack Tactics (advantage when an ally flanks the target) ──────────────────

def _wolf(name, pack=True):
    feats = [_feat("Pack Tactics", attack_advantage_when_ally_adjacent=True)] if pack else []
    return Monster(name=name, max_hit_points=11, armor_class=13,
                   ability_scores=AbilityScores(strength=12, dexterity=15),
                   proficiency_bonus=2, special_abilities=feats)


def _bite():
    return Action(name="Bite", description="x", action_type=ActionType.ACTION,
                  attack=Attack(name="Bite", attack_type="melee_weapon", ability="strength",
                                reach=5,
                                damage=[DamageRoll(dice="2d4", damage_type=DamageType.PIERCING,
                                                   ability_modifier="strength")]))


def _pack_scene(pack=True, ally_adjacent=True, ally_incapacitated=False, ally_present=True):
    """attacker + target always adjacent; an optional ally flanks the target."""
    attacker = _wolf("Wolf A", pack=pack)
    target = Creature(name="Hero", max_hit_points=20, armor_class=14,
                      ability_scores=AbilityScores())
    grid = HexGrid(10, 10)
    grid.place_creature(HexCoord(2, 2), "atk")
    grid.place_creature(HexCoord(2, 3), "tgt")
    combatants = {
        "atk": Combatant(creature_id="atk", creature=attacker, team="enemy",
                         position=HexCoord(2, 2)),
        "tgt": Combatant(creature_id="tgt", creature=target, team="player",
                         position=HexCoord(2, 3)),
    }
    if ally_present:
        ally = _wolf("Wolf B", pack=False)
        if ally_incapacitated:
            ally.active_conditions.append(_incap())
        ally_pos = HexCoord(3, 3) if ally_adjacent else HexCoord(8, 8)
        grid.place_creature(ally_pos, "ally")
        combatants["ally"] = Combatant(creature_id="ally", creature=ally,
                                       team="enemy", position=ally_pos)
    return attacker, target, grid, combatants


def _incap():
    from arena.models.conditions import AppliedCondition
    return AppliedCondition(condition=Condition.INCAPACITATED, source="test")


def _attack(attacker, target, grid, combatants):
    return resolve_attack_hit(attacker, "atk", target, "tgt", _bite(), grid,
                              combatants=combatants,
                              attacker_pos=HexCoord(2, 2), target_pos=HexCoord(2, 3))


def test_pack_tactics_advantage_with_adjacent_ally():
    attacker, target, grid, combatants = _pack_scene()
    res = _attack(attacker, target, grid, combatants)
    assert res.effective_advantage == 1


def test_pack_tactics_no_advantage_without_ally():
    attacker, target, grid, combatants = _pack_scene(ally_present=False)
    res = _attack(attacker, target, grid, combatants)
    assert res.effective_advantage == 0


def test_pack_tactics_no_advantage_when_ally_far():
    attacker, target, grid, combatants = _pack_scene(ally_adjacent=False)
    res = _attack(attacker, target, grid, combatants)
    assert res.effective_advantage == 0


def test_pack_tactics_requires_the_trait():
    attacker, target, grid, combatants = _pack_scene(pack=False)
    res = _attack(attacker, target, grid, combatants)
    assert res.effective_advantage == 0


def test_pack_tactics_ignores_incapacitated_ally():
    attacker, target, grid, combatants = _pack_scene(ally_incapacitated=True)
    res = _attack(attacker, target, grid, combatants)
    assert res.effective_advantage == 0


# ── Magic Weapons (attacks count as magical) ─────────────────────────────────

def test_magic_weapons_flag_makes_attacks_magical():
    m = Monster(name="Iron Golem", max_hit_points=210, ability_scores=AbilityScores(),
                special_abilities=[_feat("Magic Weapons", attacks_are_magical=True)])
    assert attack_is_magical(m, None, None) is True


def test_magic_weapons_name_fallback_still_works():
    m = Monster(name="Balor", max_hit_points=262, ability_scores=AbilityScores(),
                special_abilities=[_feat("Magic Weapons")])
    assert attack_is_magical(m, None, None) is True


def test_plain_monster_attacks_not_magical():
    m = Monster(name="Goblin", max_hit_points=7, ability_scores=AbilityScores())
    assert attack_is_magical(m, None, None) is False
