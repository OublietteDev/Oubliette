"""Drawing and rendering utilities for the hex grid."""

import math
import os

import pygame

from arena.models.encounter import TerrainType
from arena.util.constants import COLORS, parse_color


# Font paths - relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FONT_DIR = os.path.join(_PROJECT_ROOT, "assets", "fonts")
_FONT_MEDIEVAL = os.path.join(_FONT_DIR, "MedievalSharp-Regular.ttf")

# Font cache to avoid re-creating font objects every frame
_font_cache: dict[tuple[str, int], pygame.font.Font] = {}

# Resolved font path (None = pygame default, set on first use)
_resolved_font_path: str | None = None
_font_path_resolved: bool = False


def _get_font_path() -> str | None:
    """Resolve the fantasy font path, falling back to default if missing."""
    global _resolved_font_path, _font_path_resolved
    if not _font_path_resolved:
        if os.path.isfile(_FONT_MEDIEVAL):
            _resolved_font_path = _FONT_MEDIEVAL
        else:
            _resolved_font_path = None
        _font_path_resolved = True
    return _resolved_font_path


def get_font(size: int) -> pygame.font.Font:
    """Get a cached fantasy-themed font of the given size."""
    font_path = _get_font_path()
    key = ("body", size)
    if key not in _font_cache:
        _font_cache[key] = pygame.font.Font(font_path, size)
    return _font_cache[key]


def hex_vertices(
    cx: float, cy: float, size: float
) -> list[tuple[float, float]]:
    """Calculate the 6 vertices of a flat-top hexagon.

    Args:
        cx: Center x in screen coordinates.
        cy: Center y in screen coordinates.
        size: Distance from center to vertex (outer radius).

    Returns:
        List of 6 (x, y) tuples, starting from the rightmost vertex
        and proceeding counter-clockwise.
    """
    vertices = []
    for i in range(6):
        angle_rad = math.pi / 180 * (60 * i)
        vx = cx + size * math.cos(angle_rad)
        vy = cy + size * math.sin(angle_rad)
        vertices.append((vx, vy))
    return vertices


def draw_hex(
    surface: pygame.Surface,
    center: tuple[int, int],
    size: float,
    fill_color: tuple[int, int, int],
    border_color: tuple[int, int, int],
    border_width: int = 1,
) -> None:
    """Draw a filled hexagon with a border outline."""
    vertices = hex_vertices(center[0], center[1], size)
    pygame.draw.polygon(surface, fill_color, vertices)
    if border_width > 0:
        pygame.draw.polygon(surface, border_color, vertices, border_width)


def draw_hex_highlight(
    surface: pygame.Surface,
    center: tuple[int, int],
    size: float,
    color: tuple[int, int, int],
    alpha: int = 128,
) -> None:
    """Draw a semi-transparent highlight overlay on a hex.

    Uses a temporary SRCALPHA surface to achieve transparency.
    """
    vertices = hex_vertices(center[0], center[1], size)

    # Calculate bounding box for the temporary surface
    min_x = min(v[0] for v in vertices)
    min_y = min(v[1] for v in vertices)
    max_x = max(v[0] for v in vertices)
    max_y = max(v[1] for v in vertices)
    w = int(max_x - min_x) + 4
    h = int(max_y - min_y) + 4

    # Create temporary surface with per-pixel alpha
    temp = pygame.Surface((w, h), pygame.SRCALPHA)

    # Offset vertices to local coordinates
    offset_x = int(min_x) - 2
    offset_y = int(min_y) - 2
    local_verts = [(v[0] - offset_x, v[1] - offset_y) for v in vertices]

    pygame.draw.polygon(temp, (*color, alpha), local_verts)
    surface.blit(temp, (offset_x, offset_y))


def draw_text_centered(
    surface: pygame.Surface,
    text: str,
    center: tuple[int, int],
    color: tuple[int, int, int],
    font_size: int = 16,
) -> None:
    """Draw text centered at the given position."""
    font = get_font(font_size)
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect(center=center)
    surface.blit(text_surface, text_rect)


