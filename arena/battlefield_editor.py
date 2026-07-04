"""The battlefield-editor door — the Forge's twin of ``arena.handoff``.

The Forge server edits a location's battle map by spawning the Arena in
editor mode:

    python -m arena.battlefield_editor <spec.json> <out.json>

``spec.json`` (written by the Forge):

    {
      "place_name": "The Lantern & Wake Tavern",
      "battle": { ...the Place's BattleMap dump... },
      "background_path": "C:/abs/path/to/image.png" | null,
      "music_path": "C:/abs/path/to/track.mp3" | null
    }

On Save the editor writes ``{"battle": {...}}`` to ``out.json`` — the same
block with updated grid size, terrain, and background transform (asset
FILENAMES pass through untouched; the Forge owns file choice) — and exits 0.
Back/ESC exits 0 *without* writing; the Forge reads a missing out-file as
cancel. Bad input (unreadable/invalid spec) exits 2 with the error on stderr.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from arena.paths import ARENA_ROOT


def edit_battlefield(spec_path: str | Path, out_path: str | Path) -> None:
    """Launch the editor GUI for the given spec; blocks until the author
    exits. Paths resolve to absolute BEFORE the chdir to the package root
    (the engine's cwd-relative ``assets/`` / ``data/`` literals need it)."""
    spec_path = Path(spec_path).resolve()
    out_path = Path(out_path).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    os.chdir(ARENA_ROOT)

    # GUI imports live here so the spec contract stays importable headless.
    from arena.gui.app import App
    from arena.gui.screens.battlefield_editor import BattlefieldEditorScreen

    app = App()
    screen = BattlefieldEditorScreen(app.width, app.height, spec, out_path)
    app._switch_to(screen)
    pygame_caption(spec.get("place_name"))
    app.run()


def pygame_caption(place_name: str | None) -> None:
    import pygame
    name = f" — {place_name}" if place_name else ""
    pygame.display.set_caption(f"Battlefield Editor{name}")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m arena.battlefield_editor <spec.json> <out.json>",
              file=sys.stderr)
        return 2
    try:
        edit_battlefield(sys.argv[1], sys.argv[2])
    except (OSError, json.JSONDecodeError) as e:
        print(f"battlefield editor: bad spec: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
