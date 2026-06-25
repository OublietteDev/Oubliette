"""Launch the Vision Lab encounter standalone in the Arena (P-VISION-LIGHT test bed).

Run with the project venv from the repo root:
    .venv\\Scripts\\python.exe tools\\vision_lab.py     (Windows)
    .venv/bin/python tools/vision_lab.py                (POSIX)
or just double-click vision_lab.bat.

Drops you straight into a fight: "Mistweaver" has Fog Cloud, Darkness, and
Daylight (all free to cast) plus a quarterstaff, against three foes chosen to
exercise every vision branch. Watch the roll-type label on each attack line:

  * Plain Baboon (normal senses) — attacks across the fog read [normal]: the
    "can't see you" and "you can't see me" effects cancel. RAW.
  * Gloom Hound (blindsight 60) — it keeps seeing you in the fog, so ITS attacks
    on you stay [advantage] and YOUR attacks into the fog at it read
    [disadvantage]. This is the clean one-sided case.
  * Crystal Sentinel (truesight 120) — cast Darkness on it and it still sees you;
    its attacks read [advantage] while you're blind in your own darkness.
"""
from pathlib import Path
import tempfile

from arena.handoff import play_encounter
from arena.paths import DATA_DIR


def main() -> None:
    encounter = DATA_DIR / "encounters" / "vision_lab.json"
    result = Path(tempfile.gettempdir()) / "vision_lab_result.json"
    play_encounter(encounter, result)


if __name__ == "__main__":
    main()
