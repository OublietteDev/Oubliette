"""Headless AI-vs-AI battle simulations (Arena test beds, T3 — the war room).

``python -m arena.sim spec.json out.json`` runs N fights of one staged
encounter with the AI piloting BOTH sides, no window, no pygame, and writes
aggregate statistics. The spec:

    {"encounter": "<path to encounter.json>",   # externalized creature files
     "iterations": 100, "seed": 12345, "round_cap": 30}

Each iteration reseeds the global dice RNG (``seed + i``), so a batch is
reproducible end to end. A fight that outlives the round cap is a DRAW and
is reported, never hidden — two unkillable regenerators are a finding, not
an error.

The driver mirrors the GUI's `_check_ai_turn` glue (combat.py) with the
pacing removed: lair turns and the legendary-action phase are serviced
between regular turns, exactly as the screen would. The numbers are a FLOOR
for real parties: the AI never times a potion, calls a focus target, or
plays clever — the report's caveat says so in words.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

CAVEAT = ("AI-piloted baseline: real players coordinate, spend items, and "
          "retreat — treat these numbers as a floor for the party, not a "
          "prediction.")


def run_fight(enc_dict: dict, seed: int, round_cap: int) -> dict:
    """One complete AI-vs-AI fight. Returns {winner, rounds, party: [...]}."""
    from arena.ai.controller import AIController
    from arena.ai.executor import execute_full_plan
    from arena.combat.manager import CombatManager, CombatState, TurnPhase
    from arena.models.encounter import Encounter

    random.seed(seed)
    enc = Encounter.model_validate(enc_dict)
    enc.use_ai_for_allies = True      # the whole point: both sides play themselves
    enc.use_ai_for_enemies = True

    cm = CombatManager()
    cm.load_encounter(enc, Path("."))     # creature paths are absolute
    # Same rule the handoff sets for story fights: a fully-downed player team
    # LOSES now. Without it, stabilized-at-0 heroes count as "still fighting",
    # the enemy has no conscious target left, and a stomp drifts to the round
    # cap — an enemy victory laundered into a draw (found live by Chris:
    # 92 "draws" against a young bronze dragon that had downed everyone).
    cm.solo_defeat_when_downed = True
    cm.roll_initiative()
    cm.begin_combat()

    ai = AIController()
    last_marker = None
    stalled = False
    for _ in range(round_cap * 200):      # hard step budget — a backstop, not a pace
        if cm.state != CombatState.IN_COMBAT:
            break
        if cm.initiative.round_number > round_cap:
            break
        if cm._is_lair_turn:
            execute_full_plan(ai.plan_lair_action(cm), cm)
            continue
        if cm.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
            execute_full_plan(ai.plan_legendary_action(cm), cm)
            continue
        active = cm.active_combatant
        if active is None:
            break
        marker = (cm.initiative.round_number, active.creature_id, cm.turn_phase)
        execute_full_plan(ai.plan_turn(cm), cm)
        if cm.state == CombatState.IN_COMBAT and not cm._is_lair_turn \
                and cm.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            now = (cm.initiative.round_number,
                   cm.active_combatant.creature_id if cm.active_combatant else None,
                   cm.turn_phase)
            if now == marker:
                cm.end_turn()             # a plan without END_TURN must not hang the sim
                if marker == last_marker:
                    stalled = True        # two forced ends in a row: give up honestly
                    break
        last_marker = marker
    else:
        stalled = True

    ended = cm.state == CombatState.COMBAT_ENDED
    return {
        "winner": cm.winner if ended else None,
        "rounds": cm.initiative.round_number,
        "stalled": stalled,
        "party": [{"name": c.creature.name,
                   "hp": max(0, c.creature.current_hit_points),
                   "max_hp": c.creature.max_hit_points,
                   "conscious": c.creature.is_conscious}
                  for c in cm.combatants.values() if c.team == "player"],
    }


def run_batch(encounter_path: Path, iterations: int, seed: int,
              round_cap: int) -> dict:
    enc_dict = json.loads(encounter_path.read_text(encoding="utf-8"))
    fights = [run_fight(enc_dict, seed + i, round_cap) for i in range(iterations)]

    wins = {"player": 0, "enemy": 0, "draw": 0}
    party: dict[str, dict] = {}
    total_rounds = 0
    stalled = 0
    for f in fights:
        wins[f["winner"] or "draw"] += 1
        total_rounds += f["rounds"]
        stalled += int(f["stalled"])
        for p in f["party"]:
            slot = party.setdefault(p["name"], {"name": p["name"], "hp_pct": 0.0,
                                                "downs": 0, "max_hp": p["max_hp"]})
            slot["hp_pct"] += (p["hp"] / p["max_hp"]) if p["max_hp"] else 0.0
            slot["downs"] += int(not p["conscious"])

    n = max(1, len(fights))
    return {
        "schema": 1,
        "iterations": len(fights), "seed": seed, "round_cap": round_cap,
        "wins": wins,
        "win_pct": round(100.0 * wins["player"] / n, 1),
        "avg_rounds": round(total_rounds / n, 1),
        "stalled": stalled,
        "party": [{"name": s["name"], "max_hp": s["max_hp"],
                   "avg_hp_pct": round(100.0 * s["hp_pct"] / n, 1),
                   "downs": s["downs"]}
                  for s in party.values()],
        "caveat": CAVEAT,
    }


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: python -m arena.sim <spec.json> <out.json>", file=sys.stderr)
        raise SystemExit(2)
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = run_batch(Path(spec["encounter"]),
                       int(spec.get("iterations", 100)),
                       int(spec.get("seed", 1)),
                       int(spec.get("round_cap", 30)))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
