"""Oubliette: The Forge — a friendly companion app for authoring content packs.

The Forge reads, validates, and (later) edits *packs* (the world recipe the game
plays). Its one firm principle: it checks a pack with the EXACT same rulebook the
game uses to load it (`oubliette.content.loader`), so a pack The Forge calls
"ready to play" is guaranteed to load. It never touches save files.

Build step C1 (this commit): open a pack and check it — list packs, show a pack's
contents read-only, and report ✓ ready / ⚠ issues from the shared validator.
"""
