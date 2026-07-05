"""Combat screen - the main gameplay view.

Composes GridView, token rendering, and UI panels into a
complete combat experience. Handles user interaction for
movement, action selection, and target selection.
"""

from __future__ import annotations

import math
from pathlib import Path

import pygame

from arena.combat.manager import CombatManager, CombatState, TurnPhase
from arena.combat.actions import is_in_range, AttackHitResult
from arena.models.actions import DamageRoll, DamageType
from arena.gui.rider_popup import RiderPopup, RiderChoice
from arena.gui.reroll_popup import RerollPopup, RerollChoice
from arena.gui.settings_popup import SettingsPopup
from arena.gui.bardic_popup import BardicInspirationPopup, BardicChoice
from arena.gui.reaction_popup import ReactionPopup, ReactionChoice
from arena.gui.counterspell_popup import CounterspellPopup, CounterspellChoice
from arena.models.character import OnHitRider, RiderTrigger
from arena.combat.riders import resolve_rider, RiderResult
from arena.gui.legendary_popup import LegendaryActionPopup
from arena.gui.lair_action_popup import LairActionPopup
from arena.gui.passenger_popup import PassengerPopup
from arena.combat.stat_modifiers import get_effective_armor_class, get_effective_speed
from arena.grid.aoe_shapes import is_emanating
from arena.grid.coordinates import HexCoord
from arena.grid.footprint import get_footprint_center_pixel, get_footprint_hex_count
from arena.gui.grid_view import GridView
from arena.gui.tokens import draw_token
from arena.gui.panels.initiative import InitiativePanel
from arena.gui.panels.log import CombatLogPanel
from arena.gui.panels.creature_info import CreatureInfoPanel
from arena.gui.radial_menu import RadialMenu, RadialMenuState
from arena.gui.popup_base import draw_modal_dim
from arena.gui.renderer import get_font, draw_hex_highlight
from arena.models.encounter import Encounter, TerrainType
from arena.util.constants import (
    COLORS, FONT_SIZES, LAYOUT, TERRAIN_NAMES, TOOLTIP_BG_RGBA, parse_color,
)
from arena.util.settings import get_settings

from arena.ai.controller import AIController, TurnPlan, TurnStep, TurnStepType
from arena.ai.executor import execute_step
from arena.combat.events import CombatEventType
from arena.gui.animation_cache import get_animation_frames, get_animation_fps
from arena.gui.animation_director import AnimationDirector, Beat
from arena.gui.visual_effects import (
    AoEBlastEffect, ZoneCreationPulse, ZoneDamageFlash,
    ZoneShimmerState, SpawnEffect,
    render_visual_effects, get_zone_shimmer_alpha,
    get_zone_flash_boost, get_damage_color,
)
from arena.gui.screens.base import Screen

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arena.gui.app import App


# Layout constants (sourced from the shared LAYOUT scale; built for 1280x720)
SIDE_PANEL_WIDTH = LAYOUT["side_panel_width"]
INITIATIVE_HEIGHT = LAYOUT["initiative_height"]
LOG_HEIGHT = LAYOUT["log_height"]

# Duration (ms) for the smooth hop animation between hexes.
MOVE_ANIM_DURATION_MS = 120

# Visual effect constants
FLASH_DURATION_MS = 200
FLOATING_TEXT_DURATION_MS = 900
FLOATING_TEXT_DRIFT_PX = 40
HP_LERP_SPEED = 0.15  # per-frame blend factor

# Action animation constants
ACTION_ANIM_BASE_SIZE = 64  # Base pixel size for animation frames (before zoom)
PROJECTILE_TRAVEL_MS = 300  # How long a ranged projectile travels before impact

# Animation sequencing (beat) constants
IMPACT_BEAT_MS = 250  # hold after an impact before the next beat plays
MELEE_IMPACT_DELAY_MS = 150  # swing wind-up before melee damage lands
TELEGRAPH_MS = 550  # AI AoE danger-zone telegraph before the cast plays
LUNGE_EXTENT = 0.45  # how far toward the target a charge lunge reaches
# NOTE (2026-07-02): OublietteDev tried 1.45 here and saw NO visible difference —
# the charge lunge may not be rendering at all. Deferred (his call, not
# worth delaying v1.0); when animation polish resumes, verify the lunge
# cue actually fires and draws before tuning this number.


@dataclass
class TelegraphState:
    """A pulsing danger-zone overlay for an incoming AI AoE."""

    hexes: list  # [(q, r), ...] — the blast's true shape from the engine
    color: tuple[int, int, int]
    spawn_time: int
    duration: int


@dataclass
class FloatingText:
    """A floating damage/healing number that drifts upward and fades out."""

    text: str
    world_x: float
    world_y: float
    color: tuple[int, int, int]
    spawn_time: int  # pygame.time.get_ticks()
    duration: int = FLOATING_TEXT_DURATION_MS


@dataclass
class ActiveAnimation:
    """A playing action/spell animation instance."""

    animation_name: str
    frames: list[pygame.Surface]
    fps: int
    spawn_time: int  # pygame.time.get_ticks()
    # Position (world coordinates)
    target_wx: float
    target_wy: float
    # For projectile mode (ranged attacks):
    source_wx: float | None = None
    source_wy: float | None = None
    is_projectile: bool = False
    projectile_duration_ms: int = PROJECTILE_TRAVEL_MS


