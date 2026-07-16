"""Token image loading, scaling, circular clipping, and caching.

Provides a cached pipeline for loading creature token images from disk,
scaling them to fit the current token diameter (which varies with camera
zoom), and clipping them to a circle so they render cleanly inside the
team-color ring.

Usage::

    from arena.gui.token_cache import get_token_image

    surface = get_token_image("assets/tokens/custom/thorin.png", diameter=36)
    if surface is not None:
        screen.blit(surface, surface.get_rect(center=token_center))
"""

import logging
from pathlib import Path

import pygame

logger = logging.getLogger(__name__)

# Module-level cache: (absolute_path, diameter_pixels, zoom, ox, oy) -> Surface
# or None. Failed loads are stored as None to avoid retrying disk I/O every frame.
_token_image_cache: dict[
    tuple[str, int, float, float, float], pygame.Surface | None
] = {}


def get_token_image(
    image_path: str,
    diameter: int,
    zoom: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> pygame.Surface | None:
    """Get a circular token image, scaled to the given diameter.

    Loads from disk on first access, then caches the result.  Returns
    ``None`` if loading fails (file not found, corrupt image, etc.).

    Args:
        image_path: Path to the image file (absolute or relative to cwd).
        diameter: Target diameter in pixels (typically
                  ``TOKEN_RADIUS * 2 * camera.zoom``).
        zoom: Authored framing — multiplier on the crop-to-fill baseline
              (1.0 fills the circle exactly; <1 letterboxes toward the old
              contain look, >1 crops in tighter).
        offset_x: Authored pan, as a fraction of the diameter (+ = right).
        offset_y: Authored pan, as a fraction of the diameter (+ = down).

    Returns:
        A ``pygame.Surface`` with per-pixel alpha containing the circular
        token image, or ``None`` on failure.
    """
    if diameter < 1:
        return None

    cache_key = (str(Path(image_path).resolve()), diameter,
                 float(zoom), float(offset_x), float(offset_y))

    if cache_key in _token_image_cache:
        return _token_image_cache[cache_key]

    # Load raw image from disk
    raw_surface = _load_raw_image(image_path)
    if raw_surface is None:
        # Cache the failure so we don't retry disk I/O every frame
        _token_image_cache[cache_key] = None
        return None

    # Scale and clip to circle
    result = _scale_and_clip_circle(raw_surface, diameter, zoom, offset_x, offset_y)
    _token_image_cache[cache_key] = result
    return result


def _load_raw_image(image_path: str) -> pygame.Surface | None:
    """Load a raw image from disk.

    Returns ``None`` on any failure (missing file, corrupt data, etc.)
    and logs a warning.
    """
    try:
        path = Path(image_path)
        if not path.exists():
            logger.warning("Token image not found: %s", image_path)
            return None
        surface = pygame.image.load(str(path))
        return surface.convert_alpha()
    except (pygame.error, OSError) as exc:
        logger.warning("Failed to load token image '%s': %s", image_path, exc)
        return None


def _scale_and_clip_circle(
    raw_surface: pygame.Surface,
    diameter: int,
    zoom: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> pygame.Surface:
    """Scale an image to FILL a circle of *diameter* pixels (crop-to-fill).

    The image is scaled (maintaining aspect ratio) so its SMALLEST dimension
    equals the diameter — the same cover fit the bestiary card and character
    sheet use — times any authored ``zoom``, then centered plus the authored
    pan (fractions of the diameter). It sits on an opaque BLACK backing (so
    any letterbox margin from zoom < 1 and any transparency in the art read
    as a solid token, not a floating cutout), and a circular mask keeps only
    the pixels inside the circle.

    Args:
        raw_surface: The raw loaded image.
        diameter: Target diameter in pixels.
        zoom: Framing zoom on the cover baseline (1.0 = exact fill).
        offset_x: Framing pan, fraction of the diameter (+ = right).
        offset_y: Framing pan, fraction of the diameter (+ = down).

    Returns:
        A *diameter* x *diameter* ``SRCALPHA`` surface with the image
        clipped to a circle.
    """
    if diameter < 1:
        diameter = 1

    # Scale maintaining aspect ratio
    orig_w, orig_h = raw_surface.get_size()
    if orig_w == 0 or orig_h == 0:
        return pygame.Surface((diameter, diameter), pygame.SRCALPHA)

    scale_factor = diameter / min(orig_w, orig_h) * max(0.01, zoom)
    new_w = max(1, int(orig_w * scale_factor))
    new_h = max(1, int(orig_h * scale_factor))
    scaled = pygame.transform.smoothscale(raw_surface, (new_w, new_h))

    # Create result surface with per-pixel alpha, backed opaque black
    result = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    result.fill((0, 0, 0, 255))

    # Center the scaled image, shifted by the authored pan
    result.blit(scaled, ((diameter - new_w) // 2 + int(offset_x * diameter),
                         (diameter - new_h) // 2 + int(offset_y * diameter)))

    # Apply circular mask using BLEND_RGBA_MULT: draw a filled white
    # circle on an otherwise transparent surface, then multiply it
    # with the result.  Pixels outside the circle get alpha = 0.
    mask = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    radius = diameter // 2
    pygame.draw.circle(mask, (255, 255, 255, 255), (radius, radius), radius)
    result.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    return result


def clear_cache() -> None:
    """Clear the entire token image cache.

    Call during scene transitions or when memory pressure is a concern.
    Under normal use the cache stays bounded because there are a finite
    number of creatures and zoom levels.
    """
    _token_image_cache.clear()


def get_cache_size() -> int:
    """Return the number of entries in the cache (for diagnostics/testing)."""
    return len(_token_image_cache)