def draw_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    bg_color: str = "bg_medium",
    border_color: str = "border_accent",
) -> None:
    """Draw a panel background with a warm fantasy-styled border.

    Uses a single border with corner accents for a parchment/leather feel.
    """
    bg = parse_color(COLORS[bg_color])
    border = parse_color(COLORS[border_color])
    pygame.draw.rect(surface, bg, rect)
    pygame.draw.rect(surface, border, rect, 1)

    # Small corner accent marks (2px inset L-shapes)
    corner_len = min(8, rect.width // 6, rect.height // 6)
    if corner_len >= 4:
        accent = parse_color(COLORS.get("border_light", border_color))
        x1, y1, x2, y2 = rect.left, rect.top, rect.right - 1, rect.bottom - 1
        # Top-left
        pygame.draw.line(surface, accent, (x1 + 2, y1 + 2), (x1 + 2 + corner_len, y1 + 2), 1)
        pygame.draw.line(surface, accent, (x1 + 2, y1 + 2), (x1 + 2, y1 + 2 + corner_len), 1)
        # Top-right
        pygame.draw.line(surface, accent, (x2 - 2, y2 - 2), (x2 - 2 - corner_len, y2 - 2), 1)
        pygame.draw.line(surface, accent, (x2 - 2, y2 - 2), (x2 - 2, y2 - 2 - corner_len), 1)
        # Bottom-left
        pygame.draw.line(surface, accent, (x1 + 2, y2 - 2), (x1 + 2 + corner_len, y2 - 2), 1)
        pygame.draw.line(surface, accent, (x1 + 2, y2 - 2), (x1 + 2, y2 - 2 - corner_len), 1)
        # Bottom-right
        pygame.draw.line(surface, accent, (x2 - 2, y1 + 2), (x2 - 2 - corner_len, y1 + 2), 1)
        pygame.draw.line(surface, accent, (x2 - 2, y1 + 2), (x2 - 2, y1 + 2 + corner_len), 1)


def draw_scrollbar(
    surface: pygame.Surface,
    area_rect: pygame.Rect,
    content_height: int,
    scroll_offset: int,
    bar_width: int = 6,
    margin: int = 2,
) -> None:
    """Draw a thin scrollbar on the right edge of *area_rect*.

    Only draws when ``content_height`` exceeds the visible area height.

    Args:
        surface: Target surface.
        area_rect: The visible scrollable region.
        content_height: Total height of the scrollable content.
        scroll_offset: Current scroll position (0 = top).
        bar_width: Width of the scrollbar track in pixels.
        margin: Inset from the right edge.
    """
    visible = area_rect.height
    if content_height <= visible:
        return  # Nothing to scroll — no bar needed

    track_x = area_rect.right - bar_width - margin
    track_y = area_rect.top + margin
    track_h = visible - margin * 2

    # Draw track (subtle dark background)
    track_color = parse_color(COLORS.get("bg_dark", "#1a1410"))
    pygame.draw.rect(
        surface, track_color,
        (track_x, track_y, bar_width, track_h),
        border_radius=bar_width // 2,
    )

    # Thumb size and position
    thumb_ratio = visible / content_height
    thumb_h = max(16, int(track_h * thumb_ratio))

    max_scroll = content_height - visible
    if max_scroll > 0:
        scroll_ratio = scroll_offset / max_scroll
    else:
        scroll_ratio = 0.0
    thumb_y = track_y + int((track_h - thumb_h) * scroll_ratio)

    # Draw thumb
    thumb_color = parse_color(COLORS.get("border_accent", "#6b5530"))
    pygame.draw.rect(
        surface, thumb_color,
        (track_x, thumb_y, bar_width, thumb_h),
        border_radius=bar_width // 2,
    )


def draw_terrain_indicator(
    surface: pygame.Surface,
    center: tuple[int, int],
    size: float,
    terrain: TerrainType,
) -> None:
    """Draw a small visual indicator for special terrain types.

    Only draws for terrain types that benefit from an extra marker beyond
    their fill color: WALL, PIT, and cover types.
    """
    cx, cy = center
    indicator_size = max(4, int(size * 0.2))

    if terrain == TerrainType.WALL:
        # Draw an X pattern
        half = indicator_size
        color = parse_color(COLORS["text_secondary"])
        pygame.draw.line(surface, color, (cx - half, cy - half), (cx + half, cy + half), 2)
        pygame.draw.line(surface, color, (cx - half, cy + half), (cx + half, cy - half), 2)

    elif terrain == TerrainType.PIT:
        # Draw a downward-pointing triangle
        color = parse_color(COLORS["text_secondary"])
        half = indicator_size
        points = [
            (cx - half, cy - half // 2),
            (cx + half, cy - half // 2),
            (cx, cy + half),
        ]
        pygame.draw.polygon(surface, color, points)

    elif terrain == TerrainType.COVER_HALF:
        # Draw a small half-shield (half-height rectangle)
        color = parse_color(COLORS["text_secondary"])
        half = indicator_size
        rect = pygame.Rect(cx - half, cy, half * 2, half)
        pygame.draw.rect(surface, color, rect, 1)

    elif terrain == TerrainType.COVER_THREE_QUARTERS:
        # Draw a taller shield rectangle
        color = parse_color(COLORS["text_secondary"])
        half = indicator_size
        rect = pygame.Rect(cx - half, cy - half // 2, half * 2, int(half * 1.5))
        pygame.draw.rect(surface, color, rect, 1)

    elif terrain == TerrainType.COVER_FULL:
        # Draw a filled shield rectangle
        color = parse_color(COLORS["text_secondary"])
        half = indicator_size
        rect = pygame.Rect(cx - half, cy - half, half * 2, half * 2)
        pygame.draw.rect(surface, color, rect, 2)
