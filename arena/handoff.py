"""The integration door between Oubliette and The Arena.

Oubliette resolves a fight by spawning The Arena as a subprocess that plays out ONE
encounter and writes a result file; Oubliette then reads that file and folds the
outcome back into the story. This module is that contract:

  - ``build_result(cm)``  — turn a finished ``CombatManager`` into a plain JSON-able
    dict (winner, per-combatant final HP/conditions, who fell). Pure; unit-tested.
  - ``play_encounter(encounter_path, result_path)`` — launch the GUI straight into the
    given encounter in handoff mode; when the player leaves (combat ended → ESC, or the
    window is closed), write the result built from the final state.
  - ``main()`` — CLI: ``python -m arena.handoff <encounter.json> <result.json>``.

The result schema is deliberately a faithful dump of the engine's final truth; mapping
it onto Oubliette's ``CombatResult`` (absolute HP/XP/loot) is the bridge's job (Stage 2).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from arena.paths import ARENA_ROOT

# Result-schema version, so the bridge on the Oubliette side can guard against drift.
RESULT_SCHEMA = 1


def _condition_names(creature: Any) -> list[str]:
    """The names of conditions currently on a creature (enum value or raw string)."""
    out: list[str] = []
    for ac in getattr(creature, "active_conditions", []) or []:
        cond = getattr(ac, "condition", ac)
        out.append(getattr(cond, "value", cond))
    return out


def build_result(cm: Any) -> dict:
    """Build the handoff result dict from a (typically finished) ``CombatManager``.

    ``winner`` is "player" | "enemy" | None (None = combat never resolved, e.g. the
    player closed the window mid-fight). ``outcome`` is the Oubliette-facing label.
    """
    combatants: list[dict] = []
    for cid, c in cm.combatants.items():
        cr = c.creature
        combatants.append({
            "id": cid,
            "name": cr.name,
            "team": c.team,
            "is_pc": bool(getattr(cr, "is_player_controlled", c.team == "player")),
            "hp": cr.current_hit_points if cr.current_hit_points is not None else cr.max_hit_points,
            "max_hp": cr.max_hit_points,
            "temp_hp": getattr(cr, "temporary_hit_points", 0),
            "conditions": _condition_names(cr),
            "is_conscious": bool(cr.is_conscious),
            # Monsters carry XP for the victor; PCs default 0. Present for the bridge.
            "xp": int(getattr(cr, "experience_points", 0) or 0),
        })

    winner = getattr(cm, "winner", None)
    outcome = {"player": "victory", "enemy": "defeat"}.get(winner, "unresolved")

    rounds = None
    init = getattr(cm, "initiative", None)
    if init is not None:
        rounds = getattr(init, "round_number", None)

    return {
        "schema": RESULT_SCHEMA,
        "winner": winner,
        "outcome": outcome,
        "rounds": rounds,
        "combatants": combatants,
    }


def write_result(cm: Any, result_path: Path) -> dict:
    """Build the result from ``cm`` and write it to ``result_path`` (pretty JSON)."""
    result = build_result(cm)
    Path(result_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _error_result(message: str) -> dict:
    return {"schema": RESULT_SCHEMA, "winner": None, "outcome": "error",
            "rounds": None, "combatants": [], "error": message}


def play_encounter(encounter_path: str | Path, result_path: str | Path) -> dict:
    """Launch The Arena directly into ``encounter_path`` and, when the player exits,
    write the resolved result to ``result_path``. Returns the result dict.

    Both paths are resolved to absolute BEFORE we chdir to the package root (so the
    cwd-relative ``data/`` / ``assets/`` literals throughout the engine resolve)."""
    encounter_path = Path(encounter_path).resolve()
    result_path = Path(result_path).resolve()
    os.chdir(ARENA_ROOT)

    # Imported here, not at module top: pulling in the GUI requires pygame, and we want
    # build_result / the result schema importable without a display.
    from arena.gui.app import App
    from arena.gui.screens.combat import CombatScreen

    app = App()
    app.go_to_combat(encounter_path)
    screen = app.current_screen

    if not isinstance(screen, CombatScreen):
        # Loading failed → go_to_combat switched to an ErrorScreen. Don't trap the
        # player in a windowed dead-end; report the failure and bail.
        result = _error_result(f"encounter failed to load: {encounter_path}")
        Path(result_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    screen.handoff_mode = True
    app.run()  # blocks until the player exits (ESC after combat, or window close)

    # Write from the FINAL manager state — covers every exit path uniformly (a clean
    # win/defeat, or an abort where winner is still None → outcome "unresolved").
    return write_result(screen.combat, result_path)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python -m arena.handoff <encounter.json> <result.json>",
              file=sys.stderr)
        return 2
    play_encounter(argv[0], argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
