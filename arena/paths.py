"""Filesystem anchors for The Arena's content and assets.

The Arena historically reached for ``data/`` and ``assets/`` via cwd-relative paths
(``Path("data")`` / ``Path("assets")``) — fine when launched from its own project
root, but broken when spawned by Oubliette's server from a different directory.

Rather than rewrite ~25 call sites, the launch entry (`handoff.play_encounter`) and
the standalone `main` both ``chdir`` to ``ARENA_ROOT`` once at startup, so every
cwd-relative literal resolves. The Arena runs as its OWN process, so this chdir never
disturbs a parent process's working directory. Paths the caller passes IN (encounter
file, result file) must be ABSOLUTE so they survive the chdir.

``DATA_DIR`` / ``ASSETS_DIR`` are exported (env-overridable) for code that wants an
explicit anchor instead of relying on cwd.
"""

from __future__ import annotations

import os
from pathlib import Path

# This file lives at arena/paths.py, so its parent is the `arena` package dir, which
# contains data/ and assets/.
ARENA_ROOT: Path = Path(__file__).resolve().parent

DATA_DIR: Path = Path(os.environ.get("ARENA_DATA_DIR") or (ARENA_ROOT / "data"))
ASSETS_DIR: Path = Path(os.environ.get("ARENA_ASSETS_DIR") or (ARENA_ROOT / "assets"))
