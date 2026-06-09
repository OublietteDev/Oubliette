"""Main application class with screen management."""

from pathlib import Path

import pygame

from arena.gui.screens.base import Screen
from arena.gui.screens.main_menu import MainMenuScreen
from arena.gui.screens.combat import CombatScreen
from arena.gui.screens.encounter_select import EncounterSelectScreen
from arena.gui.screens.stub_screen import StubScreen
from arena.gui.background_slideshow import BackgroundSlideshow
from arena.gui.custom_cursor import CustomCursorManager
from arena.util.constants import COLORS, parse_color
from arena.util.loader import load_encounter
from arena.util.settings import load_settings

# Path to the menu background images folder
_BACKGROUNDS_DIR = Path("assets") / "ui" / "menu backgrounds"


class App:
    """Main application class that manages the game loop and screen transitions."""

    def __init__(self, width: int | None = None, height: int | None = None):
        """Initialize the application.

        If width/height are not provided, the resolution is read from
        the persisted settings (data/settings.json), defaulting to 1280x720.
        """
        settings = load_settings()

        if width is None and height is None:
            try:
                w_str, h_str = settings.system.resolution.split("x")
                width = int(w_str)
                height = int(h_str)
            except (ValueError, AttributeError):
                width, height = 1280, 720
        else:
            width = width or 1280
            height = height or 720

        pygame.init()

        # Initialize audio system (gracefully handles missing audio device)
        from arena.audio.manager import get_sound_manager
        sm = get_sound_manager()
        sm.play_music("menu_music.mp3")

        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("The Arena")
        self.clock = pygame.time.Clock()
        self.running = False
        self.fps = 60
        self.width = width
        self.height = height

        # Persistent background slideshow — shared across menu screens so
        # navigating between them produces a seamless, uninterrupted cycle.
        self.slideshow = BackgroundSlideshow(
            _BACKGROUNDS_DIR, width, height,
        )
        self._bg_overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        self._bg_overlay.fill((26, 20, 16, 160))  # warm dark tint at ~63% opacity
        self._last_tick: int = pygame.time.get_ticks()

        # Custom cursor — picks a random cursor from assets/ui/cursor/
        # unless the user has chosen a specific one in settings.
        self.cursor_manager = CustomCursorManager(
            settings.display.cursor,
            animations_enabled=settings.display.cursor_animations,
        )

        # Screen management
        self.current_screen: Screen | None = None
        self._switch_to(MainMenuScreen(width, height))

    def _switch_to(self, new_screen: Screen) -> None:
        """Transition from current screen to new_screen."""
        if self.current_screen is not None:
            self.current_screen.on_exit()
        self.current_screen = new_screen
        self.current_screen.on_enter(self)

        # Resume menu music when not entering combat
        from arena.gui.screens.combat import CombatScreen
        if not isinstance(new_screen, CombatScreen):
            self._ensure_menu_music()

    def _ensure_menu_music(self) -> None:
        """Start menu music if it is not already playing."""
        from arena.audio.manager import get_sound_manager
        sm = get_sound_manager()
        if sm.current_track != "menu_music.mp3":
            sm.play_music("menu_music.mp3")

    # --- Public navigation methods (called by screens) ---

    def go_to_main_menu(self) -> None:
        """Switch to the main menu screen."""
        self._switch_to(MainMenuScreen(self.width, self.height))

    def go_to_combat(self, encounter_path: Path) -> None:
        """Load an encounter and switch to the combat screen."""
        from arena.gui.screens.error_screen import ErrorScreen

        try:
            data_dir = Path("data")
            encounter = load_encounter(encounter_path)
            combat_screen = CombatScreen(self.width, self.height)
            combat_screen.load_encounter(encounter, data_dir)
            self._switch_to(combat_screen)
        except FileNotFoundError as exc:
            self._switch_to(ErrorScreen(
                self.width, self.height,
                title="Unable to Load Encounter",
                message=f"Not all referenced entities exist: {exc}",
            ))
        except Exception as exc:
            self._switch_to(ErrorScreen(
                self.width, self.height,
                title="Unable to Load Encounter",
                message=str(exc),
            ))

    def go_to_encounter_select(self) -> None:
        """Switch to the encounter file picker screen."""
        self._switch_to(EncounterSelectScreen(self.width, self.height))

    def go_to_encounter_setup(self) -> None:
        """Switch to the encounter setup screen for a new encounter."""
        from arena.gui.screens.encounter_setup import EncounterSetupScreen
        self._switch_to(EncounterSetupScreen(self.width, self.height))

    def go_to_encounter_setup_with(self, encounter_path: Path) -> None:
        """Switch to the encounter setup screen to edit an existing encounter."""
        from arena.gui.screens.encounter_setup import EncounterSetupScreen
        self._switch_to(EncounterSetupScreen(self.width, self.height, encounter_path))

    def go_to_creature_select(self) -> None:
        """Switch to the creature file picker screen."""
        from arena.gui.screens.creature_select import CreatureSelectScreen
        self._switch_to(CreatureSelectScreen(self.width, self.height))

    def go_to_creature_builder(self, creature_path: Path | None = None) -> None:
        """Switch to the creature builder screen, optionally loading an existing file."""
        from arena.gui.screens.character_builder import CreatureBuilderScreen
        self._switch_to(CreatureBuilderScreen(self.width, self.height, creature_path))

    def go_to_settings(self) -> None:
        """Switch to the settings screen."""
        from arena.gui.screens.settings_screen import SettingsScreen
        self._switch_to(SettingsScreen(self.width, self.height))

    def go_to_save_select(self) -> None:
        """Switch to the save file picker screen."""
        from arena.gui.screens.save_select import SaveSelectScreen
        self._switch_to(SaveSelectScreen(self.width, self.height))

    def go_to_combat_from_save(self, save_path: Path) -> None:
        """Load a saved combat state and switch to the combat screen."""
        from arena.gui.screens.error_screen import ErrorScreen
        from arena.util.loader import load_combat_state

        try:
            cm = load_combat_state(save_path)
            combat_screen = CombatScreen(self.width, self.height)
            combat_screen.load_from_save(cm)
            self._switch_to(combat_screen)
        except FileNotFoundError as exc:
            self._switch_to(ErrorScreen(
                self.width, self.height,
                title="Unable to Load Save",
                message=f"Save file not found: {exc}",
            ))
        except Exception as exc:
            self._switch_to(ErrorScreen(
                self.width, self.height,
                title="Unable to Load Save",
                message=str(exc),
            ))

    def go_to_stub(self, title: str) -> None:
        """Switch to a 'Coming Soon' placeholder screen."""
        self._switch_to(StubScreen(self.width, self.height, title))

    def render_background(self, surface: pygame.Surface) -> None:
        """Draw the slideshow background + dark overlay onto *surface*.

        Call this at the very start of a screen's ``render()`` method to
        get the shared animated background.  Screens that don't want it
        (e.g. the combat screen) simply don't call this.
        """
        if self.slideshow.has_images:
            self.slideshow.render(surface)
            surface.blit(self._bg_overlay, (0, 0))

    def quit(self) -> None:
        """Signal the game loop to stop."""
        self.running = False

    def run(self) -> None:
        """Main game loop."""
        self.running = True

        while self.running:
            self._handle_events()
            self._update()
            self._render()
            self.clock.tick(self.fps)

        self.cursor_manager.restore_system_cursor()
        pygame.quit()

    def _handle_events(self) -> None:
        """Process pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            else:
                # Delegate all other events to the current screen
                self.current_screen.handle_event(event)

    def _update(self) -> None:
        """Update game state."""
        # Advance the shared background slideshow timer every frame.
        now = pygame.time.get_ticks()
        dt_ms = now - self._last_tick
        self._last_tick = now
        self.slideshow.update(float(dt_ms))
        self.cursor_manager.update()

        self.current_screen.update()

    def _render(self) -> None:
        """Render the current frame."""
        self.screen.fill(parse_color(COLORS["bg_dark"]))
        self.current_screen.render(self.screen)
        # Custom cursor drawn last — always on top of everything
        self.cursor_manager.render(self.screen)
        pygame.display.flip()
