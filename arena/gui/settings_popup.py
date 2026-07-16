"""In-fight options popup: two live sliders and the stream-rate picker.

* Battle map — the background image's opacity (0–100%), for when the art makes
  terrain hexes hard to read. GridView reads the setting every frame, so
  dragging is instant; 0% is exactly the plain field.
* Music — the encounter-music volume. Applied to the playing track on the spot
  (``SoundManager.refresh_music_volume``) so a player who'd rather run their
  own soundtrack can just pull it to zero.
* Stream — the fps of the board broadcast to browsers (multiplayer S2).
  Bandwidth is the real cost: 20fps suits internet play through a tunnel;
  a same-wifi table can afford 60. The capture loop reads it every frame,
  so the change applies live mid-fight.

Everything persists through ``save_settings`` on release, so the choice sticks
across fights and sessions.
"""

from __future__ import annotations

import pygame

from arena.audio.manager import get_sound_manager
from arena.gui.popup_base import Popup
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, FONT_SIZES, parse_color
from arena.util.settings import get_settings, save_settings

_ROW_H = 52          # label line + track per slider
_TRACK_H = 6
_HANDLE_R = 8


class SettingsPopup(Popup):
    """Modal with the two in-fight sliders. ``handle_event`` returns
    ``"__close__"`` when dismissed (button, ESC, or a click outside)."""

    WIDTH = 320

    def __init__(self, screen_width: int, screen_height: int) -> None:
        super().__init__(screen_width, screen_height)
        self.rect.height = (
            self.TITLE_HEIGHT + 3 * _ROW_H + self.BTN_HEIGHT + 2 * self.PADDING
        )
        self.reposition((screen_width // 2, screen_height // 2))
        self._dragging: str | None = None   # "background" | "music"
        self._hover_close = False
        self._dirty = False                 # unsaved slider movement

    # ── Values (settings are the single source of truth) ─────────────

    @staticmethod
    def _get(which: str) -> int:
        s = get_settings()
        if which == "background":
            return s.display.battle_background_opacity
        return s.audio.music_volume

    @staticmethod
    def _set(which: str, value: int) -> None:
        value = max(0, min(100, value))
        s = get_settings()
        if which == "background":
            s.display.battle_background_opacity = value
        else:
            s.audio.music_volume = value
            get_sound_manager().refresh_music_volume()

    # ── Geometry ──────────────────────────────────────────────────────

    def _row_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(
            self.rect.x + self.PADDING,
            self.rect.y + self.TITLE_HEIGHT + index * _ROW_H,
            self.rect.width - 2 * self.PADDING,
            _ROW_H,
        )

    def _track_rect(self, index: int) -> pygame.Rect:
        row = self._row_rect(index)
        return pygame.Rect(row.x, row.y + 30, row.width, _TRACK_H)

    def _close_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self.rect.centerx - 45,
            self.rect.bottom - self.PADDING - self.BTN_HEIGHT,
            90, self.BTN_HEIGHT,
        )

    _SLIDERS = (("background", "Battle map"), ("music", "Music"))
    _FPS_CHOICES = (10, 20, 30, 60)

    def _slider_at(self, pos: tuple[int, int]) -> str | None:
        """The slider whose track (with a fat grab margin) is under *pos*."""
        for i, (key, _label) in enumerate(self._SLIDERS):
            if self._track_rect(i).inflate(0, 18).collidepoint(pos):
                return key
        return None

    def _fps_rects(self) -> list[tuple[int, pygame.Rect]]:
        """The stream-rate segments (row below the sliders)."""
        row = self._row_rect(len(self._SLIDERS))
        gap = 6
        seg_w = (row.width - gap * (len(self._FPS_CHOICES) - 1)) // len(self._FPS_CHOICES)
        return [(fps, pygame.Rect(row.x + i * (seg_w + gap), row.y + 26, seg_w, 22))
                for i, fps in enumerate(self._FPS_CHOICES)]

    def _fps_at(self, pos: tuple[int, int]) -> int | None:
        for fps, rect in self._fps_rects():
            if rect.collidepoint(pos):
                return fps
        return None

    def _value_for_x(self, key: str, x: int) -> int:
        i = 0 if key == "background" else 1
        track = self._track_rect(i)
        return round((x - track.x) * 100 / max(1, track.width))

    # ── Events ────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_o):
                return self._close()
            return None

        if event.type == pygame.MOUSEMOTION:
            self._hover_close = self._close_rect().collidepoint(event.pos)
            if self._dragging is not None:
                self._set(self._dragging, self._value_for_x(self._dragging, event.pos[0]))
                self._dirty = True
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._close_rect().collidepoint(event.pos):
                return None                       # resolve on mouse-up
            key = self._slider_at(event.pos)
            if key is not None:
                self._dragging = key
                self._set(key, self._value_for_x(key, event.pos[0]))
                self._dirty = True
                return None
            fps = self._fps_at(event.pos)
            if fps is not None:
                get_settings().system.stream_fps = fps   # capture reads it live
                self._dirty = True
                return None
            if not self.rect.collidepoint(event.pos):
                return self._close()              # click-away dismisses
            return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = None
            if self._dirty:
                save_settings()
                self._dirty = False
            if self._close_rect().collidepoint(event.pos):
                return self._close()
            return None

        return None

    def _close(self) -> str:
        if self._dirty:
            save_settings()
        return "__close__"

    # ── Rendering ─────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface) -> None:
        self.render_frame(surface, "Options")
        label_font = get_font(FONT_SIZES["label"])
        text_rgb = parse_color(COLORS["text_primary"])
        dim_rgb = parse_color(COLORS["text_secondary"])
        accent = self.border_color()

        for i, (key, label) in enumerate(self._SLIDERS):
            row = self._row_rect(i)
            value = self._get(key)
            surface.blit(label_font.render(label, True, text_rgb), (row.x, row.y + 8))
            vsurf = label_font.render(f"{value}%", True, dim_rgb)
            surface.blit(vsurf, (row.right - vsurf.get_width(), row.y + 8))

            track = self._track_rect(i)
            pygame.draw.rect(surface, (60, 52, 40), track, border_radius=3)
            filled = track.copy()
            filled.width = int(track.width * value / 100)
            if filled.width > 0:
                pygame.draw.rect(surface, accent, filled, border_radius=3)
            hx = track.x + int(track.width * value / 100)
            pygame.draw.circle(surface, text_rgb, (hx, track.centery), _HANDLE_R)
            pygame.draw.circle(surface, accent, (hx, track.centery), _HANDLE_R, 2)

        # Stream-rate picker: four segments, the active one filled
        fps_row = self._row_rect(len(self._SLIDERS))
        surface.blit(label_font.render("Stream", True, text_rgb),
                     (fps_row.x, fps_row.y + 4))
        current = get_settings().system.stream_fps
        vsurf = label_font.render(f"{current} fps", True, dim_rgb)
        surface.blit(vsurf, (fps_row.right - vsurf.get_width(), fps_row.y + 4))
        small_font = get_font(FONT_SIZES["small"])
        for fps, rect in self._fps_rects():
            active = fps == current
            if active:
                pygame.draw.rect(surface, accent, rect, border_radius=4)
            pygame.draw.rect(surface, accent if active else (60, 52, 40),
                             rect, 2, border_radius=4)
            tsurf = small_font.render(str(fps), True,
                                      parse_color(COLORS["bg_dark"]) if active else dim_rgb)
            surface.blit(tsurf, (rect.centerx - tsurf.get_width() // 2,
                                 rect.centery - tsurf.get_height() // 2))

        self.draw_button(surface, self._close_rect(), "Close",
                         hovered=self._hover_close)
