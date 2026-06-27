"""Bake spellcasting into the generated SRD monster files (idempotent migration).

The SRD monster generator deferred spellcasting (spells live as prose in a
`special_abilities` Feature). This applies `arena.util.monster_spells` to every
generated monster in place, turning that prose into castable spell Actions so
the combat AI can actually use them. `gen_arena_monsters.py` calls the same
function during generation, so a full regen reproduces this — this script just
applies it to the files already on disk without needing the raw 5e source.

Safe to re-run: hydration de-dupes by spell name, so a second pass adds nothing.

    python tools/bake_monster_spells.py [arena/data/monsters/srd]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root for `arena`

from arena.models.monster import Monster  # noqa: E402
from arena.paths import DATA_DIR  # noqa: E402
from arena.util.monster_spells import load_spell_library, hydrate_monster_spells  # noqa: E402


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else DATA_DIR / "monsters" / "srd"
    library = load_spell_library()

    changed = 0
    total_added = 0
    all_skipped: set[str] = set()
    for path in sorted(out_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = hydrate_monster_spells(data, library)
        if summary["added"] == 0:
            all_skipped.update(summary["skipped"])
            continue
        Monster.model_validate(data)  # fail loud — never write junk
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        changed += 1
        total_added += summary["added"]
        all_skipped.update(summary["skipped"])

    print(f"Baked spells into {changed} monsters (+{total_added} spell actions).")
    if all_skipped:
        print(f"Skipped {len(all_skipped)} spells not in the library "
              f"(utility/non-combat): {', '.join(sorted(all_skipped))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
