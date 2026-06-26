"""The C6 playtest lab battery must always load cleanly.

Each ``*_lab.json`` encounter is a standalone test bed OublietteDev launches via
``tools/lab.py <name>``. They reference real character/monster files, so a
later edit to one of those (a renamed field, a deleted creature) could silently
break a bench. This guards the whole battery: every lab loads through the real
CombatManager, places all its combatants, and can roll into combat.
"""
from pathlib import Path

import pytest

from arena.combat.manager import CombatManager
from arena.util.loader import load_encounter

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LAB_FILES = sorted((DATA_DIR / "encounters").glob("*_lab.json"))


@pytest.mark.parametrize("lab_path", LAB_FILES, ids=lambda p: p.stem)
def test_lab_loads_and_starts(lab_path):
    enc = load_encounter(lab_path)
    cm = CombatManager()
    cm.load_encounter(enc, DATA_DIR)
    # Every declared combatant is created and placed on the grid.
    assert cm.combatants, f"{lab_path.stem}: no combatants loaded"
    assert all(c.position is not None for c in cm.combatants.values()), \
        f"{lab_path.stem}: a combatant failed to place"
    # At least one side each, and a player-controllable hero to drive.
    teams = {c.team for c in cm.combatants.values()}
    assert "player" in teams and "enemy" in teams
    assert any(c.team == "player" and c.creature.is_player_controlled
               for c in cm.combatants.values()), \
        f"{lab_path.stem}: no player-controlled hero"
    # The fight can actually begin.
    cm.roll_initiative()
    cm.begin_combat()
    assert cm.active_combatant is not None


def test_battery_is_present():
    # The four C6 benches authored for ship-readiness, plus the earlier labs.
    names = {p.stem for p in LAB_FILES}
    for expected in ("prone_lab", "martial_lab", "caster_lab", "downed_lab"):
        assert expected in names
