"""Authored-content pipeline (design v0.1).

A *content pack* is a versioned directory of JSON files describing a world as
DATA, not code. `loader.load_pack` reads a pack, validates it whole (strict
per-entity schemas + a cross-reference linter), and builds the authored baseline
the engine seeds from — replacing the hand-coded `seed.seed_world()`.

P1 scope: core world content (items, stat blocks, NPCs, places, scenario) and a
repository-parity migration of the Brightvale seed. Authored canon, the
authoring UI, character creation, and the map are later arcs (see the design doc
`oubliette-content-pipeline-v0.1.md`).
"""

from .loader import DEFAULT_PACK, LoadedWorld, PackValidationError, load_pack

__all__ = ["DEFAULT_PACK", "LoadedWorld", "PackValidationError", "load_pack"]
