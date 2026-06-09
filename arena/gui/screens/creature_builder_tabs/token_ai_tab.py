"""Token & AI tab — token color, image, player-controlled toggle, AI profile."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pygame

from arena.gui.renderer import draw_text_centered, get_font
from arena.gui.widgets import TextInput, Checkbox, Dropdown
from arena.util.constants import COLORS, parse_color

if TYPE_CHECKING:
    from arena.gui.screens.character_builder import CreatureBuilderScreen

AI_PROFILES = [
    "(none)",
    "default_monster",
    "berserker",
    "coward",
    "support",
    "sniper",
    "tactician",
]


class TokenAITab:
    """Renders and handles the Token & AI tab."""

    def __init__(self, screen: CreatureBuilderScreen) -> None:
        self.screen = screen
        ox, oy = screen.get_content_origin()
        w = screen.content_rect.width - 20

        # Token color
        self.color_input = TextInput(
            pygame.Rect(ox, oy + 40, 160, 28),
            value=screen.form_data["token_color"],
            max_length=7,
            placeholder="#808080",
        )
        self.color_preview_rect = pygame.Rect(ox + 170, oy + 38, 32, 32)

        # Token image path — display label + Browse button
        self._image_path: str = screen.form_data["token_image"]
        browse_btn_w = 80
        self.image_display_rect = pygame.Rect(
            ox, oy + 110, w - browse_btn_w - 6, 28,
        )
        self.browse_btn_rect = pygame.Rect(
            ox + w - browse_btn_w, oy + 110, browse_btn_w, 28,
        )
        self._browse_hovered = False
        # Clear button (small x beside the path)
        self.clear_btn_rect = pygame.Rect(
            self.image_display_rect.right - 22,
            self.image_display_rect.y + 4,
            20, 20,
        )
        self._clear_hovered = False

        # Player controlled
        self.player_controlled_cb = Checkbox(
            pygame.Rect(ox, oy + 180, 250, 28),
            "Player Controlled",
            checked=screen.form_data["is_player_controlled"],
        )

        # AI profile
        ai_val = screen.form_data["ai_profile"] or "(none)"
        self.ai_dropdown = Dropdown(
            pygame.Rect(ox, oy + 250, 200, 26),
            AI_PROFILES,
        )
        try:
            self.ai_dropdown.selected_index = AI_PROFILES.index(ai_val)
        except ValueError:
            self.ai_dropdown.selected_index = 0

        self._text_inputs = [self.color_input]
        self._dropdowns = [self.ai_dropdown]

    def has_open_dropdown(self) -> bool:
        return self.ai_dropdown.is_open

    def handle_escape(self) -> bool:
        for inp in self._text_inputs:
            if inp.active:
                inp.active = False
                return True
        if self.ai_dropdown.is_open:
            self.ai_dropdown.is_open = False
            return True
        return False

    def handle_event(self, event: pygame.event.Event) -> bool:
        if self.ai_dropdown.is_open and self.ai_dropdown.handle_event(event):
            self._sync_to_form()
            return True

        if event.type == pygame.MOUSEMOTION:
            self._browse_hovered = self.browse_btn_rect.collidepoint(event.pos)
            self._clear_hovered = (
                self._image_path
                and self.clear_btn_rect.collidepoint(event.pos)
            )

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # Browse button
            if self.browse_btn_rect.collidepoint(event.pos):
                self._open_file_dialog()
                return True
            # Clear button
            if self._image_path and self.clear_btn_rect.collidepoint(event.pos):
                self._image_path = ""
                self._sync_to_form()
                return True

        for inp in self._text_inputs:
            if inp.handle_event(event):
                self._sync_to_form()
                return True

        if self.player_controlled_cb.handle_event(event):
            self._sync_to_form()
            return True

        if self.ai_dropdown.handle_event(event):
            self._sync_to_form()
            return True

        return False

    def _open_file_dialog(self) -> None:
        """Open a native file explorer dialog to select a token image."""
        try:
            import tkinter as tk
            from tkinter import filedialog

            # Create a hidden root window (required by tkinter)
            root = tk.Tk()
            root.withdraw()
            # Bring the dialog to the front
            root.attributes("-topmost", True)

            filepath = filedialog.askopenfilename(
                title="Select Token Image",
                filetypes=[
                    ("Image Files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                    ("PNG Files", "*.png"),
                    ("JPEG Files", "*.jpg *.jpeg"),
                    ("All Files", "*.*"),
                ],
            )
            root.destroy()

            if filepath:
                self._image_path = filepath
                self._sync_to_form()

        except Exception:
            # Gracefully handle if tkinter is unavailable
            pass

    def _sync_to_form(self) -> None:
        d = self.screen.form_data
        d["token_color"] = self.color_input.value
        d["token_image"] = self._image_path
        d["is_player_controlled"] = self.player_controlled_cb.checked
        ai_val = self.ai_dropdown.value
        d["ai_profile"] = "" if ai_val == "(none)" else ai_val

    def render(self, surface: pygame.Surface) -> None:
        ox, oy = self.screen.get_content_origin()
        label_color = parse_color(COLORS["text_secondary"])
        font = get_font(14)

        # Section header
        header = get_font(18)
        header_surf = header.render(
            "Token & AI Settings", True,
            parse_color(COLORS["text_gold"]),
        )
        surface.blit(header_surf, (ox, oy + 2))

        # Token color
        lbl = font.render("Token Color:", True, label_color)
        surface.blit(lbl, (ox, oy + 24))
        self.color_input.render(surface)

        # Color preview swatch
        try:
            preview_color = parse_color(self.color_input.value)
        except (ValueError, IndexError):
            preview_color = (128, 128, 128)
        pygame.draw.rect(surface, preview_color, self.color_preview_rect, border_radius=4)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.color_preview_rect, 1, border_radius=4,
        )

        # Token image
        lbl2 = font.render("Token Image:", True, label_color)
        surface.blit(lbl2, (ox, oy + 94))

        # Path display box
        pygame.draw.rect(
            surface, parse_color(COLORS["bg_dark"]),
            self.image_display_rect, border_radius=3,
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.image_display_rect, 1, border_radius=3,
        )
        if self._image_path:
            # Show just the filename for readability
            display_name = os.path.basename(self._image_path)
            path_surf = font.render(
                display_name, True, parse_color(COLORS["text_primary"]),
            )
        else:
            path_surf = font.render(
                "No image selected", True,
                parse_color(COLORS["text_secondary"]),
            )
        clip = pygame.Rect(
            0, 0, self.image_display_rect.width - 28, self.image_display_rect.height,
        )
        surface.blit(
            path_surf,
            (self.image_display_rect.x + 6,
             self.image_display_rect.y + 6),
            clip,
        )

        # Clear [x] button (only when a path is set)
        if self._image_path:
            clear_color = (
                parse_color(COLORS["text_primary"]) if self._clear_hovered
                else parse_color(COLORS["text_secondary"])
            )
            draw_text_centered(
                surface, "x", self.clear_btn_rect.center,
                clear_color, font_size=12,
            )

        # Browse button
        browse_bg = (
            parse_color(COLORS["button_hover"]) if self._browse_hovered
            else parse_color(COLORS["button_normal"])
        )
        pygame.draw.rect(surface, browse_bg, self.browse_btn_rect, border_radius=3)
        pygame.draw.rect(
            surface, parse_color(COLORS["hex_border"]),
            self.browse_btn_rect, 1, border_radius=3,
        )
        draw_text_centered(
            surface, "Browse...", self.browse_btn_rect.center,
            parse_color(COLORS["text_primary"]), font_size=13,
        )

        # Separator
        sep_y = oy + 160
        pygame.draw.line(
            surface, parse_color(COLORS["hex_border"]),
            (ox, sep_y), (ox + self.screen.content_rect.width - 20, sep_y),
        )

        # Player controlled
        lbl3 = font.render("Control:", True, label_color)
        surface.blit(lbl3, (ox, oy + 168))
        self.player_controlled_cb.render(surface)

        # AI profile
        lbl4 = font.render("AI Profile:", True, label_color)
        surface.blit(lbl4, (ox, oy + 234))
        self.ai_dropdown.render(surface)

    def render_overlays(self, surface: pygame.Surface) -> None:
        self.ai_dropdown.render_dropdown(surface)
