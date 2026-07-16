"""Token rendering for creatures on the hex grid."""

import math

import pygame

from arena.grid.coordinates import HexCoord
from arena.grid.footprint import (
    get_footprint_center_pixel,
    get_footprint_hex_count,
    get_occupied_hexes,
)
from arena.gui.camera import Camera
from arena.gui.renderer import get_font, hex_vertices
from arena.gui.token_cache import get_token_image
from arena.combat.manager import Combatant
from arena.util.constants import (
    COLORS,
    CONDITION_DISPLAY,
    parse_color,
)
from arena.util.settings import get_settings


# ---------------------------------------------------------------------------
# Merged hex boundary computation
# ---------------------------------------------------------------------------


def _hex_vertices_world(
    cx: float, cy: float, size: float,
) -> list[tuple[float, float]]:
    """Compute hex vertices in world space (matches hex_vertices but without zoom)."""
    vertices = []
    for i in range(6):
        angle_rad = math.pi / 180 * (60 * i)
        vx = cx + size * math.cos(angle_rad)
        vy = cy + size * math.sin(angle_rad)
        vertices.append((vx, vy))
    return vertices


def _compute_merged_boundary(
    hexes: list[HexCoord],
    hex_size: float,
    camera: Camera,
    origin: tuple[int, int],
) -> list[tuple[float, float]]:
    """Compute the outer boundary polygon of a cluster of hexes.

    For each hex in the cluster, examine its 6 edges.  An edge is
    *internal* if the neighbouring hex on that side is also in the
    cluster — skip those.  Collect all external edges, then walk
    them in order to produce a closed polygon.

    Computation is done in **world space** to avoid camera-dependent
    floating-point drift, then transformed to screen space at the end.

    Uses union-find to merge vertices that are within a small tolerance
    (needed because even-q hex layout computes shared vertices from
    different hex centers, introducing sub-pixel floating-point drift).

    Returns screen-space vertices.
    """
    occ_set = set((h.q, h.r) for h in hexes)

    # Collect external edges as (vertex_a, vertex_b) in world coords.
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []

    for h in hexes:
        wx, wy = h.to_pixel(hex_size)
        verts = _hex_vertices_world(wx, wy, hex_size)

        nbrs = h.neighbors()

        for i in range(6):
            v_a = verts[i]
            v_b = verts[(i + 1) % 6]
            mid_x = (v_a[0] + v_b[0]) / 2
            mid_y = (v_a[1] + v_b[1]) / 2

            dx = mid_x - wx
            dy = mid_y - wy
            best_nbr = None
            best_dot = -1e9
            norm = math.hypot(dx, dy) or 1.0
            ndx, ndy = dx / norm, dy / norm
            for nbr in nbrs:
                nwx, nwy = nbr.to_pixel(hex_size)
                d2x, d2y = nwx - wx, nwy - wy
                n2 = math.hypot(d2x, d2y) or 1.0
                dot = (d2x / n2) * ndx + (d2y / n2) * ndy
                if dot > best_dot:
                    best_dot = dot
                    best_nbr = nbr

            if best_nbr and (best_nbr.q, best_nbr.r) in occ_set:
                continue  # Internal edge — skip

            edges.append((v_a, v_b))

    if not edges:
        return []

    # Merge vertices within tolerance using union-find.
    # Even-q hex layout causes shared vertices computed from different
    # hex centers to differ by up to ~0.7 pixels at zoom 1.0.
    _VERTEX_TOLERANCE = 1.0

    all_pts = []
    for a, b in edges:
        all_pts.append(a)
        all_pts.append(b)

    parent = list(range(len(all_pts)))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: int, y: int) -> None:
        rx, ry = _find(x), _find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(len(all_pts)):
        for j in range(i + 1, len(all_pts)):
            if math.hypot(
                all_pts[i][0] - all_pts[j][0],
                all_pts[i][1] - all_pts[j][1],
            ) < _VERTEX_TOLERANCE:
                _union(i, j)

    # Build canonical position for each group (average)
    groups: dict[int, list[int]] = {}
    for i in range(len(all_pts)):
        groups.setdefault(_find(i), []).append(i)

    canonical: dict[int, tuple[float, float]] = {}
    for root, members in groups.items():
        avg_x = sum(all_pts[m][0] for m in members) / len(members)
        avg_y = sum(all_pts[m][1] for m in members) / len(members)
        key = (round(avg_x, 2), round(avg_y, 2))
        for m in members:
            canonical[m] = key

    # Remap edges to canonical vertices
    remapped: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for idx in range(len(edges)):
        remapped.append((canonical[idx * 2], canonical[idx * 2 + 1]))

    # Build adjacency and walk the boundary using angle-based ordering
    # to ensure consistent traversal direction.
    adj: dict[tuple[float, float], list[tuple[tuple[float, float], int]]] = {}
    for idx, (a, b) in enumerate(remapped):
        adj.setdefault(a, []).append((b, idx))
        adj.setdefault(b, []).append((a, idx))

    used = [False] * len(remapped)
    polygon: list[tuple[float, float]] = []
    start_key = remapped[0][0]
    current_key = remapped[0][1]
    polygon.append(start_key)
    polygon.append(current_key)
    used[0] = True

    for _ in range(len(remapped)):
        if current_key == start_key:
            break

        # Compute the incoming direction so we can pick the next edge
        # that turns the least (consistent winding order).
        prev_key = polygon[-2]
        in_dx = current_key[0] - prev_key[0]
        in_dy = current_key[1] - prev_key[1]
        in_angle = math.atan2(in_dy, in_dx)

        best_next = None
        best_idx = -1
        best_turn = float('inf')

        for next_key, idx in adj.get(current_key, []):
            if used[idx]:
                continue
            nxt = remapped[idx][1] if remapped[idx][0] == current_key else remapped[idx][0]
            out_dx = nxt[0] - current_key[0]
            out_dy = nxt[1] - current_key[1]
            out_angle = math.atan2(out_dy, out_dx)
            # Signed turn angle: positive = left turn, negative = right turn
            turn = out_angle - in_angle
            # Normalise to (-pi, pi]
            while turn > math.pi:
                turn -= 2 * math.pi
            while turn <= -math.pi:
                turn += 2 * math.pi
            # We want the smallest left turn (most clockwise unused edge).
            # Using the negative turn as priority picks the rightmost turn.
            if -turn < best_turn:
                best_turn = -turn
                best_next = nxt
                best_idx = idx

        if best_next is None:
            break

        used[best_idx] = True
        polygon.append(best_next)
        current_key = best_next

    # Transform world-space polygon to screen space
    screen_polygon: list[tuple[float, float]] = []
    for wx, wy in polygon:
        sx, sy = camera.world_to_screen(wx, wy)
        screen_polygon.append((sx + origin[0], sy + origin[1]))

    return screen_polygon


