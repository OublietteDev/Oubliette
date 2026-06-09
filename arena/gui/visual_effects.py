"""Programmatic visual effects for combat (code-drawn, not PNG frames).

Provides expanding rings for AoE blasts, zone creation pulses, zone shimmer/flash,
and spawn glow effects for summons and Wild Shape.  All effects are lightweight
Pygame draw calls that integrate with the camera/zoom system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

# ---------------------------------------------------------------------------
# Damage-type colour palette
# ---------------------------------------------------------------------------

DAMAGE_TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "fire": (255, 100, 30),
    "cold": (80, 160, 255),
    "lightning": (200, 200, 60),
    "thunder": (160, 140, 200),
    "acid": (100, 200, 50),
    "poison": (80, 180, 80),
    "necrotic": (100, 40, 120),
    "radiant": (255, 230, 140),
    "force": (180, 120, 255),
    "psychic": (200, 100, 200),
    "bludgeoning": (180, 160, 140),
    "piercing": (180, 160, 140),
    "slashing": (180, 160, 140),
}

_DEFAULT_COLOR = (200, 200, 200)


def get_damage_color(damage_type: str) -> tuple[int, int, int]:
    """Return an RGB colour for *damage_type*, with a neutral fallback."""
    return DAMAGE_TYPE_COLORS.get(damage_type, _DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ease_out_quad(t: float) -> float:
    """Quadratic ease-out: fast start, slow finish."""
    return 1.0 - (1.0 - t) ** 2


# ---------------------------------------------------------------------------
# AoE Blast Effect  (Fireball, Shatter, etc.)
# ---------------------------------------------------------------------------

@dataclass
class AoEBlastEffect:
    """Expanding ring/circle for AoE spell impacts."""

    center_wx: float
    center_wy: float
    radius_feet: float
    color: tuple[int, int, int]
    spawn_time: int  # pygame.time.get_ticks()
    duration_ms: int = 700

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms

    def render(self, surface: pygame.Surface, camera, origin: tuple[int, int], hex_size: int) -> None:
        now = pygame.time.get_ticks()
        elapsed = now - self.spawn_time
        if elapsed < 0 or elapsed >= self.duration_ms:
            return

        t = elapsed / self.duration_ms

        # Max pixel radius — each hex ≈ 5 ft
        max_radius_px = (self.radius_feet / 5.0) * hex_size * camera.zoom
        current_radius = max(1.0, max_radius_px * _ease_out_quad(t))

        alpha = int(180 * (1.0 - t))
        if alpha <= 0:
            return

        # Screen position
        sx, sy = camera.world_to_screen(self.center_wx, self.center_wy)
        cx = int(sx + origin[0])
        cy = int(sy + origin[1])

        # Temporary surface for transparency
        diameter = int(current_radius * 2) + 4
        if diameter < 4:
            return
        temp = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = (diameter // 2, diameter // 2)
        radius_int = max(1, int(current_radius))

        # Translucent fill (inner glow)
        fill_alpha = max(0, alpha // 3)
        pygame.draw.circle(temp, (*self.color, fill_alpha), center, radius_int)

        # Brighter ring outline
        ring_width = max(2, int(3 * camera.zoom))
        pygame.draw.circle(temp, (*self.color, alpha), center, radius_int, ring_width)

        surface.blit(temp, (cx - diameter // 2, cy - diameter // 2))


# ---------------------------------------------------------------------------
# Zone Creation Pulse
# ---------------------------------------------------------------------------

@dataclass
class ZoneCreationPulse:
    """Expanding glow when a persistent AoE zone first appears."""

    center_wx: float
    center_wy: float
    radius_feet: float
    color: tuple[int, int, int]
    spawn_time: int
    duration_ms: int = 800

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms

    def render(self, surface: pygame.Surface, camera, origin: tuple[int, int], hex_size: int) -> None:
        now = pygame.time.get_ticks()
        elapsed = now - self.spawn_time
        if elapsed < 0 or elapsed >= self.duration_ms:
            return

        t = elapsed / self.duration_ms

        max_radius_px = (self.radius_feet / 5.0) * hex_size * camera.zoom
        current_radius = max(1.0, max_radius_px * _ease_out_quad(t))

        # Stronger fill than AoE blast for a "glow from center" feel
        alpha = int(200 * (1.0 - t))
        if alpha <= 0:
            return

        sx, sy = camera.world_to_screen(self.center_wx, self.center_wy)
        cx = int(sx + origin[0])
        cy = int(sy + origin[1])

        diameter = int(current_radius * 2) + 4
        if diameter < 4:
            return
        temp = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = (diameter // 2, diameter // 2)
        radius_int = max(1, int(current_radius))

        # Stronger fill
        fill_alpha = max(0, alpha // 2)
        pygame.draw.circle(temp, (*self.color, fill_alpha), center, radius_int)

        # Ring outline
        ring_width = max(2, int(3 * camera.zoom))
        pygame.draw.circle(temp, (*self.color, alpha), center, radius_int, ring_width)

        surface.blit(temp, (cx - diameter // 2, cy - diameter // 2))


# ---------------------------------------------------------------------------
# Zone Shimmer State  (persistent, not one-shot)
# ---------------------------------------------------------------------------

@dataclass
class ZoneShimmerState:
    """Per-zone state for the persistent alpha shimmer animation."""

    zone_id: str
    phase_offset: float = 0.0  # random offset so zones don't pulse in sync


_SHIMMER_PERIOD_MS = 2000.0  # 2-second cycle
_SHIMMER_MIN_ALPHA = 50
_SHIMMER_MAX_ALPHA = 100


def get_zone_shimmer_alpha(
    zone_id: str,
    now: int,
    shimmer_states: dict[str, ZoneShimmerState],
) -> int:
    """Return the current alpha (50-100) for a zone's shimmer cycle."""
    state = shimmer_states.get(zone_id)
    if state is None:
        return 80  # fallback to previous static value

    t = ((now / _SHIMMER_PERIOD_MS) + state.phase_offset) % 1.0
    wave = 0.5 + 0.5 * math.sin(t * 2.0 * math.pi)
    return int(_SHIMMER_MIN_ALPHA + (_SHIMMER_MAX_ALPHA - _SHIMMER_MIN_ALPHA) * wave)


