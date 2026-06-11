"""Full screen views for the application.

The Arena runs only as Oubliette's combat subprocess now, so the standalone
screens (main menu, creature/encounter builders, selectors, settings) were
removed; only the combat screen (and the lazily-imported ErrorScreen) remain.
"""

from arena.gui.screens.base import Screen
from arena.gui.screens.combat import CombatScreen

__all__ = ["Screen", "CombatScreen"]
