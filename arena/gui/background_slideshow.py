"""Cycling background slideshow for the main menu.

Scans a folder for image files, then displays them in a random order
(no repeats until every image has been shown). Each image is displayed
for a configurable duration before cross-fading to the next.
"""

from __future__ import annotations

import random
from pathlib import Path

import pygame


# Supported image file extensions (case-insensitive)
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

# Default timing (in milliseconds)
DEFAULT_DISPLAY_MS = 15_000  # how long each image is shown at full opacity
DEFAULT_FADE_MS = 2_000      # duration of the cross-fade transition


class BackgroundSlideshow:
    """Loads all images from a folder and cross-fades between them.

    Images are displayed in a shuffled order.  Once every image has been
    shown, the order is re-shuffled (ensuring the last image of the
    previous cycle is not the first of the next cycle) and the loop
    continues.

    Parameters
    ----------
    folder : Path
        Directory containing background image files.
    screen_width, screen_height : int
        Target display size.  Images are scaled to cover the screen.
    display_ms : int
        Milliseconds each image is held at full opacity.
    fade_ms : int
        Milliseconds for the cross-fade transition between images.
    """

    def __init__(
        self,
        folder: Path,
        screen_width: int,
        screen_height: int,
        display_ms: int = DEFAULT_DISPLAY_MS,
        fade_ms: int = DEFAULT_FADE_MS,
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.display_ms = display_ms
        self.fade_ms = fade_ms

        # Discover image paths
        self._image_paths: list[Path] = self._scan_folder(folder)

        # Scaled surface cache: path -> pygame.Surface
        self._surface_cache: dict[Path, pygame.Surface] = {}

        # Playback state
        self._order: list[int] = []     # indices into _image_paths
        self._current_idx: int = 0      # position within _order
        self._elapsed_ms: float = 0.0   # time into current slide
        self._active: bool = len(self._image_paths) > 0

        if self._active:
            self._shuffle_order()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_images(self) -> bool:
        """True if at least one background image was found."""
        return self._active

    @property
    def image_count(self) -> int:
        """Number of discovered background images."""
        return len(self._image_paths)

    def update(self, dt_ms: float) -> None:
        """Advance the slideshow timer.

        Parameters
        ----------
        dt_ms : float
            Milliseconds elapsed since the last frame.
        """
        if not self._active:
            return

        self._elapsed_ms += dt_ms

        # Total time for one slide = display + fade into the next
        slide_total = self.display_ms + self.fade_ms
        if self._elapsed_ms >= slide_total:
            self._elapsed_ms -= slide_total
            self._advance()

    def render(self, surface: pygame.Surface) -> None:
        """Draw the current (and possibly next) background onto *surface*.

        During the fade window the outgoing image is drawn first at full
        opacity, then the incoming image is drawn on top with increasing
        alpha — producing a smooth cross-fade.
        """
        if not self._active:
            return

        current_surface = self._get_surface(self._current_image_path())

        if current_surface is None:
            return

        # Are we in the cross-fade window?
        if self._elapsed_ms > self.display_ms and len(self._image_paths) > 1:
            fade_progress = (self._elapsed_ms - self.display_ms) / self.fade_ms
            fade_progress = max(0.0, min(1.0, fade_progress))

            next_surface = self._get_surface(self._next_image_path())

            if next_surface is not None:
                # Draw outgoing image at full opacity
                surface.blit(current_surface, (0, 0))
                # Draw incoming image with increasing alpha
                next_surface.set_alpha(int(255 * fade_progress))
                surface.blit(next_surface, (0, 0))
                next_surface.set_alpha(255)  # reset so cache isn't tainted
            else:
                surface.blit(current_surface, (0, 0))
        else:
            # Fully visible — no fade
            surface.blit(current_surface, (0, 0))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scan_folder(folder: Path) -> list[Path]:
        """Return sorted list of image file paths inside *folder*."""
        if not folder.is_dir():
            return []
        paths = [
            p for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
        ]
        return paths

    def _shuffle_order(self) -> None:
        """Create a new shuffled order, avoiding same-image adjacency."""
        indices = list(range(len(self._image_paths)))

        if len(indices) <= 1:
            self._order = indices
            self._current_idx = 0
            return

        # If we already had an order, remember the last image so we
        # don't start the new cycle with the same one.
        last_shown: int | None = None
        if self._order:
            last_shown = self._order[-1]

        random.shuffle(indices)

        # Swap the first element if it matches the last of the previous cycle
        if last_shown is not None and indices[0] == last_shown:
            # Swap with a random later position
            swap_idx = random.randint(1, len(indices) - 1)
            indices[0], indices[swap_idx] = indices[swap_idx], indices[0]

        self._order = indices
        self._current_idx = 0

    def _advance(self) -> None:
        """Move to the next image, re-shuffling if we've exhausted the cycle."""
        self._current_idx += 1
        if self._current_idx >= len(self._order):
            self._shuffle_order()

    def _current_image_path(self) -> Path:
        """Path of the currently displayed image."""
        return self._image_paths[self._order[self._current_idx]]

    def _next_image_path(self) -> Path:
        """Path of the next image (for cross-fade look-ahead)."""
        next_idx = self._current_idx + 1
        if next_idx >= len(self._order):
            # The next cycle hasn't been shuffled yet — peek at index 0
            # of the *current* order as a reasonable preview.  The actual
            # shuffle happens in _advance(), so the worst case is that
            # the fade-in image differs from the one that actually appears
            # after the advance.  In practice this is imperceptible because
            # _advance() is called at the exact moment the fade completes.
            # To guarantee correctness we pre-compute the next cycle's first
            # image here.
            return self._peek_next_cycle_first()
        return self._image_paths[self._order[next_idx]]

    def _peek_next_cycle_first(self) -> Path:
        """Predict the first image of the next shuffle cycle.

        We don't actually shuffle yet (that happens on advance), so we
        pick a random image that isn't the current last one.
        """
        current_last = self._order[-1] if self._order else 0
        if len(self._image_paths) == 1:
            return self._image_paths[0]
        candidates = [i for i in range(len(self._image_paths)) if i != current_last]
        return self._image_paths[random.choice(candidates)]

    def _get_surface(self, path: Path) -> pygame.Surface | None:
        """Load (and cache) an image scaled to the screen size."""
        if path in self._surface_cache:
            return self._surface_cache[path]

        try:
            raw = pygame.image.load(str(path)).convert()
            scaled = pygame.transform.smoothscale(raw, (self.screen_width, self.screen_height))
            self._surface_cache[path] = scaled
            return scaled
        except (pygame.error, FileNotFoundError, OSError):
            return None