class AITurnRunner:
    """Manages step-by-step execution of an AI TurnPlan with delays.

    Each step is executed after a configurable delay, so the player
    can watch the AI's actions unfold rather than seeing them all
    happen instantly.

    MOVE steps are expanded into individual per-hex sub-moves so the
    player can see the creature walk across the grid one hex at a time
    instead of teleporting to its destination.
    """

    def __init__(self) -> None:
        self._plan: TurnPlan | None = None
        self._step_index: int = 0
        self._next_step_time: int = 0  # pygame.time.get_ticks() target
        self._active: bool = False

        # Sub-step state for MOVE expansion (hex-by-hex walking)
        self._move_path: list | None = None  # list[HexCoord]
        self._move_path_index: int = 0

        # Optional callback fired after each successful hex move:
        # (creature_id: str, old_hex: HexCoord, new_hex: HexCoord) -> None
        self.on_move = None

    @property
    def is_active(self) -> bool:
        """Whether an AI turn is currently being executed."""
        return self._active

    def start(self, plan: TurnPlan) -> None:
        """Start executing a turn plan step by step."""
        self._plan = plan
        self._step_index = 0
        self._active = True
        self._move_path = None
        self._move_path_index = 0
        self._next_step_time = (
            pygame.time.get_ticks()
            + get_settings().gameplay.ai_thinking_delay
        )

    def update(self, manager: CombatManager, current_time: int) -> bool:
        """Advance execution if the delay has elapsed.

        Args:
            manager: The CombatManager to execute steps on.
            current_time: Current time from pygame.time.get_ticks().

        Returns:
            True if the plan finished executing this frame.
        """
        if not self._active or self._plan is None:
            return False

        if current_time < self._next_step_time:
            return False

        settings = get_settings()

        # --- Handle mid-path walking (MOVE sub-steps) ---
        if self._move_path is not None:
            return self._advance_move_substep(manager, current_time, settings)

        # Execute the current step
        if self._step_index >= len(self._plan.steps):
            self._active = False
            self._plan = None
            return True

        step = self._plan.steps[self._step_index]

        # Skip thinking steps when the setting is disabled
        if (
            step.step_type == TurnStepType.LOG_THINKING
            and not settings.gameplay.show_ai_thinking
        ):
            self._step_index += 1
            self._next_step_time = current_time
            return False

        # --- MOVE steps: expand into hex-by-hex sub-moves ---
        if step.step_type == TurnStepType.MOVE and step.target_hex is not None:
            path = self._compute_move_path(step, manager)
            if path and len(path) > 1:
                # Start walking: skip the first entry (current position)
                self._move_path = path
                self._move_path_index = 1  # index 0 is start pos
                return self._advance_move_substep(manager, current_time, settings)
            else:
                # No valid path or already there – fall through to normal exec
                execute_step(step, manager)
                self._step_index += 1
                self._next_step_time = current_time + settings.gameplay.ai_step_delay
                return False

        execute_step(step, manager)
        self._step_index += 1

        # Set delay for the next step
        if step.step_type == TurnStepType.LOG_THINKING:
            self._next_step_time = current_time + settings.gameplay.ai_thinking_delay
        elif step.step_type == TurnStepType.END_TURN:
            self._active = False
            self._plan = None
            return True
        else:
            self._next_step_time = current_time + settings.gameplay.ai_step_delay

        return False

    # ------------------------------------------------------------------
    # MOVE sub-step helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_move_path(step: TurnStep, manager: CombatManager) -> list | None:
        """Compute the hex path for a MOVE step.

        Returns the full path (list of HexCoord) including the start
        position, or ``None`` if pathfinding fails.
        """
        if step.target_hex is None:
            return None
        combatant = manager.active_combatant
        if combatant is None or combatant.position is None or manager.grid is None:
            return None

        from arena.grid.pathfinding import find_path

        target = HexCoord(step.target_hex[0], step.target_hex[1])
        path = find_path(
            combatant.position, target, manager.grid,
            creature_size=combatant.creature.size,
            creature_id=combatant.creature_id,
            dead_creature_ids=manager.movement.dead_creature_ids,
            blocked_hexes=manager.movement.blocked_hexes,
        )
        return path

    def _advance_move_substep(
        self,
        manager: CombatManager,
        current_time: int,
        settings,
    ) -> bool:
        """Move one hex along the pre-computed path.

        Returns True only if the entire plan finished this frame.
        """
        assert self._move_path is not None

        combatant = manager.active_combatant
        if combatant is None or not combatant.creature.is_conscious:
            # Creature was knocked out (e.g. opportunity attack) – abort path
            self._move_path = None
            self._step_index += 1
            self._next_step_time = current_time + settings.gameplay.ai_step_delay
            return False

        if self._move_path_index >= len(self._move_path):
            # Finished walking the path
            self._move_path = None
            self._step_index += 1
            self._next_step_time = current_time + settings.gameplay.ai_step_delay
            return False

        hex_coord = self._move_path[self._move_path_index]
        old_pos = combatant.position  # capture before move
        success = manager.try_move(hex_coord)
        self._move_path_index += 1

        # Move deferred for a player opportunity-attack decision: pause here
        # (the GUI shows the popup); the move for this hex completes when the
        # player answers, and the walk resumes from the next hex.
        if manager._pending_oa is not None:
            return False

        if not success or not combatant.creature.is_conscious:
            # Move blocked or creature downed – abort remaining path
            self._move_path = None
            self._step_index += 1
            self._next_step_time = current_time + settings.gameplay.ai_step_delay
            return False

        # Notify listener so the UI can animate the hop
        if self.on_move and old_pos is not None:
            self.on_move(combatant.creature_id, old_pos, hex_coord)

        # Schedule the next sub-step (delay must be >= animation duration)
        move_delay = max(MOVE_ANIM_DURATION_MS, settings.gameplay.ai_step_delay // 3)
        self._next_step_time = current_time + move_delay
        return False


class CombatScreen(Screen):
    """The main combat gameplay screen.

    Composes:
    - GridView (hex grid with pan/zoom, left portion)
    - InitiativePanel (top-right)
    - Creature info area (mid-right)
    - RadialMenu (right-click on active token)
    - CombatLogPanel (bottom)
    - Token rendering (overlaid on grid)
    """

    OWNS_MUSIC = True   # plays the encounter track; App must not resume menu music

    def __init__(self, screen_width: int, screen_height: int) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height

        # Combat state
        self.combat = CombatManager()
        # Interactive play: a player creature's opportunity attacks prompt
        # (Attack/Skip) instead of auto-firing.
        self.combat._oa_prompts_enabled = True

        # Calculate layout rectangles
        grid_w = screen_width - SIDE_PANEL_WIDTH
        grid_h = screen_height - LOG_HEIGHT

        self.grid_rect = pygame.Rect(0, 0, grid_w, grid_h)

        side_x = grid_w
        self.initiative_rect = pygame.Rect(
            side_x, 0, SIDE_PANEL_WIDTH, INITIATIVE_HEIGHT
        )
        self.info_rect = pygame.Rect(
            side_x,
            INITIATIVE_HEIGHT,
            SIDE_PANEL_WIDTH,
            grid_h - INITIATIVE_HEIGHT,
        )
        self.log_rect = pygame.Rect(
            0, grid_h, screen_width, LOG_HEIGHT
        )

        # Sub-components (GridView initialized after encounter loads)
        self.grid_view: GridView | None = None
        self.initiative_panel = InitiativePanel(self.initiative_rect)
        self.creature_info_panel = CreatureInfoPanel(self.info_rect)
        self.radial_menu = RadialMenu()
        self.log_panel = CombatLogPanel(self.log_rect)

        # AI system
        self.ai_controller = AIController(
            randomness=get_settings().gameplay.ai_randomness,
        )
        self.ai_runner = AITurnRunner()

        # Move animation state: creature_id -> (start_wx, start_wy, end_wx, end_wy, start_time_ms, duration_ms)
        self._move_animations: dict[str, tuple[float, float, float, float, int, int]] = {}
        self.ai_runner.on_move = self._on_creature_move

        # Visual combat effects
        self._last_event_index: int = 0  # Track processed combat log events
        self._display_hp: dict[str, float] = {}  # Animated HP per creature
        self._flash_until: dict[str, int] = {}  # Damage flash expiry per creature
        self._floating_texts: list[FloatingText] = []
        self._active_animations: list[ActiveAnimation] = []

        # Animation sequencing: attack visuals play as ordered beats
        # (travel/swing → impact) instead of all spawning in one frame.
        self._director = AnimationDirector()
        self._pending_impact: Beat | None = None  # open group's impact beat
        self._impact_source: str | None = None  # acting creature of that group
        self._pending_anim: Beat | None = None  # open group's swing/travel beat
        self._pending_anim_hold: int = 0  # that beat's pre-impact hold (ms)
        self._hp_credit: dict[str, int] = {}  # damage dealt but not yet shown
        self._downed_hold: set[str] = set()  # render upright until impact lands
        self._log_reveal_index: int = 0  # log lines visible so far (chronological)
        self._lunge_animations: dict[str, tuple] = {}  # charge lunge per creature
        self._active_telegraphs: list[TelegraphState] = []

        # Programmatic visual effects (code-drawn, not PNG frame sequences)
        self._visual_effects: list[AoEBlastEffect | ZoneCreationPulse | SpawnEffect] = []
        self._zone_shimmer_states: dict[str, ZoneShimmerState] = {}
        self._zone_damage_flashes: list[ZoneDamageFlash] = []

        # Player movement path state (hex-by-hex walking, like AI)
        self._player_move_path: list[HexCoord] | None = None
        self._player_move_index: int = 0
        self._player_move_next_time: int = 0

        # AI camera tracking: zoom to restore after ranged attack zoom-out
        self._ai_pre_attack_zoom: float | None = None

        # Interaction state
        self.selected_creature_id: str | None = None
        self._grid_owns_mouse: bool = False  # True when mouse-down started in grid
        self._hovered_creature_id: str | None = None  # For hover tooltip
        self._hovered_terrain_type: TerrainType | None = None  # For terrain tooltip
        self._show_shortcuts_help: bool = False
        self._encounter_name: str = "combat"  # For save file naming
        self._music_track: str | None = None  # Encounter music track filename
        self._played_end_sound: bool = False  # Track if victory/defeat sound played
        self._pending_help: bool = False  # True when selecting ally for Help action
        self._pending_stabilize: bool = False  # True when selecting dying ally to Stabilize
        self._pending_zone_move: bool = False  # True when selecting hex for zone move
        self._zone_move_cost: str | None = None  # "action" or "bonus_action"
        self._zone_move_range: int = 60  # Max range for zone move
        self._zone_move_radius: int = 5  # Zone AoE radius in feet for preview
        self._pending_summon: bool = False  # True when placing a summoned creature
        self._pending_teleport: bool = False  # True when selecting teleport destination
        self._pending_shove: bool = False  # True when selecting enemy for Shove
        self._pending_grapple: bool = False  # True when selecting enemy for Grapple
        # Wall placement (D-WALL-1): two-click line drawing. First click anchors
        # one end, second click sets the far end; the wall is the hex line
        # between them, capped at the spell's length.
        self._pending_wall: bool = False
        self._wall_anchor: HexCoord | None = None

        # Multi-dart volley aiming (RAW Magic Missile: one click per dart,
        # repeats allowed; fires once every dart has a target)
        self._volley_targets: list[str] = []
        self._volley_action_name: str | None = None

        # Passenger selection popup state (Dimension Door)
        self._passenger_popup: PassengerPopup | None = None
        self._pending_passenger_id: str | None = None

        # On-hit rider popup state
        self._rider_popup: RiderPopup | None = None
        self._pending_rider_hit: AttackHitResult | None = None
        self._rider_queue: list[tuple] = []  # Remaining (Feature, OnHitRider) to offer
        self._accumulated_rider_results: list[RiderResult] = []

        # Damage reduction reaction popup state
        self._reaction_popup: ReactionPopup | None = None

        # Shove choice popup state
        self._shove_popup = None  # ShoveChoicePopup | None
        self._shove_target_id: str | None = None

        # Ready action popup state (D-ACT-1)
        self._ready_popup = None  # ReadyPopup | None

        # Legendary action popup state
        self._legendary_popup: LegendaryActionPopup | None = None
        self._legendary_selected_action = None  # Action chosen, awaiting target

        # Lair action popup state
        self._lair_popup: LairActionPopup | None = None

        # Forced save reroll popup state
        self._reroll_popup: RerollPopup | None = None

        # Bardic Inspiration spend popup state
        self._bardic_popup: BardicInspirationPopup | None = None

        # Opportunity-attack prompt state (player reactor chooses Attack/Skip)
        self._oa_popup = None

        # Counterspell popup state
        self._counterspell_popup: CounterspellPopup | None = None

        # Options popup (battle-map opacity + music volume sliders) and the
        # clickable "O options" corner nudge that opens it
        self._settings_popup: SettingsPopup | None = None
        self._options_rect: pygame.Rect | None = None

        self.app: App | None = None

        # Handoff mode: when The Arena is launched as a subprocess to resolve ONE
        # encounter for Oubliette, there is no menu to return to — ESC (and any
        # other exit gesture) ends the process, and the caller reads the result
        # the run writes out. Off for normal standalone play.
        self.handoff_mode: bool = False

    def on_enter(self, app: App) -> None:
        """Store app reference for navigation (e.g., ESC to main menu)."""
        self.app = app

    def load_encounter(self, encounter: Encounter, data_dir: Path) -> None:
        """Load an encounter and set up the combat screen.

        Args:
            encounter: The encounter to load.
            data_dir: Base directory for resolving creature file paths.
        """
        self._encounter_name = encounter.name
        self._music_track = encounter.music_track
        self.combat.load_encounter(encounter, data_dir)

        # Start encounter music if the Forge defined a track; otherwise play
        # nothing (and stop anything left over, so silence stays silence).
        from arena.audio.manager import get_sound_manager
        if self._music_track:
            get_sound_manager().play_music(self._music_track)
        else:
            get_sound_manager().stop_music()

        # Create grid view from combat's grid
        self.grid_view = GridView(
            self.combat.grid,
            self.grid_rect.width,
            self.grid_rect.height,
            origin=(self.grid_rect.x, self.grid_rect.y),
        )

        # Apply encounter background image
        if encounter.background_image:
            bg_path = (
                Path("assets") / "ui" / "encounter backgrounds"
                / encounter.background_image
            )
            self.grid_view.set_background(bg_path)
            self.grid_view.set_background_transform(
                encounter.background_offset, encounter.background_scale,
            )

        # Connect panels to combat manager
        self.initiative_panel.set_combat(self.combat)
        self.creature_info_panel.set_combat(self.combat)
        self.radial_menu.set_combat(self.combat)
        self.log_panel.set_log(self.combat.log)
        self.log_panel.team_resolver = self._log_team_for

        # Roll initiative and start combat
        self.combat.roll_initiative()
        self.combat.begin_combat()

        # Skip existing log events so they don't replay as visual effects
        self._last_event_index = len(self.combat.log.events)
        self._visual_effects.clear()
        self._zone_shimmer_states.clear()
        self._zone_damage_flashes.clear()
        self._director.clear(pygame.time.get_ticks())
        self._pending_impact = None
        self._impact_source = None
        self._pending_anim = None
        self._hp_credit.clear()
        self._downed_hold.clear()
        self._lunge_animations.clear()
        self._active_telegraphs.clear()
        self._log_reveal_index = len(self.combat.log.events)
        self.log_panel.reveal_count = self._log_reveal_index

        # Select the first active creature
        active = self.combat.active_combatant
        if active:
            self._select_creature_by_id(active.creature_id)

        # Check if the first turn is an AI turn
        self._check_ai_turn()

    def _log_team_for(self, creature_id: str) -> str | None:
        """Resolve a log event's source creature to its team (actor chips)."""
        combatant = self.combat.get_creature(creature_id) if self.combat else None
        return combatant.team if combatant is not None else None

    def handle_event(self, event: pygame.event.Event) -> None:
        """Process events, delegating to sub-components."""
        # --- Options popup (sliders) intercepts ALL input when open ---
        if self._settings_popup is not None:
            if self._settings_popup.handle_event(event) == "__close__":
                self._settings_popup = None
            return

        # --- Lair action popup intercepts input when open ---
        if self._lair_popup is not None:
            result = self._lair_popup.handle_event(event)
            if result is not None:
                self._resolve_lair_popup(result)
            else:
                self._forward_camera_event(event)
            return

        # --- Legendary action popup intercepts most input when open ---
        if self._legendary_popup is not None:
            result = self._legendary_popup.handle_event(event)
            if result is not None:
                self._resolve_legendary_popup(result)
            else:
                # Allow camera pan/zoom while popup is open
                self._forward_camera_event(event)
            return

        # --- Legendary targeting mode: click a creature to target ---
        if self._legendary_selected_action is not None:
            self._handle_legendary_target_event(event)
            # Allow camera pan/zoom during target selection
            self._forward_camera_event(event)
            return

        # --- Counterspell popup intercepts ALL input when open ---
        if self._counterspell_popup is not None:
            choice = self._counterspell_popup.handle_event(event)
            if choice is not None:
                self._resolve_counterspell_popup(choice)
            return

        # --- Opportunity-attack popup intercepts ALL input when open ---
        if self._oa_popup is not None:
            choice = self._oa_popup.handle_event(event)
            if choice is not None:
                self._resolve_oa_choice(choice)
            return

        # --- Reaction popup intercepts ALL input when open ---
        if self._reaction_popup is not None:
            choice = self._reaction_popup.handle_event(event)
            if choice is not None:
                self._resolve_reaction_choice(choice)
            return

        # --- Rider popup intercepts ALL input when open ---
        if self._rider_popup is not None:
            choice = self._rider_popup.handle_event(event)
            if choice is not None:
                self._resolve_rider_choice(choice)
            return

        # --- Reroll popup intercepts ALL input when open ---
        if self._reroll_popup is not None:
            choice = self._reroll_popup.handle_event(event)
            if choice is not None:
                self._resolve_reroll_choice(choice)
            return

        # --- Bardic Inspiration popup intercepts ALL input when open ---
        if self._bardic_popup is not None:
            choice = self._bardic_popup.handle_event(event)
            if choice is not None:
                self._resolve_bardic_choice(choice)
            return

        # --- Shove choice popup intercepts ALL input when open ---
        if self._shove_popup is not None:
            result = self._shove_popup.handle_event(event)
            if result is not None:
                if result == "__close__":
                    self._shove_popup = None
                    self._shove_target_id = None
                    self.combat.turn_phase = TurnPhase.AWAITING_ACTION
                else:
                    # result is "push" or "prone"
                    target_id = self._shove_target_id
                    self._shove_popup = None
                    self._shove_target_id = None
                    if target_id:
                        self.combat.execute_shove(target_id, shove_choice=result)
                    self.combat.turn_phase = TurnPhase.AWAITING_ACTION
            return

        # --- Ready action popup intercepts ALL input when open ---
        if self._ready_popup is not None:
            result = self._ready_popup.handle_event(event)
            if result == "__close__":
                self._ready_popup = None
            elif result == "__ready__":
                action = self._ready_popup.selected_action
                trigger = self._ready_popup.selected_trigger
                self._ready_popup = None
                if action is not None and trigger is not None:
                    self.combat.execute_ready_action(
                        action, trigger, None, "")
            return

        # --- Passenger selection popup intercepts ALL input when open ---
        if self._passenger_popup is not None:
            result = self._passenger_popup.handle_event(event)
            if result is not None:
                self._resolve_passenger_popup(result)
            return

        # Corner "O options" affordance opens the sliders popup
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._options_rect is not None
                and self._options_rect.collidepoint(event.pos)):
            self._settings_popup = SettingsPopup(self.screen_width, self.screen_height)
            return

        # ESC: close radial menu first, else return to main menu
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.radial_menu.state != RadialMenuState.CLOSED:
                self.radial_menu.close()
                return
            if self.app is not None:
                if self.handoff_mode:
                    self.app.quit()   # subprocess play: ESC ends the session
                else:
                    self.app.go_to_main_menu()
            return

        # Keyboard shortcuts (some work even when combat ended)
        if event.type == pygame.KEYDOWN:
            if self._handle_keyboard_shortcut(event):
                return

        if self.combat.state == CombatState.COMBAT_ENDED:
            return  # No interaction after combat ends

        # Block player input during AI turns (except log scrolling)
        if self.ai_runner.is_active:
            self.log_panel.handle_event(event)
            return

        # Block player input while player creature is walking
        if self._player_move_path is not None:
            self.log_panel.handle_event(event)
            return

        # Right-click: toggle radial menu on active creature's token
        if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            self._handle_right_click(event)
            return

        # Radial menu gets priority when open
        if self.radial_menu.state != RadialMenuState.CLOSED:
            menu_result = self.radial_menu.handle_event(event)
            if menu_result is not None:
                self._handle_radial_result(menu_result)
                return
            # The wheel belongs to the menu while it's open (sub-popup
            # lists scroll with it) — never let it also zoom the grid,
            # or scrolling a long spell list zooms the battle all the
            # way out underneath the popup.
            if event.type == pygame.MOUSEWHEEL:
                return
            # Swallow clicks inside the menu area
            if event.type in (
                pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP
            ) and hasattr(event, "pos"):
                if self.radial_menu.contains_point(event.pos):
                    return
            # Left-click outside the menu closes it (swallow the click)
            if (
                event.type == pygame.MOUSEBUTTONUP
                and event.button == 1
                and hasattr(event, "pos")
                and not self.radial_menu.contains_point(event.pos)
            ):
                self.radial_menu.close()
                self._grid_owns_mouse = False
                if self.grid_view:
                    self.grid_view._mouse_button_held = False
                    self.grid_view._is_dragging = False
                    self.grid_view._drag_start = None
                return  # Swallow the click so it doesn't cause movement

            # Swallow MOUSEBUTTONDOWN outside the menu to prevent
            # the grid from starting a drag while the menu is open.
            if (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and hasattr(event, "pos")
                and not self.radial_menu.contains_point(event.pos)
            ):
                return

        # Initiative panel (click to select creature)
        init_result = self.initiative_panel.handle_event(event)
        if init_result:
            self._select_creature_by_id(init_result)
            return

        # Log panel (scroll) and creature info panel (scroll)
        self.log_panel.handle_event(event)
        self.creature_info_panel.handle_event(event)

        # Grid interaction
        if self.grid_view:
            # Track whether the grid "owns" the current mouse press.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.grid_rect.collidepoint(event.pos):
                    self._grid_owns_mouse = True
                else:
                    self._grid_owns_mouse = False

            is_mouse_button = event.type in (
                pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP
            )

            # Only forward scroll-wheel to the grid when the cursor
            # is actually inside the grid area.  This prevents the
            # camera from zooming when the user scrolls the combat
            # log, creature-info panel, or any other non-grid panel.
            if event.type == pygame.MOUSEWHEEL:
                mouse_pos = pygame.mouse.get_pos()
                if not self.grid_rect.collidepoint(mouse_pos):
                    pass  # Swallow — don't send to grid view
                else:
                    self.grid_view.handle_event(event)
            elif is_mouse_button and not self._grid_owns_mouse:
                pass
            else:
                was_dragging = self.grid_view._is_dragging

                self.grid_view.handle_event(event)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self._grid_owns_mouse = False
                    if self.grid_rect.collidepoint(event.pos):
                        if not was_dragging:
                            self._handle_grid_click(event)

    def _handle_grid_click(self, event: pygame.event.Event) -> None:
        """Handle a left-click on the grid area during combat."""
        if self.grid_view is None or self.combat.grid is None:
            return

        clicked_hex = self.grid_view._screen_to_hex(event.pos[0], event.pos[1])
        if clicked_hex is None:
            return

        combatant = self.combat.active_combatant
        if combatant is None:
            return

        # SELECTING_TARGET: try to attack/use action on clicked creature
        if self.combat.turn_phase == TurnPhase.SELECTING_TARGET:
            selected = self.combat.selected_action

            # ── Zone move mode: click any hex to reposition zone ────
            if self._pending_zone_move:
                from arena.grid.footprint import min_distance_between
                dist_feet = min_distance_between(
                    combatant.position, combatant.creature.size,
                    clicked_hex, 1,
                ) * 5
                if dist_feet <= self._zone_move_range:
                    self._pending_zone_move = False
                    cost = self._zone_move_cost or "action"
                    self.combat.move_zone(clicked_hex, cost)
                    self.combat.turn_phase = TurnPhase.AWAITING_ACTION
                return

            # ── Summon placement: click empty hex to place creature ──
            if self._pending_summon:
                cell = self.combat.grid.get_cell(clicked_hex)
                if cell and cell.occupant_id is None:
                    self._pending_summon = False
                    self.combat.execute_summon(clicked_hex)
                return

            # ── Teleport destination: click valid hex to teleport ────
            if self._pending_teleport:
                action = self.combat.selected_action
                if action and action.teleport_range is not None:
                    from arena.grid.footprint import min_distance_between
                    dist_feet = min_distance_between(
                        combatant.position, combatant.creature.size,
                        clicked_hex, 1,
                    ) * 5
                    cell = self.combat.grid.get_cell(clicked_hex)
                    if (
                        dist_feet <= action.teleport_range
                        and cell is not None
                        and self.combat.grid.is_passable(clicked_hex)
                        and cell.occupant_id is None
                    ):
                        self._pending_teleport = False
                        self.combat.execute_teleport(
                            clicked_hex,
                            passenger_id=self._pending_passenger_id,
                        )
                        self._pending_passenger_id = None
                return

            # ── Wall placement: two clicks define a line (D-WALL-1) ──
            if self._pending_wall:
                action = self.combat.selected_action
                if action is None or not action.is_wall:
                    self._pending_wall = False
                    self._wall_anchor = None
                    return
                from arena.grid.footprint import min_distance_between
                dist_feet = min_distance_between(
                    combatant.position, combatant.creature.size, clicked_hex, 1,
                ) * 5
                if self._wall_anchor is None:
                    # First click: anchor one end of the wall (within range).
                    if dist_feet <= action.range:
                        self._wall_anchor = clicked_hex
                    return
                # Second click: draw the wall from the anchor toward here
                # (execute_wall_line caps it at the spell's length).
                self.combat.execute_wall_line(self._wall_anchor, clicked_hex)
                self._pending_wall = False
                self._wall_anchor = None
                self.combat.turn_phase = TurnPhase.AWAITING_ACTION
                self._check_pending_counterspell()
                return

            # ── AoE hex placement (area_* target types) ─────────────
            if (
                selected
                and selected.target_type.value.startswith("area_")
                and not selected.attack
            ):
                # Zone-following spells (Spirit Guardians) cast immediately
                # centered on the caster — no hex-click needed.
                if (
                    selected.zone_follows_caster
                    and self.combat._is_zone_creating_spell(selected)
                ):
                    self.combat.execute_effect_at_hex(
                        combatant.position,
                        clicked_target_id=combatant.creature_id,
                    )
                    self._check_pending_counterspell()
                    return

                from arena.grid.footprint import min_distance_between

                dist_feet = min_distance_between(
                    combatant.position, combatant.creature.size,
                    clicked_hex, 1,
                ) * 5
                # Line/cone aim by DIRECTION: the click points the shape and is
                # gated by its length (area_size), not a placement range (these
                # are usually range 0). Placed shapes gate by range as before.
                reach = ((selected.area_size or selected.range)
                         if is_emanating(selected) else selected.range)
                if dist_feet <= reach:
                    cell = self.combat.grid.get_cell(clicked_hex)
                    clicked_id = cell.occupant_id if cell else None
                    self.combat.execute_effect_at_hex(clicked_hex, clicked_target_id=clicked_id)
                    self._check_pending_counterspell()
                # Out of range — do nothing (don't cancel)
                return

            cell = self.combat.grid.get_cell(clicked_hex)
            if cell and cell.occupant_id:
                target_id = cell.occupant_id

                # Stabilize action — click an adjacent dying ally
                if self._pending_stabilize:
                    self._pending_stabilize = False
                    self.combat.turn_phase = TurnPhase.AWAITING_ACTION
                    self.combat.execute_standard_action("stabilize", target_id)
                    return

                # Help action — click an ally to grant advantage
                if self._pending_help:
                    self._pending_help = False
                    self.combat.turn_phase = TurnPhase.AWAITING_ACTION
                    self.combat.execute_standard_action("help", target_id)
                    return

                # Shove — click an adjacent enemy to show choice popup
                if self._pending_shove:
                    target_c = self.combat.combatants.get(target_id)
                    if (
                        target_c
                        and target_c.team != combatant.team
                        and target_id != combatant.creature_id
                    ):
                        from arena.grid.footprint import min_distance_between
                        dist = min_distance_between(
                            combatant.position, combatant.creature.size,
                            target_c.position, target_c.creature.size,
                        )
                        if dist <= 1:
                            from arena.gui.shove_popup import ShoveChoicePopup
                            self._shove_popup = ShoveChoicePopup(
                                target_c.creature.name,
                                screen_width=self.screen_width,
                                screen_height=self.screen_height,
                            )
                            # Position near the clicked hex
                            hx, hy = clicked_hex.to_pixel(get_settings().display.default_hex_size)
                            sx_pos, sy_pos = self.grid_view.camera.world_to_screen(hx, hy)
                            self._shove_popup.reposition((
                                int(sx_pos + self.grid_view.origin[0]),
                                int(sy_pos + self.grid_view.origin[1]),
                            ))
                            self._shove_target_id = target_id
                            self._pending_shove = False
                    return

                # Grapple — click an adjacent enemy to seize it (no popup)
                if self._pending_grapple:
                    target_c = self.combat.combatants.get(target_id)
                    if (
                        target_c
                        and target_c.team != combatant.team
                        and target_id != combatant.creature_id
                    ):
                        from arena.grid.footprint import min_distance_between
                        dist = min_distance_between(
                            combatant.position, combatant.creature.size,
                            target_c.position, target_c.creature.size,
                        )
                        if dist <= 1:
                            self._pending_grapple = False
                            self.combat.turn_phase = TurnPhase.AWAITING_ACTION
                            self.combat.execute_grapple(target_id)
                    return

                if selected and selected.attack is not None:
                    # Attack action — cannot target self
                    if target_id != combatant.creature_id:
                        self._execute_player_attack(target_id)
                        self._check_pending_counterspell()
                        return
                else:
                    # Non-attack effect (potion, scroll, etc.) — self OK
                    self.combat.execute_effect(target_id)
                    self._check_pending_counterspell()
                    self._check_pending_reroll()
                    return
            # Clicking empty hex cancels target selection
            if self._pending_help:
                self._pending_help = False
            if self._pending_stabilize:
                self._pending_stabilize = False
            if self._pending_shove:
                self._pending_shove = False
            if self._pending_grapple:
                self._pending_grapple = False
            self._pending_teleport = False
            self._pending_passenger_id = None
            self._passenger_popup = None
            self._volley_targets = []          # forfeit half-aimed darts
            self._volley_action_name = None
            self.combat.cancel_action()
            return

        # AWAITING_ACTION: move or select
        if self.combat.turn_phase == TurnPhase.AWAITING_ACTION:
            cell = self.combat.grid.get_cell(clicked_hex)

            # Clicking on an occupied hex selects that creature for info
            if cell and cell.occupant_id:
                self._select_creature_by_id(cell.occupant_id)
                return

            # Clicking on an empty hex: try to move the active creature
            if self.combat.movement.remaining_movement > 0:
                reachable = self.combat.movement.get_reachable(
                    self.combat.grid, combatant.creature.size,
                    anchor_position=combatant.position,
                )
                if (clicked_hex.q, clicked_hex.r) in reachable:
                    from arena.grid.pathfinding import find_path

                    cur_pos = combatant.position
                    if cur_pos is None:
                        return
                    path = find_path(
                        cur_pos, clicked_hex, self.combat.grid,
                        creature_size=combatant.creature.size,
                        creature_id=combatant.creature_id,
                        dead_creature_ids=self.combat.movement.dead_creature_ids,
                        blocked_hexes=self.combat.movement.blocked_hexes,
                    )
                    if path and len(path) > 1:
                        self._player_move_path = path
                        self._player_move_index = 1
                        self._player_move_next_time = pygame.time.get_ticks()
                    elif path and len(path) == 1:
                        # Already there – nothing to do
                        pass
                    return

    # ------------------------------------------------------------------
    # On-hit rider two-phase attack flow
    # ------------------------------------------------------------------

    def _execute_player_attack(self, target_id: str) -> None:
        """Execute a player attack with rider popups if eligible.

        Phase 1: Roll to hit.
        If the hit lands and the creature has applicable on-hit riders,
        resolve AUTOMATIC riders silently, then show RiderPopup for
        each POST_HIT rider sequentially. Otherwise, complete immediately.

        Multi-dart volleys (Magic Missile, Scorching Ray) aim one dart
        per click — RAW splitting, repeats allowed — then fire the whole
        volley through execute_attack, which owns the per-volley loop
        and slot accounting. On-hit rider popups don't apply to spell
        volleys (smites require weapon attacks).
        """
        from arena.combat.actions import get_effective_target_count
        from arena.combat.events import CombatEvent, CombatEventType

        action = self.combat.selected_action
        if action is not None:
            count = get_effective_target_count(action, self.combat._cast_level)
            if count > 1:
                if self._volley_action_name != action.name:
                    # New volley (or a different spell) — start fresh
                    self._volley_targets = []
                    self._volley_action_name = action.name
                self._volley_targets.append(target_id)
                aimed = len(self._volley_targets)
                if aimed < count:
                    tc = self.combat.combatants.get(target_id)
                    tname = tc.creature.name if tc else target_id
                    self.combat.log.add(CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=(
                            f"{action.name}: dart {aimed} of {count} aimed "
                            f"at {tname} — choose the next target."
                        ),
                        source_id=self.combat.active_combatant.creature_id
                        if self.combat.active_combatant else None,
                    ))
                    return  # stay in targeting — more darts to aim
                targets = list(self._volley_targets)
                self._volley_targets = []
                self._volley_action_name = None
                self.combat.execute_attack(target_id, volley_targets=targets)
                return

        hit_result = self.combat.execute_attack_hit_check(target_id)
        if hit_result is None:
            return

        if not hit_result.hit:
            # A player miss with a flippable banked die → offer the spend/skip
            # popup (shown via the per-frame poll); otherwise finalize the miss.
            if self.combat.maybe_defer_bardic(hit_result):
                return
            self.combat.complete_attack(hit_result)
            return

        # Discover applicable riders
        riders = self.combat.get_applicable_riders(hit_result)
        if not riders:
            self.combat.complete_attack(hit_result)
            return

        # Separate automatic vs player-choice riders
        auto_results: list[RiderResult] = []
        post_hit_riders: list[tuple] = []

        for feature, rider in riders:
            if rider.trigger == RiderTrigger.AUTOMATIC:
                # Resolve silently
                rr = resolve_rider(
                    feature, rider,
                    hit_result.attacker, hit_result.target,
                )
                auto_results.append(rr)
            else:
                post_hit_riders.append((feature, rider))

        if not post_hit_riders:
            # Only automatic riders — complete immediately
            self.combat.complete_attack(hit_result, rider_results=auto_results)
            return

        # Store state and start the rider popup queue
        self._pending_rider_hit = hit_result
        self._accumulated_rider_results = auto_results
        self._rider_queue = post_hit_riders
        self._show_next_rider_popup()

    def _show_next_rider_popup(self) -> None:
        """Pop the next POST_HIT rider from the queue and show its popup."""
        if not self._rider_queue:
            # Queue exhausted — complete the attack
            hit_result = self._pending_rider_hit
            results = self._accumulated_rider_results
            self._rider_popup = None
            self._pending_rider_hit = None
            self._rider_queue = []
            self._accumulated_rider_results = []
            if hit_result is not None:
                self.combat.complete_attack(
                    hit_result, rider_results=results,
                )
            return

        feature, rider = self._rider_queue.pop(0)
        hit_result = self._pending_rider_hit
        if hit_result is None or hit_result.attacker is None:
            return

        self._rider_popup = RiderPopup(
            feature, rider, hit_result.attacker,
            self.screen_width, self.screen_height,
        )
        self._rider_popup.reposition((
            self.screen_width // 2, self.screen_height // 2,
        ))

    def _resolve_rider_choice(self, choice: RiderChoice) -> None:
        """Handle a RiderPopup result and advance the queue."""
        self._rider_popup = None
        hit_result = self._pending_rider_hit

        if hit_result is None or hit_result.attacker is None:
            return

        if choice.used:
            # Find the rider config from the feature name
            features = getattr(hit_result.attacker, "features", []) or []
            special = getattr(hit_result.attacker, "special_abilities", []) or []
            rider = None
            feature = None
            for f in list(features) + list(special):
                if f.name == choice.feature_name and f.on_hit_rider:
                    feature = f
                    rider = f.on_hit_rider
                    break

            if feature and rider:
                rr = resolve_rider(
                    feature, rider,
                    hit_result.attacker, hit_result.target,
                    slot_level=choice.slot_level,
                )
                self._accumulated_rider_results.append(rr)

        # Show next rider or complete
        self._show_next_rider_popup()

    # ------------------------------------------------------------------
    # Forced save reroll popup (Indomitable, Lucky, Diamond Soul)
    # ------------------------------------------------------------------

    def _check_pending_reroll(self) -> None:
        """Check if the combat manager has a pending save reroll and show popup."""
        pending = self.combat._pending_save_reroll
        if pending is None:
            return
        tc = self.combat.combatants.get(pending.target_id)
        if tc is None:
            self.combat.resolve_save_reroll_choice(None)
            return
        sw = getattr(self, 'screen_width', 1280)
        sh = getattr(self, 'screen_height', 720)
        self._reroll_popup = RerollPopup(
            creature_name=tc.creature.name,
            save_ability=pending.save_ability,
            original_roll=pending.original_roll,
            save_dc=pending.save_dc,
            features=pending.features,
            creature=tc.creature,
            screen_width=sw,
            screen_height=sh,
        )
        # Centered (GridView has no hex_to_screen — the old grid-relative call
        # crashed; the reaction popup centers too).
        self._reroll_popup.reposition((sw // 2, sh // 2))

    def _resolve_reroll_choice(self, choice: RerollChoice) -> None:
        """Handle a RerollPopup result."""
        self._reroll_popup = None
        feature_name = choice.feature_name if choice.used else None
        self.combat.resolve_save_reroll_choice(feature_name)

    # ------------------------------------------------------------------
    # Bardic Inspiration spend popup (player attacker, missed)
    # ------------------------------------------------------------------

    def _check_pending_bardic(self) -> None:
        """Show the popup if the manager has a pending Bardic Inspiration choice."""
        pending = self.combat._pending_bardic_choice
        if pending is None:
            return
        hit_result = pending["hit_result"]
        attacker_c = self.combat.combatants.get(hit_result.attacker_id)
        attacker_name = attacker_c.creature.name if attacker_c else "Attacker"
        sw = getattr(self, "screen_width", 1280)
        sh = getattr(self, "screen_height", 720)
        self._bardic_popup = BardicInspirationPopup(
            attacker_name=attacker_name,
            die_size=pending["die_size"],
            total_roll=hit_result.total_roll,
            target_ac=hit_result.target_ac,
            screen_width=sw,
            screen_height=sh,
        )
        self._bardic_popup.reposition((sw // 2, sh // 2))

    def _resolve_bardic_choice(self, choice: BardicChoice) -> None:
        """Handle a BardicInspirationPopup result."""
        self._bardic_popup = None
        self.combat.resolve_bardic_choice(choice.use)

    # ------------------------------------------------------------------
    # Damage reduction reaction (Parry, Uncanny Dodge, Deflect Missiles)
    # ------------------------------------------------------------------

    def _show_reaction_popup(self) -> None:
        """Show the ReactionPopup for a player-controlled target's DR."""
        pending = self.combat._pending_damage_reduction
        if pending is None:
            return

        target_id = pending["target_id"]
        target_c = self.combat.combatants.get(target_id)
        if target_c is None:
            # No target -- skip
            self.combat.resolve_damage_reduction_choice(None)
            return

        target_name = target_c.creature.name
        options = pending["options"]

        self._reaction_popup = ReactionPopup(
            target_name=target_name,
            options=options,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )
        self._reaction_popup.reposition((
            self.screen_width // 2, self.screen_height // 2,
        ))

    def _resolve_reaction_choice(self, choice: ReactionChoice) -> None:
        """Handle a ReactionPopup result."""
        self._reaction_popup = None
        feature_name = choice.feature_name if choice.used else None
        self.combat.resolve_damage_reduction_choice(feature_name)

    # ------------------------------------------------------------------
    # Opportunity-attack prompt
    # ------------------------------------------------------------------

    def _show_oa_popup(self) -> None:
        """Show the Attack/Skip prompt for the front of the pending OA queue."""
        from arena.gui.oa_popup import OpportunityAttackPopup
        pending = self.combat._pending_oa
        if pending is None or not pending["queue"]:
            return
        reactor_id, reactor, _action = pending["queue"][0]
        mover = self.combat.combatants.get(pending["mover_id"])
        self._oa_popup = OpportunityAttackPopup(
            reactor_name=reactor.creature.name,
            mover_name=mover.creature.name if mover else "the enemy",
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )
        self._oa_popup.reposition((self.screen_width // 2, self.screen_height // 2))

    def _resolve_oa_choice(self, make_attack: bool) -> None:
        """Apply the player's Attack/Skip choice and clear the popup. If more
        reactors are queued, the next is shown on the following frame."""
        self._oa_popup = None
        self.combat.resolve_opportunity_attack_choice(make_attack)

    # ------------------------------------------------------------------
    # Counterspell reaction popup
    # ------------------------------------------------------------------

    def _check_pending_counterspell(self) -> None:
        """Check if the combat manager has a pending counterspell and show popup."""
        pending = self.combat._pending_counterspell
        if pending is None:
            return
        counterspellers = pending["counterspellers"]
        if not counterspellers:
            self.combat._pending_counterspell = None
            return
        cid, combatant, cs_action = counterspellers[0]
        action = pending["action"]
        spell_level = pending["cast_level"] or action.spell_level or 0
        from arena.combat.riders import get_available_spell_slots
        available_slots = get_available_spell_slots(combatant.creature)
        cs_base = cs_action.spell_level or 3
        valid_slots = {
            lvl: cnt for lvl, cnt in available_slots.items()
            if lvl >= cs_base and cnt > 0
        }
        if not valid_slots:
            self.combat._pending_counterspell = None
            return
        self._counterspell_popup = CounterspellPopup(
            spell_name=action.name,
            spell_level=spell_level,
            counterspeller_name=combatant.creature.name,
            counterspeller_id=cid,
            available_slots=valid_slots,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )
        self._counterspell_popup.reposition((
            self.screen_width // 2, self.screen_height // 2,
        ))

    def _resolve_counterspell_popup(self, choice: CounterspellChoice) -> None:
        """Handle a CounterspellPopup result."""
        self._counterspell_popup = None
        pending = self.combat._pending_counterspell
        if pending is None:
            return
        countered, _events = self.combat.resolve_counterspell_choice(
            choice.counterspeller_id, choice.cast_level,
        )
        if countered:
            caster = self.combat.combatants.get(pending["caster_id"])
            if caster is not None:
                action = pending["action"]
                cast_level = pending["cast_level"]
                from arena.combat.actions import deduct_resource_cost
                deduct_resource_cost(caster.creature, action, cast_level=cast_level)
                self.combat._mark_action_type_used(action)
                from arena.combat.events import CombatEvent, CombatEventType
                evt = CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{caster.creature.name}'s {action.name} is countered!",
                    source_id=caster.creature_id,
                    details={"counterspelled": True},
                )
                self.combat.log.add(evt)
            self.combat.selected_action = None
            self.combat._cast_level = None
            self.combat.turn_phase = TurnPhase.AWAITING_ACTION
            return
        # Not countered — resume the spell
        method = pending["method"]
        if method == "attack":
            target_id = pending["target_id"]
            volley = pending.get("volley_targets")
            if volley:
                # The volley was fully aimed before the counterspell check —
                # resume it directly, don't re-enter dart aiming.
                self.combat.execute_attack(target_id, volley_targets=volley)
            else:
                self._execute_player_attack(target_id)
        elif method == "effect":
            target_id = pending["target_id"]
            self.combat.execute_effect(target_id)
            self._check_pending_reroll()
        elif method == "effect_at_hex":
            target_hex = pending["target_hex"]
            clicked_target_id = pending.get("clicked_target_id")
            self.combat.execute_effect_at_hex(
                target_hex, clicked_target_id=clicked_target_id,
            )

    # ------------------------------------------------------------------
    # Passenger selection (Dimension Door)
    # ------------------------------------------------------------------

    def _try_show_passenger_popup(self, action) -> None:
        """Show the passenger popup if adjacent allies exist, else go solo."""
        active = self.combat.active_combatant
        if active is None or active.position is None:
            self._pending_teleport = True
            return

        candidate_ids = self.combat._find_passenger_candidates(
            active.creature_id, active.position,
        )
        if not candidate_ids:
            # No one to bring — skip popup, go straight to destination
            self._pending_teleport = True
            return

        candidates: list[tuple[str, str]] = []
        for cid in candidate_ids:
            c = self.combat.combatants.get(cid)
            if c:
                candidates.append((cid, c.creature.name))

        self._passenger_popup = PassengerPopup(
            candidates,
            caster_name=active.creature.name,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
        )
        self._passenger_popup.reposition((
            self.screen_width // 2, self.screen_height // 2,
        ))

    def _resolve_passenger_popup(self, result: str) -> None:
        """Handle the PassengerPopup result: passenger chosen or solo."""
        self._passenger_popup = None

        if result == "__solo__":
            self._pending_passenger_id = None
        else:
            self._pending_passenger_id = result

        # Now enter destination-click mode
        self._pending_teleport = True

    def _is_targeting(self) -> bool:
        """Whether the player is mid-aim: placing/aiming a spell or picking a
        hex for a shove/teleport/summon/zone-move."""
        return (
            self.combat.turn_phase == TurnPhase.SELECTING_TARGET
            or self._pending_summon
            or self._pending_teleport
            or self._pending_zone_move
            or self._pending_wall
        )

    def _cancel_targeting(self) -> None:
        """Abort any in-progress spell aim / hex placement, back to AWAITING_ACTION."""
        self._pending_help = False
        self._pending_stabilize = False
        self._pending_shove = False
        self._pending_grapple = False
        self._pending_teleport = False
        self._pending_summon = False
        self._pending_zone_move = False
        self._pending_wall = False
        self._wall_anchor = None
        self._pending_passenger_id = None
        self._passenger_popup = None
        self.combat.cancel_action()

    def _handle_right_click(self, event: pygame.event.Event) -> None:
        """Right-click: cancel an in-progress aim, or toggle the radial menu."""
        if self.combat.turn_phase not in (
            TurnPhase.AWAITING_ACTION, TurnPhase.SELECTING_TARGET
        ):
            return

        active = self.combat.active_combatant
        if active is None or not active.creature.is_player_controlled:
            return

        # If menu is already open, close it
        if self.radial_menu.state != RadialMenuState.CLOSED:
            self.radial_menu.close()
            return

        if active.position is None or self.grid_view is None:
            return

        # Is the click near the active creature's token (any footprint hex)?
        hex_size = get_settings().display.default_hex_size
        ox, oy = self.grid_view.origin
        token_r = get_settings().display.token_radius * self.grid_view.camera.zoom

        from arena.grid.footprint import get_occupied_hexes
        min_dist_sq = float("inf")
        for h in get_occupied_hexes(active.position, active.creature.size):
            hwx, hwy = h.to_pixel(hex_size)
            hlx, hly = self.grid_view.camera.world_to_screen(hwx, hwy)
            hsx = int(hlx) + ox
            hsy = int(hly) + oy
            d2 = (event.pos[0] - hsx) ** 2 + (event.pos[1] - hsy) ** 2
            min_dist_sq = min(min_dist_sq, d2)
        near_token = min_dist_sq ** 0.5 <= token_r + 10

        # Right-click while aiming a spell / placing an effect cancels it — from
        # ANYWHERE on the field, not just on your own token. If the click also
        # landed on the token, fall through and reopen the menu (a handy combo).
        if self._is_targeting():
            self._cancel_targeting()
            if not near_token:
                return

        if not near_token:
            return

        self.radial_menu.open(active.creature_id)
        # Immediately compute position
        self.radial_menu.update_position(
            self.grid_view, self.combat,
            self.screen_width, self.screen_height,
        )

    def _handle_radial_result(self, result: str) -> None:
        """Handle a command from the radial menu."""
        if result == "open_spells":
            self.radial_menu.open_spell_popup()
            return
        if result == "open_tactics":
            self.radial_menu.open_tactics_popup()
            return
        if result == "open_cantrips":
            self.radial_menu.open_cantrip_popup()
            return
        if result == "open_items":
            self.radial_menu.open_items_popup()
            return
        if result == "open_abilities":
            self.radial_menu.open_abilities_popup()
            return
        # Action Surge: execute without closing the menu, then refresh slots
        if result == "standard:action_surge":
            self._handle_combat_action(result)
            self.radial_menu._rebuild_slots()
            return

        # Close the menu and route the action
        self.radial_menu.close()
        self._handle_combat_action(result)

    def _handle_combat_action(self, result: str) -> None:
        """Route a combat action command string to the CombatManager."""
        if result == "end_turn":
            self.combat.end_turn()
            # Select the new active creature
            new_active = self.combat.active_combatant
            if new_active:
                self._select_creature_by_id(
                    new_active.creature_id, center_camera=True,
                )
            # Check if the next turn is an AI turn
            self._check_ai_turn()

        elif result.startswith("action:"):
            action_name = result[7:]
            # Optional "@<level>" suffix carries an upcast slot choice from
            # the spell popup (e.g. "action:Web@3").
            cast_level: int | None = None
            if "@" in action_name:
                maybe_name, _, lvl_str = action_name.rpartition("@")
                if lvl_str.isdigit():
                    action_name = maybe_name
                    cast_level = int(lvl_str)
            active = self.combat.active_combatant
            if active:
                for action in active.creature.actions:
                    if action.name == action_name:
                        if action.is_wall:
                            # Wall placement (D-WALL-1): enter two-click line mode
                            # — first click anchors one end, second draws the wall.
                            self.combat.select_action(action, cast_level=cast_level)
                            self._pending_wall = True
                            self._wall_anchor = None
                            self.combat.turn_phase = TurnPhase.SELECTING_TARGET
                        elif action.summon_creature:
                            self.combat.select_action(action, cast_level=cast_level)
                            if action.is_wild_shape and active.position:
                                # Wild Shape transforms in-place — no hex click needed
                                self.combat.execute_summon(active.position)
                            else:
                                # Enter summon placement mode (click a hex)
                                self._pending_summon = True
                        elif action.teleport_range is not None:
                            self.combat.select_action(action, cast_level=cast_level)
                            if action.teleport_passenger:
                                self._try_show_passenger_popup(action)
                            else:
                                self._pending_teleport = True
                        elif (
                            (action.range == 0 or action.zone_follows_caster)
                            and action.target_type.value.startswith("area_")
                            and not is_emanating(action)
                            and not action.attack
                            and active.position is not None
                        ):
                            # Self-centered area effect (Spirit Guardians aura,
                            # Turn Undead burst): a sphere/cube/cylinder centered
                            # on the caster — zero range or a caster-following
                            # zone — so cast immediately, no hex to pick. Lines
                            # and cones are excluded: they EMANATE in a chosen
                            # direction, so they need the aim step below.
                            self.combat.select_action(action, cast_level=cast_level)
                            self.combat.execute_effect_at_hex(
                                active.position,
                                clicked_target_id=active.creature_id,
                            )
                            self._check_pending_counterspell()
                        else:
                            self.combat.select_action(action, cast_level=cast_level)
                        break

        elif result == "drop_concentration":
            active = self.combat.active_combatant
            if active:
                from arena.combat.concentration import end_concentration
                events = end_concentration(
                    active.creature, active.creature_id,
                    combatants=self.combat.combatants,
                )
                for e in events:
                    self.combat.log.add(e)
                # Clean up zones linked to the dropped concentration
                self.combat._cleanup_orphaned_zones()

        elif result == "move_zone":
            active = self.combat.active_combatant
            if active:
                # Find the zone_move_cost from the caster's active zone
                caster_zones = [z for z in self.combat.active_zones
                                if z.caster_id == active.creature_id]
                if caster_zones:
                    zone = caster_zones[0]
                    for a in active.creature.actions:
                        if a.zone_move_cost and a.name.lower().replace(" ", "_") in zone.zone_id:
                            self._pending_zone_move = True
                            self._zone_move_cost = a.zone_move_cost
                            self._zone_move_range = a.range
                            self._zone_move_radius = zone.radius_feet
                            self.combat.turn_phase = TurnPhase.SELECTING_TARGET
                            break

        elif result == "shove":
            # Shove requires selecting an adjacent enemy, then a choice popup
            self._pending_shove = True
            self.combat.turn_phase = TurnPhase.SELECTING_TARGET

        elif result == "grapple":
            # Grapple requires selecting an adjacent enemy (no choice popup)
            self._pending_grapple = True
            self.combat.turn_phase = TurnPhase.SELECTING_TARGET

        elif result == "ready":
            # Ready opens a two-stage popup (pick action, pick trigger)
            active = self.combat.active_combatant
            if active is not None and not self.combat.turn_resources.has_used_action:
                from arena.gui.ready_popup import ReadyPopup, readyable_actions
                actions = readyable_actions(active.creature)
                if actions:
                    self._ready_popup = ReadyPopup(
                        actions,
                        screen_width=self.screen_width,
                        screen_height=self.screen_height,
                    )
                    self._ready_popup.reposition(
                        (self.screen_width // 2, self.screen_height // 2))

        elif result.startswith("standard:"):
            action_name = result[9:]
            if action_name == "help":
                # Help requires selecting an adjacent ally — enter target mode
                self._pending_help = True
                self.combat.turn_phase = TurnPhase.SELECTING_TARGET
            elif action_name == "stabilize":
                # Stabilize requires selecting an adjacent dying ally
                self._pending_stabilize = True
                self.combat.turn_phase = TurnPhase.SELECTING_TARGET
            else:
                self.combat.execute_standard_action(action_name)

        elif result == "bonus:offhand":
            # Two-weapon fighting: auto-target the nearest enemy.
            active = self.combat.active_combatant
            if active:
                nearest_enemy = self._find_nearest_enemy(active)
                if nearest_enemy:
                    self.combat.execute_bonus_action_attack(nearest_enemy)

        elif result.startswith("bonus_action:"):
            action_name = result[13:]
            active = self.combat.active_combatant
            if active:
                for action in active.creature.bonus_actions:
                    if action.name == action_name:
                        if action.standard_effect is not None:
                            # Cunning Action family: executes immediately —
                            # no target to select for a self Dash/Disengage/Hide
                            self.combat.execute_data_standard_action(action)
                        elif action.teleport_range is not None:
                            self.combat.select_action(action)
                            if action.teleport_passenger:
                                self._try_show_passenger_popup(action)
                            else:
                                self._pending_teleport = True
                        else:
                            self.combat.select_action(action)
                        break

    def _select_creature_by_id(
        self, creature_id: str, center_camera: bool = False,
    ) -> None:
        """Select a creature by ID, updating all relevant state.

        Args:
            creature_id: The creature to select.
            center_camera: If True, smoothly pan the camera to the creature.
        """
        self.selected_creature_id = creature_id
        self.creature_info_panel.set_creature_id(creature_id)
        combatant = self.combat.get_creature(creature_id)
        if combatant and combatant.position and self.grid_view:
            self.grid_view.selected_hex = combatant.position
            if center_camera:
                hex_size = get_settings().display.default_hex_size
                wx, wy = combatant.position.to_pixel(hex_size)
                self.grid_view.camera.smooth_center_on(
                    wx, wy,
                    self.grid_rect.width, self.grid_rect.height,
                )

    def _handle_keyboard_shortcut(self, event: pygame.event.Event) -> bool:
        """Handle keyboard shortcuts. Returns True if consumed."""
        key = event.key
        mods = event.mod

        # Ctrl+S — save combat state (works during combat, even AI turns)
        if key == pygame.K_s and (mods & pygame.KMOD_CTRL):
            self._save_combat()
            return True

        # ? (Shift+/) — toggle shortcuts help (works always)
        if key == pygame.K_SLASH and (mods & pygame.KMOD_SHIFT):
            self._show_shortcuts_help = not self._show_shortcuts_help
            return True

        # O — options popup: battle-map opacity + music volume (works always)
        if key == pygame.K_o:
            self._settings_popup = SettingsPopup(self.screen_width, self.screen_height)
            return True

        # If shortcuts overlay is showing, any other key dismisses it
        if self._show_shortcuts_help:
            self._show_shortcuts_help = False
            return True

        # Remaining shortcuts only work during active combat, non-AI turns
        if self.combat.state != CombatState.IN_COMBAT:
            return False
        if self.ai_runner.is_active:
            return False

        # C — smoothly center camera on active creature
        if key == pygame.K_c:
            active = self.combat.active_combatant
            if active and active.position and self.grid_view:
                wx, wy = active.position.to_pixel(get_settings().display.default_hex_size)
                self.grid_view.camera.smooth_center_on(
                    wx, wy,
                    self.grid_rect.width, self.grid_rect.height,
                )
            return True

        # Tab — cycle selected creature through initiative order
        if key == pygame.K_TAB:
            entries = self.combat.initiative.entries
            if entries:
                current_id = self.selected_creature_id
                # Find current index
                current_idx = -1
                for i, entry in enumerate(entries):
                    if entry.creature_id == current_id:
                        current_idx = i
                        break
                # Advance to next
                next_idx = (current_idx + 1) % len(entries)
                self._select_creature_by_id(
                    entries[next_idx].creature_id, center_camera=True,
                )
            return True

        # Backspace — cancel target selection
        if key == pygame.K_BACKSPACE:
            if self.combat.turn_phase == TurnPhase.SELECTING_TARGET:
                self._pending_help = False
                self._pending_stabilize = False
                self._pending_shove = False
                self._pending_grapple = False
                self._pending_teleport = False
                self._pending_passenger_id = None
                self._passenger_popup = None
                self.combat.cancel_action()
                return True
            return False

        # Space / Enter — end turn (only during AWAITING_ACTION)
        if key in (pygame.K_SPACE, pygame.K_RETURN):
            if self.combat.turn_phase == TurnPhase.AWAITING_ACTION:
                self.radial_menu.close()
                self._handle_combat_action("end_turn")
                return True

        return False

    def _get_creature_at_hex(self, hex_coord: HexCoord | None) -> str | None:
        """Get the creature_id at a hex coordinate, if any.

        Args:
            hex_coord: The hex coordinate to check, or ``None``.

        Returns:
            The creature_id string, or ``None`` if no creature is there.
        """
        if hex_coord is None or self.combat.grid is None:
            return None
        cell = self.combat.grid.get_cell(hex_coord)
        if cell and cell.occupant_id:
            return cell.occupant_id
        return None

    def _find_nearest_enemy(self, combatant) -> str | None:
        """Find the nearest enemy creature to the given combatant.

        Args:
            combatant: The combatant to find enemies relative to.

        Returns:
            creature_id of the nearest enemy, or None.
        """
        if combatant.position is None:
            return None
        best_id = None
        best_dist = float("inf")
        for cid, c in self.combat.combatants.items():
            if c.team == combatant.team:
                continue
            if not c.creature.is_conscious:
                continue
            if c.position is None:
                continue
            d = combatant.position.distance_to(c.position)
            if d < best_dist:
                best_dist = d
                best_id = cid
        return best_id

    def update(self) -> None:
        """Per-frame update for all sub-components."""
        # Play victory/defeat sound once when combat ends
        if (
            self.combat.state == CombatState.COMBAT_ENDED
            and not self._played_end_sound
        ):
            from arena.audio.manager import get_sound_manager
            sound_id = "victory" if self.combat.winner == "player" else "defeat"
            get_sound_manager().play_sfx(sound_id)
            self._played_end_sound = True

        # Check for a pending opportunity-attack prompt (enemy provoked a
        # player creature's OA mid-move) — show it before driving the AI.
        if self._oa_popup is None and self.combat._pending_oa is not None:
            self._show_oa_popup()

        # Drive AI turn runner (pause while a reaction / OA popup is showing,
        # or while earlier beats are still playing out on the director)
        if (self.ai_runner.is_active and self._reaction_popup is None
                and self._oa_popup is None
                and not self._director.is_busy):
            current_time = pygame.time.get_ticks()
            finished = self.ai_runner.update(self.combat, current_time)
            if finished:
                # Restore zoom if it was changed for a ranged attack
                if self._ai_pre_attack_zoom is not None and self.grid_view:
                    self.grid_view.camera._target_zoom = self._ai_pre_attack_zoom
                    self._ai_pre_attack_zoom = None
                # After AI turn ends, select the new active creature
                new_active = self.combat.active_combatant
                if new_active:
                    self._select_creature_by_id(
                        new_active.creature_id, center_camera=True,
                    )
                # Check if the next turn is also an AI turn
                self._check_ai_turn()

        # Check for pending damage reduction popup (player-controlled target hit)
        if (
            self._reaction_popup is None
            and self.combat._pending_damage_reduction is not None
        ):
            self._show_reaction_popup()

        # Check for pending Bardic Inspiration popup (player attacker missed)
        if (
            self._bardic_popup is None
            and self.combat._pending_bardic_choice is not None
        ):
            self._check_pending_bardic()

        # Drive player hex-by-hex movement
        if self._player_move_path is not None:
            current_time = pygame.time.get_ticks()
            if current_time >= self._player_move_next_time:
                self._advance_player_move(current_time)

        # Process new combat events for visual effects (damage flash, floaters)
        self._process_new_combat_events()

        # Fire animation beats that are due (travel finished → impact, etc.)
        self._director.update(pygame.time.get_ticks())

        # The log only shows lines whose beat has visually played
        self.log_panel.reveal_count = self._log_reveal_index

        # Animate display HP toward actual HP each frame. Damage that
        # hasn't visually landed yet (queued impact beats) stays "credited"
        # so the bar doesn't drop before the projectile arrives.
        for cid, combatant in self.combat.combatants.items():
            actual = float(combatant.creature.current_hit_points or 0)
            credit = self._hp_credit.get(cid, 0)
            if credit:
                max_hp = float(combatant.creature.max_hit_points or 0)
                actual = min(actual + credit, max_hp) if max_hp else actual
            current = self._display_hp.get(cid, actual)
            if abs(current - actual) < 0.5:
                self._display_hp[cid] = actual
            else:
                self._display_hp[cid] = current + (actual - current) * HP_LERP_SPEED

        if self.grid_view:
            self.grid_view.update()
            # Resolve hovered hex for tooltips
            hovered_hex = self.grid_view.hovered_hex
            self._hovered_creature_id = self._get_creature_at_hex(hovered_hex)

            # Always check for special terrain on hovered hex
            if hovered_hex is not None:
                cell = self.combat.grid.get_cell(hovered_hex)
                if cell and cell.terrain != TerrainType.NORMAL:
                    self._hovered_terrain_type = cell.terrain
                else:
                    self._hovered_terrain_type = None
            else:
                self._hovered_terrain_type = None
        else:
            self._hovered_creature_id = None
            self._hovered_terrain_type = None
        self.initiative_panel.update()
        self.log_panel.update()

        # Auto-close radial menu when turn changes or AI takes over
        if self.radial_menu.state != RadialMenuState.CLOSED:
            active = self.combat.active_combatant
            if (
                active is None
                or active.creature_id != self.radial_menu.creature_id
                or not active.creature.is_player_controlled
                or self.combat.state == CombatState.COMBAT_ENDED
            ):
                self.radial_menu.close()
            elif self.grid_view:
                self.radial_menu.update_position(
                    self.grid_view, self.combat,
                    self.screen_width, self.screen_height,
                )

    def render(self, surface: pygame.Surface) -> None:
        """Render the complete combat screen."""
        # Render grid
        if self.grid_view:
            self.grid_view.render(surface)

            # Persistent AoE zone overlays (below movement/attack range overlays)
            self._render_aoe_zones(surface)

            # Incoming-AoE danger telegraphs (same layer as zone overlays)
            self._render_telegraphs(surface)

            # Placed wall spells (Wall of Force/Fire/Stone/...) — a barrier you
            # can't see is confusing even when it's narratively invisible.
            self._render_active_walls(surface)

            # Movement range overlay
            self._render_movement_range(surface)

            # Ranged weapon range overlay (when awaiting action)
            self._render_ranged_range(surface)

            # Attack range overlay (when selecting target)
            self._render_attack_range(surface)

            # Legendary action range overlay (when targeting a legendary action)
            self._render_legendary_range(surface)

            # Teleport range overlay (when selecting teleport destination)
            self._render_teleport_range(surface)

            # AoE placement preview (follows mouse during target selection)
            self._render_aoe_preview(surface)

            # Tokens on top of grid
            self._render_tokens(surface)

            # Action/spell animations (between tokens and floating text)
            self._render_action_animations(surface)

            # Programmatic visual effects (AoE blasts, spawn glows, etc.)
            self._render_visual_effects(surface)

            # Floating damage/healing numbers
            self._render_floating_texts(surface)

        # Radial menu (on top of tokens, within grid area)
        if self.radial_menu.state != RadialMenuState.CLOSED:
            self.radial_menu.render(surface)

        # UI panels
        self.initiative_panel.render(surface)
        self.creature_info_panel.render(surface)
        self.log_panel.render(surface)

        # Radial menu tooltip (drawn on top of panels)
        if self.radial_menu.state != RadialMenuState.CLOSED:
            self.radial_menu.render_tooltip(surface)

        # Modal dim: input is already blocked while any decision popup is
        # open — make that visible so the board behind it doesn't look live.
        # (Lair/legendary allow camera panning while open, so they stay
        # undimmed — the player is often inspecting the board to decide.)
        if any(p is not None for p in (
            self._rider_popup, self._oa_popup, self._reaction_popup,
            self._reroll_popup, self._bardic_popup, self._shove_popup,
            self._ready_popup, self._passenger_popup, self._counterspell_popup,
        )):
            draw_modal_dim(surface)

        # Options popup (no dim: the whole point of its sliders is watching
        # the battle map change live underneath)
        if self._settings_popup is not None:
            self._settings_popup.render(surface)

        # Rider popup (above panels, below end overlay)
        if self._rider_popup is not None:
            self._rider_popup.render(surface)

        # Opportunity-attack prompt
        if self._oa_popup is not None:
            self._oa_popup.render(surface)

        # Damage reduction reaction popup
        if self._reaction_popup is not None:
            self._reaction_popup.render(surface)

        # Forced save reroll popup
        if self._reroll_popup is not None:
            self._reroll_popup.render(surface)

        # Bardic Inspiration spend popup
        if self._bardic_popup is not None:
            self._bardic_popup.render(surface)

        # Shove choice popup
        if self._shove_popup is not None:
            self._shove_popup.render(surface)

        # Ready action popup (D-ACT-1)
        if self._ready_popup is not None:
            self._ready_popup.render(surface)

        # Passenger selection popup (teleport)
        if self._passenger_popup is not None:
            self._passenger_popup.render(surface)

        # Counterspell popup
        if self._counterspell_popup is not None:
            self._counterspell_popup.render(surface)

        # Lair action popup
        if self._lair_popup is not None:
            self._lair_popup.render(surface)

        # Legendary action popup
        if self._legendary_popup is not None:
            self._legendary_popup.render(surface)

        # Legendary targeting hint
        if self._legendary_selected_action is not None:
            hint_font = get_font(FONT_SIZES["label"])
            hint_text = f"Select target for {self._legendary_selected_action.name} (ESC to cancel)"
            hint_surf = hint_font.render(
                hint_text, True, parse_color(COLORS["legendary_accent"])
            )
            hx = (self.screen_width - hint_surf.get_width()) // 2
            surface.blit(hint_surf, (hx, 8))

        # General targeting hint — the cancel key is otherwise invisible
        elif (
            self.combat.state == CombatState.IN_COMBAT
            and self.combat.turn_phase == TurnPhase.SELECTING_TARGET
            and not self.ai_runner.is_active
        ):
            hint_font = get_font(FONT_SIZES["label"])
            selected = self.combat.selected_action
            what = f"{selected.name} — " if selected is not None else ""
            hint_surf = hint_font.render(
                f"{what}Backspace to cancel", True,
                parse_color(COLORS["text_secondary"]),
            )
            hx = (self.screen_width - hint_surf.get_width()) // 2
            surface.blit(hint_surf, (hx, 8))

        # Corner nudges: shortcuts overlay + the options sliders
        if not self._show_shortcuts_help:
            corner_font = get_font(FONT_SIZES["small"])
            corner = corner_font.render(
                "? shortcuts", True, parse_color(COLORS["text_secondary"]),
            )
            cx = self.grid_rect.right - corner.get_width() - 10
            cy = self.grid_rect.bottom - corner.get_height() - 6
            surface.blit(corner, (cx, cy))
            opts = corner_font.render(
                "O options", True, parse_color(COLORS["text_secondary"]),
            )
            ox = cx - opts.get_width() - 16
            surface.blit(opts, (ox, cy))
            self._options_rect = pygame.Rect(
                ox - 4, cy - 4, opts.get_width() + 8, opts.get_height() + 8,
            )
        else:
            self._options_rect = None

        # Victory/Defeat overlay
        if self.combat.state == CombatState.COMBAT_ENDED:
            self._render_end_overlay(surface)

        # Shortcuts help overlay
        if self._show_shortcuts_help:
            self._render_shortcuts_help(surface)

        # Hover tooltips (drawn last so they appear on top of everything)
        if self._hovered_creature_id is not None:
            self._render_hover_tooltip(surface)
        elif self._hovered_terrain_type is not None:
            self._render_terrain_tooltip(surface)

    # ------------------------------------------------------------------
    # AI turn support
    # ------------------------------------------------------------------

    def _check_ai_turn(self) -> None:
        """If the active combatant is AI-controlled, plan and start its turn.

        Also handles AI legendary action decisions during LEGENDARY_ACTION_PHASE.
        """
        if self.combat.state != CombatState.IN_COMBAT:
            return
        if self.ai_runner.is_active:
            return

        # --- Lair turn routing ---
        if self.combat._is_lair_turn:
            if self.combat._use_ai_for_lair:
                # AI picks lair action
                plan = self.ai_controller.plan_lair_action(self.combat)
                self.ai_runner.start(plan)
            else:
                # DM controls: show popup
                if self._lair_popup is None:
                    available = self.combat.get_available_lair_actions()
                    self._lair_popup = LairActionPopup(
                        available_actions=available,
                        screen_width=self.screen_width,
                        screen_height=self.screen_height,
                    )
                    self._lair_popup.reposition((
                        self.screen_width // 2, self.screen_height // 2,
                    ))
            return

        # --- Legendary action phase routing ---
        if self.combat.turn_phase == TurnPhase.LEGENDARY_ACTION_PHASE:
            actor = self.combat.legendary_actor
            if actor and not actor.creature.is_player_controlled:
                # AI decides on legendary action
                plan = self.ai_controller.plan_legendary_action(self.combat)
                self.ai_runner.start(plan)
            elif actor and actor.creature.is_player_controlled:
                # Player-controlled: show popup if not already open
                if self._legendary_popup is None:
                    available = self.combat.get_available_legendary_actions(
                        actor.creature_id
                    )
                    remaining = self.combat.legendary_points.get(
                        actor.creature_id, 0
                    )
                    self._legendary_popup = LegendaryActionPopup(
                        creature_name=actor.creature.name,
                        remaining_points=remaining,
                        available_actions=available,
                        screen_width=self.screen_width,
                        screen_height=self.screen_height,
                    )
                    self._legendary_popup.reposition((
                        self.screen_width // 2, self.screen_height // 2,
                    ))
            return

        active = self.combat.active_combatant
        if active is None:
            return

        # Player-controlled creatures are handled by the GUI
        if active.creature.is_player_controlled:
            return

        # Plan and start AI turn
        plan = self.ai_controller.plan_turn(self.combat)
        self.ai_runner.start(plan)

    def _resolve_lair_popup(self, result) -> None:
        """Handle the LairActionPopup result: action chosen or pass."""
        self._lair_popup = None

        if result == "__pass__":
            self.combat.pass_lair_action()
            self._check_ai_turn()
            return

        # result is an Action — execute against all player-side targets
        action = result
        target_ids = [
            cid for cid, c in self.combat.combatants.items()
            if c.team in ("player", "ally") and c.creature.is_conscious
        ]
        self.combat.execute_lair_action(action, target_ids)
        self._check_ai_turn()

    def _resolve_legendary_popup(self, result) -> None:
        """Handle the LegendaryActionPopup result: action chosen or pass."""
        self._legendary_popup = None

        if result == "__pass__":
            self.combat.pass_legendary_action()
            self._check_ai_turn()
            return

        # result is an Action object — need to select a target
        action = result
        if action.target_type.value == "self":
            # Self-targeted legendary action: execute immediately
            actor = self.combat.legendary_actor
            if actor:
                self.combat.execute_legendary_action(action, actor.creature_id)
            self._check_ai_turn()
        else:
            # Need target selection — store the action and wait for click
            self._legendary_selected_action = action

    def _handle_legendary_target_event(self, event: pygame.event.Event) -> None:
        """Handle target selection for a player-controlled legendary action."""
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # Cancel — re-show the popup
            self._legendary_selected_action = None
            actor = self.combat.legendary_actor
            if actor:
                available = self.combat.get_available_legendary_actions(
                    actor.creature_id
                )
                remaining = self.combat.legendary_points.get(
                    actor.creature_id, 0
                )
                self._legendary_popup = LegendaryActionPopup(
                    creature_name=actor.creature.name,
                    remaining_points=remaining,
                    available_actions=available,
                    screen_width=self.screen_width,
                    screen_height=self.screen_height,
                )
                self._legendary_popup.reposition((
                    self.screen_width // 2, self.screen_height // 2,
                ))
            return

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # Ignore if user was dragging the camera
            if self.grid_view and self.grid_view._is_dragging:
                return
            # Find clicked creature
            mx, my = event.pos
            clicked_id = self._get_creature_at_screen_pos(mx, my)
            if clicked_id is not None:
                action = self._legendary_selected_action
                self._legendary_selected_action = None
                self.combat.execute_legendary_action(action, clicked_id)
                self._check_ai_turn()

    def _get_creature_at_screen_pos(
        self, mx: int, my: int
    ) -> str | None:
        """Find which creature (if any) is at the given screen position."""
        if self.grid_view is None or self.combat.grid is None:
            return None
        hex_coord = self.grid_view._screen_to_hex(mx, my)
        if hex_coord is None:
            return None
        cell = self.combat.grid.get_cell(hex_coord)
        if cell is None or cell.occupant_id is None:
            return None
        return cell.occupant_id

    def _forward_camera_event(self, event: pygame.event.Event) -> None:
        """Forward mouse/scroll events to the grid view for camera pan/zoom.

        Called during modal states (legendary popup, legendary targeting)
        so the player can still move the camera while choosing an action.
        """
        if self.grid_view is None:
            return
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if self.grid_rect.collidepoint(mouse_pos):
                self.grid_view.handle_event(event)
        elif event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                            pygame.MOUSEBUTTONUP):
            self.grid_view.handle_event(event)

    # ------------------------------------------------------------------
    # Move animation support
    # ------------------------------------------------------------------

    def _on_creature_move(
        self, creature_id: str, old_hex: HexCoord, new_hex: HexCoord
    ) -> None:
        """Record a hop animation when a creature moves one hex."""
        hex_size = get_settings().display.default_hex_size

        # For multi-hex creatures, animate from footprint centroid to centroid
        # so the whole polygon slides smoothly.
        combatant = self.combat.combatants.get(creature_id)
        if combatant and get_footprint_hex_count(combatant.creature.size) > 1:
            sx, sy = get_footprint_center_pixel(old_hex, combatant.creature.size, hex_size)
            ex, ey = get_footprint_center_pixel(new_hex, combatant.creature.size, hex_size)
        else:
            sx, sy = old_hex.to_pixel(hex_size)
            ex, ey = new_hex.to_pixel(hex_size)

        now = pygame.time.get_ticks()
        self._move_animations[creature_id] = (
            sx, sy, ex, ey, now, MOVE_ANIM_DURATION_MS,
        )

        # Smoothly follow AI creatures with the camera
        if self.ai_runner.is_active and self.grid_view:
            # If we zoomed out for a ranged attack, restore zoom as
            # the creature starts moving again.
            if self._ai_pre_attack_zoom is not None:
                cam = self.grid_view.camera
                cam._target_zoom = self._ai_pre_attack_zoom
                self._ai_pre_attack_zoom = None

            self.grid_view.camera.smooth_center_on(
                ex, ey,
                self.grid_rect.width, self.grid_rect.height,
            )

    def _zoom_to_frame_pair(
        self,
        ax: float, ay: float,
        bx: float, by: float,
    ) -> None:
        """Smoothly zoom out so that two world positions are both visible.

        Centers the camera on the midpoint between the two positions and
        adjusts zoom so both fit within the viewport with some padding.
        Saves the current zoom level so it can be restored later.
        """
        assert self.grid_view is not None
        cam = self.grid_view.camera
        vw = self.grid_rect.width
        vh = self.grid_rect.height

        # Save current zoom for restoration (only if not already saved)
        if self._ai_pre_attack_zoom is None:
            self._ai_pre_attack_zoom = (
                cam._target_zoom if cam._target_zoom is not None else cam.zoom
            )

        # Midpoint in world space
        mid_x = (ax + bx) / 2
        mid_y = (ay + by) / 2

        # World-space span needed (with 30% padding on each side)
        span_x = abs(bx - ax) * 1.6
        span_y = abs(by - ay) * 1.6

        # Zoom level that fits both axes
        if span_x < 1 and span_y < 1:
            # Attacker and target are nearly overlapping — no zoom change
            cam.smooth_center_on(mid_x, mid_y, vw, vh)
            return

        zoom_x = vw / span_x if span_x > 0 else cam.zoom
        zoom_y = vh / span_y if span_y > 0 else cam.zoom
        needed_zoom = min(zoom_x, zoom_y)

        # Only zoom out, never zoom in past the current level
        current_zoom = (
            cam._target_zoom if cam._target_zoom is not None else cam.zoom
        )
        target_zoom = min(current_zoom, needed_zoom)

        cam.smooth_frame_on(mid_x, mid_y, target_zoom, vw, vh)

    def _advance_player_move(self, current_time: int) -> None:
        """Move the player creature one hex along the pre-computed path."""
        assert self._player_move_path is not None

        combatant = self.combat.active_combatant
        if combatant is None or not combatant.creature.is_conscious:
            self._player_move_path = None
            return

        if self._player_move_index >= len(self._player_move_path):
            # Finished walking
            self._player_move_path = None
            if self.grid_view and combatant.position:
                self.grid_view.selected_hex = combatant.position
            return

        hex_coord = self._player_move_path[self._player_move_index]
        old_pos = combatant.position
        success = self.combat.try_move(hex_coord)
        self._player_move_index += 1

        if not success or not combatant.creature.is_conscious:
            # Move blocked (e.g. opportunity attack downed creature) – stop
            self._player_move_path = None
            if self.grid_view and combatant.position:
                self.grid_view.selected_hex = combatant.position
            return

        # Trigger the hop animation
        if old_pos is not None:
            self._on_creature_move(combatant.creature_id, old_pos, hex_coord)

        # Follow the creature with the selection highlight
        if self.grid_view:
            self.grid_view.selected_hex = hex_coord

        # Schedule next sub-step (same timing as AI movement)
        self._player_move_next_time = current_time + MOVE_ANIM_DURATION_MS

    def _process_new_combat_events(self) -> None:
        """Scan the combat log for new events and sequence their visuals.

        Animation-bearing events (attacks, spell effects) open a beat
        group on the director: a travel/swing beat, then a mutable
        impact beat. Damage numbers, flashes, blast rings, KO slumps
        and HP-bar drops belonging to that action attach to the impact
        beat, so they land when the projectile does instead of the
        frame the engine resolved. Everything outside a group spawns
        immediately, exactly as before.
        """
        events = self.combat.log.events
        if self._last_event_index >= len(events):
            return

        now = pygame.time.get_ticks()
        hex_size = get_settings().display.default_hex_size

        for idx in range(self._last_event_index, len(events)):
            self._sequence_event(events[idx], idx, hex_size, now)

        self._last_event_index = len(events)

    def _sequence_event(self, event, idx: int, hex_size: int, now: int) -> None:
        """Route one combat event's visuals: into beats or immediate."""
        # World position of the target (visual anchor for most cues)
        wx: float | None = None
        wy: float | None = None
        target_id = event.target_id
        if target_id is not None:
            combatant = self.combat.combatants.get(target_id)
            if combatant is not None and combatant.position is not None:
                wx, wy = combatant.position.to_pixel(hex_size)

        # AoE casts have no single target: anchor their beats (and the
        # cast animation) on the blast center instead.
        anchor_x, anchor_y = wx, wy
        if anchor_x is None:
            center = event.details.get("aoe_center_hex")
            if center is not None:
                anchor_x, anchor_y = HexCoord(
                    center[0], center[1]
                ).to_pixel(hex_size)

        # An animation-bearing event opens a new group: a travel/swing
        # beat, then an impact beat that later cues attach to.
        hold_ms = self._animation_hold_ms(event)
        if hold_ms is not None and anchor_x is not None:
            # Incoming AI AoE: telegraph the true blast shape first, so
            # the player can see what a breath/burst covers before it
            # lands. (The player aimed their own casts — no telegraph.)
            aoe_shape = event.details.get("aoe_hexes")
            if aoe_shape and self.ai_runner.is_active:
                color = get_damage_color(
                    event.details.get("aoe_damage_type", "force")
                )
                telegraph_cue = (
                    lambda t, hexes=list(aoe_shape), c=color,
                    dur=TELEGRAPH_MS + hold_ms:
                    self._active_telegraphs.append(
                        TelegraphState(hexes, c, t, dur)
                    )
                )
                self._director.enqueue(
                    Beat(cues=[telegraph_cue], duration_ms=TELEGRAPH_MS)
                )

            anim_cue = (
                lambda t, e=event, x=anchor_x, y=anchor_y:
                self._try_spawn_animation(e, x, y, hex_size, t)
            )
            # The action's log line ("X attacks Y") reveals with the swing
            reveal_cue = lambda t, i=idx: self._reveal_log_to(i + 1)
            self._pending_anim = self._director.enqueue(
                Beat(cues=[anim_cue, reveal_cue], duration_ms=hold_ms)
            )
            self._pending_anim_hold = hold_ms
            self._pending_impact = self._director.enqueue(
                Beat(duration_ms=IMPACT_BEAT_MS)
            )
            self._impact_source = event.source_id
        elif event.event_type == CombatEventType.ATTACK_ROLL:
            # A new attack that can't animate closes the previous group:
            # its visuals must not glue onto the earlier swing's impact.
            self._pending_impact = None
            self._impact_source = None

        beat = self._open_impact_beat_for(event)

        # Log reveal: an event's line shows when its visuals land. Events
        # outside the group still wait for any pending impact ahead of
        # them, so the log never runs ahead of the action chronologically.
        if hold_ms is None or anchor_x is None:
            reveal_beat = beat if beat is not None else self._pending_impact
            if reveal_beat is not None and not reveal_beat.fired:
                reveal_beat.add_cue(
                    lambda t, i=idx: self._reveal_log_to(i + 1)
                )
            else:
                self._reveal_log_to(idx + 1)

        # Programmatic visual effects (blast rings, shove trails, spawn
        # glows): land with the group's impact when part of one.
        effect_cue = (
            lambda t, e=event: self._try_spawn_visual_effect(e, hex_size, t)
        )
        if beat is not None:
            beat.add_cue(effect_cue)
        else:
            effect_cue(now)

        if wx is None:
            return

        if event.event_type == CombatEventType.DAMAGE:
            amount = event.details.get("damage", 0)
            if amount > 0:
                is_crit = event.details.get("critical", False)
                if beat is not None:
                    # Freeze the HP bar at its pre-hit value until impact
                    self._hp_credit[target_id] = (
                        self._hp_credit.get(target_id, 0) + amount
                    )
                    beat.add_cue(self._make_damage_cue(
                        target_id, wx, wy, amount, is_crit, deferred=True,
                    ))
                    # Charge/Pounce hit: the attacker lunges into the
                    # target with the swing, apex right at the impact
                    if event.details.get("charged") and event.source_id:
                        anim_beat = self._pending_anim
                        if anim_beat is not None and not anim_beat.fired:
                            anim_beat.add_cue(self._make_lunge_cue(
                                event.source_id, wx, wy,
                                self._pending_anim_hold * 2,
                            ))
                else:
                    self._make_damage_cue(
                        target_id, wx, wy, amount, is_crit, deferred=False,
                    )(now)

        elif event.event_type == CombatEventType.HEALING:
            amount = event.details.get("healing", 0)
            if amount > 0:
                text = f"+{amount}"
                color = (60, 255, 60)  # green
                self._floating_texts.append(
                    FloatingText(text, wx, wy, color, now)
                )

        elif event.event_type == CombatEventType.CREATURE_DOWNED:
            # Keep the token upright until the blow that downed it lands
            pending = self._pending_impact
            if (
                pending is not None
                and not pending.fired
                and self._hp_credit.get(target_id)
            ):
                self._downed_hold.add(target_id)
                pending.add_cue(
                    lambda t, cid=target_id: self._downed_hold.discard(cid)
                )

    def _make_lunge_cue(
        self, attacker_id: str, target_wx: float, target_wy: float,
        duration_ms: int,
    ):
        """Build the cue that starts a charge lunge toward the target.

        The attacker's position is read at fire time (it may still be
        mid-walk when the beats are built).
        """
        def cue(t: int) -> None:
            c = self.combat.combatants.get(attacker_id)
            if c is None or c.position is None:
                return
            hex_size = get_settings().display.default_hex_size
            fx, fy = c.position.to_pixel(hex_size)
            self._lunge_animations[attacker_id] = (
                fx, fy, target_wx, target_wy, t, max(80, duration_ms),
            )
        return cue

    def _reveal_log_to(self, idx: int) -> None:
        """Advance the log's visible-line cap (monotonic)."""
        if idx > self._log_reveal_index:
            self._log_reveal_index = idx

    def _open_impact_beat_for(self, event) -> Beat | None:
        """The open impact beat this event's visuals belong to, if any.

        An event joins the open group when the group's impact beat
        hasn't fired yet and the event comes from the same acting
        creature (source-less events ride along — e.g. follow-up
        bookkeeping the engine logs without a source).
        """
        beat = self._pending_impact
        if beat is None or beat.fired:
            return None
        if event.source_id is not None and event.source_id != self._impact_source:
            return None
        return beat

    def _animation_hold_ms(self, event) -> int | None:
        """How long this event's animation delays its impact visuals.

        Returns None when the event won't spawn an animation (same
        checks as _try_spawn_animation), so no beat group opens and
        visuals spawn instantly — the pre-sequencer behavior.
        """
        anim_name = event.details.get("animation")
        if not anim_name:
            return None
        if event.event_type == CombatEventType.INFO:
            if not event.details.get("is_effect_use"):
                return None
        frames = get_animation_frames(anim_name, ACTION_ANIM_BASE_SIZE)
        if not frames:
            return None

        # Ranged attacks: impact lands when the projectile travel ends
        attack_type = event.details.get("attack_type", "")
        if "ranged" in attack_type and event.source_id:
            source = self.combat.combatants.get(event.source_id)
            if source is not None and source.position is not None:
                return PROJECTILE_TRAVEL_MS

        # Melee swings / spell effects: land partway into the animation
        fps = get_animation_fps(anim_name)
        total_ms = len(frames) * 1000.0 / max(1, fps)
        return int(min(MELEE_IMPACT_DELAY_MS, total_ms / 2))

    def _make_damage_cue(
        self,
        target_id: str,
        wx: float,
        wy: float,
        amount: int,
        is_crit: bool,
        deferred: bool,
    ):
        """Build the cue that shows one hit landing: flash + number.

        Deferred cues also release the target's HP credit so the bar
        starts draining exactly when the number pops.
        """
        def cue(t: int) -> None:
            if deferred:
                remaining = self._hp_credit.get(target_id, 0) - amount
                if remaining > 0:
                    self._hp_credit[target_id] = remaining
                else:
                    self._hp_credit.pop(target_id, None)
            self._flash_until[target_id] = t + FLASH_DURATION_MS
            if is_crit:
                text = f"CRIT! -{amount}"
                color = (255, 215, 0)  # gold
            else:
                text = f"-{amount}"
                color = (255, 60, 60)  # red
            self._floating_texts.append(
                FloatingText(text, wx, wy, color, t)
            )
        return cue

    def _try_spawn_animation(
        self,
        event,
        target_wx: float,
        target_wy: float,
        hex_size: int,
        now: int,
    ) -> None:
        """Spawn an action animation if the event carries animation data."""
        anim_name = event.details.get("animation")
        if not anim_name:
            return

        # For INFO events, only animate effect-use events (not range errors, etc.)
        if event.event_type == CombatEventType.INFO:
            if not event.details.get("is_effect_use"):
                return

        # Determine display size based on camera zoom
        camera_zoom = 1.0
        if self.grid_view is not None:
            camera_zoom = self.grid_view.camera.zoom
        anim_size = max(16, int(ACTION_ANIM_BASE_SIZE * camera_zoom))

        frames = get_animation_frames(anim_name, anim_size)
        if not frames:
            return

        # Determine if this is a projectile (ranged attack)
        attack_type = event.details.get("attack_type", "")
        is_projectile = "ranged" in attack_type

        # Get source position for projectiles
        source_wx: float | None = None
        source_wy: float | None = None
        if is_projectile and event.source_id:
            source = self.combat.combatants.get(event.source_id)
            if source and source.position:
                source_wx, source_wy = source.position.to_pixel(hex_size)

        self._active_animations.append(ActiveAnimation(
            animation_name=anim_name,
            frames=frames,
            fps=get_animation_fps(anim_name),
            spawn_time=now,
            target_wx=target_wx,
            target_wy=target_wy,
            source_wx=source_wx,
            source_wy=source_wy,
            is_projectile=is_projectile,
        ))

        # During AI turns, zoom out to frame both attacker and target
        if (
            is_projectile
            and source_wx is not None
            and source_wy is not None
            and self.ai_runner.is_active
            and self.grid_view
        ):
            self._zoom_to_frame_pair(
                source_wx, source_wy, target_wx, target_wy,
            )

        # Play accompanying sound if present
        from arena.gui.animation_cache import get_animation_sound
        sound = get_animation_sound(anim_name)
        if sound is not None:
            try:
                settings = get_settings()
                # Use SFX volume from settings (0-100 → 0.0-1.0)
                master = settings.audio.master_volume / 100.0
                sfx = settings.audio.sfx_volume / 100.0
                sound.set_volume(master * sfx)
                sound.play()
            except Exception:
                pass  # Don't crash if sound playback fails

    def _try_spawn_visual_effect(
        self, event, hex_size: int, now: int,
    ) -> None:
        """Spawn programmatic visual effects from combat events."""
        from arena.gui.visual_effects import TeleportEffect, ForcedMovementEffect, _FM_COLORS

        # Terrain modification effect (own event type)
        if event.event_type == CombatEventType.TERRAIN_MODIFICATION:
            details = event.details
            center = details.get("center_hex")
            if center is not None and details.get("terrain_modified"):
                from arena.gui.visual_effects import TerrainModificationEffect, TERRAIN_MOD_COLORS
                cx, cy = HexCoord(center[0], center[1]).to_pixel(hex_size)
                terrain_type = details.get("terrain_type", "normal")
                color = TERRAIN_MOD_COLORS.get(terrain_type, (200, 200, 200))
                radius = float(details.get("radius_feet", 0))
                self._visual_effects.append(TerrainModificationEffect(
                    center_wx=cx, center_wy=cy,
                    radius_feet=radius, color=color, spawn_time=now,
                ))
            return

        # Forced movement effect (own event type)
        if event.event_type == CombatEventType.FORCED_MOVEMENT:
            details = event.details
            from_hex = details.get("from_hex")
            to_hex = details.get("to_hex")
            fm_type = details.get("fm_type", "push")
            if from_hex and to_hex and from_hex != to_hex:
                ox, oy = HexCoord(from_hex[0], from_hex[1]).to_pixel(hex_size)
                dx, dy = HexCoord(to_hex[0], to_hex[1]).to_pixel(hex_size)
                color = _FM_COLORS.get(fm_type, (255, 140, 60))
                self._visual_effects.append(ForcedMovementEffect(
                    origin_wx=ox, origin_wy=oy,
                    dest_wx=dx, dest_wy=dy,
                    color=color, spawn_time=now,
                ))
            return

        # Teleport effect (own event type)
        if event.event_type == CombatEventType.TELEPORT:
            details = event.details
            from_hex = details.get("from_hex")
            to_hex = details.get("to_hex")
            if from_hex and to_hex and not details.get("is_passenger"):
                ox, oy = HexCoord(from_hex[0], from_hex[1]).to_pixel(hex_size)
                dx, dy = HexCoord(to_hex[0], to_hex[1]).to_pixel(hex_size)
                self._visual_effects.append(TeleportEffect(
                    origin_wx=ox, origin_wy=oy,
                    dest_wx=dx, dest_wy=dy,
                    spawn_time=now,
                ))
            return

        if event.event_type != CombatEventType.INFO:
            return

        details = event.details

        # AoE blast effect (Fireball, Shatter, etc.)
        aoe_center = details.get("aoe_center_hex")
        area_size = details.get("area_size")
        if aoe_center is not None and area_size is not None:
            cx, cy = HexCoord(aoe_center[0], aoe_center[1]).to_pixel(hex_size)
            color = get_damage_color(details.get("aoe_damage_type", "force"))
            self._visual_effects.append(AoEBlastEffect(
                center_wx=cx, center_wy=cy,
                radius_feet=float(area_size), color=color, spawn_time=now,
            ))
            return

        # Zone creation pulse
        if details.get("zone_created"):
            center = details.get("zone_center_hex")
            if center is not None:
                zx, zy = HexCoord(center[0], center[1]).to_pixel(hex_size)
                color = get_damage_color(details.get("zone_damage_type", "radiant"))
                self._visual_effects.append(ZoneCreationPulse(
                    center_wx=zx, center_wy=zy,
                    radius_feet=float(details.get("zone_radius_feet", 15)),
                    color=color, spawn_time=now,
                ))
            return

        # Zone damage flash
        zone_dmg_id = details.get("zone_damage")
        if zone_dmg_id:
            self._zone_damage_flashes.append(ZoneDamageFlash(
                zone_id=zone_dmg_id, spawn_time=now,
            ))
            return

        # Summon / Wild Shape spawn effect
        summon_hex = details.get("summon_hex")
        if summon_hex is not None:
            sx, sy = HexCoord(summon_hex[0], summon_hex[1]).to_pixel(hex_size)
            is_ws = details.get("is_wild_shape", False)
            self._visual_effects.append(SpawnEffect(
                center_wx=sx, center_wy=sy,
                color=(200, 180, 255) if is_ws else (100, 255, 180),
                spawn_time=now, is_wild_shape=is_ws,
            ))

    def _render_telegraphs(self, surface: pygame.Surface) -> None:
        """Render pulsing danger-zone overlays for incoming AI AoEs."""
        if not self._active_telegraphs or self.grid_view is None:
            return

        now = pygame.time.get_ticks()
        hex_size = get_settings().display.default_hex_size
        scaled_size = hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin
        alive: list[TelegraphState] = []

        for tg in self._active_telegraphs:
            elapsed = now - tg.spawn_time
            if elapsed >= tg.duration:
                continue
            alive.append(tg)
            # Urgent pulse (~2 Hz) so the zone reads as danger, not decor
            pulse = 0.5 + 0.5 * math.sin(elapsed / 80.0)
            alpha = int(45 + 75 * pulse)
            for q, r in tg.hexes:
                wx, wy = HexCoord(q, r).to_pixel(hex_size)
                sx, sy = self.grid_view.camera.world_to_screen(wx, wy)
                draw_hex_highlight(
                    surface, (sx + ox, sy + oy), scaled_size,
                    tg.color, alpha=alpha,
                )

        self._active_telegraphs = alive

    def _render_visual_effects(self, surface: pygame.Surface) -> None:
        """Render programmatic visual effects (AoE blasts, spawn glows, etc.)."""
        if not self._visual_effects or self.grid_view is None:
            return
        hex_size = get_settings().display.default_hex_size
        self._visual_effects = render_visual_effects(
            self._visual_effects, surface,
            self.grid_view.camera, self.grid_view.origin, hex_size,
        )

    # ------------------------------------------------------------------
    # Save / Load support
    # ------------------------------------------------------------------

    def load_from_save(self, cm: CombatManager) -> None:
        """Restore combat from a deserialized CombatManager.

        Unlike load_encounter(), this does NOT roll initiative or call
        begin_combat — the manager is already in a mid-combat state.
        """
        self.combat = cm
        self.combat._oa_prompts_enabled = True  # interactive OA prompts (see __init__)

        # Create grid view from the loaded grid
        if cm.grid:
            self.grid_view = GridView(
                cm.grid,
                self.grid_rect.width,
                self.grid_rect.height,
                origin=(self.grid_rect.x, self.grid_rect.y),
            )

        # Connect panels to the loaded combat manager
        self.initiative_panel.set_combat(self.combat)
        self.creature_info_panel.set_combat(self.combat)
        self.radial_menu.set_combat(self.combat)
        self.log_panel.set_log(self.combat.log)
        self.log_panel.team_resolver = self._log_team_for

        # Skip existing log events so they don't replay as visual effects
        self._last_event_index = len(self.combat.log.events)
        self._visual_effects.clear()
        self._zone_shimmer_states.clear()
        self._zone_damage_flashes.clear()
        self._director.clear(pygame.time.get_ticks())
        self._pending_impact = None
        self._impact_source = None
        self._pending_anim = None
        self._hp_credit.clear()
        self._downed_hold.clear()
        self._lunge_animations.clear()
        self._active_telegraphs.clear()
        self._log_reveal_index = len(self.combat.log.events)
        self.log_panel.reveal_count = self._log_reveal_index

        # Select the active combatant
        active = self.combat.active_combatant
        if active:
            self._select_creature_by_id(active.creature_id)

        # Check if the current turn is an AI turn
        self._check_ai_turn()

    def _save_combat(self) -> None:
        """Save current combat state to data/saves/."""
        from datetime import datetime
        from arena.util.loader import save_combat_state
        from arena.combat.events import CombatEvent, CombatEventType

        if self.combat.state != CombatState.IN_COMBAT:
            return

        slug = self._encounter_name.lower().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{slug}_{timestamp}.json"
        save_path = Path("data") / "saves" / filename

        save_combat_state(self.combat, save_path)

        from arena.audio.manager import get_sound_manager
        get_sound_manager().play_sfx("save_success")

        self.combat.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"Combat state saved.",
        ))

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_aoe_zones(self, surface: pygame.Surface) -> None:
        """Render persistent AoE zone overlays on the hex grid."""
        if self.combat.state not in (CombatState.IN_COMBAT,):
            return
        if not self.combat.active_zones:
            return

        from arena.combat.zones import get_zone_hexes
        import random as _random

        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin
        now = pygame.time.get_ticks()

        for zone in self.combat.active_zones:
            # Lazy-init shimmer state for this zone
            if zone.zone_id not in self._zone_shimmer_states:
                self._zone_shimmer_states[zone.zone_id] = ZoneShimmerState(
                    zone_id=zone.zone_id,
                    phase_offset=_random.random(),
                )

            # Dynamic alpha: shimmer + optional damage flash boost
            base_alpha = get_zone_shimmer_alpha(zone.zone_id, now, self._zone_shimmer_states)
            flash_boost = get_zone_flash_boost(zone.zone_id, now, self._zone_damage_flashes)
            final_alpha = min(255, base_alpha + flash_boost)

            # Pick color based on zone's team
            caster = self.combat.combatants.get(zone.caster_id)
            if caster and caster.team == "player":
                color = parse_color(COLORS["hex_zone_friendly"])
            else:
                color = parse_color(COLORS["hex_zone_enemy"])

            hexes = get_zone_hexes(zone, self.combat.combatants, self.combat.grid)
            for coord in hexes:
                wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                draw_hex_highlight(
                    surface, (lx + ox, ly + oy), scaled_size, color, alpha=final_alpha
                )

        # Prune expired damage flashes
        self._zone_damage_flashes = [
            f for f in self._zone_damage_flashes if not f.is_expired(now)
        ]
        # Remove shimmer states for zones that no longer exist
        active_ids = {z.zone_id for z in self.combat.active_zones}
        self._zone_shimmer_states = {
            k: v for k, v in self._zone_shimmer_states.items() if k in active_ids
        }

    # Per-wall display style: (RGB, base alpha). Damaging walls glow brighter;
    # Wall of Force is a faint shimmer (narratively invisible, but it must read).
    _WALL_STYLES = {
        "Wall of Force": ((120, 150, 230), 60),
        "Wall of Stone": ((140, 130, 120), 150),
        "Wall of Fire": ((235, 95, 30), 135),
        "Wall of Ice": ((150, 210, 235), 140),
        "Wall of Thorns": ((85, 145, 70), 140),
        "Blade Barrier": ((205, 205, 220), 140),
    }
    _WALL_DMG_COLORS = {
        "fire": (235, 95, 30), "cold": (150, 210, 235),
        "piercing": (85, 145, 70), "slashing": (205, 205, 220),
    }

    @classmethod
    def _wall_render_style(cls, wall) -> tuple:
        """(color, base_alpha) for a placed wall, by name then damage type."""
        if wall.name in cls._WALL_STYLES:
            return cls._WALL_STYLES[wall.name]
        color = cls._WALL_DMG_COLORS.get(
            (wall.damage_type or "").lower(), (150, 150, 160))
        return color, (130 if wall.damage_on_enter else 90)

    def _render_active_walls(self, surface: pygame.Surface) -> None:
        """Render placed wall spells so the barrier is visible on the field.

        A wall blocks movement/LOS even when it's narratively invisible (Wall of
        Force), so it must read on the grid — otherwise enemies just stop at thin
        air. A gentle global pulse gives the overlay life (and makes a faint
        force wall catch the eye)."""
        if self.combat.state != CombatState.IN_COMBAT:
            return
        if not self.combat.active_walls or self.grid_view is None:
            return

        import math
        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 400.0)

        for wall in self.combat.active_walls:
            color, base_alpha = self._wall_render_style(wall)
            alpha = min(255, int(base_alpha + 30 * pulse))
            for coord in wall.get_wall_hexes():
                wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                draw_hex_highlight(
                    surface, (lx + ox, ly + oy), scaled_size, color, alpha=alpha,
                )

    def _render_movement_range(self, surface: pygame.Surface) -> None:
        """Highlight hexes the active creature can move to."""
        if self.combat.state != CombatState.IN_COMBAT:
            return
        if self.combat.turn_phase != TurnPhase.AWAITING_ACTION:
            return

        combatant = self.combat.active_combatant
        if combatant is None:
            return
        if self.combat.movement.remaining_movement <= 0:
            return

        reachable = self.combat.movement.get_reachable(
            self.combat.grid, combatant.creature.size,
            anchor_position=combatant.position,
        )
        move_color = parse_color(COLORS["hex_move_range"])
        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin

        for (q, r), cost in reachable.items():
            if cost == 0:
                continue  # Skip the creature's own hex
            coord = HexCoord(q, r)
            wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
            lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
            draw_hex_highlight(
                surface, (lx + ox, ly + oy), scaled_size, move_color, alpha=80
            )

    def _render_teleport_range(self, surface: pygame.Surface) -> None:
        """Highlight valid teleport destination hexes with a cyan overlay."""
        if self.combat.state != CombatState.IN_COMBAT:
            return
        if self.combat.turn_phase != TurnPhase.SELECTING_TARGET:
            return
        if not self._pending_teleport:
            return

        action = self.combat.selected_action
        if action is None or action.teleport_range is None:
            return

        combatant = self.combat.active_combatant
        if combatant is None or combatant.position is None:
            return

        from arena.grid.footprint import min_distance_between

        tp_range = action.teleport_range
        hex_size = get_settings().display.default_hex_size
        scaled_size = hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin
        teleport_color = (100, 180, 255)  # Arcane cyan-blue

        # Highlight all valid destination hexes within teleport range
        for r in range(self.combat.grid.height):
            for q in range(self.combat.grid.width):
                coord = HexCoord(q, r)
                if coord == combatant.position:
                    continue
                if not self.combat.grid.is_passable(coord):
                    continue
                cell = self.combat.grid.get_cell(coord)
                if cell and cell.occupant_id is not None:
                    continue
                dist_feet = min_distance_between(
                    combatant.position, combatant.creature.size, coord, 1,
                ) * 5
                if dist_feet > tp_range:
                    continue
                wx, wy = coord.to_pixel(hex_size)
                lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                draw_hex_highlight(
                    surface, (lx + ox, ly + oy), scaled_size,
                    teleport_color, alpha=60,
                )

    def _render_ranged_range(self, surface: pygame.Surface) -> None:
        """Highlight hexes within ranged weapon range when a ranged action is selected.

        Shows normal range (brighter) and long/disadvantage range (dimmer)
        during SELECTING_TARGET after the player picks a ranged attack
        from the radial menu.
        """
        if self.combat.state != CombatState.IN_COMBAT:
            return
        if self.combat.turn_phase != TurnPhase.SELECTING_TARGET:
            return

        action = self.combat.selected_action
        if action is None:
            return
        if not action.attack or not action.attack.attack_type.startswith("ranged"):
            return

        combatant = self.combat.active_combatant
        if combatant is None or combatant.position is None:
            return

        # Get the selected action's specific ranges
        normal_range = action.attack.range_normal or action.range
        long_range = action.attack.range_long or normal_range
        if normal_range == 0:
            return

        # Convert feet to hexes
        normal_hexes = normal_range // 5
        long_hexes = long_range // 5

        normal_color = parse_color(COLORS["hex_ranged_normal"])
        long_color = parse_color(COLORS["hex_ranged_long"])
        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin

        # For multi-hex creatures, check from all occupied hexes
        from arena.grid.footprint import get_occupied_hexes
        origin_hexes = get_occupied_hexes(combatant.position, combatant.creature.size)

        grid = self.combat.grid
        for q in range(grid.width):
            for r in range(grid.height):
                coord = HexCoord(q, r)
                # Min distance from any origin hex to this hex
                dist = min(oh.distance_to(coord) for oh in origin_hexes)
                if dist == 0:
                    continue  # Skip creature's own hexes

                if dist <= normal_hexes:
                    wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                    lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                    draw_hex_highlight(
                        surface, (lx + ox, ly + oy), scaled_size,
                        normal_color, alpha=55,
                    )
                elif dist <= long_hexes:
                    wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                    lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                    draw_hex_highlight(
                        surface, (lx + ox, ly + oy), scaled_size,
                        long_color, alpha=35,
                    )

    def _render_attack_range(self, surface: pygame.Surface) -> None:
        """Highlight valid targets when selecting a target for an attack."""
        if self.combat.turn_phase != TurnPhase.SELECTING_TARGET:
            return
        if self.combat.selected_action is None:
            return

        action = self.combat.selected_action
        combatant = self.combat.active_combatant
        if combatant is None or combatant.position is None:
            return

        attack_color = parse_color(COLORS["hex_attack_range"])
        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin

        for cid, target in self.combat.combatants.items():
            if cid == combatant.creature_id:
                continue
            if not target.creature.is_conscious:
                continue
            if target.position is None:
                continue

            if is_in_range(
                combatant.position, target.position, action,
                combatant.creature.size, target.creature.size,
            ):
                # Highlight all hexes of target's footprint
                from arena.grid.footprint import get_occupied_hexes
                for h in get_occupied_hexes(target.position, target.creature.size):
                    wx, wy = h.to_pixel(get_settings().display.default_hex_size)
                    lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                    draw_hex_highlight(
                        surface, (lx + ox, ly + oy), scaled_size, attack_color, alpha=100
                    )

    def _render_legendary_range(self, surface: pygame.Surface) -> None:
        """Highlight all hexes within legendary action range.

        Shows a purple area overlay (like the ranged attack range indicator)
        covering every hex within the legendary action's range, so the
        player can see the full reach before picking a target.
        """
        if self._legendary_selected_action is None:
            return
        if self.grid_view is None or self.combat.grid is None:
            return

        action = self._legendary_selected_action
        actor = self.combat.legendary_actor
        if actor is None or actor.position is None:
            return

        # Determine effective range in feet
        if action.attack:
            atk = action.attack
            if atk.attack_type.startswith("ranged"):
                range_feet = atk.range_normal or action.range or 0
            else:
                # Melee: use reach
                range_feet = atk.reach or action.range or 5
        elif action.saving_throw:
            range_feet = action.range or 0
        else:
            range_feet = action.range or 0

        if range_feet <= 0:
            return

        range_hexes = range_feet // 5

        legendary_color = (140, 80, 220)  # Purple to match legendary theme
        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin

        # For multi-hex creatures, check from all occupied hexes
        from arena.grid.footprint import get_occupied_hexes
        origin_hexes = get_occupied_hexes(actor.position, actor.creature.size)

        grid = self.combat.grid
        for q in range(grid.width):
            for r in range(grid.height):
                coord = HexCoord(q, r)
                # Min distance from any origin hex to this hex
                dist = min(oh.distance_to(coord) for oh in origin_hexes)
                if dist == 0:
                    continue  # Skip creature's own hexes

                if dist <= range_hexes:
                    wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                    lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                    draw_hex_highlight(
                        surface, (lx + ox, ly + oy), scaled_size,
                        legendary_color, alpha=55,
                    )

    def _render_aoe_preview(self, surface: pygame.Surface) -> None:
        """Highlight the AoE blast radius centered on the hovered hex.

        Shown during SELECTING_TARGET when the selected action has an
        area_* target type, OR when in zone-move mode.  The preview
        follows the mouse cursor so the player can see which hexes will
        be affected before clicking.
        """
        if self.combat.turn_phase != TurnPhase.SELECTING_TARGET:
            return

        combatant = self.combat.active_combatant
        if combatant is None or combatant.position is None:
            return
        if self.grid_view is None or self.grid_view.hovered_hex is None:
            return

        center_hex = self.grid_view.hovered_hex
        grid = self.combat.grid
        if grid is None or not grid.is_valid(center_hex):
            return

        # Wall placement preview (D-WALL-1): draw the hex line the wall will
        # occupy — from the anchored end (or the caster, before the first click)
        # to the hovered hex, capped at the spell's length. Preview == reality
        # (same hex_line + length cap as execute_wall_line).
        if self._pending_wall:
            action = self.combat.selected_action
            if action is None or not action.is_wall:
                return
            anchor = self._wall_anchor or combatant.position
            # Same geometry + length cap as the cast — preview can't lie.
            wall_shape = {
                (h.q, h.r)
                for h in self.combat.wall_line_hexes(anchor, center_hex, action)
            }
            preview_color = parse_color(COLORS["hex_aoe_preview"])
            scaled_size = (get_settings().display.default_hex_size
                           * self.grid_view.camera.zoom)
            ox, oy = self.grid_view.origin
            for q, r in wall_shape:
                coord = HexCoord(q, r)
                wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
                lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                draw_hex_highlight(
                    surface, (lx + ox, ly + oy), scaled_size,
                    preview_color, alpha=90,
                )
            return

        from arena.grid.footprint import min_distance_between

        # Determine area radius and range from either zone-move state
        # or the currently selected action.
        area_feet: float | None = None
        max_range: int = 0

        if self._pending_zone_move:
            area_feet = float(self._zone_move_radius)
            max_range = self._zone_move_range
        else:
            action = self.combat.selected_action
            if action is None:
                return
            if not action.target_type.value.startswith("area_"):
                return
            if action.attack is not None:
                return  # AoE attacks (breath weapons) use creature targeting
            area_feet = float(action.area_size or action.range)
            max_range = action.range

        # Emanating shapes (cone/line) aim by direction and self-limit to their
        # length; placed shapes (sphere/cube) must land within range.
        action = None if self._pending_zone_move else self.combat.selected_action
        emanating = action is not None and is_emanating(action)
        if not emanating:
            dist_feet = min_distance_between(
                combatant.position, combatant.creature.size,
                center_hex, 1,
            ) * 5
            if dist_feet > max_range:
                return

        # The exact hex set that will be hit — the SAME geometry the resolver
        # uses (aoe_hexes), so the preview can't lie. Zone-move has no action:
        # fall back to a plain radius around the hovered hex.
        if action is not None:
            from arena.grid.aoe_shapes import aoe_hexes
            shape = {
                (h.q, h.r) for h in aoe_hexes(
                    action, combatant.position, center_hex, grid,
                )
            }
        else:
            area_hexes = area_feet / 5
            shape = {
                (q, r)
                for q in range(grid.width) for r in range(grid.height)
                if center_hex.distance_to(HexCoord(q, r)) <= area_hexes
            }

        preview_color = parse_color(COLORS["hex_aoe_preview"])
        scaled_size = get_settings().display.default_hex_size * self.grid_view.camera.zoom
        ox, oy = self.grid_view.origin

        for q, r in shape:
            coord = HexCoord(q, r)
            wx, wy = coord.to_pixel(get_settings().display.default_hex_size)
            lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
            draw_hex_highlight(
                surface, (lx + ox, ly + oy), scaled_size,
                preview_color, alpha=60,
            )

        # Mark every creature actually caught in the blast (same geometry as
        # _resolve_effect_targets_at_hex). Friendly fire is real (B5), so a
        # caught ally glows warning-red — see the splash BEFORE you click.
        if not self._pending_zone_move:
            from arena.grid.footprint import get_occupied_hexes
            warning_color = parse_color(COLORS["hp_critical"])
            caster_team = combatant.team
            # Beneficial AoE (Mass Cure) never splashes — no warning there
            harmful = not (action.healing and not action.saving_throw)
            # Sculpt Spells: this caster's blasts spare allies entirely —
            # no red warning (and no hit) for the caster's own side.
            from arena.combat.stat_modifiers import has_sculpt_spells
            sculpted = harmful and has_sculpt_spells(combatant.creature)
            for c in self.combat.combatants.values():
                if c.position is None or not c.creature.is_conscious:
                    continue
                caught = any(
                    (h.q, h.r) in shape
                    for h in get_occupied_hexes(c.position, c.creature.size)
                )
                if not caught:
                    continue
                if sculpted and c.team == caster_team:
                    continue  # exempt: not caught at all, draw nothing
                warn = harmful and c.team == caster_team
                wx, wy = c.position.to_pixel(
                    get_settings().display.default_hex_size
                )
                lx, ly = self.grid_view.camera.world_to_screen(wx, wy)
                draw_hex_highlight(
                    surface, (lx + ox, ly + oy), scaled_size,
                    warning_color if warn else preview_color,
                    alpha=150 if warn else 110,
                )

    def _render_tokens(self, surface: pygame.Surface) -> None:
        """Render all creature tokens on the grid."""
        if self.grid_view is None:
            return

        active_entry = self.combat.initiative.current_entry
        active_id = active_entry.creature_id if active_entry else None

        now = pygame.time.get_ticks()
        expired: list[str] = []
        lunge_expired: list[str] = []

        for cid, combatant in self.combat.combatants.items():
            # Compute interpolated position if a hop animation is active
            pixel_override: tuple[float, float] | None = None
            if cid in self._move_animations:
                sx, sy, ex, ey, start_time, duration = self._move_animations[cid]
                elapsed = now - start_time
                if elapsed >= duration:
                    expired.append(cid)
                else:
                    t = elapsed / duration
                    # Ease-out quadratic for a snappy hop feel
                    t = 1.0 - (1.0 - t) ** 2
                    pixel_override = (sx + (ex - sx) * t, sy + (ey - sy) * t)

            # Charge lunge: dart toward the target and back (apex at the
            # midpoint, where the impact beat lands)
            if pixel_override is None and cid in self._lunge_animations:
                fx, fy, tx, ty, start_time, duration = self._lunge_animations[cid]
                elapsed = now - start_time
                if elapsed >= duration:
                    lunge_expired.append(cid)
                else:
                    k = math.sin(math.pi * (elapsed / duration)) * LUNGE_EXTENT
                    pixel_override = (fx + (tx - fx) * k, fy + (ty - fy) * k)

            # Animated HP percentage
            display_hp_pct: float | None = None
            max_hp = combatant.creature.max_hit_points
            if cid in self._display_hp and max_hp > 0:
                display_hp_pct = max(0.0, self._display_hp[cid] / max_hp)

            # Damage flash (fades out over FLASH_DURATION_MS)
            flash_alpha = 0
            if cid in self._flash_until:
                remaining = self._flash_until[cid] - now
                if remaining > 0:
                    flash_alpha = int(180 * (remaining / FLASH_DURATION_MS))
                else:
                    del self._flash_until[cid]

            draw_token(
                surface,
                combatant,
                self.grid_view.camera,
                is_selected=(cid == self.selected_creature_id),
                is_active_turn=(cid == active_id),
                origin=self.grid_view.origin,
                pixel_override=pixel_override,
                display_hp_pct=display_hp_pct,
                flash_alpha=flash_alpha,
                appear_conscious=(cid in self._downed_hold),
            )

        for cid in expired:
            del self._move_animations[cid]
        for cid in lunge_expired:
            del self._lunge_animations[cid]

    def _render_action_animations(self, surface: pygame.Surface) -> None:
        """Render active action/spell animations (impacts and projectiles)."""
        if not self._active_animations or self.grid_view is None:
            return

        now = pygame.time.get_ticks()
        camera = self.grid_view.camera
        ox, oy = self.grid_view.origin
        alive: list[ActiveAnimation] = []

        for anim in self._active_animations:
            elapsed = now - anim.spawn_time

            # Projectile travel phase (ranged attacks)
            if anim.is_projectile and anim.source_wx is not None:
                if elapsed < anim.projectile_duration_ms:
                    # Interpolate position from source to target
                    t = elapsed / anim.projectile_duration_ms
                    t = 1.0 - (1.0 - t) ** 2  # ease-out quadratic
                    cur_wx = anim.source_wx + (anim.target_wx - anim.source_wx) * t
                    cur_wy = anim.source_wy + (anim.target_wy - anim.source_wy) * t
                    # Rotate first frame to match flight direction.
                    # Frames are authored pointing right (→ = 0°);
                    # pygame.transform.rotate() goes counter-clockwise.
                    dx = anim.target_wx - anim.source_wx
                    dy = anim.target_wy - anim.source_wy
                    angle_deg = -math.degrees(math.atan2(dy, dx))
                    frame = pygame.transform.rotate(anim.frames[0], angle_deg)
                    sx, sy = camera.world_to_screen(cur_wx, cur_wy)
                    rect = frame.get_rect(center=(int(sx) + ox, int(sy) + oy))
                    surface.blit(frame, rect)
                    alive.append(anim)
                    continue
                else:
                    # Switch to impact phase — adjust elapsed time
                    elapsed -= anim.projectile_duration_ms

            # Impact/effect phase: cycle through frames at configured FPS
            frame_duration_ms = 1000.0 / max(1, anim.fps)
            total_duration = len(anim.frames) * frame_duration_ms

            if elapsed >= total_duration:
                continue  # Animation complete

            frame_idx = min(int(elapsed / frame_duration_ms), len(anim.frames) - 1)
            frame = anim.frames[frame_idx]

            # Rotate impact frames for projectiles so debris/shatter
            # aligns with the flight direction (same angle as travel).
            if anim.is_projectile and anim.source_wx is not None:
                dx = anim.target_wx - anim.source_wx
                dy = anim.target_wy - anim.source_wy
                angle_deg = -math.degrees(math.atan2(dy, dx))
                frame = pygame.transform.rotate(frame, angle_deg)

            sx, sy = camera.world_to_screen(anim.target_wx, anim.target_wy)
            rect = frame.get_rect(center=(int(sx) + ox, int(sy) + oy))
            surface.blit(frame, rect)
            alive.append(anim)

        self._active_animations = alive

    def _render_floating_texts(self, surface: pygame.Surface) -> None:
        """Render floating damage/healing numbers that drift up and fade."""
        if not self._floating_texts or self.grid_view is None:
            return

        now = pygame.time.get_ticks()
        camera = self.grid_view.camera
        ox, oy = self.grid_view.origin
        alive: list[FloatingText] = []

        for ft in self._floating_texts:
            elapsed = now - ft.spawn_time
            if elapsed >= ft.duration:
                continue  # expired
            alive.append(ft)

            t = elapsed / ft.duration  # 0.0 → 1.0

            # Convert world position to screen
            sx, sy = camera.world_to_screen(ft.world_x, ft.world_y)
            screen_x = int(sx) + ox
            screen_y = int(sy) + oy

            # Drift upward and fade out
            y_offset = int(FLOATING_TEXT_DRIFT_PX * t)
            alpha = int(255 * (1.0 - t))

            font = get_font(max(12, int(16 * camera.zoom)))
            text_surf = font.render(ft.text, True, ft.color)
            # Apply alpha via a temporary surface
            alpha_surf = pygame.Surface(text_surf.get_size(), pygame.SRCALPHA)
            alpha_surf.blit(text_surf, (0, 0))
            alpha_surf.set_alpha(alpha)

            rect = alpha_surf.get_rect(center=(screen_x, screen_y - y_offset))
            surface.blit(alpha_surf, rect)

        self._floating_texts = alive

    def _render_shortcuts_help(self, surface: pygame.Surface) -> None:
        """Render a semi-transparent overlay showing keyboard shortcuts."""
        shortcuts = [
            ("Right-click", "Toggle Action Menu"),
            ("Space / Enter", "End Turn"),
            ("Tab", "Cycle Selected Creature"),
            ("Backspace", "Cancel Target Selection"),
            ("C", "Center on Active Creature"),
            ("G", "Toggle Grid Coordinates"),
            ("Ctrl+S", "Save Combat State"),
            ("Home", "Center Camera on Grid"),
            ("Esc", "Return to Main Menu"),
            ("?", "Toggle This Help"),
        ]

        font = get_font(FONT_SIZES["label"])
        title_font = get_font(FONT_SIZES["title"], "heading")
        padding = 16
        line_height = 22
        col_gap = 20

        # Measure
        key_width = max(font.size(s[0])[0] for s in shortcuts) + col_gap
        desc_width = max(font.size(s[1])[0] for s in shortcuts)
        box_width = key_width + desc_width + padding * 2
        box_height = len(shortcuts) * line_height + padding * 2 + 28

        # Center on screen
        box_x = (self.screen_width - box_width) // 2
        box_y = (self.screen_height - box_height) // 2

        # Semi-transparent background
        overlay = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
        overlay.fill((26, 20, 16, 230))
        surface.blit(overlay, (box_x, box_y))
        pygame.draw.rect(
            surface, parse_color(COLORS["border_accent"]),
            (box_x, box_y, box_width, box_height), 1,
        )

        # Title
        title = title_font.render(
            "Keyboard Shortcuts", True, parse_color(COLORS["text_gold"]),
        )
        surface.blit(title, (box_x + padding, box_y + padding))

        # Shortcut lines
        y = box_y + padding + 28
        for key_text, desc_text in shortcuts:
            key_surf = font.render(
                key_text, True, parse_color(COLORS["team_player"]),
            )
            desc_surf = font.render(
                desc_text, True, parse_color(COLORS["text_secondary"]),
            )
            surface.blit(key_surf, (box_x + padding, y))
            surface.blit(desc_surf, (box_x + padding + key_width, y))
            y += line_height

    def _render_end_overlay(self, surface: pygame.Surface) -> None:
        """Render the victory or defeat overlay."""
        overlay = pygame.Surface(
            (self.screen_width, self.screen_height), pygame.SRCALPHA
        )
        overlay.fill((20, 16, 10, 180))
        surface.blit(overlay, (0, 0))

        font = get_font(48, "heading")
        if self.combat.winner == "player":
            text = "VICTORY!"
            color = parse_color(COLORS["text_gold"])
        else:
            text = "DEFEAT!"
            color = parse_color(COLORS["hp_critical"])

        text_surf = font.render(text, True, color)
        text_rect = text_surf.get_rect(
            center=(self.screen_width // 2, self.screen_height // 2 - 20)
        )
        surface.blit(text_surf, text_rect)

        sub_font = get_font(20)
        sub_text = f"Combat ended in {self.combat.initiative.round_number} rounds"
        sub_surf = sub_font.render(
            sub_text, True, parse_color(COLORS["text_primary"])
        )
        sub_rect = sub_surf.get_rect(
            center=(self.screen_width // 2, self.screen_height // 2 + 30)
        )
        surface.blit(sub_surf, sub_rect)

        hint_font = get_font(16)
        hint_text = ("Press ESC to return to the story" if self.handoff_mode
                     else "Press ESC to quit")
        hint_surf = hint_font.render(
            hint_text, True, parse_color(COLORS["text_secondary"])
        )
        hint_rect = hint_surf.get_rect(
            center=(self.screen_width // 2, self.screen_height // 2 + 60)
        )
        surface.blit(hint_surf, hint_rect)

    def _render_hover_tooltip(self, surface: pygame.Surface) -> None:
        """Render a floating tooltip near the mouse for the hovered creature.

        Shows creature name, HP (color-coded), AC, speed, and active
        conditions.  Positioned near the mouse cursor and clamped to
        screen bounds so it never goes off-screen.
        """
        combatant = self.combat.get_creature(self._hovered_creature_id)
        if combatant is None:
            return

        creature = combatant.creature
        white = parse_color(COLORS["text_primary"])
        gray = parse_color(COLORS["text_secondary"])

        # Build tooltip lines as (text, color) pairs
        lines: list[tuple[str, tuple[int, int, int]]] = []

        # Name
        lines.append((creature.name, white))

        # HP (color-coded by health status)
        hp_pct = creature.hp_percent
        if hp_pct > 0.5:
            hp_color = parse_color(COLORS["hp_full"])
        elif hp_pct > 0.25:
            hp_color = parse_color(COLORS["hp_bloodied"])
        else:
            hp_color = parse_color(COLORS["hp_critical"])
        hp_text = f"HP: {creature.current_hit_points}/{creature.max_hit_points}"
        temp_hp = getattr(creature, "temporary_hit_points", 0) or 0
        if temp_hp > 0:
            hp_text += f" (+{temp_hp} temp)"
        lines.append((hp_text, hp_color))

        # AC and Speed
        speed_val = get_effective_speed(creature)
        lines.append((f"AC: {get_effective_armor_class(creature)}  Speed: {speed_val} ft", gray))

        # Conditions (if any)
        if creature.active_conditions:
            cond_names = [
                ac.condition.value.capitalize()
                for ac in creature.active_conditions
            ]
            lines.append(
                ("Conditions: " + ", ".join(cond_names),
                 parse_color(COLORS["condition_debuff"]))
            )

        # Terrain (if creature is on special terrain)
        if self._hovered_terrain_type is not None:
            terrain_name = TERRAIN_NAMES.get(
                self._hovered_terrain_type, "Unknown Terrain"
            )
            lines.append(
                (f"Terrain: {terrain_name}",
                 parse_color(COLORS["border_accent"]))
            )

        # Render layout
        font = get_font(FONT_SIZES["label"])
        padding = 6
        line_height = 18

        max_text_width = max(font.size(text)[0] for text, _ in lines)
        tooltip_width = max_text_width + padding * 2
        tooltip_height = len(lines) * line_height + padding * 2

        # Position near mouse cursor, offset down-right
        mouse_x, mouse_y = pygame.mouse.get_pos()
        tooltip_x = mouse_x + 16
        tooltip_y = mouse_y + 16

        # Clamp to screen bounds (flip to other side if near edge)
        if tooltip_x + tooltip_width > self.screen_width:
            tooltip_x = mouse_x - tooltip_width - 8
        if tooltip_y + tooltip_height > self.screen_height:
            tooltip_y = mouse_y - tooltip_height - 8

        # Semi-transparent background
        tooltip_bg = pygame.Surface(
            (tooltip_width, tooltip_height), pygame.SRCALPHA
        )
        tooltip_bg.fill(TOOLTIP_BG_RGBA)
        surface.blit(tooltip_bg, (tooltip_x, tooltip_y))

        # Border
        tooltip_rect = pygame.Rect(
            tooltip_x, tooltip_y, tooltip_width, tooltip_height
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["border_accent"]), tooltip_rect, 1
        )

        # Text lines
        y = tooltip_y + padding
        for text, color in lines:
            text_surf = font.render(text, True, color)
            surface.blit(text_surf, (tooltip_x + padding, y))
            y += line_height

    def _render_terrain_tooltip(self, surface: pygame.Surface) -> None:
        """Render a floating tooltip showing terrain type near the mouse.

        Uses the same visual style as the creature hover tooltip.
        Only shown when hovering non-normal terrain with no creature present.
        """
        terrain_name = TERRAIN_NAMES.get(
            self._hovered_terrain_type, "Unknown Terrain"
        )
        # An authored hazard names its price up front ("Hazard — 1d6 fire on
        # entry"), so stepping in is a choice, not a surprise.
        if (self._hovered_terrain_type == TerrainType.HAZARD
                and self.grid_view is not None
                and self.grid_view.hovered_hex is not None):
            hh = self.grid_view.hovered_hex
            spec = self.combat.terrain_hazards.get((hh.q, hh.r))
            if spec:
                terrain_name = f"{terrain_name} — {spec} on entry"

        font = get_font(FONT_SIZES["label"])
        padding = 6

        text_surf = font.render(
            terrain_name, True, parse_color(COLORS["text_primary"]),
        )
        tooltip_width = text_surf.get_width() + padding * 2
        tooltip_height = text_surf.get_height() + padding * 2

        # Position near mouse cursor, offset down-right
        mouse_x, mouse_y = pygame.mouse.get_pos()
        tooltip_x = mouse_x + 16
        tooltip_y = mouse_y + 16

        # Clamp to screen bounds (flip to other side if near edge)
        if tooltip_x + tooltip_width > self.screen_width:
            tooltip_x = mouse_x - tooltip_width - 8
        if tooltip_y + tooltip_height > self.screen_height:
            tooltip_y = mouse_y - tooltip_height - 8

        # Semi-transparent background
        tooltip_bg = pygame.Surface(
            (tooltip_width, tooltip_height), pygame.SRCALPHA,
        )
        tooltip_bg.fill(TOOLTIP_BG_RGBA)
        surface.blit(tooltip_bg, (tooltip_x, tooltip_y))

        # Border
        tooltip_rect = pygame.Rect(
            tooltip_x, tooltip_y, tooltip_width, tooltip_height,
        )
        pygame.draw.rect(
            surface, parse_color(COLORS["border_accent"]), tooltip_rect, 1,
        )

        # Text
        surface.blit(text_surf, (tooltip_x + padding, tooltip_y + padding))
