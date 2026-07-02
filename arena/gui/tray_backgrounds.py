"""Tray background rendering for UI panels.

Provides two tray image variants — a framed dark-leather tray for standard
panels (initiative, creature info) and a light parchment sheet for the
combat log.  Images are scaled and cached at each requested size.
"""

from __future__ import annotations

from pathlib import Path

import pygame

# ------------------------------------------------------------------
# Asset paths
# ------------------------------------------------------------------
_TRAY_DIR = Path("assets") / "ui" / "tray backgrounds"
_STANDARD_PATH = _TRAY_DIR / "standard_tray.png"
_COMBATLOG_PATH = _TRAY_DIR / "combatlog_tray.png"

# ------------------------------------------------------------------
# Caches
# ------------------------------------------------------------------
_raw_cache: dict[Path, pygame.Surface | None] = {}
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


def _get_scaled(
    path: Path, width: int, height: int, fit: str = "stretch"
) -> pygame.Surface | None:
    """Return a cached, scaled copy of the tray image.

    ``fit="stretch"`` distorts the image to the rect — right for framed art
    whose border must survive on all four sides (a stretch is a poor man's
    9-slice). ``fit="cover"`` scales to fill and center-crops the overflow —
    right for extreme aspect targets (the full-width log strip), where a
    stretch would smear the texture beyond recognition.
    """
    key = (path, width, height, fit)
    if key in _scaled_cache:
        return _scaled_cache[key]

    raw = _load_raw(path)
    if raw is None:
        _scaled_cache[key] = None
        return None

    if fit == "cover":
        # Trim the art's ragged border first — cover mode is for texture
        # fill, and a surviving edge band reads as a dark smear.
        rw, rh = raw.get_size()
        trim_x, trim_y = int(rw * 0.06), int(rh * 0.06)
        inner = raw.subsurface(
            pygame.Rect(trim_x, trim_y, rw - trim_x * 2, rh - trim_y * 2)
        )
        rw, rh = inner.get_size()
        scale = max(width / rw, height / rh)
        sw, sh = max(width, round(rw * scale)), max(height, round(rh * scale))
        big = pygame.transform.smoothscale(inner, (sw, sh))
        scaled = pygame.Surface((width, height), pygame.SRCALPHA)
        scaled.blit(big, (0, 0),
                    area=pygame.Rect((sw - width) // 2, (sh - height) // 2,
                                     width, height))
    else:
        scaled = pygame.transform.smoothscale(raw, (width, height))
    _scaled_cache[key] = scaled
    return scaled


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def draw_tray_background(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    variant: str = "standard",
    fit: str = "stretch",
) -> bool:
    """Draw a tray background image into *rect*.

    Parameters
    ----------
    surface : pygame.Surface
        Target surface to draw on.
    rect : pygame.Rect
        Position and size of the panel.
    variant : str
        ``"standard"`` for the framed dark-leather tray, ``"combatlog"``
        for the light parchment sheet.
    fit : str
        ``"stretch"`` (default) or ``"cover"`` — see ``_get_scaled``.

    Returns
    -------
    bool
        True if the tray image was drawn, False if the image was
        missing and the caller should fall back to the plain
        ``draw_panel()`` style.
    """
    path = _COMBATLOG_PATH if variant == "combatlog" else _STANDARD_PATH
    img = _get_scaled(path, rect.width, rect.height, fit)
    if img is not None:
        surface.blit(img, rect.topleft)
        return True
    return False


def clear_tray_cache() -> None:
    """Clear all cached tray surfaces."""
    _raw_cache.clear()
    _scaled_cache.clear()
