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

RESULT SCHEMA v2 (the Phase-B contract — the Arena-side twin of Oubliette's Phase-A
item-schema freeze; designed once, here). All v1 fields are unchanged; each combatant
with ``is_pc`` true ADDITIONALLY carries:

  "resources": {
      "spell_slots":     {"<level>": {"remaining": int, "max": int|null}, ...},
      "class_resources": {"<name>": remaining, ...}     # ki_points, rage_uses, ...
  },
  "consumables_used": [{"item_id": str|null, "name": str, "used": int,
                        "spell": str|null, "spell_level": int|null}, ...],
                       # spell/spell_level (additive, C5): scroll variant
                       # riders — the launching app keys scroll stacks by
                       # (item, spell, level), so the debit names the variant
  "death_saves":      {"successes": int, "failures": int, "stabilized": bool}

Derivation notes (all read from the FINAL engine state — nothing new is tracked):

  - The engine spends spell slots as ``class_resources["spell_slot_<N>"]``; we fold
    those keys into the ``spell_slots`` block (max from ``PlayerCharacter.spell_slots``,
    which the engine never mutates) so the reader never learns that key convention.
    What remains of ``class_resources`` is reported as-is.
  - ``consumables_used`` is ``uses_per_rest - current_uses`` summed over the creature's
    item actions (those with ``source_item`` set). INVARIANT for generators that feed
    this contract: an item action must ENTER combat with ``current_uses`` equal to
    ``uses_per_rest`` (= the inventory stack quantity), so the difference is exactly
    what this fight consumed. ``item_id`` echoes ``Action.source_item_id`` (the
    launching app's catalog id; null for native Arena content — the name still lands).
  - Non-PC combatants never carry the v2 blocks (monsters hold none of this state).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from arena.paths import ARENA_ROOT

# Result-schema version, so the bridge on the Oubliette side can guard against drift.
RESULT_SCHEMA = 2

_SLOT_KEY = re.compile(r"^spell_slot_(\d+)$")


def _condition_names(creature: Any) -> list[str]:
    """The names of conditions currently on a creature (enum value or raw string)."""
    out: list[str] = []
    for ac in getattr(creature, "active_conditions", []) or []:
        cond = getattr(ac, "condition", ac)
        out.append(getattr(cond, "value", cond))
    return out


def _pc_resources(creature: Any) -> dict:
    """Spell slots + class resources remaining (see the v2 contract above).

    The engine's spend ledger is ``class_resources`` (``spell_slot_<N>`` keys for
    slots); ``spell_slots`` holds the untouched maxima. Slots authored only in
    ``class_resources`` (no maxima entry) report ``max: None``."""
    class_res = dict(getattr(creature, "class_resources", {}) or {})
    slots_max = {int(k): v for k, v in (getattr(creature, "spell_slots", {}) or {}).items()}
    levels = set(slots_max)
    for key in class_res:
        m = _SLOT_KEY.match(key)
        if m:
            levels.add(int(m.group(1)))
    slots: dict[str, dict] = {}
    for lvl in sorted(levels):
        remaining = class_res.pop(f"spell_slot_{lvl}", slots_max.get(lvl, 0))
        slots[str(lvl)] = {"remaining": remaining, "max": slots_max.get(lvl)}
    return {"spell_slots": slots, "class_resources": class_res}


def _consumables_used(creature: Any) -> list[dict]:
    """Items spent this fight: ``uses_per_rest - current_uses`` over item actions,
    aggregated per item VARIANT. Relies on the entry invariant (current == per at
    load). Scroll actions (C5) carry spell/spell_level riders — two differently
    inscribed scrolls share an item_id but are distinct inventory stacks, so the
    riders join the aggregation key and the reported entry (additive v2 keys)."""
    used: dict[tuple, dict] = {}
    for attr in ("actions", "bonus_actions", "reactions"):
        for a in getattr(creature, attr, []) or []:
            name = getattr(a, "source_item", None)
            per = getattr(a, "uses_per_rest", None)
            cur = getattr(a, "current_uses", None)
            if not name or per is None or cur is None or cur >= per:
                continue
            spell = getattr(a, "source_item_spell", None)
            spell_level = getattr(a, "source_item_spell_level", None)
            key = (getattr(a, "source_item_id", None), name, spell, spell_level)
            entry = used.setdefault(key, {
                "item_id": key[0], "name": name, "used": 0,
                "spell": spell, "spell_level": spell_level,
            })
            entry["used"] += per - cur
    return list(used.values())


def _death_saves(creature: Any) -> dict:
    return {
        "successes": int(getattr(creature, "death_save_successes", 0) or 0),
        "failures": int(getattr(creature, "death_save_failures", 0) or 0),
        "stabilized": bool(getattr(creature, "is_stabilized", False)),
    }


def build_result(cm: Any) -> dict:
    """Build the handoff result dict from a (typically finished) ``CombatManager``.

    ``winner`` is "player" | "enemy" | None (None = combat never resolved, e.g. the
    player closed the window mid-fight). ``outcome`` is the Oubliette-facing label.
    """
    combatants: list[dict] = []
    for cid, c in cm.combatants.items():
        cr = c.creature
        is_pc = bool(getattr(cr, "is_player_controlled", c.team == "player"))
        entry = {
            "id": cid,
            "name": cr.name,
            "team": c.team,
            "is_pc": is_pc,
            "hp": cr.current_hit_points if cr.current_hit_points is not None else cr.max_hit_points,
            "max_hp": cr.max_hit_points,
            "temp_hp": getattr(cr, "temporary_hit_points", 0),
            "conditions": _condition_names(cr),
            "is_conscious": bool(cr.is_conscious),
            # Monsters carry XP for the victor; PCs default 0. Present for the bridge.
            "xp": int(getattr(cr, "experience_points", 0) or 0),
        }
        if is_pc:  # the v2 blocks — PCs only (see the contract in the module docstring)
            entry["resources"] = _pc_resources(cr)
            entry["consumables_used"] = _consumables_used(cr)
            entry["death_saves"] = _death_saves(cr)
        combatants.append(entry)

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
    # Solo story combat: a fully-downed player team loses now, rather than lingering
    # in a death-save vacuum that never ends (which would hang this subprocess and the
    # calling story turn). The combatant `.creature` objects are shared with the
    # manager, so set the flag on it directly.
    screen.combat.solo_defeat_when_downed = True
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
