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
from arena.models.character import Creature
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


def test_write_result_roundtrip(tmp_path):
    cm = _loaded_manager()
    out = tmp_path / "result.json"
    returned = write_result(cm, out)
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == returned
    assert on_disk["schema"] == RESULT_SCHEMA
    assert len(on_disk["combatants"]) == 2
