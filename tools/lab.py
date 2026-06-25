"""Generic feature test-bed launcher: drop you straight into any Arena encounter.

    .venv\\Scripts\\python.exe tools\\lab.py <encounter_name>      (Windows)
    .venv/bin/python tools/lab.py <encounter_name>               (POSIX)

<encounter_name> is the filename (without .json) of any encounter in
arena/data/encounters/. This is the standard way to playtest a single feature in
isolation: author a focused encounter (a caster with just the relevant spells, a
roster of foes that hit each branch), then launch it by name. No per-feature
launcher code needed — just the JSON.

Existing labs:
  vision_lab   — P-VISION-LIGHT: fog / darkness / daylight, blindsight, truesight.
"""
import sys
import tempfile
from pathlib import Path

from arena.handoff import play_encounter
from arena.paths import DATA_DIR


def main(name: str | None = None) -> None:
    name = name or (sys.argv[1] if len(sys.argv) > 1 else "vision_lab")
    name = name[:-5] if name.endswith(".json") else name
    encounter = DATA_DIR / "encounters" / f"{name}.json"
    if not encounter.is_file():
        avail = sorted(p.stem for p in (DATA_DIR / "encounters").glob("*.json"))
        sys.exit(f"No encounter '{name}'. Available:\n  " + "\n  ".join(avail))
    result = Path(tempfile.gettempdir()) / f"{name}_result.json"
    print(f"Launching {encounter} ...")
    play_encounter(encounter, result)


if __name__ == "__main__":
    main()
