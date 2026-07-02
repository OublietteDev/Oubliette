"""Tests for the Oubliette<->Arena handoff result extraction (Stage 1).

These cover the *return* half of the wire — turning a finished CombatManager into
the result dict Oubliette reads. The GUI launch glue (handoff_mode, ESC-exits) is
verified by playing; here we drive the manager directly, as the engine's own tests do.
"""

import json
from pathlib import Path

from arena.combat.manager import CombatManager
from arena.handoff import build_result, write_result, RESULT_SCHEMA
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, TargetType
from arena.models.character import Creature, PlayerCharacter
from arena.models.conditions import AppliedCondition, Condition
from arena.models.encounter import Encounter, CombatantEntry


def _creature(name: str, hp: int, is_player: bool) -> Creature:
    return Creature(
        name=name, max_hit_points=hp, armor_class=10,
        ability_scores=AbilityScores(), is_player_controlled=is_player,
    )


def _loaded_manager() -> CombatManager:
    enc = Encounter(
        name="Handoff Test", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="hero", creature_data=_creature("Hero", 20, True),
                           team="player", starting_position=(2, 2)),
            CombatantEntry(creature_id="gob", creature_data=_creature("Goblin", 7, False),
                           team="enemy", starting_position=(4, 2)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("data"))
    return cm


def _by_team(result: dict, team: str) -> dict:
    return next(c for c in result["combatants"] if c["team"] == team)


def test_unresolved_before_any_outcome():
    """A combat with no winner yet maps to 'unresolved' (e.g. window closed mid-fight)."""
    r = build_result(_loaded_manager())
    assert r["schema"] == RESULT_SCHEMA
    assert r["winner"] is None
    assert r["outcome"] == "unresolved"
    assert {c["team"] for c in r["combatants"]} == {"player", "enemy"}


def test_victory_when_enemies_down():
    cm = _loaded_manager()
    for c in cm.combatants.values():
        if c.team == "enemy":
            c.creature.current_hit_points = 0
    cm._check_victory()
    assert cm.winner == "player"

    r = build_result(cm)
    assert r["outcome"] == "victory"
    enemy = _by_team(r, "enemy")
    assert enemy["hp"] == 0 and enemy["is_conscious"] is False
    hero = _by_team(r, "player")
    assert hero["is_pc"] is True and hero["hp"] == 20 and hero["is_conscious"] is True


def test_defeat_mapping():
    cm = _loaded_manager()
    cm.winner = "enemy"
    assert build_result(cm)["outcome"] == "defeat"


def test_conditions_captured():
    cm = _loaded_manager()
    enemy = next(c for c in cm.combatants.values() if c.team == "enemy")
    enemy.creature.active_conditions.append(
        AppliedCondition(condition=Condition.PRONE, source="Hero")
    )
    r = build_result(cm)
    assert "prone" in _by_team(r, "enemy")["conditions"]


# --- schema v2: per-PC resources / consumables / death saves -------------

def _potion_action(name: str, item_id: str | None, per: int, cur: int) -> Action:
    return Action(
        name=name, description=f"Drink a {name}.",
        action_type=ActionType.BONUS_ACTION, target_type=TargetType.SELF,
        healing="2d4+2", uses_per_rest=per, current_uses=cur,
        source_item=name, source_item_id=item_id,
    )


def _pc(**overrides) -> PlayerCharacter:
    fields: dict = dict(
        name="Mira", character_class="Cleric", level=5,
        max_hit_points=33, armor_class=16, ability_scores=AbilityScores(),
        is_player_controlled=True,
        spell_slots={1: 4, 2: 3},
        class_resources={"channel_divinity": 1},
    )
    fields.update(overrides)
    return PlayerCharacter(**fields)


def _manager_with(pc: PlayerCharacter) -> CombatManager:
    enc = Encounter(
        name="Handoff v2 Test", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="pc", creature_data=pc,
                           team="player", starting_position=(2, 2)),
            CombatantEntry(creature_id="gob", creature_data=_creature("Goblin", 7, False),
                           team="enemy", starting_position=(4, 2)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("data"))
    return cm


def _result_pc(cm: CombatManager) -> dict:
    return _by_team(build_result(cm), "player")


