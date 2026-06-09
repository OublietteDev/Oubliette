"""Image-backed button rendering for the fantasy UI theme.

Provides two button image variants (standard and quit/back) that are
scaled and cached at any requested size.  Call ``draw_image_button()``
anywhere a button needs to be rendered with the fantasy button artwork.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from arena.gui.renderer import draw_text_centered
from arena.util.constants import COLORS, parse_color

# ------------------------------------------------------------------
# Asset paths
# ------------------------------------------------------------------
_BUTTONS_DIR = Path("assets") / "ui" / "buttons"
_STANDARD_PATH = _BUTTONS_DIR / "mainmenu_button_standard.png"
_QUIT_PATH = _BUTTONS_DIR / "mainmenu_button_quit.png"

# ------------------------------------------------------------------
# Raw image cache  (loaded once, then scaled copies are derived)
# ------------------------------------------------------------------
_raw_cache: dict[Path, pygame.Surface | None] = {}

# Scaled surface cache:  (path, width, height) -> Surface | None
_scaled_cache: dict[tuple[Path, int, int], pygame.Surface | None] = {}


def _load_raw(path: Path) -> pygame.Surface | None:
    """Load a raw image from disk (cached)."""
    if path in _raw_cache:
        return _raw_cache[path]
    try:
        surf = pygame.image.load(str(path)).convert_alpha()
        _raw_cache[path] = surf
        return surf
    except (pygame.error, FileNotFoundError, OSError):
        _raw_cache[path] = None
        return None


def _get_scaled(path: Path, width: int, height: int) -> pygame.Surface | None:
    """Return a cached, scaled copy of the button image."""
    key = (path, width, height)
    if key in _scaled_cache:
        return _scaled_cache[key]

    raw = _load_raw(path)
    if raw is None:
        _scaled_cache[key] = None
        return None

    scaled = pygame.transform.smoothscale(raw, (width, height))
    _scaled_cache[key] = scaled
    return scaled


# ------------------------------------------------------------------
# Brightness adjustment for hover state
# ------------------------------------------------------------------

def _brighten_surface(surface: pygame.Surface, amount: int = 30) -> pygame.Surface:
    """Return a slightly brightened copy of *surface* for hover feedback.

    Uses additive blending with a flat white overlay.
    """
    bright = surface.copy()
    overlay = pygame.Surface(bright.get_size(), pygame.SRCALPHA)
    overlay.fill((amount, amount, amount, 0))
    bright.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    return bright


# Brightened hover cache:  (path, width, height) -> Surface | None
_hover_cache: dict[tuple[Path, int, int], pygame.Surface | None] = {}


def _get_hover(path: Path, width: int, height: int) -> pygame.Surface | None:
    """Return a cached, brightened variant for hover state."""
    key = (path, width, height)
    if key in _hover_cache:
        return _hover_cache[key]

    base = _get_scaled(path, width, height)
    if base is None:
        _hover_cache[key] = None
        return None

    bright = _brighten_surface(base)
    _hover_cache[key] = bright
    return bright


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def draw_image_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    *,
    is_hovered: bool = False,
    is_quit: bool = False,
    font_size: int = 22,
    text_color: tuple[int, int, int] | None = None,
    hover_text_color: tuple[int, int, int] | None = None,
) -> None:
    """Draw a button using the fantasy button image artwork.

    Parameters
    ----------
    surface : pygame.Surface
        Target surface to draw on.
    rect : pygame.Rect
        Position and size of the button.
    label : str
        Text to render centered on the button.
    is_hovered : bool
        If True, draw the brightened hover variant.
    is_quit : bool
        If True, use the red/quit image. Otherwise use the standard
        blue image.
    font_size : int
        Font size for the label text.
    text_color : tuple or None
        RGB color for normal-state text. Defaults to ``COLORS["text_primary"]``.
    hover_text_color : tuple or None
        RGB color for hovered-state text. Defaults to ``COLORS["text_gold"]``.
    """
    path = _QUIT_PATH if is_quit else _STANDARD_PATH
    w, h = rect.width, rect.height

    if is_hovered:
        img = _get_hover(path, w, h)
    else:
        img = _get_scaled(path, w, h)

    if img is not None:
        surface.blit(img, rect.topleft)
    else:
        # Fallback: plain rectangle if images are missing
        color = (
            parse_color(COLORS["button_hover"])
            if is_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, color, rect, border_radius=4)
        pygame.draw.rect(
            surface,
            parse_color(COLORS["border_accent"]),
            rect, 1, border_radius=4,
        )

    # Text
    if text_color is None:
        text_color = parse_color(COLORS["text_primary"])
    if hover_text_color is None:
        hover_text_color = parse_color(COLORS["text_gold"])

    color = hover_text_color if is_hovered else text_color
    draw_text_centered(surface, label, rect.center, color, font_size=font_size)


def clear_button_cache() -> None:
    """Clear all cached button surfaces (for testing or resolution changes)."""
    _raw_cache.clear()
    _scaled_cache.clear()
    _hover_cache.clear()
