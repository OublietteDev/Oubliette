"""Animation frame loading, scaling, and caching.

Provides a cached pipeline for loading action/spell animation frames from
disk, scaling them to the requested display size, and returning them as a
list of ``pygame.Surface`` objects ready for sequential blitting.

Each animation lives in a subfolder of ``assets/animations/`` and consists
of sequentially-numbered PNG frames (``frame_001.png``, ``frame_002.png``,
etc.).  An optional ``meta.json`` can set the playback FPS.

Usage::

    from arena.gui.animation_cache import get_animation_frames, get_animation_fps

    frames = get_animation_frames("sword_slash", size=64)
    if frames is not None:
        fps = get_animation_fps("sword_slash")
        # Blit frames[frame_index] each tick ...
"""

import json
import logging
from pathlib import Path

import pygame

logger = logging.getLogger(__name__)

# Base directory for animation assets (relative to cwd / project root).
_ANIMATIONS_DIR = Path("assets/animations")

# Default playback speed when no meta.json is present.
_DEFAULT_FPS = 12

# ── Caches ────────────────────────────────────────────────────────────

# (animation_name, size_px) → list[Surface] | None
# Failed loads are stored as None to avoid retrying disk I/O every frame.
_animation_cache: dict[tuple[str, int], list[pygame.Surface] | None] = {}

# animation_name → fps (loaded from meta.json or default)
_fps_cache: dict[str, int] = {}

# animation_name → pygame.mixer.Sound | None (or _SOUND_NOT_CHECKED sentinel)
_sound_cache: dict[str, pygame.mixer.Sound | None] = {}

# Cached list of discovered animation folder names (None = not yet scanned).
_available_animations: list[str] | None = None


# ── Public API ────────────────────────────────────────────────────────


def get_animation_frames(
    animation_name: str,
    size: int,
) -> list[pygame.Surface] | None:
    """Get scaled animation frames for an animation, loading from disk on
    first access.

    Args:
        animation_name: Folder name inside ``assets/animations/``.
        size: Target width and height in pixels for each frame.

    Returns:
        A list of ``pygame.Surface`` objects (one per frame) with per-pixel
        alpha, or ``None`` if the animation could not be loaded.
    """
    if size < 1:
        return None

    cache_key = (animation_name, size)
    if cache_key in _animation_cache:
        return _animation_cache[cache_key]

    raw_frames = _load_raw_frames(animation_name)
    if raw_frames is None or len(raw_frames) == 0:
        _animation_cache[cache_key] = None
        return None

    scaled: list[pygame.Surface] = []
    for raw in raw_frames:
        try:
            frame = pygame.transform.smoothscale(raw, (size, size))
            scaled.append(frame)
        except (pygame.error, ValueError) as exc:
            logger.warning(
                "Failed to scale animation frame for '%s': %s",
                animation_name, exc,
            )
            # Skip this frame but continue with others
            continue

    if not scaled:
        _animation_cache[cache_key] = None
        return None

    _animation_cache[cache_key] = scaled
    return scaled


def get_animation_fps(animation_name: str) -> int:
    """Return the playback FPS for an animation.

    Reads from ``meta.json`` inside the animation folder on first access.
    Falls back to the default (12 FPS) if the file is missing or invalid.
    """
    if animation_name in _fps_cache:
        return _fps_cache[animation_name]

    fps = _DEFAULT_FPS
    meta_path = _ANIMATIONS_DIR / animation_name / "meta.json"
    if meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            fps_val = data.get("fps", _DEFAULT_FPS)
            if isinstance(fps_val, (int, float)) and fps_val > 0:
                fps = int(fps_val)
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning(
                "Failed to read meta.json for animation '%s': %s",
                animation_name, exc,
            )

    _fps_cache[animation_name] = fps
    return fps


def get_animation_sound(animation_name: str) -> "pygame.mixer.Sound | None":
    """Return a cached ``pygame.mixer.Sound`` for an animation, or ``None``.

    Looks for ``sound.ogg``, ``sound.wav``, or ``sound.mp3`` inside the
    animation folder (checked in that order).  The result is cached so
    disk I/O only happens once per animation name.
    """
    if animation_name in _sound_cache:
        return _sound_cache[animation_name]

    anim_dir = _ANIMATIONS_DIR / animation_name
    sound: pygame.mixer.Sound | None = None

    for ext in ("ogg", "wav", "mp3"):
        sound_path = anim_dir / f"sound.{ext}"
        if sound_path.is_file():
            try:
                sound = pygame.mixer.Sound(str(sound_path))
            except (pygame.error, OSError) as exc:
                logger.warning(
                    "Failed to load sound for animation '%s': %s",
                    animation_name, exc,
                )
            break  # Stop after first match (even on failure)

    _sound_cache[animation_name] = sound
    return sound


def get_available_animations() -> list[str]:
    """Scan ``assets/animations/`` and return a sorted list of animation
    folder names that contain at least one ``frame_*.png``.

    Results are cached after the first call.  Call
    :func:`clear_animation_cache` to force a rescan.
    """
    global _available_animations
    if _available_animations is not None:
        return _available_animations

    names: list[str] = []
    if _ANIMATIONS_DIR.is_dir():
        for child in sorted(_ANIMATIONS_DIR.iterdir()):
            if child.is_dir():
                # Check that the folder contains at least one frame PNG
                frame_files = sorted(child.glob("frame_*.png"))
                if frame_files:
                    names.append(child.name)

    _available_animations = names
    return names


def clear_animation_cache() -> None:
    """Clear all cached animation data.

    Call during scene transitions or when animation files may have changed
    on disk (e.g. the user dropped in new frames).
    """
    global _available_animations
    _animation_cache.clear()
    _fps_cache.clear()
    _sound_cache.clear()
    _available_animations = None


def get_cache_size() -> int:
    """Return the number of entries in the frame cache (for diagnostics)."""
    return len(_animation_cache)


# ── Private helpers ───────────────────────────────────────────────────


def _load_raw_frames(animation_name: str) -> list[pygame.Surface] | None:
    """Load raw (unscaled) frames from disk for an animation.

    Returns ``None`` if the animation folder doesn't exist or contains
    no valid frame PNGs.
    """
    anim_dir = _ANIMATIONS_DIR / animation_name
    if not anim_dir.is_dir():
        logger.debug("Animation folder not found: %s", anim_dir)
        return None

    frame_files = sorted(anim_dir.glob("frame_*.png"))
    if not frame_files:
        logger.debug("No frame_*.png files in: %s", anim_dir)
        return None

    frames: list[pygame.Surface] = []
    for fp in frame_files:
        try:
            surface = pygame.image.load(str(fp))
            frames.append(surface.convert_alpha())
        except (pygame.error, OSError) as exc:
            logger.warning(
                "Failed to load animation frame '%s': %s", fp, exc,
            )
            # Skip corrupt frames, continue loading others

    return frames if frames else None
