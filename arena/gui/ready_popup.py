"""Ready action popup — two-stage chooser for the Ready action (D-ACT-1).

Stage 1 picks which action to hold; stage 2 picks the trigger. On the final
choice the combat screen reads ``selected_action`` + ``selected_trigger`` and
calls ``execute_ready_action``.

Only actions the engine can resolve against the triggering creature are
offered: attacks (weapon or spell attack) and single-target offensive save
spells (e.g. Hold Person). AoE / zone / self-buff actions are filtered out —
they have no single trigger-target to resolve against in this basic version.
"""

from __future__ import annotations

import pygame

from arena.combat.ready_action import TriggerType
from arena.gui.renderer import get_font
from arena.util.constants import COLORS, parse_color


# Trigger options, in display order. (label, TriggerType)
_TRIGGERS: list[tuple[str, TriggerType]] = [
    ("When an enemy enters my reach", TriggerType.CREATURE_ENTERS_RANGE),
    ("When an enemy moves", TriggerType.CREATURE_MOVES),
    ("When an enemy attacks", TriggerType.CREATURE_ATTACKS),
    ("When an enemy casts a spell", TriggerType.CREATURE_CASTS),
]


def _is_zone_spell(action) -> bool:
    """A concentration AoE that places a persistent zone (Web, Spirit
    Guardians, Cloudkill). Mirrors CombatManager._is_zone_creating_spell —
    these aren't readyable (they'd need zone-placement, not a one-shot release)."""
    return (
        action.requires_concentration
        and action.target_type.value.startswith("area_")
        and action.saving_throw is not None
        and bool(action.saving_throw.damage_on_fail
                 or action.saving_throw.conditions_on_fail)
    )


def is_readyable(action) -> bool:
    """Whether an action can be held with Ready in this basic version.

    Readyable: attacks (weapon / spell attack, incl. multi-ray); single-target
    save spells (Hold Person); and placed radius bursts (Fireball — sphere /
    cylinder). NOT readyable: self-target, zone spells, and the directional
    cone/line/cube shapes (those wait on the D-AOE-1 geometry pass).
    """
    from arena.models.actions import ActionType, TargetType

    # Only full actions can be readied (not bonus/reaction/free/legendary).
    if action.action_type not in (ActionType.ACTION, ActionType.ACTION.value):
        return False
    # An attack (weapon or spell attack) resolves against the trigger creature.
    if action.attack is not None:
        return True
    if _is_zone_spell(action):
        return False
    # A single-target save spell (Hold Person etc.) resolves cleanly.
    if (action.saving_throw is not None and action.target_type in (
            TargetType.ONE_CREATURE, TargetType.ONE_ALLY, TargetType.ONE_ENEMY)):
        return True
    # A placed radius burst (Fireball) — released centered on the trigger hex.
    if action.target_type in (TargetType.AREA_SPHERE, TargetType.AREA_CYLINDER):
        return True
    return False


def readyable_actions(creature) -> list:
    """The creature's actions that can be readied."""
    return [a for a in creature.actions if is_readyable(a)]


class ReadyPopup:
    """Two-stage modal: choose an action to ready, then choose its trigger."""

    WIDTH = 280
    ROW_HEIGHT = 30
    TITLE_HEIGHT = 30
    PADDING = 6

    def __init__(
        self,
        actions: list,
        screen_width: int = 1280,
        screen_height: int = 720,
    ) -> None:
        self._actions = actions
        self._screen_width = screen_width
        self._screen_height = screen_height

        self.stage = "action"  # "action" -> "trigger"
        self.selected_action = None
        self.selected_trigger: TriggerType | None = None
        self.hovered_index: int | None = None

        self._layout()

    # ── Layout ────────────────────────────────────────────────────────

    def _rows(self) -> list[str]:
        if self.stage == "action":
            return [a.name for a in self._actions]
        return [label for label, _ in _TRIGGERS]

    def _layout(self) -> None:
        total_h = (
            self.TITLE_HEIGHT
            + len(self._rows()) * self.ROW_HEIGHT
            + self.PADDING * 2
        )
        center = getattr(self, "rect", None)
        self.rect = pygame.Rect(0, 0, self.WIDTH, total_h)
        if center is not None:
            self.rect.center = center.center
            self._clamp()

    def reposition(self, center: tuple[int, int]) -> None:
        self.rect.center = center
        self._clamp()

    def _clamp(self) -> None:
        if self.rect.left < 4:
            self.rect.left = 4
        if self.rect.right > self._screen_width - 4:
            self.rect.right = self._screen_width - 4
        if self.rect.top < 4:
            self.rect.top = 4
        if self.rect.bottom > self._screen_height - 4:
            self.rect.bottom = self._screen_height - 4

    def _row_rect(self, index: int) -> pygame.Rect:
        y = self.rect.y + self.TITLE_HEIGHT + self.PADDING + index * self.ROW_HEIGHT
        return pygame.Rect(
            self.rect.x + self.PADDING, y,
            self.WIDTH - self.PADDING * 2, self.ROW_HEIGHT,
        )

    # ── Event handling ────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Process input.

        Returns:
            "__ready__" once both an action and a trigger are chosen.
            "__close__" to cancel.
            None otherwise.
        """
        if event.type == pygame.MOUSEMOTION:
            self.hovered_index = None
            for i in range(len(self._rows())):
                if self._row_rect(i).collidepoint(event.pos):
                    self.hovered_index = i
                    break

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(len(self._rows())):
                if self._row_rect(i).collidepoint(event.pos):
                    from arena.audio.manager import get_sound_manager
                    get_sound_manager().play_sfx("button_click")
                    return self._choose(i)
            if not self.rect.collidepoint(event.pos):
                return "__close__"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # Esc backs out of trigger stage to action stage, else cancels.
            if self.stage == "trigger":
                self.stage = "action"
                self.selected_action = None
                self.hovered_index = None
                self._layout()
                return None
            return "__close__"

        return None

    def _choose(self, index: int) -> str | None:
        if self.stage == "action":
            self.selected_action = self._actions[index]
            self.stage = "trigger"
            self.hovered_index = None
            self._layout()
            return None
        # trigger stage
        self.selected_trigger = _TRIGGERS[index][1]
        return "__ready__"

    # ── Rendering ─────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface) -> None:
        bg = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        bg.fill((30, 24, 18, 240))
        surface.blit(bg, self.rect.topleft)
        pygame.draw.rect(surface, parse_color(COLORS["border_accent"]), self.rect, 2)

        font = get_font(13)
        gold = parse_color(COLORS["text_gold"])
        white = parse_color(COLORS["text_primary"])

        if self.stage == "action":
            title = "Ready which action?"
        else:
            name = self.selected_action.name if self.selected_action else ""
            title = f"Ready {name} — trigger?"
        title_surf = font.render(title, True, gold)
        tx = self.rect.x + (self.WIDTH - title_surf.get_width()) // 2
        surface.blit(title_surf, (tx, self.rect.y + 8))

        for i, label in enumerate(self._rows()):
            rect = self._row_rect(i)
            if self.hovered_index == i:
                hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                hl.fill((80, 70, 50, 80))
                surface.blit(hl, rect.topleft)
            label_surf = font.render(label, True, white)
            surface.blit(label_surf, (rect.x + 8, rect.y + 7))
