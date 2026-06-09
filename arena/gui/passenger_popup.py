"""Passenger selection popup for teleportation spells like Dimension Door."""

from __future__ import annotations

import pygame

from arena.gui.renderer import get_font


class PassengerPopup:
    """Modal popup asking the player to pick a passenger or teleport solo.

    Shown when a teleport action has ``teleport_passenger=True`` and at
    least one willing ally is adjacent to the caster.  Returns the
    chosen passenger's creature-ID string, or ``"__solo__"`` if the
    player declines.
    """

    WIDTH = 260
    ROW_HEIGHT = 32
    TITLE_HEIGHT = 50
    SOLO_HEIGHT = 32
    PADDING = 6

    # Cyan / teleport theme
    _BG_COLOR = (15, 25, 40, 240)
    _BORDER_COLOR = (100, 180, 255)
    _HOVER_COLOR = (50, 80, 120, 80)
    _TITLE_COLOR = (100, 180, 255)
    _TEXT_COLOR = (240, 230, 210)
    _SUBTITLE_COLOR = (160, 150, 135)
    _SOLO_COLOR = (160, 150, 135)

    def __init__(
        self,
        candidates: list[tuple[str, str]],
        caster_name: str,
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        """
        Args:
            candidates: List of ``(creature_id, display_name)`` for each
                eligible passenger (same-team allies within 5 ft).
            caster_name: Name of the caster, shown in the subtitle.
        """
        self.candidates = candidates
        self.caster_name = caster_name
        self._screen_width = screen_width
        self._screen_height = screen_height
        self.hovered_index: int | None = None
        self._hovered_solo: bool = False

        total_h = (
            self.TITLE_HEIGHT
            + max(len(candidates), 1) * self.ROW_HEIGHT
            + self.SOLO_HEIGHT
            + self.PADDING * 2
        )
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def reposition(self, center: tuple[int, int]) -> None:
        """Center the popup at *center*, clamped to the screen."""
        self.rect.center = center
        if self.rect.left < 4:
            self.rect.left = 4
        if self.rect.right > self._screen_width - 4:
            self.rect.right = self._screen_width - 4
        if self.rect.top < 4:
            self.rect.top = 4
        if self.rect.bottom > self._screen_height - 4:
            self.rect.bottom = self._screen_height - 4

    # ------------------------------------------------------------------
    # Rect helpers
    # ------------------------------------------------------------------

    def _get_candidate_rect(self, index: int) -> pygame.Rect:
        """Clickable rect for a candidate row."""
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    def _get_solo_rect(self) -> pygame.Rect:
        """Clickable rect for the 'Teleport Solo' button."""
        y = (
            self.rect.y + self.TITLE_HEIGHT + self.PADDING
            + len(self.candidates) * self.ROW_HEIGHT
        )
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.SOLO_HEIGHT,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Process input.

        Returns:
            - ``creature_id`` string: player chose that passenger.
            - ``"__solo__"``: player chose to teleport alone (or
              clicked outside / pressed Escape).
            - ``None``: no decision yet (keep popup open).
        """
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            self.hovered_index = None
            self._hovered_solo = False
            for i in range(len(self.candidates)):
                if self._get_candidate_rect(i).collidepoint(mx, my):
                    self.hovered_index = i
                    break
            if self._get_solo_rect().collidepoint(mx, my):
                self._hovered_solo = True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            # Check candidate clicks
            for i, (cid, _name) in enumerate(self.candidates):
                if self._get_candidate_rect(i).collidepoint(mx, my):
                    return cid
            # Check solo button
            if self._get_solo_rect().collidepoint(mx, my):
                return "__solo__"
            # Click outside popup = solo
            if not self.rect.collidepoint(mx, my):
                return "__solo__"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "__solo__"

        return None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, surface: pygame.Surface) -> None:
        """Draw the passenger selection popup."""
        # Background
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill(self._BG_COLOR)
        surface.blit(bg, self.rect.topleft)
        pygame.draw.rect(surface, self._BORDER_COLOR, self.rect, 2)

        font = get_font(13)
        font_small = get_font(11)

        # Title
        title = font.render("Bring a Passenger?", True, self._TITLE_COLOR)
        tx = self.rect.x + (self.WIDTH - title.get_width()) // 2
        surface.blit(title, (tx, self.rect.y + 8))

        # Subtitle
        subtitle = font_small.render(
            f"{self.caster_name} \u2014 Dimension Door",
            True, self._SUBTITLE_COLOR,
        )
        sx = self.rect.x + (self.WIDTH - subtitle.get_width()) // 2
        surface.blit(subtitle, (sx, self.rect.y + 28))

        # Candidate rows
        for i, (_cid, name) in enumerate(self.candidates):
            rect = self._get_candidate_rect(i)
            is_hovered = self.hovered_index == i

            if is_hovered:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill(self._HOVER_COLOR)
                surface.blit(hl, rect.topleft)

            label = font.render(name, True, self._TEXT_COLOR)
            surface.blit(label, (rect.x + 10, rect.y + 6))

        # Solo button
        solo_rect = self._get_solo_rect()
        if self._hovered_solo:
            hl = pygame.Surface((solo_rect.width, solo_rect.height), pygame.SRCALPHA)
            hl.fill(self._HOVER_COLOR)
            surface.blit(hl, solo_rect.topleft)

        solo_text = font.render("Teleport Solo", True, self._SOLO_COLOR)
        stx = solo_rect.x + (solo_rect.width - solo_text.get_width()) // 2
        surface.blit(solo_text, (stx, solo_rect.y + 8))