# ---------------------------------------------------------------------------
# Main draw function
# ---------------------------------------------------------------------------


def draw_token(
    surface: pygame.Surface,
    combatant: Combatant,
    camera: Camera,
    is_selected: bool = False,
    is_active_turn: bool = False,
    origin: tuple[int, int] = (0, 0),
    pixel_override: tuple[float, float] | None = None,
    display_hp_pct: float | None = None,
    flash_alpha: int = 0,
    appear_conscious: bool = False,
) -> None:
    """Draw a creature token on the hex grid.

    For single-hex creatures, renders a circle (or custom image).
    For multi-hex creatures, renders a merged polygon spanning all
    occupied hexes.

    Args:
        surface: Pygame surface to draw on.
        combatant: The combatant to draw.
        camera: Camera for world-to-screen conversion.
        is_selected: Whether this token is currently selected.
        is_active_turn: Whether it is this creature's turn.
        origin: (x, y) offset for the grid view area on the screen.
        pixel_override: Optional (world_x, world_y) to use instead of
            the combatant's grid position. Used for move animations.
        display_hp_pct: Optional animated HP percentage (0.0-1.0) for
            smooth HP bar transitions. Uses actual HP if None.
        flash_alpha: Red damage flash intensity (0-255). 0 = no flash.
        appear_conscious: Suppress the unconscious dim overlay. Used by
            animation sequencing so a creature doesn't slump before the
            blow that downed it visually lands.
    """
    if combatant.position is None:
        return

    creature = combatant.creature
    settings = get_settings()
    hex_size = settings.display.default_hex_size
    size = creature.size
    multi = get_footprint_hex_count(size) > 1

    # Single-hex creatures always use circle rendering
    if not multi:
        _draw_single_hex_token(
            surface, combatant, camera, is_selected, is_active_turn,
            origin, pixel_override, display_hp_pct, flash_alpha,
            appear_conscious,
        )
        return

    # --- Multi-hex rendering ---
    hexes = get_occupied_hexes(combatant.position, size)
    center_wx, center_wy = get_footprint_center_pixel(
        combatant.position, size, hex_size
    )
    clx, cly = camera.world_to_screen(center_wx, center_wy)
    center = (int(clx) + origin[0], int(cly) + origin[1])

    # Animation offset: when pixel_override is set (movement animation),
    # compute the screen-space delta between the animated centroid and
    # the rest centroid, then shift the entire polygon by that amount.
    anim_dx, anim_dy = 0.0, 0.0
    if pixel_override is not None:
        anim_wx, anim_wy = pixel_override  # animated centroid in world space
        anim_sx, anim_sy = camera.world_to_screen(anim_wx, anim_wy)
        anim_dx = anim_sx - clx
        anim_dy = anim_sy - cly
        center = (int(clx + anim_dx) + origin[0], int(cly + anim_dy) + origin[1])

    # Effective "radius" for HP bar / condition sizing (scaled to footprint)
    radius = int(settings.display.token_radius * camera.zoom)
    scaled_hex = hex_size * camera.zoom
    if radius < 3 or scaled_hex < 3:
        return

    # Compute merged polygon
    polygon = _compute_merged_boundary(hexes, hex_size, camera, origin)
    if len(polygon) < 3:
        return

    # Apply animation offset to the polygon
    if anim_dx != 0.0 or anim_dy != 0.0:
        polygon = [(p[0] + anim_dx, p[1] + anim_dy) for p in polygon]

    int_polygon = [(int(p[0]), int(p[1])) for p in polygon]

    # Team color
    team_color_key = f"team_{combatant.team}"
    team_color = parse_color(COLORS.get(team_color_key, COLORS["team_neutral"]))
    body_color = _body_color(creature, team_color)

    # Active turn glow (per-creature phase so the pulse doesn't visibly
    # "reset" to the same brightness every time the turn passes)
    if is_active_turn:
        pulse_t = math.sin(
            pygame.time.get_ticks() / 1500.0 * math.tau
            + _glow_phase(creature.name)
        )
        pulse_01 = (pulse_t + 1.0) / 2.0
        glow_alpha = int(100 + 155 * pulse_01)
        # Draw a slightly inflated polygon outline
        glow_color = (255, 255, 100, glow_alpha)
        _draw_polygon_outline_alpha(surface, int_polygon, glow_color, width=3)

    # Selection ring
    if is_selected:
        pygame.draw.polygon(
            surface, parse_color(COLORS["token_outline"]), int_polygon, 2
        )

    # Body fill + optional token image clipped to polygon
    token_img = None
    if creature.token_image:
        min_x = min(p[0] for p in int_polygon)
        min_y = min(p[1] for p in int_polygon)
        max_x = max(p[0] for p in int_polygon)
        max_y = max(p[1] for p in int_polygon)
        poly_w = max_x - min_x
        poly_h = max_y - min_y
        if poly_w > 0 and poly_h > 0:
            token_img = _get_polygon_token_image(
                creature.token_image, poly_w, poly_h,
                int_polygon, min_x, min_y,
                creature.token_zoom, creature.token_offset_x,
                creature.token_offset_y,
            )

    if token_img is not None:
        min_x = min(p[0] for p in int_polygon)
        min_y = min(p[1] for p in int_polygon)
        surface.blit(token_img, (min_x, min_y))
    else:
        pygame.draw.polygon(surface, body_color, int_polygon)
        # Initials at centroid (only when no image)
        if radius >= 8:
            initials = _get_initials(creature.name)
            font_size = max(10, int(14 * camera.zoom))
            font = get_font(font_size)
            text_surf = font.render(
                initials, True, parse_color(COLORS["text_primary"])
            )
            text_rect = text_surf.get_rect(center=center)
            surface.blit(text_surf, text_rect)

    # Damage flash overlay
    if flash_alpha > 0:
        _draw_polygon_alpha(surface, int_polygon, (255, 40, 40, flash_alpha))

    # Team color ring (outline)
    pygame.draw.polygon(surface, team_color, int_polygon, 2)

    # HP bar below the lowest point of the polygon
    if radius >= 6:
        max_y = max(p[1] for p in int_polygon)
        min_x = min(p[0] for p in int_polygon)
        max_x = max(p[0] for p in int_polygon)
        bar_half_w = (max_x - min_x) // 2
        bar_cx = (min_x + max_x) // 2
        # _draw_hp_bar places the bar at center.y + radius + 2, so
        # set center.y so the bar sits just below the polygon bottom.
        bar_center = (bar_cx, max_y - bar_half_w)
        _draw_hp_bar(surface, bar_center, bar_half_w, creature, display_hp_pct,
                     show_number=True)

    # Condition icons above the highest point
    if radius >= 6 and creature.active_conditions:
        min_y = min(p[1] for p in int_polygon)
        min_x_top = min(p[0] for p in int_polygon)
        max_x_top = max(p[0] for p in int_polygon)
        icon_half_w = (max_x_top - min_x_top) // 2
        # _draw_condition_icons places icons at center.y - radius - ...,
        # so set center.y so they sit just above the polygon top.
        icon_center = ((min_x_top + max_x_top) // 2, min_y + icon_half_w)
        _draw_condition_icons(surface, icon_center, icon_half_w, creature, camera.zoom)

    # Dim overlay for unconscious creatures
    if not creature.is_conscious and not appear_conscious:
        _draw_polygon_alpha(surface, int_polygon, (0, 0, 0, 128))


def _draw_polygon_alpha(
    surface: pygame.Surface,
    polygon: list[tuple[int, int]],
    color: tuple[int, int, int, int],
) -> None:
    """Draw a filled polygon with alpha transparency."""
    if len(polygon) < 3:
        return
    min_x = min(p[0] for p in polygon)
    min_y = min(p[1] for p in polygon)
    max_x = max(p[0] for p in polygon)
    max_y = max(p[1] for p in polygon)
    w = max_x - min_x + 2
    h = max_y - min_y + 2
    if w <= 0 or h <= 0:
        return
    tmp = pygame.Surface((w, h), pygame.SRCALPHA)
    shifted = [(p[0] - min_x, p[1] - min_y) for p in polygon]
    pygame.draw.polygon(tmp, color, shifted)
    surface.blit(tmp, (min_x, min_y))


def _draw_polygon_outline_alpha(
    surface: pygame.Surface,
    polygon: list[tuple[int, int]],
    color: tuple[int, int, int, int],
    width: int = 2,
) -> None:
    """Draw a polygon outline with alpha transparency."""
    if len(polygon) < 3:
        return
    min_x = min(p[0] for p in polygon)
    min_y = min(p[1] for p in polygon)
    max_x = max(p[0] for p in polygon)
    max_y = max(p[1] for p in polygon)
    pad = width + 2
    w = max_x - min_x + pad * 2
    h = max_y - min_y + pad * 2
    if w <= 0 or h <= 0:
        return
    tmp = pygame.Surface((w, h), pygame.SRCALPHA)
    shifted = [(p[0] - min_x + pad, p[1] - min_y + pad) for p in polygon]
    pygame.draw.polygon(tmp, color, shifted, width)
    surface.blit(tmp, (min_x - pad, min_y - pad))


# ---------------------------------------------------------------------------
# Single-hex token (original rendering path)
# ---------------------------------------------------------------------------


def _decoy_image_count(creature) -> int:
    """Remaining Mirror Image duplicates on this creature (0 = none).

    The decoy buff's trigger charges ARE the images — combat code
    decrements them as attacks shatter duplicates, so the render count
    tracks the fight for free.
    """
    for buff in getattr(creature, "active_buffs", []):
        for mod in buff.modifiers:
            if mod.stat == "decoy_images":
                return max(0, buff.charges or 0)
    return 0


# Fanned offsets (in token radii) for up to three duplicates peeking
# out from behind the real token.
_GHOST_OFFSETS = [(-0.95, -0.40), (0.95, -0.40), (0.0, -1.05)]


def _draw_decoy_ghosts(
    surface: pygame.Surface,
    creature,
    center: tuple[int, int],
    radius: int,
    count: int,
    body_color: tuple[int, int, int] | None = None,
) -> None:
    """Draw translucent duplicate tokens behind the real one (Mirror Image)."""
    ghost_img = None
    if creature.token_image:
        img = get_token_image(creature.token_image, radius * 2,
                              creature.token_zoom, creature.token_offset_x,
                              creature.token_offset_y)
        if img is not None:
            ghost_img = img.copy()
            ghost_img.set_alpha(110)

    if body_color is None:
        body_color = parse_color(creature.token_color)
    for dx, dy in _GHOST_OFFSETS[:count]:
        gcx = int(center[0] + dx * radius)
        gcy = int(center[1] + dy * radius)
        if ghost_img is not None:
            rect = ghost_img.get_rect(center=(gcx, gcy))
            surface.blit(ghost_img, rect)
        else:
            ghost = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(
                ghost, (*body_color[:3], 110), (radius, radius), radius,
            )
            pygame.draw.circle(
                ghost, (255, 255, 255, 70), (radius, radius), radius, 2,
            )
            surface.blit(ghost, (gcx - radius, gcy - radius))


def _draw_single_hex_token(
    surface: pygame.Surface,
    combatant: Combatant,
    camera: Camera,
    is_selected: bool = False,
    is_active_turn: bool = False,
    origin: tuple[int, int] = (0, 0),
    pixel_override: tuple[float, float] | None = None,
    display_hp_pct: float | None = None,
    flash_alpha: int = 0,
    appear_conscious: bool = False,
) -> None:
    """Draw a single-hex creature token (circle or image)."""
    if combatant.position is None:
        return

    creature = combatant.creature
    settings = get_settings()
    if pixel_override is not None:
        wx, wy = pixel_override
    else:
        wx, wy = combatant.position.to_pixel(settings.display.default_hex_size)
    lx, ly = camera.world_to_screen(wx, wy)
    center = (int(lx) + origin[0], int(ly) + origin[1])
    radius = int(settings.display.token_radius * camera.zoom)

    if radius < 3:
        return

    team_color_key = f"team_{combatant.team}"
    team_color = parse_color(COLORS.get(team_color_key, COLORS["team_neutral"]))
    body_color = _body_color(creature, team_color)

    # Mirror Image duplicates (C4): translucent ghost copies fanned out
    # behind the real token, one per remaining image — they vanish as
    # attacks shatter them (the buff's charges count down).
    ghost_count = _decoy_image_count(creature)
    if ghost_count:
        _draw_decoy_ghosts(surface, creature, center, radius, ghost_count,
                           body_color)

    # Active turn glow (per-creature phase — see multi-hex note)
    if is_active_turn:
        pulse_t = math.sin(
            pygame.time.get_ticks() / 1500.0 * math.tau
            + _glow_phase(creature.name)
        )
        pulse_01 = (pulse_t + 1.0) / 2.0
        glow_alpha = int(100 + 155 * pulse_01)
        glow_extra = 3 + int(3 * pulse_01)
        glow_surf = pygame.Surface(
            ((radius + glow_extra + 2) * 2, (radius + glow_extra + 2) * 2),
            pygame.SRCALPHA,
        )
        glow_center = (radius + glow_extra + 2, radius + glow_extra + 2)
        pygame.draw.circle(
            glow_surf, (255, 255, 100, glow_alpha),
            glow_center, radius + glow_extra, 3,
        )
        surface.blit(
            glow_surf,
            (center[0] - glow_center[0], center[1] - glow_center[1]),
        )

    # Selection ring
    if is_selected:
        pygame.draw.circle(
            surface, parse_color(COLORS["token_outline"]), center, radius + 2, 2
        )

    # Token body
    token_img = None
    if creature.token_image:
        diameter = radius * 2
        token_img = get_token_image(creature.token_image, diameter,
                                    creature.token_zoom,
                                    creature.token_offset_x,
                                    creature.token_offset_y)

    if token_img is not None:
        img_rect = token_img.get_rect(center=center)
        surface.blit(token_img, img_rect)
    else:
        pygame.draw.circle(surface, body_color, center, radius)
        if radius >= 8:
            initials = _get_initials(creature.name)
            font_size = max(10, int(14 * camera.zoom))
            font = get_font(font_size)
            text_surf = font.render(
                initials, True, parse_color(COLORS["text_primary"])
            )
            text_rect = text_surf.get_rect(center=center)
            surface.blit(text_surf, text_rect)

    # Damage flash
    if flash_alpha > 0:
        flash_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(
            flash_surf, (255, 40, 40, flash_alpha), (radius, radius), radius
        )
        surface.blit(flash_surf, (center[0] - radius, center[1] - radius))

    # Team color ring
    pygame.draw.circle(surface, team_color, center, radius, 2)

    # HP bar
    if radius >= 6:
        _draw_hp_bar(surface, center, radius, creature, display_hp_pct)

    # Condition icons
    if radius >= 6 and creature.active_conditions:
        _draw_condition_icons(surface, center, radius, creature, camera.zoom)

    # Unconscious overlay
    if not creature.is_conscious and not appear_conscious:
        dim_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(dim_surf, (0, 0, 0, 128), (radius, radius), radius)
        surface.blit(dim_surf, (center[0] - radius, center[1] - radius))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Cache for polygon-clipped token images.
# Key: (resolved_path, width, height, zoom, pan_x, pan_y) -> Surface or None.
_polygon_token_cache: dict[
    tuple[str, int, int, float, float, float], pygame.Surface | None
] = {}


def _get_polygon_token_image(
    image_path: str,
    width: int,
    height: int,
    polygon: list[tuple[int, int]],
    offset_x: int,
    offset_y: int,
    zoom: float = 1.0,
    pan_x: float = 0.0,
    pan_y: float = 0.0,
) -> pygame.Surface | None:
    """Load, scale, and clip a token image to a polygon boundary.

    The image FILLS the polygon's bounding box (cover — the short sides
    crop, matching the single-hex circle and the bestiary card) times any
    authored zoom, centered plus the authored pan, over an opaque black
    backing, then clipped to the polygon shape using an alpha mask. The
    black backing fills any margin from zoom < 1 and shows through any
    transparency in the art, so portraits read as solid tokens instead of
    floating cutouts.

    Args:
        image_path: Path to the image file.
        width: Bounding box width of the polygon in pixels.
        height: Bounding box height of the polygon in pixels.
        polygon: Screen-space polygon vertices (int coordinates).
        offset_x: Minimum x of the polygon bounding box.
        offset_y: Minimum y of the polygon bounding box.
        zoom: Authored framing zoom on the cover baseline (1.0 = fill).
        pan_x: Authored pan, fraction of the box width (+ = right).
        pan_y: Authored pan, fraction of the box height (+ = down).

    Returns:
        A ``width`` x ``height`` SRCALPHA surface with the image clipped
        to the polygon, or ``None`` on failure.
    """
    from pathlib import Path as _Path

    if width < 1 or height < 1:
        return None

    resolved = str(_Path(image_path).resolve())
    cache_key = (resolved, width, height,
                 float(zoom), float(pan_x), float(pan_y))

    if cache_key in _polygon_token_cache:
        cached_img = _polygon_token_cache[cache_key]
        if cached_img is None:
            return None
        return _clip_surface_to_polygon(cached_img, width, height, polygon, offset_x, offset_y)

    # Load raw image
    try:
        path = _Path(image_path)
        if not path.exists():
            _polygon_token_cache[cache_key] = None
            return None
        raw = pygame.image.load(str(path)).convert_alpha()
    except (pygame.error, OSError):
        _polygon_token_cache[cache_key] = None
        return None

    # Fill the bounding box (cover), centered plus the authored pan, on an
    # opaque black backing — the short sides crop, like the circle token.
    orig_w, orig_h = raw.get_size()
    if orig_w == 0 or orig_h == 0:
        _polygon_token_cache[cache_key] = None
        return None

    scale = max(width / orig_w, height / orig_h) * max(0.01, zoom)
    new_w = max(1, int(orig_w * scale))
    new_h = max(1, int(orig_h * scale))
    scaled = pygame.transform.smoothscale(raw, (new_w, new_h))

    composed = pygame.Surface((width, height), pygame.SRCALPHA)
    composed.fill((0, 0, 0, 255))
    composed.blit(scaled, ((width - new_w) // 2 + int(pan_x * width),
                           (height - new_h) // 2 + int(pan_y * height)))

    # Cache the composed (but unclipped) image
    _polygon_token_cache[cache_key] = composed

    return _clip_surface_to_polygon(composed, width, height, polygon, offset_x, offset_y)


def _clip_surface_to_polygon(
    source: pygame.Surface,
    width: int,
    height: int,
    polygon: list[tuple[int, int]],
    offset_x: int,
    offset_y: int,
) -> pygame.Surface:
    """Clip a surface to a polygon using an alpha mask.

    Args:
        source: The pre-scaled image (width x height).
        width: Surface width.
        height: Surface height.
        polygon: Screen-space polygon vertices.
        offset_x: Minimum x of polygon bounding box (for shifting).
        offset_y: Minimum y of polygon bounding box (for shifting).

    Returns:
        A new SRCALPHA surface with pixels outside the polygon transparent.
    """
    result = source.copy()

    # Shift polygon vertices so they're relative to the bounding box origin
    local_poly = [(p[0] - offset_x, p[1] - offset_y) for p in polygon]

    # Create polygon mask
    mask = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.polygon(mask, (255, 255, 255, 255), local_poly)

    # Apply mask: multiply alpha so pixels outside polygon become transparent
    result.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    return result


def _get_initials(name: str) -> str:
    """Get 1-2 character initials from a creature name."""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[0].upper() if name else "?"


_DEFAULT_TOKEN_COLOR = "#808080"  # the model's placeholder fallback


def _glow_phase(name: str) -> float:
    """A stable per-creature phase offset for the turn-glow pulse."""
    return (sum(name.encode()) % 100) / 100.0 * math.tau


def _body_color(creature, team_color: tuple[int, int, int]) -> tuple[int, int, int]:
    """The disc color for an image-less token.

    An authored ``token_color`` is respected; the model's gray placeholder
    is replaced with a dark team tint so fallback discs still read as
    friend/foe at a glance.
    """
    if creature.token_color.lower() != _DEFAULT_TOKEN_COLOR:
        return parse_color(creature.token_color)
    bg = parse_color(COLORS["bg_medium"])
    return tuple(
        int(t * 0.45 + b * 0.55) for t, b in zip(team_color, bg)
    )


def _draw_hp_bar(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    creature,
    display_hp_pct: float | None = None,
    show_number: bool = False,
) -> None:
    """Draw a small HP bar below the token."""
    bar_width = radius * 2
    bar_height = max(3, int(radius * 0.2))
    bar_x = center[0] - radius
    bar_y = center[1] + radius + 2

    # Background (dark)
    pygame.draw.rect(
        surface, parse_color(COLORS["bar_track"]),
        (bar_x, bar_y, bar_width, bar_height),
    )

    # Fill based on HP percentage
    hp_pct = display_hp_pct if display_hp_pct is not None else creature.hp_percent
    fill_width = int(bar_width * hp_pct)

    if hp_pct > 0.5:
        color = parse_color(COLORS["hp_full"])
    elif hp_pct > 0.25:
        color = parse_color(COLORS["hp_bloodied"])
    else:
        color = parse_color(COLORS["hp_critical"])

    if fill_width > 0:
        pygame.draw.rect(surface, color, (bar_x, bar_y, fill_width, bar_height))

    # Temp HP overlay (cyan segment after the real HP fill)
    temp_hp = getattr(creature, "temporary_hit_points", 0) or 0
    if temp_hp > 0 and creature.max_hit_points > 0:
        temp_pct = temp_hp / creature.max_hit_points
        temp_w = min(int(bar_width * temp_pct), bar_width - fill_width)
        if temp_w > 0:
            temp_color = parse_color(COLORS["hp_temp"])
            pygame.draw.rect(
                surface, temp_color,
                (bar_x + fill_width, bar_y, temp_w, bar_height),
            )

    # HP numbers (large tokens only — their wide bar has room for text)
    if show_number and bar_height >= 9 and bar_width >= 40:
        font = get_font(max(9, bar_height - 2), "body_bold")
        hp_text = f"{creature.current_hit_points}/{creature.max_hit_points}"
        text = font.render(hp_text, True, parse_color(COLORS["text_primary"]))
        shadow = font.render(hp_text, True, (0, 0, 0))
        pos = text.get_rect(
            center=(center[0], bar_y + bar_height // 2)
        )
        surface.blit(shadow, (pos.x + 1, pos.y + 1))
        surface.blit(text, pos)


def _draw_condition_icons(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    creature,
    zoom: float,
) -> None:
    """Draw small condition indicator dots above the token."""
    conditions = creature.active_conditions
    if not conditions:
        return

    dot_radius = max(4, int(6 * zoom))
    dot_gap = max(1, int(2 * zoom))
    dot_spacing = dot_radius * 2 + dot_gap
    font_size = max(7, int(9 * zoom))
    font = get_font(font_size)

    count = len(conditions)
    total_width = count * dot_spacing - dot_gap
    start_x = center[0] - total_width // 2 + dot_radius
    y = center[1] - radius - dot_radius - max(2, int(3 * zoom))

    for i, applied_cond in enumerate(conditions):
        cond_value = applied_cond.condition.value
        display_info = CONDITION_DISPLAY.get(cond_value)
        if display_info is None:
            abbrev, color_key = "??", "condition_neutral"
        else:
            abbrev, color_key = display_info

        dot_color = parse_color(COLORS[color_key])
        cx = start_x + i * dot_spacing

        pygame.draw.circle(surface, dot_color, (cx, y), dot_radius)

        if dot_radius >= 6:
            text_surf = font.render(
                abbrev, True, parse_color(COLORS["text_primary"])
            )
            text_rect = text_surf.get_rect(center=(cx, y))
            surface.blit(text_surf, text_rect)
