"""Mark monster signature recharge abilities (breath weapons) as high AI priority.

Generated breath weapons defaulted to ai_priority 5, which puts a once-per-rest
ability's use-willingness at 0.375 — just under the 0.4 threshold in
should_use_limited_ability — so they were NEVER used (a dragon that never
breathes). gen_arena_monsters.py now stamps recharge abilities at ai_priority 9;
this applies the same to the files already on disk.

Targets only recharge/short-rest SAVE abilities (recharge_min set, or
rest_type == "short") — i.e. breath weapons and the like — never the spell
actions bound by bake_monster_spells.py (those carry their own library priority).

Idempotent. Re-runnable.

    python tools/bake_signature_priorities.py [arena/data/monsters/srd]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root for `arena`

from arena.models.monster import Monster  # noqa: E402
from arena.paths import DATA_DIR  # noqa: E402

SIGNATURE_PRIORITY = 9


def _is_signature_recharge(action: dict) -> bool:
    if not action.get("saving_throw"):
        return False
    return action.get("recharge_min") is not None or action.get("rest_type") == "short"


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else DATA_DIR / "monsters" / "srd"

    changed = 0
    bumped = 0
    names: set[str] = set()
    for path in sorted(out_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for action in data.get("actions", []):
            if _is_signature_recharge(action) and action.get("ai_priority", 5) < SIGNATURE_PRIORITY:
                action["ai_priority"] = SIGNATURE_PRIORITY
                touched = True
                bumped += 1
                names.add(action.get("name", "?"))
        if touched:
            Monster.model_validate(data)  # fail loud
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            changed += 1

    print(f"Raised {bumped} signature abilities to ai_priority {SIGNATURE_PRIORITY} "
          f"across {changed} monsters.")
    if names:
        print("Abilities: " + ", ".join(sorted(names)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