# ---------------------------------------------------------------------------
# Zone Damage Flash  (one-shot, modifies zone render alpha)
# ---------------------------------------------------------------------------

@dataclass
class ZoneDamageFlash:
    """Brief colour intensification when a zone deals damage."""

    zone_id: str
    spawn_time: int
    duration_ms: int = 400

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms


def get_zone_flash_boost(
    zone_id: str,
    now: int,
    active_flashes: list[ZoneDamageFlash],
) -> int:
    """Return additional alpha boost (0-100) if a damage flash is active."""
    for flash in active_flashes:
        if flash.zone_id != zone_id:
            continue
        elapsed = now - flash.spawn_time
        if 0 <= elapsed < flash.duration_ms:
            t = elapsed / flash.duration_ms
            return int(100 * (1.0 - t))
    return 0


# ---------------------------------------------------------------------------
# Spawn Effect  (summon / Wild Shape)
# ---------------------------------------------------------------------------

@dataclass
class SpawnEffect:
    """Glowing ring effect for summoning or Wild Shape."""

    center_wx: float
    center_wy: float
    color: tuple[int, int, int]
    spawn_time: int
    duration_ms: int = 800
    is_wild_shape: bool = False

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms

    def render(self, surface: pygame.Surface, camera, origin: tuple[int, int], hex_size: int) -> None:
        now = pygame.time.get_ticks()
        elapsed = now - self.spawn_time
        if elapsed < 0 or elapsed >= self.duration_ms:
            return

        t = elapsed / self.duration_ms

        base_radius = hex_size * camera.zoom

        # Inner ring: starts small, expands to 1.5x
        inner_radius = max(1.0, base_radius * (0.3 + 1.2 * t))
        # Outer ring: expands faster
        outer_radius = max(1.0, base_radius * (0.3 + 1.5 * t))

        # Alpha: sine arch — fades in, peaks at t=0.5, fades out
        alpha = int(200 * math.sin(t * math.pi))
        if alpha <= 0:
            return

        sx, sy = camera.world_to_screen(self.center_wx, self.center_wy)
        cx = int(sx + origin[0])
        cy = int(sy + origin[1])

        diameter = int(outer_radius * 2) + 8
        if diameter < 4:
            return
        temp = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = (diameter // 2, diameter // 2)

        ring_width = max(2, int(3 * camera.zoom))

        # Inner bright ring
        pygame.draw.circle(
            temp, (*self.color, alpha),
            center, max(1, int(inner_radius)), ring_width,
        )

        # Outer dimmer ring
        outer_alpha = max(0, alpha // 2)
        pygame.draw.circle(
            temp, (*self.color, outer_alpha),
            center, max(1, int(outer_radius)), max(1, ring_width // 2),
        )

        # Wild Shape pillar effect
        if self.is_wild_shape:
            pillar_h = int(2 * base_radius)
            pillar_w = max(2, int(base_radius * 0.3))
            pillar_alpha = max(0, alpha * 2 // 3)
            pillar_rect = pygame.Rect(
                center[0] - pillar_w // 2,
                center[1] - pillar_h // 2,
                pillar_w,
                pillar_h,
            )
            pillar_surf = pygame.Surface((pillar_w, pillar_h), pygame.SRCALPHA)
            pillar_surf.fill((*self.color, pillar_alpha))
            temp.blit(pillar_surf, pillar_rect.topleft)

        surface.blit(temp, (cx - diameter // 2, cy - diameter // 2))


# ---------------------------------------------------------------------------
# Teleport Effect  (Misty Step, Dimension Door, etc.)
# ---------------------------------------------------------------------------

@dataclass
class TeleportEffect:
    """Vanish-at-origin, appear-at-destination effect.

    Renders a contracting ring at the origin (fade-out) and an
    expanding ring at the destination (fade-in), both in arcane
    cyan-blue.
    """

    origin_wx: float
    origin_wy: float
    dest_wx: float
    dest_wy: float
    color: tuple[int, int, int] = (100, 180, 255)  # arcane cyan-blue
    spawn_time: int = 0
    duration_ms: int = 600

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms

    def render(self, surface: pygame.Surface, camera, origin: tuple[int, int], hex_size: int) -> None:
        now = pygame.time.get_ticks()
        elapsed = now - self.spawn_time
        if elapsed < 0 or elapsed >= self.duration_ms:
            return

        t = elapsed / self.duration_ms
        base_radius = hex_size * camera.zoom

        # Alpha: sine arch
        alpha = int(220 * math.sin(t * math.pi))
        if alpha <= 0:
            return

        ring_width = max(2, int(3 * camera.zoom))

        # ── Origin: contracting ring (disappearing) ──────────────
        origin_radius = max(1.0, base_radius * (1.2 * (1.0 - t)))
        sx, sy = camera.world_to_screen(self.origin_wx, self.origin_wy)
        ocx = int(sx + origin[0])
        ocy = int(sy + origin[1])

        diam = int(origin_radius * 2) + 4
        if diam >= 4:
            temp = pygame.Surface((diam, diam), pygame.SRCALPHA)
            center = (diam // 2, diam // 2)
            r = max(1, int(origin_radius))
            # Translucent fill
            fill_alpha = max(0, alpha // 4)
            pygame.draw.circle(temp, (*self.color, fill_alpha), center, r)
            # Bright ring
            pygame.draw.circle(temp, (*self.color, alpha), center, r, ring_width)
            surface.blit(temp, (ocx - diam // 2, ocy - diam // 2))

        # ── Destination: expanding ring (appearing) ──────────────
        dest_radius = max(1.0, base_radius * (0.2 + 1.0 * _ease_out_quad(t)))
        sx2, sy2 = camera.world_to_screen(self.dest_wx, self.dest_wy)
        dcx = int(sx2 + origin[0])
        dcy = int(sy2 + origin[1])

        diam2 = int(dest_radius * 2) + 4
        if diam2 >= 4:
            temp2 = pygame.Surface((diam2, diam2), pygame.SRCALPHA)
            center2 = (diam2 // 2, diam2 // 2)
            r2 = max(1, int(dest_radius))
            fill_alpha2 = max(0, alpha // 3)
            pygame.draw.circle(temp2, (*self.color, fill_alpha2), center2, r2)
            pygame.draw.circle(temp2, (*self.color, alpha), center2, r2, ring_width)
            surface.blit(temp2, (dcx - diam2 // 2, dcy - diam2 // 2))


# ---------------------------------------------------------------------------
# Forced Movement Effect  (Push, Pull, Slide)
# ---------------------------------------------------------------------------

# Colour palette for forced movement directions
_FM_COLORS: dict[str, tuple[int, int, int]] = {
    "push": (255, 140, 60),    # orange — kinetic force
    "pull": (100, 160, 255),   # blue — magnetic pull
    "slide": (100, 255, 160),  # green — tactical slide
}


@dataclass
class ForcedMovementEffect:
    """Sliding circle from origin to destination for push/pull/slide.

    Renders a moving circle that travels from origin_wx/wy to dest_wx/wy
    over the duration, with a fading trail behind it.
    """

    origin_wx: float
    origin_wy: float
    dest_wx: float
    dest_wy: float
    color: tuple[int, int, int] = (255, 140, 60)
    spawn_time: int = 0
    duration_ms: int = 500

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms

    def render(self, surface: pygame.Surface, camera, origin: tuple[int, int], hex_size: int) -> None:
        now = pygame.time.get_ticks()
        elapsed = now - self.spawn_time
        if elapsed < 0 or elapsed >= self.duration_ms:
            return

        t = elapsed / self.duration_ms

        # Position: lerp from origin to destination with ease-out
        ease_t = _ease_out_quad(t)
        wx = self.origin_wx + (self.dest_wx - self.origin_wx) * ease_t
        wy = self.origin_wy + (self.dest_wy - self.origin_wy) * ease_t

        sx, sy = camera.world_to_screen(wx, wy)
        cx = int(sx + origin[0])
        cy = int(sy + origin[1])

        # Alpha: sine arch — fades in, peaks at 0.5, fades out
        alpha = int(220 * math.sin(t * math.pi))
        if alpha <= 0:
            return

        base_radius = hex_size * camera.zoom * 0.4
        radius = max(2, int(base_radius))
        ring_width = max(2, int(3 * camera.zoom))

        diameter = radius * 2 + 6
        temp = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = (diameter // 2, diameter // 2)

        # Filled glow
        fill_alpha = max(0, alpha // 2)
        pygame.draw.circle(temp, (*self.color, fill_alpha), center, radius)

        # Bright ring
        pygame.draw.circle(temp, (*self.color, alpha), center, radius, ring_width)

        surface.blit(temp, (cx - diameter // 2, cy - diameter // 2))

        # Trail: dimmer circle at a trailing position
        trail_t = max(0.0, ease_t - 0.15)
        trail_wx = self.origin_wx + (self.dest_wx - self.origin_wx) * trail_t
        trail_wy = self.origin_wy + (self.dest_wy - self.origin_wy) * trail_t
        tsx, tsy = camera.world_to_screen(trail_wx, trail_wy)
        tcx = int(tsx + origin[0])
        tcy = int(tsy + origin[1])

        trail_alpha = max(0, alpha // 3)
        trail_radius = max(1, int(base_radius * 0.6))
        trail_diam = trail_radius * 2 + 4
        trail_temp = pygame.Surface((trail_diam, trail_diam), pygame.SRCALPHA)
        trail_center = (trail_diam // 2, trail_diam // 2)
        pygame.draw.circle(trail_temp, (*self.color, trail_alpha), trail_center, trail_radius)
        surface.blit(trail_temp, (tcx - trail_diam // 2, tcy - trail_diam // 2))


# ---------------------------------------------------------------------------
# Terrain modification effect
# ---------------------------------------------------------------------------

TERRAIN_MOD_COLORS: dict[str, tuple[int, int, int]] = {
    "wall": (160, 155, 145),
    "difficult": (80, 160, 60),
    "normal": (200, 200, 200),
    "pit": (60, 40, 30),
    "hazard": (200, 60, 30),
    "water": (60, 120, 200),
    "cover_half": (140, 140, 120),
    "cover_three_quarters": (120, 120, 110),
    "cover_full": (100, 100, 90),
}


@dataclass
class TerrainModificationEffect:
    """Expanding pulse for terrain-altering spells.

    Similar to ZoneCreationPulse but with higher opacity and sharper
    outer ring for a crystallisation/growth feel.
    """

    center_wx: float
    center_wy: float
    radius_feet: float
    color: tuple[int, int, int]
    spawn_time: int
    duration_ms: int = 600

    def is_expired(self, now: int) -> bool:
        return (now - self.spawn_time) >= self.duration_ms

    def render(
        self,
        surface: pygame.Surface,
        camera,
        origin: tuple[int, int],
        hex_size: int,
    ) -> None:
        now = pygame.time.get_ticks()
        elapsed = now - self.spawn_time
        if elapsed < 0 or elapsed >= self.duration_ms:
            return

        t = elapsed / self.duration_ms

        # Max radius in pixels
        if self.radius_feet > 0:
            max_radius_px = max(1.0, (self.radius_feet / 5.0) * hex_size * camera.zoom)
        else:
            max_radius_px = hex_size * camera.zoom * 0.8

        current_radius = max(1.0, max_radius_px * _ease_out_quad(t))
        alpha = int(220 * (1.0 - t))
        if alpha <= 0:
            return

        sx, sy = camera.world_to_screen(self.center_wx, self.center_wy)
        cx = int(sx + origin[0])
        cy = int(sy + origin[1])

        radius_int = max(1, int(current_radius))
        diameter = radius_int * 2 + 4
        if diameter < 4:
            return
        temp = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = (diameter // 2, diameter // 2)

        # Strong fill
        fill_alpha = max(0, alpha * 2 // 3)
        pygame.draw.circle(temp, (*self.color, fill_alpha), center, radius_int)

        # Sharp outer ring
        ring_width = max(2, int(4 * camera.zoom))
        pygame.draw.circle(temp, (*self.color, alpha), center, radius_int, ring_width)

        surface.blit(temp, (cx - diameter // 2, cy - diameter // 2))


# ---------------------------------------------------------------------------
# Convenience render function
# ---------------------------------------------------------------------------

# Type alias for the mixed effect list
VisualEffect = (
    AoEBlastEffect
    | ZoneCreationPulse
    | SpawnEffect
    | TeleportEffect
    | ForcedMovementEffect
    | TerrainModificationEffect
)


def render_visual_effects(
    effects: list[VisualEffect],
    surface: pygame.Surface,
    camera,
    origin: tuple[int, int],
    hex_size: int,
) -> list[VisualEffect]:
    """Render all active effects and return only the still-alive ones."""
    now = pygame.time.get_ticks()
    alive: list[VisualEffect] = []
    for fx in effects:
        if not fx.is_expired(now):
            fx.render(surface, camera, origin, hex_size)
            alive.append(fx)
    return alive
