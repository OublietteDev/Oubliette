"""Custom cursor rendering with optional particle effects.

Scans ``assets/ui/cursor/`` for PNG images and selects one at random
on startup (or a specific one chosen via settings).  The system cursor
is hidden and replaced with the custom artwork, drawn at the mouse
position each frame.

Each cursor has a unique particle effect:

* **Wand** — small blue motes drift downward from its tip.
* **Arrow** — red/yellow flame particles trail from the tip.
* **Sword** — green drips fall from the blade (orc blood).
"""

from __future__ import annotations

import random
from pathlib import Path

import pygame

# ------------------------------------------------------------------
# Asset location
# ------------------------------------------------------------------
_CURSOR_DIR = Path("assets") / "ui" / "cursor"

# Supported image extensions (same set as background_slideshow)
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

# Desired cursor height in pixels (width scaled proportionally)
_CURSOR_HEIGHT = 48

# ------------------------------------------------------------------
# Particle system for the wand cursor
# ------------------------------------------------------------------

class _Particle:
    """A single blue mote that drifts downward from the wand tip."""

    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size")

    def __init__(self, x: float, y: float) -> None:
        self.x = x + random.uniform(-2, 2)
        self.y = y + random.uniform(-1, 1)
        self.vx = random.uniform(-8, 8)
        self.vy = random.uniform(15, 40)
        self.max_life = random.uniform(0.4, 0.9)
        self.life = self.max_life
        self.size = random.uniform(1.5, 3.5)

    def update(self, dt: float) -> bool:
        """Advance the particle.  Returns False when dead."""
        self.life -= dt
        if self.life <= 0:
            return False
        self.x += self.vx * dt
        self.vy += 20 * dt  # gentle gravity
        self.y += self.vy * dt
        # Slight horizontal drift
        self.vx *= 0.96
        return True

    def render(self, surface: pygame.Surface) -> None:
        """Draw the particle as a translucent blue circle."""
        t = max(0.0, self.life / self.max_life)  # 1.0 → 0.0
        alpha = int(200 * t)
        # Blue-cyan colour with slight variation
        r = int(60 * (1 - t))
        g = int(140 + 80 * t)
        b = int(220 + 35 * t)
        radius = max(1, int(self.size * t))

        # Draw glow (larger, dimmer)
        glow_radius = radius + 2
        glow_surf = pygame.Surface((glow_radius * 4, glow_radius * 4), pygame.SRCALPHA)
        glow_alpha = max(0, alpha // 3)
        pygame.draw.circle(
            glow_surf,
            (r, g, b, glow_alpha),
            (glow_radius * 2, glow_radius * 2),
            glow_radius,
        )
        surface.blit(glow_surf, (int(self.x) - glow_radius * 2, int(self.y) - glow_radius * 2))

        # Draw core
        core_surf = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
        pygame.draw.circle(
            core_surf,
            (r, g, b, alpha),
            (radius * 2, radius * 2),
            radius,
        )
        surface.blit(core_surf, (int(self.x) - radius * 2, int(self.y) - radius * 2))


class _WandParticles:
    """Manages a pool of falling blue motes for the wand cursor."""

    def __init__(self) -> None:
        self._particles: list[_Particle] = []
        self._spawn_accum: float = 0.0

    def update(self, dt: float, tip_x: float, tip_y: float) -> None:
        """Spawn new particles at the tip and advance existing ones."""
        # Spawn rate: ~30 particles/sec
        self._spawn_accum += dt
        spawn_interval = 1.0 / 30.0
        while self._spawn_accum >= spawn_interval:
            self._spawn_accum -= spawn_interval
            self._particles.append(_Particle(tip_x, tip_y))

        # Update & cull
        self._particles = [p for p in self._particles if p.update(dt)]

    def render(self, surface: pygame.Surface) -> None:
        """Draw all living particles."""
        for p in self._particles:
            p.render(surface)

    def clear(self) -> None:
        """Remove all particles immediately."""
        self._particles.clear()
        self._spawn_accum = 0.0


# ------------------------------------------------------------------
# Particle system for the arrow cursor (flame)
# ------------------------------------------------------------------

class _FlameParticle:
    """A single red/yellow flame mote that rises from the arrow tip."""

    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size")

    def __init__(self, x: float, y: float) -> None:
        self.x = x + random.uniform(-3, 3)
        self.y = y + random.uniform(-1, 1)
        self.vx = random.uniform(-12, 12)
        self.vy = random.uniform(-45, -15)  # flames rise upward
        self.max_life = random.uniform(0.3, 0.7)
        self.life = self.max_life
        self.size = random.uniform(2.0, 4.0)

    def update(self, dt: float) -> bool:
        """Advance the particle.  Returns False when dead."""
        self.life -= dt
        if self.life <= 0:
            return False
        self.x += self.vx * dt
        self.vy -= 30 * dt  # buoyancy — accelerate upward
        self.y += self.vy * dt
        # Flicker / horizontal jitter
        self.vx += random.uniform(-40, 40) * dt
        self.vx *= 0.94
        return True

    def render(self, surface: pygame.Surface) -> None:
        """Draw the particle as a translucent red/yellow circle."""
        t = max(0.0, self.life / self.max_life)  # 1.0 → 0.0
        alpha = int(220 * t)
        # Colour goes from bright yellow (young) → deep red (old)
        r = 255
        g = int(220 * t)          # 220 → 0
        b = int(60 * t * t)       # faint orange tinge, fades fast
        radius = max(1, int(self.size * (0.4 + 0.6 * t)))

        # Glow layer
        glow_radius = radius + 2
        glow_surf = pygame.Surface((glow_radius * 4, glow_radius * 4), pygame.SRCALPHA)
        glow_alpha = max(0, alpha // 3)
        pygame.draw.circle(
            glow_surf,
            (r, g // 2, 0, glow_alpha),
            (glow_radius * 2, glow_radius * 2),
            glow_radius,
        )
        surface.blit(glow_surf, (int(self.x) - glow_radius * 2, int(self.y) - glow_radius * 2))

        # Core
        core_surf = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
        pygame.draw.circle(
            core_surf,
            (r, g, b, alpha),
            (radius * 2, radius * 2),
            radius,
        )
        surface.blit(core_surf, (int(self.x) - radius * 2, int(self.y) - radius * 2))


class _ArrowFlame:
    """Manages a pool of flame particles for the arrow cursor."""

    def __init__(self) -> None:
        self._particles: list[_FlameParticle] = []
        self._spawn_accum: float = 0.0

    def update(self, dt: float, tip_x: float, tip_y: float) -> None:
        self._spawn_accum += dt
        spawn_interval = 1.0 / 35.0  # ~35 particles/sec
        while self._spawn_accum >= spawn_interval:
            self._spawn_accum -= spawn_interval
            self._particles.append(_FlameParticle(tip_x, tip_y))
        self._particles = [p for p in self._particles if p.update(dt)]

    def render(self, surface: pygame.Surface) -> None:
        for p in self._particles:
            p.render(surface)

    def clear(self) -> None:
        self._particles.clear()
        self._spawn_accum = 0.0


# ------------------------------------------------------------------
# Particle system for the sword cursor (green drip)
# ------------------------------------------------------------------

class _DripParticle:
    """A single green droplet that falls from the sword blade.

    The droplet starts as a small bead clinging to the tip, then
    elongates vertically as it accelerates downward (teardrop shape).
    Near the end of its life it flattens into a brief horizontal
    splat before disappearing.
    """

    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "phase")

    # Phase constants
    FALLING = 0
    SPLAT = 1

    def __init__(self, x: float, y: float) -> None:
        self.x = x + random.uniform(-1.5, 1.5)
        self.y = y + random.uniform(0, 1)
        self.vx = random.uniform(-1, 1)         # almost no horizontal drift
        self.vy = random.uniform(2, 8)           # start slow, gravity does the work
        self.max_life = random.uniform(0.6, 1.2)
        self.life = self.max_life
        self.size = random.uniform(2.0, 3.5)
        self.phase = self.FALLING

    def update(self, dt: float) -> bool:
        """Advance the droplet.  Returns False when dead."""
        self.life -= dt
        if self.life <= 0:
            return False

        if self.phase == self.FALLING:
            self.vy += 80 * dt          # heavy gravity — viscous liquid
            self.y += self.vy * dt
            self.x += self.vx * dt
            self.vx *= 0.90

            # Transition to splat in the last 15% of life
            if self.life < self.max_life * 0.15:
                self.phase = self.SPLAT
                self.vy = 0
                self.vx = 0
        else:
            # Splat phase: stationary, just fading out
            pass

        return True

    def render(self, surface: pygame.Surface) -> None:
        """Draw the droplet — elongated while falling, flat when splatting."""
        t = max(0.0, self.life / self.max_life)  # 1.0 → 0.0
        alpha = int(210 * min(1.0, t * 3))       # fade in last third of life

        # Sickly green, darkens over lifetime
        r = int(20 + 30 * (1 - t))     # 20 → 50
        g = int(100 + 100 * t)         # 200 → 100
        b = int(10 + 15 * t)           # 25 → 10

        if self.phase == self.FALLING:
            # Teardrop: narrow width, height stretches with speed
            speed_factor = min(abs(self.vy) / 60.0, 1.0)
            w = max(2, int(self.size * (0.5 + 0.3 * t)))
            h = max(3, int(self.size * (1.0 + 2.5 * speed_factor)))

            surf_w = w + 4
            surf_h = h + 4
            drop_surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
            # Main droplet body
            pygame.draw.ellipse(
                drop_surf,
                (r, g, b, alpha),
                (2, 2, w, h),
            )
            # Bright highlight near top for a wet sheen
            if w >= 3 and h >= 4:
                hi_alpha = min(255, alpha + 40)
                hi_r = min(255, r + 40)
                hi_g = min(255, g + 60)
                pygame.draw.ellipse(
                    drop_surf,
                    (hi_r, hi_g, b + 20, hi_alpha // 2),
                    (2 + w // 4, 2 + 1, max(1, w // 2), max(1, h // 3)),
                )

            surface.blit(drop_surf, (int(self.x) - surf_w // 2, int(self.y) - surf_h // 2))
        else:
            # Splat: wide, very short ellipse
            splat_t = 1.0 - (self.life / (self.max_life * 0.15))  # 0→1 during splat
            w = max(3, int(self.size * (1.5 + 2.0 * splat_t)))
            h = max(1, int(self.size * (0.5 - 0.3 * splat_t)))

            surf_w = w + 4
            surf_h = h + 4
            splat_surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
            pygame.draw.ellipse(
                splat_surf,
                (r, g, b, alpha),
                (2, 2, w, h),
            )
            surface.blit(splat_surf, (int(self.x) - surf_w // 2, int(self.y) - surf_h // 2))


class _SwordDrip:
    """Manages intermittent green drips for the sword cursor.

    Instead of a constant stream, drips spawn in small bursts of 1-3
    droplets separated by brief pauses, mimicking liquid collecting
    on the blade and releasing.
    """

    def __init__(self) -> None:
        self._particles: list[_DripParticle] = []
        self._drip_timer: float = 0.0
        # Time until next burst (randomised)
        self._next_drip: float = random.uniform(0.08, 0.35)

    def update(self, dt: float, tip_x: float, tip_y: float) -> None:
        self._drip_timer += dt
        if self._drip_timer >= self._next_drip:
            self._drip_timer = 0.0
            self._next_drip = random.uniform(0.10, 0.40)
            # Burst of 1-3 droplets
            for _ in range(random.randint(1, 3)):
                self._particles.append(_DripParticle(tip_x, tip_y))

        self._particles = [p for p in self._particles if p.update(dt)]

    def render(self, surface: pygame.Surface) -> None:
        for p in self._particles:
            p.render(surface)

    def clear(self) -> None:
        self._particles.clear()
        self._drip_timer = 0.0


# ------------------------------------------------------------------
# Main cursor manager
# ------------------------------------------------------------------

class CustomCursorManager:
    """Manages custom cursor display and optional particle effects.

    Parameters
    ----------
    setting_value : str
        ``"Random"`` to pick at random, or a cursor name like ``"sword"``
        to use a specific cursor.  Case-insensitive stem match.
    animations_enabled : bool
        Whether cursor particle animations are active.  Can be toggled
        at runtime via :pyattr:`animations_enabled`.
    """

    def __init__(self, setting_value: str = "Random", *, animations_enabled: bool = True) -> None:
        self._available: dict[str, Path] = {}  # stem -> path
        self._cursor_surface: pygame.Surface | None = None
        self._cursor_name: str = ""
        # Hotspot offset from top-left of the rendered cursor surface
        self._hotspot: tuple[int, int] = (0, 0)
        self._particles: _WandParticles | _ArrowFlame | _SwordDrip | None = None
        self._animations_enabled: bool = animations_enabled
        self._last_tick: int = pygame.time.get_ticks()

        self._scan_folder()

        if not self._available:
            return  # No custom cursors found; system cursor stays

        self._select_cursor(setting_value)

    # ------------------------------------------------------------------
    # Animation toggle
    # ------------------------------------------------------------------

    @property
    def animations_enabled(self) -> bool:
        return self._animations_enabled

    @animations_enabled.setter
    def animations_enabled(self, value: bool) -> None:
        self._animations_enabled = value
        if not value and self._particles is not None:
            self._particles.clear()

    # ------------------------------------------------------------------
    # Scanning & selection
    # ------------------------------------------------------------------

    def _scan_folder(self) -> None:
        """Discover cursor images in the assets folder."""
        if not _CURSOR_DIR.is_dir():
            return
        for f in sorted(_CURSOR_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
                self._available[f.stem.lower()] = f

    def _select_cursor(self, setting_value: str) -> None:
        """Choose and load a cursor based on the setting."""
        key = setting_value.strip().lower()

        if key == "random":
            chosen_stem = random.choice(list(self._available.keys()))
        elif key in self._available:
            chosen_stem = key
        else:
            # Setting names an unknown cursor — fall back to random
            chosen_stem = random.choice(list(self._available.keys()))

        self._cursor_name = chosen_stem
        self._load_cursor(self._available[chosen_stem])

        # Each cursor gets its own particle effect
        _particle_factories: dict[str, type] = {
            "wand": _WandParticles,
            "arrow": _ArrowFlame,
            "sword": _SwordDrip,
        }
        factory = _particle_factories.get(chosen_stem)
        self._particles = factory() if factory is not None else None

        # Hide system cursor
        pygame.mouse.set_visible(False)

    def _load_cursor(self, path: Path) -> None:
        """Load and scale the cursor image."""
        try:
            raw = pygame.image.load(str(path)).convert_alpha()
        except (pygame.error, FileNotFoundError, OSError):
            return

        # Scale to fixed height, preserving aspect ratio
        orig_w, orig_h = raw.get_size()
        scale = _CURSOR_HEIGHT / orig_h
        new_w = max(1, int(orig_w * scale))
        new_h = _CURSOR_HEIGHT

        self._cursor_surface = pygame.transform.smoothscale(raw, (new_w, new_h))

        # Hotspot: the "active point" of the cursor.
        # Sword: tip is at top-left corner.
        # Wand: tip is at top-left corner.
        # Default assumption: top-left (0, 0).
        self._hotspot = (0, 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_cursor(self) -> bool:
        """Whether a custom cursor image was loaded successfully."""
        return self._cursor_surface is not None

    @property
    def cursor_name(self) -> str:
        """The stem name of the active cursor (e.g. 'sword', 'wand')."""
        return self._cursor_name

    @property
    def available_cursors(self) -> list[str]:
        """List of cursor stem names found in the folder, sorted."""
        return sorted(self._available.keys())

    def update(self) -> None:
        """Advance particle effects (call once per frame from App)."""
        now = pygame.time.get_ticks()
        dt = (now - self._last_tick) / 1000.0
        self._last_tick = now

        if self._particles is None or not self._animations_enabled:
            return

        mx, my = pygame.mouse.get_pos()
        # The tip is at the hotspot (top-left of cursor image)
        tip_x = float(mx - self._hotspot[0])
        tip_y = float(my - self._hotspot[1])
        self._particles.update(dt, tip_x, tip_y)

    def render(self, surface: pygame.Surface) -> None:
        """Draw the custom cursor and any particle effects.

        Call this as the **very last** draw operation in the frame,
        so the cursor is always on top.
        """
        if self._cursor_surface is None:
            return

        mx, my = pygame.mouse.get_pos()

        # Particles render behind the cursor
        if self._particles is not None and self._animations_enabled:
            self._particles.render(surface)

        # Draw cursor image with hotspot offset
        surface.blit(
            self._cursor_surface,
            (mx - self._hotspot[0], my - self._hotspot[1]),
        )

    def change_cursor(self, setting_value: str) -> None:
        """Switch to a different cursor (called when settings change).

        If *setting_value* is ``"Random"``, a new random cursor is chosen.
        """
        if not self._available:
            return

        # Clear any existing particles
        if self._particles is not None:
            self._particles.clear()
            self._particles = None

        self._select_cursor(setting_value)

    def restore_system_cursor(self) -> None:
        """Re-show the system cursor (call on shutdown)."""
        pygame.mouse.set_visible(True)