def test_v2_blocks_on_pc_only():
    r = build_result(_manager_with(_pc()))
    pc, enemy = _by_team(r, "player"), _by_team(r, "enemy")
    assert r["schema"] == 2
    assert {"resources", "consumables_used", "death_saves"} <= set(pc)
    assert not {"resources", "consumables_used", "death_saves"} & set(enemy)


def test_spell_slots_folded_out_of_class_resources():
    cm = _manager_with(_pc())
    pc_creature = next(c.creature for c in cm.combatants.values() if c.team == "player")
    # The model validator seeded spell_slot_N from spell_slots; spend 2 first-level
    # slots and the channel divinity, the way the engine does (deduct_resource_cost).
    pc_creature.class_resources["spell_slot_1"] -= 2
    pc_creature.class_resources["channel_divinity"] -= 1

    res = _result_pc(cm)["resources"]
    assert res["spell_slots"] == {
        "1": {"remaining": 2, "max": 4},
        "2": {"remaining": 3, "max": 3},
    }
    # The folded slot keys must NOT leak; what's left is the real class resource.
    assert res["class_resources"] == {"channel_divinity": 0}


def test_consumables_used_diff_and_item_id():
    spent = _potion_action("Potion of Healing", "potion_healing", per=2, cur=1)
    untouched = _potion_action("Potion of Greater Healing", "potion_greater_healing",
                               per=1, cur=1)
    cm = _manager_with(_pc(bonus_actions=[spent, untouched]))
    used = _result_pc(cm)["consumables_used"]
    assert used == [{"item_id": "potion_healing", "name": "Potion of Healing",
                     "used": 1, "spell": None, "spell_level": None}]


def test_consumable_without_catalog_id_still_reports_name():
    cm = _manager_with(_pc(bonus_actions=[_potion_action("Elixir", None, per=3, cur=0)]))
    used = _result_pc(cm)["consumables_used"]
    assert used == [{"item_id": None, "name": "Elixir", "used": 3,
                     "spell": None, "spell_level": None}]


def test_death_saves_captured():
    pc = _pc(death_save_successes=1, death_save_failures=2, is_stabilized=True)
    pc.current_hit_points = 0
    saves = _result_pc(_manager_with(pc))["death_saves"]
    assert saves == {"successes": 1, "failures": 2, "stabilized": True}


def test_plain_creature_pc_gets_empty_v2_blocks():
    """A v1-era plain Creature on the player team must not crash the v2 builder."""
    pc = _by_team(build_result(_loaded_manager()), "player")
    assert pc["resources"] == {"spell_slots": {}, "class_resources": {}}
    assert pc["consumables_used"] == []
    assert pc["death_saves"] == {"successes": 0, "failures": 0, "stabilized": False}


def test_write_result_roundtrip(tmp_path):
    cm = _loaded_manager()
    out = tmp_path / "result.json"
    returned = write_result(cm, out)
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == returned
    assert on_disk["schema"] == RESULT_SCHEMA
    assert len(on_disk["combatants"]) == 2


def test_dump_log_writes_readable_lines_with_details(tmp_path):
    """The per-run diagnostics dump: every log event becomes one line of
    'TYPE message', with details appended as JSON (so a charged hit can be
    audited after the window closes)."""
    from arena.combat.events import CombatEvent, CombatEventType
    from arena.handoff import dump_log

    cm = _loaded_manager()
    cm.log.add(CombatEvent(event_type=CombatEventType.ROUND_START,
                           message="--- Round 1 ---"))
    cm.log.add(CombatEvent(event_type=CombatEventType.DAMAGE,
                           message="Charge! Hero takes 9 slashing damage",
                           target_id="hero",
                           details={"damage": 9, "charged": True}))
    out = tmp_path / "last_combat_log.txt"
    assert dump_log(cm, out) == out

    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert any(l.startswith("ROUND_START") and "--- Round 1 ---" in l for l in lines)
    charged = next(l for l in lines if l.startswith("DAMAGE"))
    assert "Charge! Hero takes 9 slashing damage" in charged
    assert '"charged": true' in charged


def test_dump_log_never_raises(tmp_path):
    """A failed dump must not break the handoff contract."""
    from arena.handoff import dump_log

    assert dump_log(object(), tmp_path / "x.txt") is not None  # no log attr -> empty dump
    assert dump_log(_loaded_manager(), tmp_path / "no_dir" / "x.txt") is None
