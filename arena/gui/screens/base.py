"""Base class for application screens."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from arena.gui.app import App


class Screen:
    """Base class for all screens.

    Subclasses must implement handle_event, update, and render.
    They may optionally override on_enter and on_exit for lifecycle hooks.
    """

    def on_enter(self, app: App) -> None:
        """Called when this screen becomes the active screen.

        The app reference allows screens to request transitions via
        navigation methods like app.go_to_main_menu().
        """
        pass

    def on_exit(self) -> None:
        """Called when this screen is being replaced by another.

        Override to perform cleanup (e.g., stopping timers).
        """
        pass

    def handle_event(self, event: pygame.event.Event) -> None:
        """Process a single pygame event."""
        raise NotImplementedError

    def update(self) -> None:
        """Per-frame update logic."""
        raise NotImplementedError

    def render(self, surface: pygame.Surface) -> None:
        """Render this screen onto the given surface."""
        raise NotImplementedError
