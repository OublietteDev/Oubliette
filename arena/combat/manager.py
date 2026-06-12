"""Combat state machine and turn management."""

from __future__ import annotations

import copy
import random
from enum import Enum, auto
from dataclasses import dataclass
from pathlib import Path

from arena.combat.initiative import InitiativeTracker, InitiativeEntry
from arena.combat.events import CombatLog, CombatEvent, CombatEventType
from arena.combat.movement import MovementTracker
from arena.combat.actions import (
    resolve_attack, resolve_attack_hit, resolve_attack_damage,
    resolve_effect, ActionResult, AttackHitResult,
    get_effective_target_count,
)
from arena.combat.chain_effects import has_chain_effect, get_chain_targets
from arena.models.actions import DamageRoll
from arena.combat.conditions import process_start_of_turn, process_end_of_turn
from arena.combat.buff_effects import process_buff_start_of_turn, process_buff_end_of_turn
from arena.combat.death_saves import process_death_save
from arena.combat.condition_effects import can_take_actions, get_movement_multiplier
from arena.combat.stat_modifiers import (
    get_effective_speed,
    get_effective_ability_modifier,
    get_initiative_bonus,
    get_extra_attack_count,
)
from arena.combat.standard_actions import (
    execute_action_surge,
    execute_dash,
    execute_disengage,
    execute_dodge,
    execute_help,
    execute_hide,
)
from arena.combat.reactions import check_opportunity_attacks, execute_opportunity_attack
from arena.combat.ready_action import (
    ReadiedAction,
    TriggerType,
    set_ready_action,
    check_ready_triggers,
    expire_readied_actions,
)
from arena.grid.hexgrid import HexGrid
from arena.grid.coordinates import HexCoord
from arena.models.character import Creature
from arena.models.actions import Action
from arena.models.encounter import Encounter, CombatantEntry
from arena.util.dice import roll_die
from arena.util.loader import load_json
from arena.combat.riders import (
    discover_riders,
    RiderResult,
)
from arena.combat.recurring_actions import (
    ActiveRecurringAction,
    create_recurring_action,
    can_use_recurring_action,
    get_recurring_damage,
)
from arena.combat.counterspell import can_counterspell, resolve_counterspell
from arena.combat.forced_reroll import (
    get_forced_reroll_features,
    can_afford_reroll,
    deduct_reroll_cost,
)


class CombatState(Enum):
    """States of the combat state machine."""

    NOT_STARTED = auto()
    ROLLING_INITIATIVE = auto()
    IN_COMBAT = auto()
    COMBAT_ENDED = auto()


class TurnPhase(Enum):
    """Sub-states within a single turn."""

    START_OF_TURN = auto()
    AWAITING_ACTION = auto()
    SELECTING_TARGET = auto()
    LEGENDARY_ACTION_PHASE = auto()
    TURN_COMPLETE = auto()


@dataclass
class TurnResources:
    """Tracks which action economy slots have been used this turn.

    Per 5e rules:
    - One action per turn
    - One bonus action per turn (only if a feature grants one)
    - One reaction per round (resets at start of your turn)
    - One free object interaction per turn
    - is_disengaging: whether Disengage was used (prevents opportunity attacks)
    """

    has_used_action: bool = False
    has_used_bonus_action: bool = False
    has_used_reaction: bool = False
    free_actions_used: int = 0
    free_action_limit: int = 1
    is_disengaging: bool = False
    used_riders: set[str] | None = None  # Feature names of once-per-turn riders used
    attacks_remaining: int = 0  # Extra Attack: attacks left in current Attack action

    def reset_for_new_turn(self) -> None:
        """Reset resources at the start of a new turn.

        Reaction resets at start of own turn per 5e rules.
        """
        self.has_used_action = False
        self.has_used_bonus_action = False
        self.has_used_reaction = False
        self.free_actions_used = 0
        self.is_disengaging = False
        self.used_riders = None
        self.attacks_remaining = 0


@dataclass
class PendingSaveReroll:
    """State for a pending forced save reroll (Indomitable, Lucky, Diamond Soul).

    When a player-controlled creature fails a saving throw and has a reroll
    feature available, the effect resolution pauses and this state is set.
    The GUI shows a popup; the player chooses to use or skip the reroll.
    """

    target_id: str
    target_snapshot: object  # Deep copy of creature state before resolve_effect
    save_ability: str
    save_dc: int
    original_roll: int  # The natural roll that failed
    features: list  # list[Feature] that can reroll
    # Context to re-resolve if reroll is used
    user_id: str
    action: Action
    cast_level: int | None
    events_before: list  # Events accumulated before this target's resolve
    remaining_target_ids: list[str]  # Targets not yet processed
    remaining_index: int  # Index into target_ids where we paused
    saved_cost: dict  # Original resource_cost for restore
    saved_uses: int | None  # Original uses_per_rest for restore


@dataclass
class Combatant:
    """Runtime wrapper linking a creature to its grid presence.

    Attributes:
        creature_id: Unique ID for this combatant (e.g., "thorin", "goblin_1").
        creature: The Pydantic model instance (mutable HP, conditions, etc.).
        team: Team affiliation ("player", "enemy", "ally", "neutral").
        position: Current hex coordinate on the grid.
    """

    creature_id: str
    creature: Creature
    team: str
    position: HexCoord | None = None
    max_resources: dict[str, int] | None = None  # Snapshot of class_resources at combat start


class CombatManager:
    """Manages the overall combat state, turn flow, and creature registry."""

    def __init__(self) -> None:
        self.state: CombatState = CombatState.NOT_STARTED
        self.turn_phase: TurnPhase = TurnPhase.START_OF_TURN
        self.initiative: InitiativeTracker = InitiativeTracker()
        self.log: CombatLog = CombatLog()
        self.grid: HexGrid | None = None

        # Creature registry: creature_id -> Combatant
        self.combatants: dict[str, Combatant] = {}

        # Turn state
        self.movement: MovementTracker = MovementTracker(
            creature_id="", max_movement=0, remaining_movement=0
        )
        self.turn_resources: TurnResources = TurnResources()
        self.selected_action: Action | None = None
        self._cast_level: int | None = None

        # Per-combatant reaction tracking (resets at start of each creature's turn)
        self.reaction_used: dict[str, bool] = {}

        # Pending damage reduction reaction (for player-controlled targets)
        self._pending_damage_reduction: dict | None = None

        # Readied actions: creature_id -> ReadiedAction
        self.readied_actions: dict[str, ReadiedAction] = {}

        # Persistent AoE zones (e.g., Spirit Guardians)
        self.active_zones: list = []  # list[ActiveZone], imported lazily

        # Terrain modifications (e.g., Wall of Stone, Spike Growth)
        self.active_terrain_mods: list = []  # list[TerrainModification], imported lazily

        # Wall spells (e.g., Wall of Force, Wall of Fire)
        self.active_walls: list = []  # list[ActiveWall], imported lazily

        # Summoned creature tracking
        self.summon_links: dict[str, str] = {}  # summon_id -> summoner_id
        self.stored_creatures: dict[str, tuple] = {}  # summoner_id -> (original Creature, HexCoord | None)
        self.concentration_summons: set[str] = set()  # summon IDs linked to concentration

        # Recurring actions (Witch Bolt, Sunbeam, Call Lightning, Spiritual Weapon)
        self.active_recurring_actions: list[ActiveRecurringAction] = []

        # Legendary action tracking
        self.legendary_points: dict[str, int] = {}  # creature_id -> remaining points
        self._legendary_queue: list[str] = []  # eligible creature IDs after turn ends
        self._legendary_actor_id: str | None = None  # who is currently acting

        # Lair action tracking
        self.lair_actions: list = []  # list[Action], loaded from encounter
        self.last_lair_action_name: str | None = None  # prevent same action 2 rounds
        self._is_lair_turn: bool = False
        self._use_ai_for_lair: bool = True

        # Forced save reroll pending state (Indomitable, Lucky, Diamond Soul)
        self._pending_save_reroll: PendingSaveReroll | None = None
        self._pending_reroll_original_events: list = []
        self._pending_reroll_original_success: bool = False

        # Counterspell pending state (player-controlled counterspellers)
        self._pending_counterspell: dict | None = None

        # Result
        self.winner: str | None = None

        # Solo handoff play (Oubliette): with no allies to revive a downed PC, a
        # player team that is entirely UNCONSCIOUS is defeated immediately rather
        # than lingering through death saves in a vacuum (which never ends, so the
        # subprocess never exits and the calling story turn hangs). Off by default
        # — standalone play keeps the full death-save grace.
        self.solo_defeat_when_downed: bool = False

    # ------------------------------------------------------------------
    # Action Economy
    # ------------------------------------------------------------------

    @property
    def has_used_action(self) -> bool:
        """Backward-compatible access to action usage state."""
        return self.turn_resources.has_used_action

    @has_used_action.setter
    def has_used_action(self, value: bool) -> None:
        self.turn_resources.has_used_action = value

    def can_use_action_type(self, action_type: str) -> bool:
        """Check if the given action type slot is still available this turn.

        Args:
            action_type: One of "action", "bonus_action", "reaction", "free".

        Returns:
            True if the slot is available.
        """
        from arena.models.actions import ActionType

        if action_type == ActionType.ACTION.value or action_type == ActionType.ACTION:
            return not self.turn_resources.has_used_action
        elif action_type == ActionType.BONUS_ACTION.value or action_type == ActionType.BONUS_ACTION:
            return not self.turn_resources.has_used_bonus_action
        elif action_type == ActionType.REACTION.value or action_type == ActionType.REACTION:
            return not self.turn_resources.has_used_reaction
        elif action_type == ActionType.FREE.value or action_type == ActionType.FREE:
            return self.turn_resources.free_actions_used < self.turn_resources.free_action_limit
        # LEGENDARY and LAIR always allowed for now
        return True

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def load_encounter(self, encounter: Encounter, data_dir: Path) -> None:
        """Load an encounter, creating grid and placing combatants.

        Args:
            encounter: The Encounter model to load.
            data_dir: Base directory for resolving creature_id file paths.
        """
        self.grid = HexGrid(encounter.grid_width, encounter.grid_height)

        # Apply terrain
        for th in encounter.terrain:
            coord = HexCoord(th.position[0], th.position[1])
            self.grid.set_terrain(coord, th.terrain_type)

        # Load and place combatants
        for entry in encounter.combatants:
            for i in range(entry.count):
                creature = self._load_creature(entry, data_dir)

                # Apply encounter-level AI overrides
                if entry.team == "enemy" and not encounter.use_ai_for_enemies:
                    creature.is_player_controlled = True
                elif entry.team == "player" and encounter.use_ai_for_allies:
                    creature.is_player_controlled = False

                # Determine display name
                if entry.name_override:
                    display_name = entry.name_override
                elif entry.count > 1:
                    display_name = f"{creature.name} {i + 1}"
                else:
                    display_name = creature.name

                creature_id = self._make_unique_id(display_name)
                creature.name = display_name

                combatant = Combatant(
                    creature_id=creature_id,
                    creature=creature,
                    team=entry.team,
                )

                # Place on grid
                if entry.starting_position:
                    coord = HexCoord(
                        entry.starting_position[0], entry.starting_position[1]
                    )
                    if self.grid.place_creature(coord, creature_id, creature.size):
                        combatant.position = coord

                self.combatants[creature_id] = combatant

        # Load lair actions from encounter
        if encounter.has_lair and encounter.lair_actions:
            self.lair_actions = list(encounter.lair_actions)
        self._use_ai_for_lair = encounter.use_ai_for_enemies

    def _load_creature(self, entry: CombatantEntry, data_dir: Path) -> Creature:
        """Load a creature from file reference or inline data.

        Returns a deep copy so each instance has independent state.
        """
        if entry.creature_data:
            return entry.creature_data.model_copy(deep=True)

        file_path = data_dir / entry.creature_id
        data = load_json(file_path)

        # Determine model type from file path
        if "characters" in entry.creature_id:
            from arena.models.character import PlayerCharacter

            return PlayerCharacter.model_validate(data)
        else:
            from arena.models.monster import Monster

            return Monster.model_validate(data)

    def _make_unique_id(self, base_name: str) -> str:
        """Generate a unique creature ID from a display name."""
        slug = base_name.lower().replace(" ", "_")
        if slug not in self.combatants:
            return slug
        counter = 2
        while f"{slug}_{counter}" in self.combatants:
            counter += 1
        return f"{slug}_{counter}"

    # ------------------------------------------------------------------
    # Initiative
    # ------------------------------------------------------------------

    def roll_initiative(self) -> None:
        """Roll initiative for all combatants and sort."""
        self.state = CombatState.ROLLING_INITIATIVE
        self.initiative.reset()

        for cid, combatant in self.combatants.items():
            c = combatant.creature
            dex_mod = get_effective_ability_modifier(c, "dexterity")
            init_bonus = get_initiative_bonus(c)
            roll = roll_die(20) + dex_mod + init_bonus
            dex_score = c.ability_scores.get_score("dexterity")

            # Snapshot max resources for display (PlayerCharacter only)
            class_resources = getattr(c, "class_resources", None)
            if class_resources:
                combatant.max_resources = dict(class_resources)

            entry = InitiativeEntry(
                creature_id=cid,
                name=c.name,
                initiative_roll=roll,
                dexterity=dex_score,
                is_player_controlled=c.is_player_controlled,
                tiebreaker=random.random(),
            )
            self.initiative.add_entry(entry)

        self.log.add(
            CombatEvent(
                event_type=CombatEventType.COMBAT_START,
                message="Combat begins! Initiative rolled.",
            )
        )

        # Add lair pseudo-entry at initiative 20 (loses all ties)
        if self.lair_actions:
            lair_entry = InitiativeEntry(
                creature_id="__lair__",
                name="Lair",
                initiative_roll=20,
                dexterity=0,
                is_player_controlled=False,
                is_lair=True,
            )
            self.initiative.add_entry(lair_entry)

        # Log initiative order
        for entry in self.initiative.entries:
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"  {entry.name}: {entry.initiative_roll}",
                    source_id=entry.creature_id,
                )
            )

        # Initialize legendary action point pools
        for cid, combatant in self.combatants.items():
            legendary_count = getattr(combatant.creature, "legendary_action_count", 0)
            if legendary_count > 0:
                self.legendary_points[cid] = legendary_count

    def begin_combat(self) -> None:
        """Transition from ROLLING_INITIATIVE to IN_COMBAT. Start first turn."""
        self.state = CombatState.IN_COMBAT
        self.log.add(
            CombatEvent(
                event_type=CombatEventType.ROUND_START,
                message=f"--- Round {self.initiative.round_number} ---",
            )
        )
        self._start_current_turn()

    # ------------------------------------------------------------------
    # Turn Management
    # ------------------------------------------------------------------

    @property
    def active_combatant(self) -> Combatant | None:
        """Get the combatant whose turn it currently is."""
        entry = self.initiative.current_entry
        if entry is None:
            return None
        return self.combatants.get(entry.creature_id)

    def _start_current_turn(self) -> None:
        """Initialize state for the current creature's turn."""
        # Check for lair pseudo-turn first
        entry = self.initiative.current_entry
        if entry is not None and entry.is_lair:
            self._is_lair_turn = True
            self.turn_phase = TurnPhase.AWAITING_ACTION
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.TURN_START,
                    message="Lair Actions (Initiative 20)",
                )
            )
            return

        self._is_lair_turn = False

        combatant = self.active_combatant
        if combatant is None:
            return

        self.turn_phase = TurnPhase.START_OF_TURN
        self.turn_resources.reset_for_new_turn()
        self.selected_action = None
        self._cast_level = None

        # Reset legendary action points at start of own turn
        if combatant.creature_id in self.legendary_points:
            max_points = getattr(combatant.creature, "legendary_action_count", 0)
            self.legendary_points[combatant.creature_id] = max_points

        # Reset this creature's reaction for the new round
        self.reaction_used[combatant.creature_id] = False

        # Expire any readied action from this creature
        expire_events = expire_readied_actions(self, combatant.creature_id)
        for e in expire_events:
            self.log.add(e)

        # Reset movement (apply condition-based multiplier)
        base_speed = get_effective_speed(combatant.creature)
        multiplier = get_movement_multiplier(combatant.creature)
        speed = int(base_speed * multiplier)
        self.movement.reset(combatant.creature_id, speed)
        self.movement.dead_creature_ids = self._get_dead_creature_ids()
        self.movement.blocked_hexes = self._get_wall_blocked_hexes()

        # Process start-of-turn effects (condition ticks + buff duration ticks)
        events = process_start_of_turn(combatant.creature, combatant.creature_id)
        for e in events:
            self.log.add(e)
        buff_events = process_buff_start_of_turn(combatant.creature, combatant.creature_id)
        for e in buff_events:
            self.log.add(e)

        # Tick recurring action durations and remove expired ones
        self._tick_recurring_actions(combatant.creature_id)

        # Process persistent AoE zone damage (e.g., Spirit Guardians)
        if self.active_zones:
            from arena.combat.zones import process_zone_start_of_turn
            zone_events = process_zone_start_of_turn(
                self.active_zones, combatant.creature_id,
                self.combatants, self.grid,
            )
            for ze in zone_events:
                self.log.add(ze)
            # Zone damage may have broken concentration — clean up orphaned zones
            self._cleanup_orphaned_zones()
            # Zone damage could knock creature unconscious
            if not combatant.creature.is_conscious:
                self.log.add(
                    CombatEvent(
                        event_type=CombatEventType.TURN_START,
                        message=f"{combatant.creature.name}'s turn",
                        source_id=combatant.creature_id,
                    )
                )
                self.end_turn()
                return

        self.log.add(
            CombatEvent(
                event_type=CombatEventType.TURN_START,
                message=f"{combatant.creature.name}'s turn",
                source_id=combatant.creature_id,
            )
        )

        # Unconscious creatures: process death saves (PCs) or skip
        if not combatant.creature.is_conscious:
            is_pc = hasattr(combatant.creature, "death_save_successes")
            is_stabilized = getattr(combatant.creature, "is_stabilized", False)

            if is_pc and not is_stabilized:
                # Roll a death save
                ds_events = process_death_save(
                    combatant.creature, combatant.creature_id,
                )
                for e in ds_events:
                    self.log.add(e)

                # Nat 20 restores consciousness — creature gets a normal turn
                if combatant.creature.is_conscious:
                    # Re-calculate movement now that they're awake
                    base_speed = get_effective_speed(combatant.creature)
                    multiplier = get_movement_multiplier(combatant.creature)
                    speed = int(base_speed * multiplier)
                    self.movement.reset(combatant.creature_id, speed)
                    self.movement.dead_creature_ids = self._get_dead_creature_ids()
                    self.movement.blocked_hexes = self._get_wall_blocked_hexes()
                    self.turn_phase = TurnPhase.AWAITING_ACTION
                    return

                # Check if creature died (3 failures)
                if self._check_victory():
                    return
            elif is_stabilized:
                self.log.add(
                    CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=f"{combatant.creature.name} is unconscious but stable.",
                        source_id=combatant.creature_id,
                    )
                )
            else:
                self.log.add(
                    CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=f"{combatant.creature.name} is unconscious. Skipping turn.",
                        source_id=combatant.creature_id,
                    )
                )

            self.end_turn()
            return

        # Skip incapacitated creatures (stunned, paralyzed, petrified)
        if not can_take_actions(combatant.creature):
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{combatant.creature.name} is incapacitated. Skipping turn.",
                    source_id=combatant.creature_id,
                )
            )
            self.end_turn()
            return

        # Skip creatures currently in Wild Shape (the beast form acts instead)
        if combatant.creature_id in self.stored_creatures:
            self.end_turn()
            return

        self.turn_phase = TurnPhase.AWAITING_ACTION

    def end_turn(self) -> None:
        """End the current creature's turn, then check legendary action opportunities.

        After end-of-turn processing, builds a queue of creatures eligible for
        legendary actions.  If any exist, enters LEGENDARY_ACTION_PHASE so each
        gets a chance to act (or pass) before the next creature's turn begins.
        """
        combatant = self.active_combatant
        if combatant:
            events = process_end_of_turn(combatant.creature, combatant.creature_id)
            for e in events:
                self.log.add(e)
            buff_events = process_buff_end_of_turn(combatant.creature, combatant.creature_id)
            for e in buff_events:
                self.log.add(e)

            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.TURN_END,
                    message=f"{combatant.creature.name}'s turn ends",
                    source_id=combatant.creature_id,
                )
            )
        elif self._is_lair_turn:
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.TURN_END,
                    message="Lair turn ends",
                )
            )

        was_lair_turn = self._is_lair_turn
        self._is_lair_turn = False

        # Check victory before advancing
        if self._check_victory():
            return

        # Legendary actions only trigger after a creature's turn, not the lair
        if was_lair_turn:
            self._advance_to_next_turn()
            return

        # Build legendary action queue (excludes the creature whose turn just ended)
        self._legendary_queue = self._build_legendary_queue(
            exclude_id=combatant.creature_id if combatant else None
        )

        if self._legendary_queue:
            self.turn_phase = TurnPhase.LEGENDARY_ACTION_PHASE
            self._legendary_actor_id = self._legendary_queue[0]
        else:
            self._advance_to_next_turn()

    def _advance_to_next_turn(self) -> None:
        """Advance initiative to the next creature and start their turn.

        Separated from end_turn() so legendary action processing can happen
        in between.
        """
        old_round = self.initiative.round_number
        self.initiative.next_turn()
        new_round = self.initiative.round_number

        if new_round > old_round:
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.ROUND_START,
                    message=f"--- Round {new_round} ---",
                )
            )
            # Reset per-round zone tracking so creatures can be damaged again
            if self.active_zones:
                from arena.combat.zones import reset_zone_round_tracking
                reset_zone_round_tracking(self.active_zones)

        self._start_current_turn()

    # ------------------------------------------------------------------
    # Legendary Actions
    # ------------------------------------------------------------------

    def _build_legendary_queue(self, exclude_id: str | None) -> list[str]:
        """Build queue of creatures eligible for legendary actions.

        A creature is eligible if it has legendary action points remaining,
        is conscious, can take actions, and is NOT the creature whose turn
        just ended (per 5e: can't use at end of own turn).
        """
        queue: list[str] = []
        for cid, points in self.legendary_points.items():
            if points <= 0:
                continue
            if cid == exclude_id:
                continue
            combatant = self.combatants.get(cid)
            if combatant is None:
                continue
            if not combatant.creature.is_conscious:
                continue
            if not can_take_actions(combatant.creature):
                continue
            queue.append(cid)
        return queue

    @property
    def legendary_actor(self) -> Combatant | None:
        """Get the combatant currently eligible for a legendary action."""
        if self._legendary_actor_id is None:
            return None
        return self.combatants.get(self._legendary_actor_id)

    def get_available_legendary_actions(self, creature_id: str) -> list[Action]:
        """Get legendary actions the creature can afford with remaining points."""
        combatant = self.combatants.get(creature_id)
        if combatant is None:
            return []
        remaining = self.legendary_points.get(creature_id, 0)
        legendary_actions = getattr(combatant.creature, "legendary_actions", [])
        return [a for a in legendary_actions if a.legendary_action_cost <= remaining]

    def execute_legendary_action(
        self, action: Action, target_id: str
    ) -> ActionResult | None:
        """Execute a legendary action for the current legendary actor.

        Uses the same resolve_attack/resolve_effect pipeline but acts on
        behalf of the legendary creature (not the active turn creature).

        Args:
            action: The legendary action to execute.
            target_id: creature_id of the target.

        Returns:
            ActionResult with events, or None if invalid.
        """
        if self.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            return None
        if self._legendary_actor_id is None:
            return None

        actor = self.combatants.get(self._legendary_actor_id)
        if actor is None:
            return None
        if self.grid is None:
            return None

        # Check point cost
        cost = action.legendary_action_cost
        remaining = self.legendary_points.get(self._legendary_actor_id, 0)
        if cost > remaining:
            return None

        # Deduct points
        self.legendary_points[self._legendary_actor_id] = remaining - cost

        self.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{actor.creature.name} uses a legendary action: "
                f"{action.name}! ({cost} point{'s' if cost != 1 else ''})"
            ),
            source_id=self._legendary_actor_id,
        ))

        target = self.combatants.get(target_id)
        if target is None:
            self._advance_legendary_queue()
            return None

        # Resolve the action using existing pipelines
        if action.attack:
            result = resolve_attack(
                attacker=actor.creature,
                attacker_id=actor.creature_id,
                target=target.creature,
                target_id=target_id,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                attacker_pos=actor.position,
                target_pos=target.position,
            )
        elif action.saving_throw or action.healing:
            result = resolve_effect(
                user=actor.creature,
                user_id=actor.creature_id,
                target=target.creature,
                target_id=target_id,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                user_pos=actor.position,
                target_pos=target.position,
            )
        else:
            # Action with no attack/save/heal (e.g., applies conditions directly)
            result = resolve_effect(
                user=actor.creature,
                user_id=actor.creature_id,
                target=target.creature,
                target_id=target_id,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                user_pos=actor.position,
                target_pos=target.position,
            )

        for event in result.events:
            self.log.add(event)

        self._cleanup_orphaned_zones()

        if self._check_victory():
            return result

        # Advance to next legendary creature or next turn
        self._advance_legendary_queue()

        return result

    def pass_legendary_action(self) -> None:
        """Pass on the current legendary action opportunity."""
        if self.turn_phase != TurnPhase.LEGENDARY_ACTION_PHASE:
            return
        self._advance_legendary_queue()

    def _advance_legendary_queue(self) -> None:
        """Move to the next legendary creature in queue, or advance to next turn."""
        if self._legendary_queue:
            self._legendary_queue.pop(0)

        if self._legendary_queue:
            # More legendary creatures to process
            self._legendary_actor_id = self._legendary_queue[0]
        else:
            # All done — advance to the next creature's turn
            self._legendary_actor_id = None
            self._advance_to_next_turn()

    # ------------------------------------------------------------------
    # Lair Actions
    # ------------------------------------------------------------------

    def get_available_lair_actions(self) -> list:
        """Get lair actions available this round.

        Filters out the action used last round (same name can't be used
        two consecutive rounds per 5e rules).
        """
        return [
            a for a in self.lair_actions
            if a.name != self.last_lair_action_name
        ]

    def execute_lair_action(
        self, action, target_ids: list[str],
    ) -> ActionResult | None:
        """Execute a lair action against one or more targets.

        Lair actions are typically saving-throw-based effects.  Each target
        rolls a saving throw independently.  Does NOT use resolve_effect
        because lair actions have no "user" creature.

        Args:
            action: The lair action to execute.
            target_ids: List of creature_ids to target.

        Returns:
            ActionResult with all events, or None if invalid.
        """
        if not self._is_lair_turn:
            return None
        if self.grid is None:
            return None

        from arena.combat.actions import resolve_saving_throw
        from arena.combat.concentration import check_concentration
        from arena.combat.damage import (
            roll_damage, apply_damage, halve_packets, zero_packets,
        )
        from arena.combat.conditions import apply_condition
        from arena.models.conditions import Condition

        self.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"Lair action: {action.name}!",
        ))

        all_events: list[CombatEvent] = []

        for tid in target_ids:
            target = self.combatants.get(tid)
            if target is None or not target.creature.is_conscious:
                continue

            if action.saving_throw:
                save = action.saving_throw
                dc = save.dc or 10
                save_success, save_event = resolve_saving_throw(
                    target.creature, tid, save.ability, dc,
                )
                all_events.append(save_event)

                # Damage on fail (or half on success)
                if save.damage_on_fail:
                    packets = roll_damage(
                        save.damage_on_fail, target.creature,
                        is_critical=False,
                    )
                    if save_success:
                        if save.damage_on_success == "half":
                            halve_packets(packets)
                        elif save.damage_on_success == "none":
                            zero_packets(packets)
                    if sum(p.amount for p in packets) > 0:
                        roll_details = [p.to_detail() for p in packets]
                        dmg_event, dp_events = apply_damage(
                            target.creature, packets,
                            creature_id=tid,
                        )
                        dmg_event.source_id = "__lair__"
                        dmg_event.target_id = tid
                        dmg_event.message = (
                            f"{target.creature.name} {dmg_event.message}"
                        )
                        dmg_event.details["roll_details"] = roll_details
                        all_events.append(dmg_event)
                        all_events.extend(dp_events)

                        # Concentration check
                        conc_events = check_concentration(
                            target.creature, tid,
                            dmg_event.details["damage"],
                            combatants=self.combatants,
                        )
                        all_events.extend(conc_events)

                # Conditions on fail
                if not save_success and save.conditions_on_fail:
                    for cond_name in save.conditions_on_fail:
                        try:
                            cond = Condition(cond_name)
                        except ValueError:
                            continue
                        cond_event = apply_condition(
                            target.creature, tid, cond,
                            source="Lair",
                            duration_type="end_of_turn",
                            save_to_end=save.ability,
                            save_dc=dc,
                        )
                        if cond_event:
                            all_events.append(cond_event)

        # ----------------------------------------------------------
        # Healing — heal all conscious enemy-side creatures
        # ----------------------------------------------------------
        if action.healing:
            from arena.combat.damage import apply_healing
            from arena.util.dice import roll_expression

            for cid, c in self.combatants.items():
                if c.team == "enemy" and c.creature.is_conscious:
                    total, _ = roll_expression(action.healing)
                    if total > 0:
                        heal_event = apply_healing(c.creature, total)
                        heal_event.source_id = "__lair__"
                        heal_event.target_id = cid
                        heal_event.message = (
                            f"{c.creature.name} {heal_event.message}"
                        )
                        all_events.append(heal_event)

        # ----------------------------------------------------------
        # Temporary HP — grant to all conscious enemy-side creatures
        # 5e no-stack rule: only replace if new value is higher
        # ----------------------------------------------------------
        if action.grants_temporary_hp:
            from arena.util.dice import roll_expression

            for cid, c in self.combatants.items():
                if c.team == "enemy" and c.creature.is_conscious:
                    total, _ = roll_expression(action.grants_temporary_hp)
                    if total > c.creature.temporary_hit_points:
                        c.creature.temporary_hit_points = total
                        all_events.append(CombatEvent(
                            event_type=CombatEventType.INFO,
                            source_id="__lair__",
                            target_id=cid,
                            message=(
                                f"{c.creature.name} gains {total} "
                                f"temporary hit points!"
                            ),
                            details={"temp_hp": total},
                        ))

        # ----------------------------------------------------------
        # Summoning — spawn a creature on the enemy side
        # ----------------------------------------------------------
        if action.summon_creature:
            summon_events = self._execute_lair_summon(action)
            all_events.extend(summon_events)

        for event in all_events:
            self.log.add(event)

        # Record which action was used (consecutive-round filter)
        self.last_lair_action_name = action.name

        self._cleanup_orphaned_zones()

        if self._check_victory():
            return ActionResult(events=all_events, success=True)

        # Lair turn is over — end it
        self.end_turn()
        return ActionResult(events=all_events, success=True)

    def pass_lair_action(self) -> None:
        """Pass on using a lair action this round."""
        if not self._is_lair_turn:
            return
        self.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message="No lair action used this round.",
        ))
        self.end_turn()

    def _execute_lair_summon(self, action) -> list[CombatEvent]:
        """Summon a creature via a lair action.

        Loads the creature from JSON, places it on an empty hex near
        existing enemies, adds it to the combatants dict, and inserts
        it into initiative right after the lair entry.

        Returns a list of events describing the summon.
        """
        from pathlib import Path
        from arena.models.encounter import CombatantEntry

        events: list[CombatEvent] = []
        if self.grid is None:
            return events

        # Load creature from JSON
        data_dir = Path("data")
        try:
            entry = CombatantEntry(
                creature_id=action.summon_creature,
                team="enemy",
            )
            creature = self._load_creature(entry, data_dir)
        except Exception as e:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"Lair summon failed: {e}",
                source_id="__lair__",
            ))
            return events

        # Generate unique ID and configure
        summon_id = self._make_unique_id(creature.name)
        creature.is_player_controlled = not self._use_ai_for_lair

        # Find an empty hex near existing enemies
        place_hex = self._find_summon_hex()
        if place_hex is None:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message="Lair summon failed: no empty hex available!",
                source_id="__lair__",
            ))
            return events

        # Create Combatant and place on grid
        new_combatant = Combatant(
            creature_id=summon_id,
            creature=creature,
            team="enemy",
        )
        if self.grid.place_creature(place_hex, summon_id, creature.size):
            new_combatant.position = place_hex
        self.combatants[summon_id] = new_combatant

        # Insert into initiative right after the lair entry
        lair_entry = None
        for ie in self.initiative.entries:
            if ie.is_lair:
                lair_entry = ie
                break
        if lair_entry:
            summon_entry = InitiativeEntry(
                creature_id=summon_id,
                name=creature.name,
                initiative_roll=lair_entry.initiative_roll,
                dexterity=creature.ability_scores.get_modifier("dexterity"),
                is_player_controlled=creature.is_player_controlled,
                tiebreaker=lair_entry.tiebreaker - 0.0001,
            )
            self.initiative.add_entry(summon_entry)

            # Re-sort shifts entries — re-find the lair entry so
            # current_index still points at it (prevents double-fire)
            for i, ie in enumerate(self.initiative.entries):
                if ie.is_lair:
                    self.initiative.current_index = i
                    break

        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"The lair summons {creature.name}!",
            source_id="__lair__",
            details={
                "action_name": action.name,
                "summoned_id": summon_id,
            },
        ))
        return events

    def _find_summon_hex(self):
        """Find an empty hex near existing enemy creatures.

        Collects all enemy positions, picks one at random, and searches
        its neighbors for an unoccupied hex.  Fallback: scans the whole
        grid for any empty hex.

        Returns a HexCoord or None.
        """
        from arena.grid.coordinates import HexCoord

        if self.grid is None:
            return None

        # Gather enemy positions
        enemy_positions = []
        for c in self.combatants.values():
            if c.team == "enemy" and c.position is not None:
                enemy_positions.append(c.position)

        # Try adjacent hexes of a random enemy first
        if enemy_positions:
            random.shuffle(enemy_positions)
            for pos in enemy_positions:
                for neighbor in pos.neighbors():
                    if (self.grid.is_valid(neighbor)
                            and not self.grid.is_occupied(neighbor)
                            and self.grid.is_passable(neighbor)):
                        return neighbor

        # Fallback: scan entire grid for any empty, passable hex
        for r in range(self.grid.height):
            for q in range(self.grid.width):
                coord = HexCoord(q, r)
                if (not self.grid.is_occupied(coord)
                        and self.grid.is_passable(coord)):
                    return coord

        return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def select_action(
        self, action: Action, cast_level: int | None = None,
    ) -> None:
        """Player selects an action to use. Transitions to target selection."""
        self.selected_action = action
        self._cast_level = cast_level
        self.turn_phase = TurnPhase.SELECTING_TARGET

    def cancel_action(self) -> None:
        """Cancel the current action selection."""
        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

    def _mark_action_type_used(self, action: Action) -> None:
        """Mark the correct action economy slot as used based on action_type."""
        from arena.models.actions import ActionType
        if action.action_type == ActionType.BONUS_ACTION:
            self.turn_resources.has_used_bonus_action = True
        elif action.action_type == ActionType.REACTION:
            self.turn_resources.has_used_reaction = True
        elif action.action_type == ActionType.FREE:
            self.turn_resources.free_actions_used += 1
        elif action.action_type == ActionType.LEGENDARY:
            pass  # Legendary actions use their own point pool
        elif action.action_type == ActionType.LAIR:
            pass  # Lair actions don't consume action economy
        else:
            self.turn_resources.has_used_action = True

    def _handle_extra_attack_tracking(
        self, action: Action, creature: Creature | None,
    ) -> None:
        """Handle Extra Attack tracking for successful attacks.

        On the first attack of a turn (attacks_remaining == 0), initializes
        the counter from the creature's extra_attack_count. Only applies
        to "action"-type attacks (not bonus action, reaction, etc.).

        When attacks_remaining reaches 0, the action slot is consumed normally.
        """
        from arena.models.actions import ActionType

        is_action_type_attack = (
            action.action_type == ActionType.ACTION.value
            or action.action_type == ActionType.ACTION
        )

        if is_action_type_attack and action.attack is not None and creature is not None:
            if self.turn_resources.attacks_remaining == 0:
                # First attack: initialize from extra_attack_count
                total = get_extra_attack_count(creature)
                self.turn_resources.attacks_remaining = total - 1
                if self.turn_resources.attacks_remaining > 0:
                    # More attacks to go — don't consume the action slot yet
                    return
            else:
                # Subsequent attack in the sequence
                self.turn_resources.attacks_remaining -= 1
                if self.turn_resources.attacks_remaining > 0:
                    return

        # All attacks used (or not an action-type attack) — consume the slot
        self._mark_action_type_used(action)

    def has_attacks_remaining(self) -> bool:
        """Return True if there are extra attacks remaining."""
        return self.turn_resources.attacks_remaining > 0

    def _check_counterspell_opportunities(self, action: Action, caster_id: str) -> list[tuple[str, 'Combatant', Action]]:
        """Find creatures that can counterspell a spell being cast."""
        if action.spell_level is None:
            return []
        caster = self.combatants.get(caster_id)
        if caster is None or caster.position is None:
            return []
        from arena.grid.footprint import min_distance_between
        from arena.combat.condition_effects import can_take_actions as _can_act
        result = []
        for cid, combatant in self.combatants.items():
            if cid == caster_id:
                continue
            if combatant.position is None:
                continue
            if not combatant.creature.is_conscious:
                continue
            if not _can_act(combatant.creature):
                continue
            if combatant.team == caster.team:
                continue
            if self.reaction_used.get(cid, False):
                continue
            cs_action = None
            for a in combatant.creature.actions:
                if a.is_counterspell:
                    cs_action = a
                    break
            if cs_action is None:
                continue
            cs_range = cs_action.range or 60
            dist = min_distance_between(
                combatant.position, combatant.creature.size,
                caster.position, caster.creature.size,
            )
            if dist * 5 > cs_range:
                continue
            from arena.combat.actions import check_resource_cost
            can_use, _ = check_resource_cost(combatant.creature, cs_action)
            if not can_use:
                continue
            result.append((cid, combatant, cs_action))
        return result

    def _try_counterspell(self, action: Action, caster_id: str) -> tuple[bool, list[CombatEvent]]:
        """Attempt counterspell by AI-controlled creatures. Sets _pending_counterspell for player ones."""
        opportunities = self._check_counterspell_opportunities(action, caster_id)
        if not opportunities:
            return False, []
        from arena.combat.actions import deduct_resource_cost
        ai_cs = [(c, cb, a) for c, cb, a in opportunities if not getattr(cb.creature, 'is_player_controlled', False)]
        player_cs = [(c, cb, a) for c, cb, a in opportunities if getattr(cb.creature, 'is_player_controlled', False)]
        target_level = self._cast_level or action.spell_level or 0
        all_events: list[CombatEvent] = []
        for cid, combatant, cs_action in ai_cs:
            if target_level < 3:
                cr = getattr(combatant.creature, 'class_resources', {})
                total_slots = sum(v for k, v in cr.items() if k.startswith("spell_slot_"))
                if total_slots < 3:
                    continue
            cs_cast_level = cs_action.spell_level or 3
            cr = getattr(combatant.creature, 'class_resources', {})
            for lvl in range(max(target_level, cs_cast_level), 10):
                slot_key = f"spell_slot_{lvl}"
                if cr.get(slot_key, 0) > 0:
                    cs_cast_level = lvl
                    break
            all_events.append(CombatEvent(
                event_type=CombatEventType.REACTION,
                message=f"{combatant.creature.name} uses its reaction to cast Counterspell (level {cs_cast_level})!",
                source_id=cid,
                details={"reaction_type": "counterspell"},
            ))
            self.reaction_used[cid] = True
            deduct_resource_cost(combatant.creature, cs_action, cast_level=cs_cast_level)
            success, cs_events = resolve_counterspell(
                caster=combatant.creature, caster_id=cid,
                counterspell_action=cs_action, target_spell=action,
                target_spell_cast_level=self._cast_level,
                counterspell_cast_level=cs_cast_level,
            )
            all_events.extend(cs_events)
            if success:
                return True, all_events
        if player_cs:
            for evt in all_events:
                self.log.add(evt)
            return False, []
        return False, all_events

    def get_pending_counterspell_opportunities(self, action: Action, caster_id: str) -> list[tuple[str, 'Combatant', Action]]:
        """Get player-controlled creatures that can counterspell."""
        opportunities = self._check_counterspell_opportunities(action, caster_id)
        return [(cid, cb, a) for cid, cb, a in opportunities if getattr(cb.creature, 'is_player_controlled', False)]

    def resolve_counterspell_choice(self, counterspeller_id: str | None, cast_level: int | None) -> tuple[bool, list[CombatEvent]]:
        """Resolve a player's counterspell choice from the GUI popup."""
        if self._pending_counterspell is None:
            return False, []
        pending = self._pending_counterspell
        self._pending_counterspell = None
        if counterspeller_id is None:
            return False, []
        combatant = self.combatants.get(counterspeller_id)
        if combatant is None:
            return False, []
        cs_action = None
        for a in combatant.creature.actions:
            if a.is_counterspell:
                cs_action = a
                break
        if cs_action is None:
            return False, []
        from arena.combat.actions import deduct_resource_cost
        events: list[CombatEvent] = []
        events.append(CombatEvent(
            event_type=CombatEventType.REACTION,
            message=f"{combatant.creature.name} uses its reaction to cast Counterspell (level {cast_level or cs_action.spell_level or 3})!",
            source_id=counterspeller_id,
            details={"reaction_type": "counterspell"},
        ))
        self.reaction_used[counterspeller_id] = True
        deduct_resource_cost(combatant.creature, cs_action, cast_level=cast_level)
        target_action = pending["action"]
        target_cast_level = pending["cast_level"]
        success, cs_events = resolve_counterspell(
            caster=combatant.creature, caster_id=counterspeller_id,
            counterspell_action=cs_action, target_spell=target_action,
            target_spell_cast_level=target_cast_level,
            counterspell_cast_level=cast_level,
        )
        events.extend(cs_events)
        for evt in events:
            self.log.add(evt)
        return success, events

    def execute_attack(self, target_id: str) -> ActionResult | None:
        """Execute the selected attack action against a target.

        Convenience method that performs both hit and damage in one call.
        Used by AI, reactions, and opportunity attacks.

        Args:
            target_id: creature_id of the target.

        Returns:
            ActionResult with events, or None if invalid.
        """
        combatant = self.active_combatant
        if combatant is None or self.selected_action is None:
            return None
        if self.grid is None:
            return None

        # Pre-check: action economy slot must be available
        if not self.can_use_action_type(self.selected_action.action_type):
            return None

        target_combatant = self.combatants.get(target_id)
        if target_combatant is None:
            return None

        action = self.selected_action

        # ── Counterspell check (before spell resolves) ─────────────────
        if action.spell_level is not None:
            countered, cs_events = self._try_counterspell(action, combatant.creature_id)
            if cs_events:
                for evt in cs_events:
                    self.log.add(evt)
            if countered:
                # Spell is negated — consume caster's action + spell slot
                from arena.combat.actions import deduct_resource_cost
                deduct_resource_cost(combatant.creature, action, cast_level=self._cast_level)
                self._mark_action_type_used(action)
                cs_events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{combatant.creature.name}'s {action.name} is countered!",
                    source_id=combatant.creature_id,
                    details={"counterspelled": True},
                ))
                self.log.add(cs_events[-1])
                self.selected_action = None
                self._cast_level = None
                self.turn_phase = TurnPhase.AWAITING_ACTION
                return ActionResult(events=cs_events, success=False)
            # Check if player counterspellers need a popup
            player_cs = self.get_pending_counterspell_opportunities(action, combatant.creature_id)
            if player_cs:
                self._pending_counterspell = {
                    "caster_id": combatant.creature_id,
                    "action": action,
                    "cast_level": self._cast_level,
                    "target_id": target_id,
                    "counterspellers": player_cs,
                    "method": "attack",
                }
                return None  # GUI will handle popup

        effective_count = get_effective_target_count(action, self._cast_level)

        # ── Multi-target attacks (Eldritch Blast beams, Magic Missile darts) ──
        if effective_count > 1:
            from arena.combat.actions import check_resource_cost

            # Affordability gate BEFORE the volley: once the first dart blanks
            # the cost (below), later darts could no longer fail it themselves.
            can_use, reason = check_resource_cost(
                combatant.creature, action, self._cast_level,
            )
            if not can_use:
                result = ActionResult(
                    events=[CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=reason,
                        source_id=combatant.creature_id,
                    )],
                    success=False,
                )
            else:
                all_events: list[CombatEvent] = []
                any_success = False
                # One cast = one cost: each resolve_attack deducts
                # resource_cost, so blank it after the first beam/dart (same
                # pattern as the multi-target effect path) and restore once
                # the volley is done.
                saved_cost = dict(action.resource_cost)
                saved_uses = action.uses_per_rest
                for i in range(effective_count):
                    # Re-fetch target in case it died from a previous hit
                    tc = self.combatants.get(target_id)
                    if tc is None:
                        break
                    if i > 0:
                        action.resource_cost = {}
                        action.uses_per_rest = None
                    single = resolve_attack(
                        attacker=combatant.creature,
                        attacker_id=combatant.creature_id,
                        target=tc.creature,
                        target_id=target_id,
                        action=action,
                        grid=self.grid,
                        combatants=self.combatants,
                        attacker_pos=combatant.position,
                        target_pos=tc.position,
                        cast_level=self._cast_level,
                    )
                    all_events.extend(single.events)
                    if single.success:
                        any_success = True
                        if combatant.position is not None:
                            fm_events = self._apply_pending_forced_movement(
                                single.events, combatant.creature_id,
                                combatant.position,
                            )
                            all_events.extend(fm_events)
                action.resource_cost = saved_cost
                action.uses_per_rest = saved_uses
                result = ActionResult(events=all_events, success=any_success)
        else:
            # Two-phase: hit check, then evaluate damage reduction, then damage
            hit_result = resolve_attack_hit(
                attacker=combatant.creature,
                attacker_id=combatant.creature_id,
                target=target_combatant.creature,
                target_id=target_id,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                attacker_pos=combatant.position,
                target_pos=target_combatant.position,
                cast_level=self._cast_level,
            )
            if not hit_result.hit and not hit_result.events:
                result = ActionResult(events=[], success=False)
            elif (
                hit_result.events
                and not hit_result.hit
                and hit_result.natural_roll == 0
            ):
                result = ActionResult(
                    events=hit_result.events, success=False,
                )
            else:
                # Evaluate damage reduction reaction on the target
                dr_amount = 0
                if hit_result.hit and hit_result.attack is not None:
                    tc = self.combatants.get(target_id)
                    is_player_target = (
                        tc is not None
                        and getattr(tc.creature, "is_player_controlled", False)
                    )
                    if is_player_target:
                        # Check for player DR -- defer to GUI popup
                        attack_type = hit_result.attack.attack_type
                        options = self.check_damage_reduction_reaction(
                            target_id, attack_type,
                        )
                        if options:
                            # Log hit events before deferring
                            for evt in hit_result.events:
                                self.log.add(evt)
                            self._pending_damage_reduction = {
                                "hit_result": hit_result,
                                "rider_results": None,
                                "target_id": target_id,
                                "options": options,
                                "from_execute_attack": True,
                                "action": action,
                                "combatant": combatant,
                            }
                            return None  # Deferred
                    else:
                        dr_amount = self._evaluate_ai_damage_reduction(
                            target_id, hit_result,
                        )
                result = resolve_attack_damage(
                    hit_result, damage_reduction=dr_amount,
                )

            # Apply pending forced movement from the attack result
            if result.success and combatant.position is not None:
                fm_events = self._apply_pending_forced_movement(
                    result.events, combatant.creature_id, combatant.position,
                )
                result.events.extend(fm_events)

        for event in result.events:
            self.log.add(event)

        if result.success:
            self._handle_extra_attack_tracking(action, combatant.creature)

        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        # Attack damage may have broken concentration — clean up orphaned zones
        self._cleanup_orphaned_zones()
        self._cleanup_orphaned_recurring_actions()

        # Create recurring action for attack-based spells (e.g., Witch Bolt)
        if result.success and action.recurring_action_type:
            self._maybe_create_recurring_action(
                action, combatant.creature_id, target_id,
            )

        # Check if combat has ended
        self._check_victory()

        return result

    def execute_attack_hit_check(self, target_id: str) -> AttackHitResult | None:
        """Phase 1: Roll to hit only. Returns intermediate result.

        The selected_action is NOT cleared — it remains set so
        complete_attack() can reference it for turn resource tracking.

        Used by the GUI to allow triggered abilities (Divine Smite)
        between hit determination and damage application.
        """
        combatant = self.active_combatant
        if combatant is None or self.selected_action is None:
            return None
        if self.grid is None:
            return None

        # Pre-check: action economy slot must be available
        if not self.can_use_action_type(self.selected_action.action_type):
            return None

        target_combatant = self.combatants.get(target_id)
        if target_combatant is None:
            return None

        action = self.selected_action

        # ── Counterspell check (before spell attack resolves) ──────────
        if action.spell_level is not None:
            countered, cs_events = self._try_counterspell(action, combatant.creature_id)
            if cs_events:
                for evt in cs_events:
                    self.log.add(evt)
            if countered:
                from arena.combat.actions import deduct_resource_cost
                deduct_resource_cost(combatant.creature, action, cast_level=self._cast_level)
                self._mark_action_type_used(action)
                cs_events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{combatant.creature.name}'s {action.name} is countered!",
                    source_id=combatant.creature_id,
                    details={"counterspelled": True},
                ))
                self.log.add(cs_events[-1])
                self.selected_action = None
                self._cast_level = None
                self.turn_phase = TurnPhase.AWAITING_ACTION
                return None  # Countered — no hit result
            # Player counterspell popup is handled by the GUI
            player_cs = self.get_pending_counterspell_opportunities(action, combatant.creature_id)
            if player_cs:
                self._pending_counterspell = {
                    "caster_id": combatant.creature_id,
                    "action": action,
                    "cast_level": self._cast_level,
                    "target_id": target_id,
                    "counterspellers": player_cs,
                    "method": "attack",
                }
                return None  # GUI will handle popup

        hit_result = resolve_attack_hit(
            attacker=combatant.creature,
            attacker_id=combatant.creature_id,
            target=target_combatant.creature,
            target_id=target_id,
            action=action,
            grid=self.grid,
            combatants=self.combatants,
            attacker_pos=combatant.position,
            target_pos=target_combatant.position,
            cast_level=self._cast_level,
        )

        # Log the hit-check events immediately (attack roll result)
        for event in hit_result.events:
            self.log.add(event)

        return hit_result

    def get_applicable_riders(
        self,
        hit_result: AttackHitResult,
    ) -> list[tuple]:
        """Get on-hit riders applicable to the current attack.

        Filters by attack context (melee/weapon) and once-per-turn usage.
        Returns list of (Feature, OnHitRider) tuples.
        """
        if not hit_result.hit or hit_result.attacker is None:
            return []
        if hit_result.action is None or hit_result.action.attack is None:
            return []

        used = self.turn_resources.used_riders or set()
        return discover_riders(
            hit_result.attacker, hit_result.action, used_this_turn=used,
        )

    # ------------------------------------------------------------------
    # Damage reduction reactions (Parry, Uncanny Dodge, Deflect Missiles)
    # ------------------------------------------------------------------

    def check_damage_reduction_reaction(
        self, target_id: str, attack_type: str,
    ) -> list[tuple]:
        """Check if a target can use a damage reduction reaction.

        Args:
            target_id: The creature_id of the attack target.
            attack_type: e.g. "melee_weapon", "ranged_weapon", "melee_spell".

        Returns:
            List of (Feature, reduction_amount) tuples.  ``reduction_amount``
            is -1 for Uncanny Dodge (halving), or a rolled value for Parry etc.
        """
        from arena.combat.damage_reduction import (
            get_damage_reduction_features,
            can_use_damage_reduction,
            calculate_damage_reduction,
        )

        target_c = self.combatants.get(target_id)
        if target_c is None:
            return []

        # Reaction already used this round?
        if self.reaction_used.get(target_id, False):
            return []

        # Target must be alive
        creature = target_c.creature
        if (creature.current_hit_points or 0) <= 0:
            return []

        is_melee = attack_type.startswith("melee")
        is_ranged = attack_type.startswith("ranged")

        results: list[tuple] = []
        for feature in get_damage_reduction_features(creature):
            if not can_use_damage_reduction(
                feature, is_melee=is_melee, is_ranged=is_ranged,
            ):
                continue
            reduction = calculate_damage_reduction(creature, feature)
            results.append((feature, reduction))

        return results

    def _evaluate_ai_damage_reduction(
        self, target_id: str, hit_result: AttackHitResult,
    ) -> int:
        """AI auto-evaluates whether to use a damage reduction reaction.

        Returns the reduction amount (0 means skip, -1 means halve).
        Consumes the target's reaction if used.
        """
        if hit_result.attack is None:
            return 0

        attack_type = hit_result.attack.attack_type
        options = self.check_damage_reduction_reaction(target_id, attack_type)
        if not options:
            return 0

        # Pick the best option (highest reduction, or -1 for halving which
        # is usually best against big hits)
        best_feature, best_reduction = options[0]
        for feature, reduction in options[1:]:
            if reduction == -1:
                best_feature, best_reduction = feature, reduction
                break
            if reduction > best_reduction:
                best_feature, best_reduction = feature, reduction

        # AI threshold: use if reduction >= 5 or >= 25% of expected damage,
        # or if it's Uncanny Dodge (always worth halving)
        if best_reduction == -1:
            # Uncanny Dodge: always use
            pass
        elif best_reduction < 5:
            return 0

        # Use it -- consume reaction
        self.reaction_used[target_id] = True

        # Log
        target_c = self.combatants.get(target_id)
        target_name = target_c.creature.name if target_c else target_id
        if best_reduction == -1:
            msg = f"{target_name} uses {best_feature.name} to halve the damage!"
        else:
            msg = (
                f"{target_name} uses {best_feature.name} to reduce "
                f"damage by {best_reduction}!"
            )
        self.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            source_id=target_id,
            target_id=target_id,
            message=msg,
        ))

        return best_reduction

    def resolve_damage_reduction_choice(
        self, feature_name: str | None,
    ) -> None:
        """Resolve a player's damage reduction reaction choice.

        Called by the GUI after the ReactionPopup closes.

        Args:
            feature_name: Name of the chosen feature, or None to skip.
        """
        pending = self._pending_damage_reduction
        if pending is None:
            return

        hit_result = pending["hit_result"]
        rider_results = pending.get("rider_results")
        target_id = pending["target_id"]
        reduction = 0

        if feature_name is not None:
            # Find the matching option
            for feat, red in pending["options"]:
                if feat.name == feature_name:
                    reduction = red
                    break

            if reduction != 0:
                # Consume reaction
                self.reaction_used[target_id] = True

                # Log
                target_c = self.combatants.get(target_id)
                target_name = (
                    target_c.creature.name if target_c else target_id
                )
                if reduction == -1:
                    msg = (
                        f"{target_name} uses {feature_name} "
                        f"to halve the damage!"
                    )
                else:
                    msg = (
                        f"{target_name} uses {feature_name} to reduce "
                        f"damage by {reduction}!"
                    )
                self.log.add(CombatEvent(
                    event_type=CombatEventType.INFO,
                    source_id=target_id,
                    target_id=target_id,
                    message=msg,
                ))

        # Now complete the attack with the reduction applied
        self._pending_damage_reduction = None

        if pending.get("from_execute_attack"):
            # Came from execute_attack() -- finalize inline
            result = resolve_attack_damage(
                hit_result, damage_reduction=reduction,
            )
            action = pending.get("action")
            combatant = pending.get("combatant")

            # Apply pending forced movement
            if (
                result.success
                and combatant is not None
                and combatant.position is not None
            ):
                fm_events = self._apply_pending_forced_movement(
                    result.events, combatant.creature_id,
                    combatant.position,
                )
                result.events.extend(fm_events)

            # Log only NEW events (hit events already logged)
            new_events = result.events[len(hit_result.events):]
            for event in new_events:
                self.log.add(event)

            if result.success and action is not None and combatant is not None:
                self._handle_extra_attack_tracking(
                    action, combatant.creature,
                )

            self.selected_action = None
            self._cast_level = None
            self.turn_phase = TurnPhase.AWAITING_ACTION
            self._cleanup_orphaned_zones()
            self._cleanup_orphaned_recurring_actions()
            self._check_victory()
        else:
            # Came from complete_attack() via AI executor or GUI rider flow
            self.complete_attack(
                hit_result,
                rider_results=rider_results,
                damage_reduction=reduction,
            )

    def complete_attack(
        self,
        hit_result: AttackHitResult,
        bonus_damage: list[DamageRoll] | None = None,
        rider_results: list[RiderResult] | None = None,
        damage_reduction: int = 0,
    ) -> ActionResult | None:
        """Phase 2: Roll damage and complete the attack.

        Args:
            hit_result: The intermediate result from execute_attack_hit_check().
            bonus_damage: Optional extra damage (e.g., Divine Smite radiant dice).
            rider_results: Resolved on-hit rider outcomes (damage + conditions).
            damage_reduction: Flat reduction from a reaction (Parry, Deflect
                Missiles) or -1 for halving (Uncanny Dodge).

        Returns:
            ActionResult with damage events, or None if invalid.
        """
        # Check if the target is player-controlled with available damage
        # reduction reactions.  If so, defer to the GUI popup instead of
        # completing the attack right now.
        if (
            hit_result.hit
            and damage_reduction == 0
            and hit_result.attack is not None
        ):
            target_c = self.combatants.get(hit_result.target_id)
            if (
                target_c is not None
                and getattr(target_c.creature, "is_player_controlled", False)
            ):
                attack_type = hit_result.attack.attack_type
                options = self.check_damage_reduction_reaction(
                    hit_result.target_id, attack_type,
                )
                if options:
                    self._pending_damage_reduction = {
                        "hit_result": hit_result,
                        "rider_results": rider_results,
                        "target_id": hit_result.target_id,
                        "options": options,
                    }
                    return None  # Deferred -- GUI will show popup

        # Aggregate rider bonus damage into the bonus_damage list
        all_bonus = list(bonus_damage) if bonus_damage else []
        if rider_results:
            for rr in rider_results:
                if rr.used:
                    all_bonus.extend(rr.bonus_damage)

        result = resolve_attack_damage(
            hit_result,
            bonus_damage=all_bonus if all_bonus else None,
            damage_reduction=damage_reduction,
        )

        # Apply pending forced movement from the attack result
        attacker_c = self.combatants.get(hit_result.attacker_id)
        if result.success and attacker_c and attacker_c.position is not None:
            fm_events = self._apply_pending_forced_movement(
                result.events, hit_result.attacker_id, attacker_c.position,
            )
            result.events.extend(fm_events)

        # Log only the NEW events (damage, concentration, KO, forced movement)
        # — hit events were already logged in execute_attack_hit_check()
        new_events = result.events[len(hit_result.events):]
        for event in new_events:
            self.log.add(event)

        # Apply rider conditions (e.g., Stunning Strike's stunned)
        if rider_results:
            from arena.combat.conditions import apply_condition
            from arena.models.conditions import AppliedCondition

            for rr in rider_results:
                if rr.used and rr.condition_to_apply:
                    target_c = self.combatants.get(hit_result.target_id)
                    if target_c:
                        cond = AppliedCondition(
                            condition=rr.condition_to_apply,
                            source=hit_result.attacker_id,
                            duration_type=rr.condition_duration,
                            save_to_end=rr.condition_save_to_end,
                            save_dc=rr.save_dc,
                        )
                        events = apply_condition(
                            target_c.creature, hit_result.target_id, cond,
                        )
                        for event in events:
                            self.log.add(event)
                            result.events.append(event)

                # Log rider messages
                if rr.used and rr.log_message:
                    event = CombatEvent(
                        event_type=CombatEventType.INFO,
                        source_id=hit_result.attacker_id,
                        target_id=hit_result.target_id,
                        message=rr.log_message,
                    )
                    self.log.add(event)
                    result.events.append(event)

        # Track once-per-turn rider usage
        if rider_results:
            if self.turn_resources.used_riders is None:
                self.turn_resources.used_riders = set()
            for rr in rider_results:
                if rr.used:
                    self.turn_resources.used_riders.add(rr.feature_name)

        if result.success and hit_result.action is not None:
            attacker = self.combatants.get(hit_result.attacker_id)
            creature = attacker.creature if attacker else None
            self._handle_extra_attack_tracking(hit_result.action, creature)

        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        # Damage may have broken concentration — clean up orphaned zones
        self._cleanup_orphaned_zones()
        self._cleanup_orphaned_recurring_actions()

        self._check_victory()

        return result

    def _is_zone_creating_spell(self, action: Action) -> bool:
        """Check if an action creates a persistent AoE zone rather than a one-time burst.

        Zone spells are concentration AoE spells with saving throw damage.
        Per 5e, these don't deal damage on cast — only when creatures start
        their turn in the zone or enter it.
        """
        return (
            action.requires_concentration
            and action.target_type.value.startswith("area_")
            and action.saving_throw is not None
            and bool(action.saving_throw.damage_on_fail)
        )

    def _apply_terrain_modification(
        self, action: Action, combatant, center_hex: HexCoord,
    ) -> list[CombatEvent]:
        """Apply terrain modification from an action, if applicable.

        Called after effect resolution.  Creates a TerrainModification
        record, applies it to the grid, and tracks it for potential
        reversion when concentration ends.
        """
        if action.terrain_modification is None or self.grid is None:
            return []

        from arena.combat.terrain_effects import apply_terrain_modification
        from arena.models.encounter import TerrainType

        try:
            terrain_type = TerrainType(action.terrain_modification)
        except ValueError:
            return []

        mod, events = apply_terrain_modification(
            grid=self.grid,
            center=center_hex,
            radius_feet=action.area_size or 0,
            terrain_type=terrain_type,
            caster_id=combatant.creature_id,
            spell_name=action.name,
            concentration_linked=action.requires_concentration,
            combatants=self.combatants,
        )

        if mod.original_terrain:  # Only track if it actually changed something
            self.active_terrain_mods.append(mod)

            # Start concentration if needed and not already concentrating.
            # Zone spells (_execute_zone_spell) start concentration before
            # calling this method, so the check prevents double-start.
            if action.requires_concentration:
                from arena.combat.conditions import has_condition
                from arena.models.conditions import Condition

                if not has_condition(combatant.creature, Condition.CONCENTRATING):
                    from arena.combat.concentration import start_concentrating

                    conc_events = start_concentrating(
                        combatant.creature,
                        combatant.creature_id,
                        action.name,
                        combatants=self.combatants,
                    )
                    events.extend(conc_events)

        return events

    def _execute_wall_spell(
        self, action: Action, combatant, wall_hexes: list,
    ) -> ActionResult:
        """Create a wall spell from an action with is_wall=True.

        Args:
            action: The wall spell action.
            combatant: The casting combatant.
            wall_hexes: List of HexCoord forming the wall path.

        Returns:
            ActionResult with creation events.
        """
        from arena.combat.wall_spells import create_wall
        from arena.combat.actions import check_resource_cost, deduct_resource_cost

        events: list[CombatEvent] = []

        # Check and deduct resources
        can_use, reason = check_resource_cost(
            combatant.creature, action, cast_level=self._cast_level,
        )
        if not can_use:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=reason,
                source_id=combatant.creature_id,
            ))
            self.selected_action = None
            self._cast_level = None
            self.turn_phase = TurnPhase.AWAITING_ACTION
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)

        deduct_resource_cost(
            combatant.creature, action, cast_level=self._cast_level,
        )

        wall = create_wall(action, combatant.creature_id, wall_hexes)
        if wall is not None:
            self.active_walls.append(wall)
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{combatant.creature.name} creates {action.name}!",
                source_id=combatant.creature_id,
                details={"action_name": action.name, "is_effect_use": True},
            ))

            # Start concentration if needed
            if action.requires_concentration:
                from arena.combat.concentration import start_concentrating
                conc_events = start_concentrating(
                    combatant.creature,
                    combatant.creature_id,
                    action.name,
                    combatants=self.combatants,
                )
                events.extend(conc_events)

        self._mark_action_type_used(action)
        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        for e in events:
            self.log.add(e)

        self._cleanup_orphaned_zones()
        self._check_victory()

        return ActionResult(events=events, success=wall is not None)

    def _get_wall_blocked_hexes(self) -> set[tuple[int, int]]:
        """Compute the set of (q, r) tuples blocked by active walls.

        Used to pass to pathfinding so movement avoids wall hexes.
        """
        blocked: set[tuple[int, int]] = set()
        for wall in self.active_walls:
            for h in wall.get_wall_hexes():
                if wall.is_blocking_hex(h):
                    blocked.add((h.q, h.r))
        return blocked

    def _get_wall_los_blocked_hexes(self) -> set[tuple[int, int]]:
        """Compute the set of (q, r) tuples that block line of sight.

        Used to pass to has_line_of_sight so LOS checks respect wall spells.
        """
        blocked: set[tuple[int, int]] = set()
        for wall in self.active_walls:
            for h in wall.get_wall_hexes():
                if wall.is_blocking_los_hex(h):
                    blocked.add((h.q, h.r))
        return blocked

    def execute_effect(self, target_id: str) -> ActionResult | None:
        """Execute the selected non-attack action (healing, saves, conditions).

        For area-of-effect actions (target_type starts with "area_"),
        automatically expands to hit ALL creatures within area_size feet
        of the caster (except the caster itself).  The originally-clicked
        target is always included.

        Zone-creating spells (concentration AoE with save damage, e.g.
        Spirit Guardians) skip the initial damage burst and instead create
        a persistent zone.  Per 5e, damage only occurs when enemies start
        their turn in the zone or first enter it on a turn.

        Args:
            target_id: creature_id of the target (may be self).

        Returns:
            ActionResult with merged events, or None if invalid.
        """
        combatant = self.active_combatant
        if combatant is None or self.selected_action is None:
            return None
        if self.grid is None:
            return None

        # Pre-check: action economy slot must be available
        if not self.can_use_action_type(self.selected_action.action_type):
            return None

        action = self.selected_action

        # ── Counterspell check (before spell resolves) ─────────────────
        if action.spell_level is not None:
            countered, cs_events = self._try_counterspell(action, combatant.creature_id)
            if cs_events:
                for evt in cs_events:
                    self.log.add(evt)
            if countered:
                from arena.combat.actions import deduct_resource_cost
                deduct_resource_cost(combatant.creature, action, cast_level=self._cast_level)
                self._mark_action_type_used(action)
                cs_events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{combatant.creature.name}'s {action.name} is countered!",
                    source_id=combatant.creature_id,
                    details={"counterspelled": True},
                ))
                self.log.add(cs_events[-1])
                self.selected_action = None
                self._cast_level = None
                self.turn_phase = TurnPhase.AWAITING_ACTION
                return ActionResult(events=cs_events, success=False)
            player_cs = self.get_pending_counterspell_opportunities(action, combatant.creature_id)
            if player_cs:
                self._pending_counterspell = {
                    "caster_id": combatant.creature_id,
                    "action": action,
                    "cast_level": self._cast_level,
                    "target_id": target_id,
                    "counterspellers": player_cs,
                    "method": "effect",
                }
                return None  # GUI will handle popup

        # ── Zone-creating spells: no initial burst ────────────────────
        if self._is_zone_creating_spell(action):
            return self._execute_zone_spell(action, combatant)

        # ── Determine target list ──────────────────────────────────────
        target_ids = self._resolve_effect_targets(
            action, combatant, target_id
        )
        if not target_ids:
            return None

        # ── Multi-target: repeat single-target for multiple darts/rays ─
        is_area = action.target_type.value.startswith("area_")
        effective_count = get_effective_target_count(action, self._cast_level)
        if not is_area and effective_count > 1 and len(target_ids) == 1:
            # Repeat the single target (Magic Missile pattern: N darts at same target)
            target_ids = target_ids * effective_count

        # ── Resolve against each target ────────────────────────────────
        all_events: list[CombatEvent] = []
        any_success = False
        # Save one-time costs so they only apply on the first target
        saved_cost = dict(action.resource_cost)
        saved_uses = action.uses_per_rest

        for i, tid in enumerate(target_ids):
            tc = self.combatants.get(tid)
            if tc is None:
                continue
            # Only deduct resource cost / use tracking on the first target
            if i > 0:
                action.resource_cost = {}
                action.uses_per_rest = None

            # Snapshot target before resolve for potential forced reroll
            creature_snapshot = (
                copy.deepcopy(tc.creature) if action.saving_throw else None
            )

            result = resolve_effect(
                user=combatant.creature,
                user_id=combatant.creature_id,
                target=tc.creature,
                target_id=tid,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                user_pos=combatant.position,
                target_pos=tc.position,
                cast_level=self._cast_level,
            )

            # ── Forced save reroll (Indomitable, Lucky, Diamond Soul) ──
            if action.saving_throw and creature_snapshot is not None:
                failed_save = self._find_failed_save(result.events)
                if failed_save is not None:
                    reroll_features = [
                        f for f in get_forced_reroll_features(tc.creature)
                        if can_afford_reroll(tc.creature, f)
                    ]
                    if reroll_features:
                        if tc.creature.is_player_controlled:
                            # Player: pause for popup decision
                            self._pending_save_reroll = PendingSaveReroll(
                                target_id=tid,
                                target_snapshot=creature_snapshot,
                                save_ability=failed_save["ability"],
                                save_dc=failed_save["dc"],
                                original_roll=failed_save["natural"],
                                features=reroll_features,
                                user_id=combatant.creature_id,
                                action=action,
                                cast_level=self._cast_level,
                                events_before=list(all_events),
                                remaining_target_ids=target_ids[i + 1:],
                                remaining_index=i + 1,
                                saved_cost=saved_cost,
                                saved_uses=saved_uses,
                            )
                            self._pending_reroll_original_events = list(
                                result.events
                            )
                            self._pending_reroll_original_success = (
                                result.success
                            )
                            # Restore cost/uses before pausing
                            action.resource_cost = saved_cost
                            action.uses_per_rest = saved_uses
                            return ActionResult(
                                events=all_events, success=any_success,
                            )
                        else:
                            # AI: auto-reroll
                            reroll_result = self._attempt_ai_save_reroll(
                                tc, tid, creature_snapshot,
                                failed_save, reroll_features,
                                combatant, action, result,
                            )
                            if reroll_result is not None:
                                result = reroll_result

            all_events.extend(result.events)
            if result.success:
                any_success = True

        # Restore original values
        action.resource_cost = saved_cost
        action.uses_per_rest = saved_uses

        # ── Chain effects: resolve against secondary targets ───────────
        if any_success and has_chain_effect(action):
            primary_tid = target_ids[0] if target_ids else target_id
            combatants_dict = {
                cid: c.creature for cid, c in self.combatants.items()
            }
            positions_dict = {
                cid: c.position
                for cid, c in self.combatants.items()
                if c.position is not None
            }
            chain_targets = get_chain_targets(
                action, primary_tid, combatants_dict,
                positions_dict, combatant.creature_id,
            )
            for chain_tid in chain_targets:
                tc = self.combatants.get(chain_tid)
                if tc is None:
                    continue
                # Chain targets: no resource cost (already paid)
                action.resource_cost = {}
                action.uses_per_rest = None
                result = resolve_effect(
                    user=combatant.creature,
                    user_id=combatant.creature_id,
                    target=tc.creature,
                    target_id=chain_tid,
                    action=action,
                    grid=self.grid,
                    combatants=self.combatants,
                    user_pos=combatant.position,
                    target_pos=tc.position,
                    cast_level=self._cast_level,
                )
                all_events.extend(result.events)
            # Restore after chain resolution
            action.resource_cost = saved_cost
            action.uses_per_rest = saved_uses

        # Apply pending forced movement for all targets
        if any_success and combatant.position is not None:
            fm_events = self._apply_pending_forced_movement(
                all_events, combatant.creature_id, combatant.position,
            )
            all_events.extend(fm_events)

        merged = ActionResult(events=all_events, success=any_success)

        # Inject AoE center into the first effect-use event for visual effects
        if all_events and action.target_type.value.startswith("area_"):
            for evt in all_events:
                if evt.event_type == CombatEventType.INFO and evt.details.get("is_effect_use"):
                    if combatant.position is not None:
                        evt.details["aoe_center_hex"] = (combatant.position.q, combatant.position.r)
                        evt.details["area_size"] = action.area_size or action.range
                        if action.saving_throw and action.saving_throw.damage_on_fail:
                            evt.details["aoe_damage_type"] = action.saving_throw.damage_on_fail[0].damage_type.value
                    break

        for event in merged.events:
            self.log.add(event)

        if any_success:
            self._mark_action_type_used(action)
            # Create recurring action if the spell supports it
            self._maybe_create_recurring_action(
                action, combatant.creature_id, target_ids[0] if target_ids else target_id,
            )

        # Apply terrain modification (e.g., self-centered terrain spells)
        if combatant.position is not None:
            terrain_events = self._apply_terrain_modification(
                action, combatant, combatant.position,
            )
            for te in terrain_events:
                all_events.append(te)
                self.log.add(te)

        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        # A new concentration spell may have ended old concentration — clean up zones
        self._cleanup_orphaned_zones()
        # Also clean up recurring actions whose concentration was just broken
        self._cleanup_orphaned_recurring_actions()

        # Check if combat has ended
        self._check_victory()

        return merged

    # ------------------------------------------------------------------
    # Forced save reroll helpers (Indomitable, Lucky, Diamond Soul)
    # ------------------------------------------------------------------

    @staticmethod
    def _find_failed_save(
        events: list[CombatEvent],
    ) -> dict | None:
        """Find the first failed saving throw in an event list.

        Returns the event details dict if found, None otherwise.
        """
        for evt in events:
            if (
                evt.event_type == CombatEventType.SAVING_THROW
                and not evt.details.get("success")
                and not evt.details.get("auto_fail")
            ):
                return evt.details
        return None

    def _attempt_ai_save_reroll(
        self,
        tc: Combatant,
        tid: str,
        creature_snapshot: Creature,
        failed_save: dict,
        reroll_features: list,
        caster_combatant: Combatant,
        action: Action,
        original_result: ActionResult,
    ) -> ActionResult | None:
        """AI auto-rerolls a failed save if the effect is significant.

        Restores the creature snapshot, re-resolves the effect, and uses
        the reroll result (whether better or worse -- the reroll replaces
        the original per D&D rules). Deducts the feature's resource cost.

        Returns the new ActionResult if reroll was used, None if skipped.
        """
        feature = reroll_features[0]  # Use first available

        # AI heuristic: always reroll if there's a condition or damage
        save = action.saving_throw
        has_condition = bool(
            save and (save.conditions_on_fail or action.conditions_applied)
        )
        has_damage = bool(save and save.damage_on_fail)
        if not has_condition and not has_damage:
            return None  # Trivial effect, skip reroll

        # Restore creature to pre-resolve state, then deduct reroll cost
        self._restore_creature_snapshot(tc, creature_snapshot)
        deduct_reroll_cost(tc.creature, feature)

        # Log the reroll attempt
        reroll_event = CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{tc.creature.name} uses {feature.name} to reroll the "
                f"{failed_save['ability'].upper()} saving throw!"
            ),
            source_id=tid,
            details={"forced_reroll": True, "feature_name": feature.name},
        )

        # Re-resolve the entire effect (new save roll).
        # Resource cost was already paid on first resolve, so zero it out.
        saved_cost = dict(action.resource_cost)
        saved_uses = action.uses_per_rest
        action.resource_cost = {}
        action.uses_per_rest = None

        new_result = resolve_effect(
            user=caster_combatant.creature,
            user_id=caster_combatant.creature_id,
            target=tc.creature,
            target_id=tid,
            action=action,
            grid=self.grid,
            combatants=self.combatants,
            user_pos=caster_combatant.position,
            target_pos=tc.position,
            cast_level=self._cast_level,
        )

        action.resource_cost = saved_cost
        action.uses_per_rest = saved_uses

        # Return combined events: reroll log + new resolution
        combined_events = [reroll_event] + list(new_result.events)
        return ActionResult(events=combined_events, success=new_result.success)

    def _restore_creature_snapshot(
        self, tc: Combatant, snapshot: Creature,
    ) -> None:
        """Restore a combatant's creature to a previous snapshot state."""
        tc.creature.current_hit_points = snapshot.current_hit_points
        tc.creature.temporary_hit_points = snapshot.temporary_hit_points
        tc.creature.active_conditions = copy.deepcopy(snapshot.active_conditions)
        tc.creature.active_buffs = copy.deepcopy(snapshot.active_buffs)
        if hasattr(snapshot, 'class_resources'):
            tc.creature.class_resources = copy.deepcopy(snapshot.class_resources)

    def resolve_save_reroll_choice(
        self, feature_name: str | None,
    ) -> ActionResult | None:
        """Resolve the player's forced reroll choice.

        Args:
            feature_name: Name of the feature to use for reroll,
                or None to skip the reroll.

        Returns:
            ActionResult with the continuation events, or None if
            no pending reroll.
        """
        pending = self._pending_save_reroll
        if pending is None:
            return None

        tc = self.combatants.get(pending.target_id)
        if tc is None:
            self._pending_save_reroll = None
            return None

        all_events = list(pending.events_before)
        any_success = False

        if feature_name is not None:
            # Player chose to reroll -- find the feature
            feature = None
            for f in pending.features:
                if f.name == feature_name:
                    feature = f
                    break
            if feature is None:
                # Feature not found, treat as skip
                return self.resolve_save_reroll_choice(None)

            # Restore creature to pre-resolve snapshot, then deduct reroll cost
            self._restore_creature_snapshot(tc, pending.target_snapshot)
            deduct_reroll_cost(tc.creature, feature)

            # Log reroll
            reroll_event = CombatEvent(
                event_type=CombatEventType.INFO,
                message=(
                    f"{tc.creature.name} uses {feature.name} to reroll "
                    f"the {pending.save_ability.upper()} saving throw!"
                ),
                source_id=pending.target_id,
                details={
                    "forced_reroll": True,
                    "feature_name": feature.name,
                },
            )
            all_events.append(reroll_event)

            # Get the caster combatant
            caster = self.combatants.get(pending.user_id)
            if caster is None:
                self._pending_save_reroll = None
                return None

            # Re-resolve with new save roll (resource cost already paid
            # on first resolve, so zero it out)
            action = pending.action
            saved_cost = dict(action.resource_cost)
            saved_uses = action.uses_per_rest
            action.resource_cost = {}
            action.uses_per_rest = None

            result = resolve_effect(
                user=caster.creature,
                user_id=pending.user_id,
                target=tc.creature,
                target_id=pending.target_id,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                user_pos=caster.position,
                target_pos=tc.position,
                cast_level=pending.cast_level,
            )
            all_events.extend(result.events)
            if result.success:
                any_success = True

            action.resource_cost = saved_cost
            action.uses_per_rest = saved_uses
        else:
            # Player skipped -- use original events
            all_events.extend(self._pending_reroll_original_events)
            if self._pending_reroll_original_success:
                any_success = True

        # Continue processing remaining targets
        caster = self.combatants.get(pending.user_id)
        action = pending.action
        if caster is not None and pending.remaining_target_ids:
            for tid in pending.remaining_target_ids:
                rtc = self.combatants.get(tid)
                if rtc is None:
                    continue
                action.resource_cost = {}
                action.uses_per_rest = None

                result = resolve_effect(
                    user=caster.creature,
                    user_id=pending.user_id,
                    target=rtc.creature,
                    target_id=tid,
                    action=action,
                    grid=self.grid,
                    combatants=self.combatants,
                    user_pos=caster.position,
                    target_pos=rtc.position,
                    cast_level=pending.cast_level,
                )
                all_events.extend(result.events)
                if result.success:
                    any_success = True

            action.resource_cost = pending.saved_cost
            action.uses_per_rest = pending.saved_uses

        # Finalize: same post-processing as execute_effect
        merged = ActionResult(events=all_events, success=any_success)
        for event in all_events:
            self.log.add(event)

        if any_success and caster is not None:
            self._mark_action_type_used(action)

        self._pending_save_reroll = None
        self._pending_reroll_original_events = []
        self._pending_reroll_original_success = False
        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        self._cleanup_orphaned_zones()
        self._cleanup_orphaned_recurring_actions()
        self._check_victory()

        return merged

    def _execute_zone_spell(
        self, action: Action, combatant,
        target_hex: HexCoord | None = None,
    ) -> ActionResult:
        """Handle concentration AoE zone spells (e.g., Spirit Guardians).

        Per 5e rules, these spells don't deal damage on cast.  They
        create a persistent zone and start concentration.  Damage occurs
        when enemies start their turn in the zone or first enter it.
        """
        from arena.combat.actions import check_resource_cost, deduct_resource_cost
        from arena.combat.concentration import start_concentrating
        from arena.combat.zones import ActiveZone

        events: list[CombatEvent] = []

        # ── Resource cost ─────────────────────────────────────────────
        can_use, reason = check_resource_cost(
            combatant.creature, action, cast_level=self._cast_level,
        )
        if not can_use:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=reason,
                source_id=combatant.creature_id,
            ))
            self.selected_action = None
            self._cast_level = None
            self.turn_phase = TurnPhase.AWAITING_ACTION
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)
        deduct_resource_cost(
            combatant.creature, action, cast_level=self._cast_level,
        )

        # ── Log the cast ──────────────────────────────────────────────
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{combatant.creature.name} casts {action.name}!",
            source_id=combatant.creature_id,
            details={
                "action_name": action.name,
                "animation": action.animation,
                "target_type": action.target_type.value,
                "is_effect_use": True,
            },
        ))

        # ── Start concentration ───────────────────────────────────────
        conc_events = start_concentrating(
            combatant.creature, combatant.creature_id,
            action.name, combatants=self.combatants,
        )
        events.extend(conc_events)

        # ── Create the persistent zone ────────────────────────────────
        save = action.saving_throw

        # Upcast: augment zone damage dice if cast at higher level
        zone_dice = save.damage_on_fail[0].dice
        if self._cast_level is not None:
            from arena.combat.upcast import calculate_upcast_zone_dice
            upcast_dice = calculate_upcast_zone_dice(action, self._cast_level)
            if upcast_dice:
                zone_dice = upcast_dice

        zone = ActiveZone(
            zone_id=f"{action.name.lower().replace(' ', '_')}_{combatant.creature_id}",
            caster_id=combatant.creature_id,
            name=action.name,
            radius_feet=action.area_size or action.range,
            follows_caster=action.zone_follows_caster,
            center=None if action.zone_follows_caster else target_hex,
            saving_throw_ability=save.ability,
            saving_throw_dc=save.dc or 10,
            damage_dice=zone_dice,
            damage_type=save.damage_on_fail[0].damage_type.value,
            damage_on_save=save.damage_on_success,
            affects_enemies_only=True,
            team=combatant.team,
            concentration_linked=True,
            already_damaged=set(),
        )
        # Remove any existing zone from this caster first
        self.active_zones = [z for z in self.active_zones if z.caster_id != combatant.creature_id]
        self.active_zones.append(zone)

        zone_center = (
            (combatant.position.q, combatant.position.r)
            if action.zone_follows_caster and combatant.position
            else (target_hex.q, target_hex.r) if target_hex
            else (combatant.position.q, combatant.position.r)
            if combatant.position else (0, 0)
        )
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{combatant.creature.name}'s {action.name} zone is now active!",
            source_id=combatant.creature_id,
            details={
                "zone_created": True,
                "zone_id": zone.zone_id,
                "zone_center_hex": zone_center,
                "zone_radius_feet": zone.radius_feet,
                "zone_damage_type": zone.damage_type,
            },
        ))

        # ── Terrain modification (combo: zone + terrain, e.g. Spike Growth) ─
        terrain_center = target_hex if target_hex else combatant.position
        if terrain_center is not None:
            terrain_events = self._apply_terrain_modification(
                action, combatant, terrain_center,
            )
            events.extend(terrain_events)

        # ── Finalize ──────────────────────────────────────────────────
        merged = ActionResult(events=events, success=True)
        for event in merged.events:
            self.log.add(event)

        self._mark_action_type_used(action)
        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        # Clean up old zones if old concentration was replaced
        self._cleanup_orphaned_zones()

        return merged

    def _resolve_effect_targets(
        self,
        action: Action,
        combatant,
        clicked_target_id: str,
    ) -> list[str]:
        """Determine which creatures are affected by an effect action.

        For single-target actions, returns [clicked_target_id].
        For area-of-effect actions, returns all conscious creatures within
        area_size feet of the caster (except the caster), with the
        originally-clicked target first.
        """
        # Single-target: just validate and return
        if not action.target_type.value.startswith("area_"):
            if clicked_target_id in self.combatants:
                return [clicked_target_id]
            return []

        # Area-of-effect: find all creatures in range
        area_feet = action.area_size or action.range
        caster_pos = combatant.position
        if caster_pos is None or self.grid is None:
            return [clicked_target_id] if clicked_target_id in self.combatants else []

        from arena.grid.footprint import min_distance_between

        # Determine which teams are valid targets.
        # Beneficial AoE only reaches the caster's side; harmful AoE hits
        # EVERY team — friendly fire is real (B5): allies standing in the
        # blast take it like anyone else, 5e-style.
        caster_team = combatant.team
        if action.healing and not action.saving_throw:
            # Beneficial AoE (e.g., Mass Cure Wounds) — target allies
            target_teams = {caster_team}
        else:
            # Harmful AoE (e.g., breath weapons, Thunderwave) — everyone in it
            target_teams = {c.team for c in self.combatants.values()}

        affected: list[str] = []
        for cid, c in self.combatants.items():
            # Don't hit yourself
            if cid == combatant.creature_id:
                continue
            # Skip already-dead creatures
            if not c.creature.is_conscious:
                continue
            # Filter by team
            if c.team not in target_teams:
                continue
            target_pos = c.position
            if target_pos is None:
                continue
            dist_hexes = min_distance_between(
                caster_pos, combatant.creature.size,
                target_pos, c.creature.size,
            )
            dist_feet = dist_hexes * 5
            if dist_feet <= area_feet:
                affected.append(cid)

        # Ensure clicked target is first (and included) — but never the caster
        if clicked_target_id != combatant.creature_id:
            if clicked_target_id in affected:
                affected.remove(clicked_target_id)
            affected.insert(0, clicked_target_id)

        return affected

    def _resolve_effect_targets_at_hex(
        self,
        action: Action,
        combatant,
        target_hex: HexCoord,
    ) -> list[str]:
        """Find all creatures within area_size feet of a target hex.

        Unlike ``_resolve_effect_targets``, uses the clicked hex as the AoE
        center instead of the caster's position, and does NOT automatically
        skip the caster (they may be in their own Fireball).
        """
        area_feet = action.area_size or action.range
        if self.grid is None:
            return []

        from arena.grid.footprint import min_distance_between

        # Team filtering — same logic as _resolve_effect_targets:
        # beneficial AoE is allies-only, harmful AoE hits every team
        # (friendly fire is real — and here even the caster, who may well
        # be standing in their own Fireball).
        caster_team = combatant.team
        if action.healing and not action.saving_throw:
            target_teams = {caster_team}
        else:
            target_teams = {c.team for c in self.combatants.values()}

        affected: list[str] = []
        for cid, c in self.combatants.items():
            if not c.creature.is_conscious:
                continue
            if c.team not in target_teams:
                continue
            target_pos = c.position
            if target_pos is None:
                continue
            # Distance from AoE center (the clicked hex, size 1)
            dist_feet = min_distance_between(
                target_hex, 1,
                target_pos, c.creature.size,
            ) * 5
            if dist_feet <= area_feet:
                affected.append(cid)

        return affected

    def execute_effect_at_hex(
        self, target_hex: HexCoord, clicked_target_id: str | None = None,
    ) -> ActionResult | None:
        """Execute an AoE action centered on a specific hex.

        For zone-creating spells, creates a fixed-center zone at *target_hex*.
        For non-zone AoE (Fireball, etc.), resolves immediately against all
        creatures within *area_size* feet of *target_hex*.
        """
        from arena.combat.actions import (
            check_resource_cost,
            deduct_resource_cost,
            resolve_effect,
        )

        combatant = self.active_combatant
        if combatant is None or self.selected_action is None:
            return None
        if self.grid is None:
            return None
        if not self.can_use_action_type(self.selected_action.action_type):
            return None

        action = self.selected_action

        # ── Counterspell check (before spell resolves) ─────────────────
        if action.spell_level is not None:
            countered, cs_events = self._try_counterspell(action, combatant.creature_id)
            if cs_events:
                for evt in cs_events:
                    self.log.add(evt)
            if countered:
                deduct_resource_cost(combatant.creature, action, cast_level=self._cast_level)
                self._mark_action_type_used(action)
                cs_events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{combatant.creature.name}'s {action.name} is countered!",
                    source_id=combatant.creature_id,
                    details={"counterspelled": True},
                ))
                self.log.add(cs_events[-1])
                self.selected_action = None
                self._cast_level = None
                self.turn_phase = TurnPhase.AWAITING_ACTION
                return ActionResult(events=cs_events, success=False)
            player_cs = self.get_pending_counterspell_opportunities(action, combatant.creature_id)
            if player_cs:
                self._pending_counterspell = {
                    "caster_id": combatant.creature_id,
                    "action": action,
                    "cast_level": self._cast_level,
                    "target_hex": target_hex,
                    "clicked_target_id": clicked_target_id,
                    "counterspellers": player_cs,
                    "method": "effect_at_hex",
                }
                return None  # GUI will handle popup

        # ── Zone-creating spells: create fixed-center zone ──────────
        if self._is_zone_creating_spell(action):
            return self._execute_zone_spell(action, combatant, target_hex=target_hex)

        # ── Non-zone AoE: resolve against creatures near target hex ─
        target_ids = self._resolve_effect_targets_at_hex(action, combatant, target_hex)

        if not target_ids:
            # Fireball into empty space — still consumes the action + resources
            events: list[CombatEvent] = []
            can_use, reason = check_resource_cost(
                combatant.creature, action, cast_level=self._cast_level,
            )
            if not can_use:
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=reason,
                    source_id=combatant.creature_id,
                ))
                self.selected_action = None
                self._cast_level = None
                self.turn_phase = TurnPhase.AWAITING_ACTION
                for e in events:
                    self.log.add(e)
                return ActionResult(events=events, success=False)
            deduct_resource_cost(
                combatant.creature, action, cast_level=self._cast_level,
            )

            aoe_details: dict = {
                    "action_name": action.name,
                    "animation": action.animation,
                    "target_type": action.target_type.value,
                    "is_effect_use": True,
                    "aoe_center_hex": (target_hex.q, target_hex.r),
                    "area_size": action.area_size or action.range,
            }
            if action.saving_throw and action.saving_throw.damage_on_fail:
                aoe_details["aoe_damage_type"] = action.saving_throw.damage_on_fail[0].damage_type.value
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{combatant.creature.name} uses {action.name} — no targets in area!",
                source_id=combatant.creature_id,
                details=aoe_details,
            ))
            self._mark_action_type_used(action)

            # Apply terrain modification even with no creature targets
            terrain_events = self._apply_terrain_modification(
                action, combatant, target_hex,
            )
            events.extend(terrain_events)

            self.selected_action = None
            self._cast_level = None
            self.turn_phase = TurnPhase.AWAITING_ACTION
            for e in events:
                self.log.add(e)
            self._cleanup_orphaned_zones()
            return ActionResult(events=events, success=True)

        # ── Resolve against each target ─────────────────────────────
        all_events: list[CombatEvent] = []
        any_success = False
        saved_cost = dict(action.resource_cost)
        saved_uses = action.uses_per_rest

        for i, tid in enumerate(target_ids):
            tc = self.combatants.get(tid)
            if tc is None:
                continue
            if i > 0:
                action.resource_cost = {}
                action.uses_per_rest = None

            result = resolve_effect(
                user=combatant.creature,
                user_id=combatant.creature_id,
                target=tc.creature,
                target_id=tid,
                action=action,
                grid=self.grid,
                combatants=self.combatants,
                user_pos=combatant.position,
                target_pos=tc.position,
                cast_level=self._cast_level,
            )
            all_events.extend(result.events)
            if result.success:
                any_success = True

        action.resource_cost = saved_cost
        action.uses_per_rest = saved_uses

        # Apply pending forced movement for all targets
        if any_success and combatant.position is not None:
            fm_events = self._apply_pending_forced_movement(
                all_events, combatant.creature_id, combatant.position,
            )
            all_events.extend(fm_events)

        merged = ActionResult(events=all_events, success=any_success)

        # Inject AoE center into the first effect-use event for visual effects
        if all_events:
            for evt in all_events:
                if evt.event_type == CombatEventType.INFO and evt.details.get("is_effect_use"):
                    evt.details["aoe_center_hex"] = (target_hex.q, target_hex.r)
                    evt.details["area_size"] = action.area_size or action.range
                    if action.saving_throw and action.saving_throw.damage_on_fail:
                        evt.details["aoe_damage_type"] = action.saving_throw.damage_on_fail[0].damage_type.value
                    break

        for event in merged.events:
            self.log.add(event)

        if any_success:
            self._mark_action_type_used(action)

        # Apply terrain modification (e.g., click-to-place terrain spells)
        terrain_events = self._apply_terrain_modification(
            action, combatant, target_hex,
        )
        for te in terrain_events:
            all_events.append(te)
            self.log.add(te)

        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        self._cleanup_orphaned_zones()
        self._check_victory()

        return merged

    def can_two_weapon_fight(self) -> bool:
        """Check if the active combatant can make a two-weapon fighting attack.

        Requirements per 5e:
        - Must have used a melee attack action this turn (action used).
        - Must have a light melee weapon available (for off-hand).
        - Bonus action must be available.

        Returns:
            True if TWF bonus action attack is available.
        """
        combatant = self.active_combatant
        if combatant is None:
            return False
        if not self.turn_resources.has_used_action:
            return False
        if self.turn_resources.has_used_bonus_action:
            return False

        # Check for a light melee weapon
        return self._get_offhand_weapon(combatant.creature) is not None

    def _get_offhand_weapon(self, creature: Creature) -> Action | None:
        """Find a light melee weapon action for off-hand attack."""
        for action in creature.actions:
            if (
                action.attack
                and action.attack.attack_type.startswith("melee")
                and "light" in action.attack.properties
            ):
                return action
        return None

    def execute_bonus_action_attack(self, target_id: str) -> ActionResult | None:
        """Execute a two-weapon fighting off-hand attack as a bonus action.

        Per 5e rules, the off-hand attack does not add the ability modifier
        to damage (unless the creature has Two-Weapon Fighting style, which
        is not tracked here yet).

        Args:
            target_id: creature_id of the target.

        Returns:
            ActionResult with events, or None if invalid.
        """
        if not self.can_two_weapon_fight():
            return None

        combatant = self.active_combatant
        if combatant is None or self.grid is None:
            return None

        target_combatant = self.combatants.get(target_id)
        if target_combatant is None:
            return None

        offhand = self._get_offhand_weapon(combatant.creature)
        if offhand is None:
            return None

        # Create a temporary copy of the action without ability modifier on damage
        import copy
        twf_action = copy.deepcopy(offhand)
        if twf_action.attack:
            for dr in twf_action.attack.damage:
                dr.ability_modifier = None

        result = resolve_attack(
            attacker=combatant.creature,
            attacker_id=combatant.creature_id,
            target=target_combatant.creature,
            target_id=target_id,
            action=twf_action,
            grid=self.grid,
            combatants=self.combatants,
            attacker_pos=combatant.position,
            target_pos=target_combatant.position,
        )

        for event in result.events:
            self.log.add(event)

        if result.success:
            self.turn_resources.has_used_bonus_action = True

        self._check_victory()
        return result

    def try_move(self, target: HexCoord) -> bool:
        """Attempt to move the active creature to target hex.

        Checks for opportunity attacks when leaving an enemy's reach.
        OAs are resolved before the move completes.

        Args:
            target: Destination hex coordinate.

        Returns:
            True if the move was successful.
        """
        if self.grid is None:
            return False

        combatant = self.active_combatant
        if combatant is None:
            return False

        from_pos = combatant.position
        if from_pos is None:
            return False

        # Check for opportunity attacks before moving
        oa_attackers = check_opportunity_attacks(
            mover_id=combatant.creature_id,
            from_pos=from_pos,
            to_pos=target,
            combatants=self.combatants,
            reaction_used=self.reaction_used,
            is_disengaging=self.turn_resources.is_disengaging,
        )

        # Resolve opportunity attacks
        for reactor_id, reactor, melee_action in oa_attackers:
            oa_result = execute_opportunity_attack(
                reactor_id=reactor_id,
                reactor=reactor,
                target_id=combatant.creature_id,
                target=combatant,
                action=melee_action,
                grid=self.grid,
                reaction_used=self.reaction_used,
                combatants=self.combatants,
            )
            for oa_event in oa_result.events:
                self.log.add(oa_event)
            # OA damage may have broken concentration — clean up zones
            self._cleanup_orphaned_zones()

            # If the mover was knocked out, cancel the move
            if not combatant.creature.is_conscious:
                self._check_victory()
                return False

        success, event = self.movement.try_move(
            target, self.grid, combatant.creature.size,
            anchor_position=from_pos,
        )
        if success and event:
            event.message = f"{combatant.creature.name} " + event.message
            self.log.add(event)
            combatant.position = target

            # Check if any readied actions trigger on movement
            ready_events = check_ready_triggers(
                self, TriggerType.CREATURE_MOVES, combatant.creature_id
            )
            for re in ready_events:
                self.log.add(re)

            # Check zone entry damage (e.g., walking into Spirit Guardians)
            if self.active_zones:
                from arena.combat.zones import process_zone_entry
                zone_entry_events = process_zone_entry(
                    self.active_zones, combatant.creature_id,
                    self.combatants, self.grid,
                )
                for ze in zone_entry_events:
                    self.log.add(ze)
                # Zone entry damage may break concentration — clean up
                self._cleanup_orphaned_zones()
                # If knocked out by zone damage, stop moving
                if not combatant.creature.is_conscious:
                    self._check_victory()
                    return True

        return success

    def execute_standard_action(
        self, action_name: str, target_id: str | None = None
    ) -> CombatEvent | None:
        """Execute a built-in standard action (Dash, Disengage, Dodge, Help).

        Args:
            action_name: Name of the action ("dash", "disengage", "dodge", "help").
            target_id: Required for Help (the ally to help).

        Returns:
            A combat event, or None if invalid.
        """
        combatant = self.active_combatant
        if combatant is None:
            return None
        if not can_take_actions(combatant.creature):
            return None

        action_name_lower = action_name.lower()

        if action_name_lower == "dash":
            event = execute_dash(self)
        elif action_name_lower == "disengage":
            event = execute_disengage(self)
        elif action_name_lower == "dodge":
            event = execute_dodge(self)
        elif action_name_lower == "help":
            if target_id is None:
                return None
            event = execute_help(self, target_id)
        elif action_name_lower == "hide":
            event = execute_hide(self)
        elif action_name_lower == "action_surge":
            event = execute_action_surge(self)
        elif action_name_lower == "ready":
            # Ready requires additional parameters passed through kwargs
            # Use execute_ready_action() directly for full control
            return None
        else:
            return None

        if event:
            self.log.add(event)

        return event

    def execute_data_standard_action(self, action: Action) -> CombatEvent | None:
        """Execute a data Action that routes to built-in standard-action logic
        via ``Action.standard_effect`` — Cunning Action's bonus-action Dash/
        Disengage/Hide, Step of the Wind, Vanish.

        The action's OWN economy slot and resource cost govern: the standard
        logic runs with ``consume_action=False`` and this method marks the
        bonus/action slot and deducts the cost (1 ki for Step of the Wind).

        Returns:
            The combat event, or None if invalid/unaffordable.
        """
        from arena.combat.actions import check_resource_cost, deduct_resource_cost

        combatant = self.active_combatant
        if combatant is None or action.standard_effect is None:
            return None
        if not can_take_actions(combatant.creature):
            return None
        if not self.can_use_action_type(action.action_type):
            return None
        can_use, reason = check_resource_cost(combatant.creature, action)
        if not can_use:
            event = CombatEvent(
                event_type=CombatEventType.INFO,
                message=reason,
                source_id=combatant.creature_id,
            )
            self.log.add(event)
            return None

        effect = action.standard_effect.lower()
        if effect == "dash":
            event = execute_dash(self, consume_action=False)
        elif effect == "disengage":
            event = execute_disengage(self, consume_action=False)
        elif effect == "dodge":
            event = execute_dodge(self, consume_action=False)
        elif effect == "hide":
            event = execute_hide(self, consume_action=False)
        else:
            return None

        if event is not None:
            deduct_resource_cost(combatant.creature, action)
            self._mark_action_type_used(action)
            self.log.add(event)
        return event

    def execute_shove(
        self,
        target_id: str,
        shove_choice: str = "push",
    ) -> ActionResult | None:
        """Execute a shove action (contested Athletics check).

        Every creature can shove as a standard action. On success,
        the target is either pushed 5ft or knocked prone.

        Args:
            target_id: Creature to shove.
            shove_choice: "push" (5ft away) or "prone" (knock prone).

        Returns:
            ActionResult with events, or None if invalid.
        """
        from arena.combat.forced_movement import resolve_shove_contest, resolve_forced_movement
        from arena.combat.actions import ActionResult
        from arena.grid.footprint import min_distance_between

        combatant = self.active_combatant
        if combatant is None or self.grid is None:
            return None
        if not can_take_actions(combatant.creature):
            return None

        # Shove uses the action
        if self.turn_resources.has_used_action:
            return None

        target_c = self.combatants.get(target_id)
        if target_c is None or target_c.position is None:
            return None
        if combatant.position is None:
            return None

        # Range check: shove is melee (5ft / adjacent)
        dist = min_distance_between(
            combatant.position, combatant.creature.size,
            target_c.position, target_c.creature.size,
        )
        if dist > 1:
            return None

        events: list[CombatEvent] = []

        # Log the shove attempt
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{combatant.creature.name} attempts to shove {target_c.creature.name}.",
            source_id=combatant.creature_id,
            target_id=target_id,
            details={"is_effect_use": True, "action_name": "Shove"},
        ))

        # Contested check
        success, contest_events = resolve_shove_contest(
            combatant.creature, combatant.creature_id,
            target_c.creature, target_id,
        )
        events.extend(contest_events)

        if success:
            if shove_choice == "prone":
                from arena.combat.conditions import apply_condition
                from arena.models.conditions import Condition
                cond_event = apply_condition(
                    target_c.creature, target_id, Condition.PRONE,
                    source=combatant.creature.name,
                )
                if cond_event:
                    events.append(cond_event)
            else:
                # Push 5ft away
                fm_result = resolve_forced_movement(
                    source_id=combatant.creature_id,
                    source_pos=combatant.position,
                    target_id=target_id,
                    target_pos=target_c.position,
                    movement_type="push",
                    distance_feet=5,
                    grid=self.grid,
                    combatants=self.combatants,
                    target_creature=target_c.creature,
                )
                target_c.position = fm_result.destination_hex
                events.extend(fm_result.events)

                # Zone entry at new position
                if self.active_zones and fm_result.distance_moved > 0:
                    from arena.combat.zones import process_zone_entry
                    zone_events = process_zone_entry(
                        self.active_zones, target_id,
                        self.combatants, self.grid,
                    )
                    events.extend(zone_events)

        # Mark action as used
        self.turn_resources.has_used_action = True

        for e in events:
            self.log.add(e)

        self._check_victory()

        return ActionResult(events=events, success=success)

    def execute_ready_action(
        self,
        action: Action,
        trigger_type: TriggerType,
        trigger_target_id: str | None = None,
        description: str = "",
    ) -> CombatEvent | None:
        """Ready an action with a trigger.

        Uses the action slot. The readied action will fire as a reaction
        when the trigger conditions are met.

        Args:
            action: The action to ready.
            trigger_type: Type of trigger event.
            trigger_target_id: Optional specific creature to watch.
            description: Human-readable trigger description.

        Returns:
            A combat event, or None if invalid.
        """
        combatant = self.active_combatant
        if combatant is None:
            return None
        if not can_take_actions(combatant.creature):
            return None

        event = set_ready_action(
            self, action, trigger_type, trigger_target_id, description
        )
        if event:
            self.log.add(event)
        return event

    # ------------------------------------------------------------------
    # Dead Creature Helpers
    # ------------------------------------------------------------------

    def _get_dead_creature_ids(self) -> set[str]:
        """Return IDs of unconscious/dead creatures on the grid.

        Per 5e, a dead creature's space is difficult terrain (passable,
        costs double movement) rather than impassable.
        """
        return {
            cid
            for cid, c in self.combatants.items()
            if not c.creature.is_conscious
        }

    # ------------------------------------------------------------------
    # Summoning
    # ------------------------------------------------------------------

    def execute_summon(self, target_hex: HexCoord) -> ActionResult | None:
        """Summon a creature from JSON and place it on the grid.

        The selected action must have ``summon_creature`` set (relative path
        to a creature JSON file under the data directory).  The summoned
        creature is placed at *target_hex*, added to the combatants dict,
        and inserted into initiative right after the summoner.
        """
        import copy
        from pathlib import Path
        from arena.combat.actions import check_resource_cost, deduct_resource_cost
        from arena.models.encounter import CombatantEntry

        combatant = self.active_combatant
        if combatant is None or self.grid is None:
            return None

        action = self.selected_action
        if action is None or not action.summon_creature:
            return None

        # Validate target hex is empty and on the grid
        # (Wild Shape skips this — summoner will vacate the hex first)
        cell = self.grid.get_cell(target_hex)
        if cell is None:
            return None
        if not action.is_wild_shape and cell.occupant_id is not None:
            events = [CombatEvent(
                event_type=CombatEventType.INFO,
                message="Cannot summon there — hex is occupied!",
                source_id=combatant.creature_id,
            )]
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)

        # Validate range (Wild Shape is self-targeted, skip range check)
        from arena.grid.footprint import min_distance_between
        if not action.is_wild_shape:
            dist_feet = min_distance_between(
                combatant.position, combatant.creature.size,
                target_hex, 1,
            ) * 5
        else:
            dist_feet = 0
        if dist_feet > action.range:
            events = [CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"Target hex is out of range for {action.name}!",
                source_id=combatant.creature_id,
            )]
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)

        # Resource cost
        can_use, reason = check_resource_cost(combatant.creature, action)
        if not can_use:
            events = [CombatEvent(
                event_type=CombatEventType.INFO,
                message=reason,
                source_id=combatant.creature_id,
            )]
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)
        deduct_resource_cost(combatant.creature, action)

        events: list[CombatEvent] = []

        # Wild Shape: store original creature before replacing
        if action.is_wild_shape:
            self.stored_creatures[combatant.creature_id] = (
                copy.deepcopy(combatant.creature),
                combatant.position,
            )

        # Load creature from JSON
        data_dir = Path("data")
        try:
            entry = CombatantEntry(
                creature_id=action.summon_creature,
                team=combatant.team,
            )
            creature = self._load_creature(entry, data_dir)
        except Exception as e:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"Failed to summon: {e}",
                source_id=combatant.creature_id,
            ))
            for ev in events:
                self.log.add(ev)
            return ActionResult(events=events, success=False)

        # Generate unique ID
        summon_id = self._make_unique_id(creature.name)
        creature.is_player_controlled = combatant.creature.is_player_controlled

        # Wild Shape: remove summoner from grid first (they transform
        # into the new creature), then place at the summoner's position.
        place_hex = target_hex
        if action.is_wild_shape and combatant.position is not None:
            place_hex = combatant.position
            self.grid.remove_creature(
                combatant.position, combatant.creature.size,
            )
            combatant.position = None

        # Create Combatant and place on grid
        new_combatant = Combatant(
            creature_id=summon_id,
            creature=creature,
            team=combatant.team,
        )
        if self.grid.place_creature(place_hex, summon_id, creature.size):
            new_combatant.position = place_hex
        self.combatants[summon_id] = new_combatant

        # Track summoner-summon link
        self.summon_links[summon_id] = combatant.creature_id

        # Insert into initiative right after the summoner
        summoner_entry = self.initiative.current_entry
        if summoner_entry:
            from arena.combat.initiative import InitiativeEntry
            summon_entry = InitiativeEntry(
                creature_id=summon_id,
                name=creature.name,
                initiative_roll=summoner_entry.initiative_roll,
                dexterity=creature.ability_scores.get_modifier("dexterity"),
                is_player_controlled=creature.is_player_controlled,
                tiebreaker=summoner_entry.tiebreaker - 0.0001,
            )
            self.initiative.add_entry(summon_entry)

        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"{combatant.creature.name} transforms into {creature.name}!"
                if action.is_wild_shape
                else f"{combatant.creature.name} summons {creature.name}!"
            ),
            source_id=combatant.creature_id,
            details={
                "action_name": action.name,
                "animation": action.animation,
                "is_effect_use": True,
                "summon_hex": (place_hex.q, place_hex.r),
                "is_wild_shape": action.is_wild_shape,
            },
        ))

        # Concentration linking (summon disappears when concentration ends)
        if action.requires_concentration:
            self.concentration_summons.add(summon_id)
            from arena.combat.concentration import start_concentrating
            conc_events = start_concentrating(
                combatant.creature, combatant.creature_id,
                action.name, combatants=self.combatants,
            )
            events.extend(conc_events)

        self._mark_action_type_used(action)
        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        for e in events:
            self.log.add(e)

        return ActionResult(events=events, success=True)

    def _remove_summon(self, summon_id: str) -> None:
        """Remove a summoned creature from combat entirely."""
        combatant = self.combatants.get(summon_id)
        if combatant is None:
            return

        # Remove from grid
        if self.grid and combatant.position:
            self.grid.remove_creature(combatant.position, combatant.creature.size)

        # Remove from initiative
        self.initiative.remove_entry(summon_id)

        # Remove from combatants
        del self.combatants[summon_id]

        # Clean up links
        self.summon_links.pop(summon_id, None)
        self.concentration_summons.discard(summon_id)

        self.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{combatant.creature.name} disappears!",
            source_id=summon_id,
        ))

    def _check_summon_death(self, creature_id: str) -> None:
        """Handle a summoned creature dropping to 0 HP.

        Wild Shape: restore the original creature at the bear's position.
        Regular summon: just remove from combat.
        """
        if creature_id not in self.summon_links:
            return

        summoner_id = self.summon_links[creature_id]

        # Wild Shape revert
        if summoner_id in self.stored_creatures:
            original_creature, _original_pos = self.stored_creatures.pop(summoner_id)
            summoner = self.combatants.get(summoner_id)
            bear = self.combatants.get(creature_id)

            if summoner:
                # Place the original creature at the bear form's position
                bear_pos = bear.position if bear else None
                summoner.creature = original_creature

                if bear_pos and self.grid:
                    # Remove bear from grid first (done by _remove_summon),
                    # then place original creature at that position.
                    # We need to grab the position before _remove_summon
                    # clears it.
                    self.grid.remove_creature(
                        bear_pos, bear.creature.size,
                    )
                    bear.position = None  # prevent _remove_summon double-remove
                    if self.grid.place_creature(
                        bear_pos, summoner_id, original_creature.size,
                    ):
                        summoner.position = bear_pos

                self.log.add(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{summoner.creature.name} reverts to their original form!",
                    source_id=summoner_id,
                ))
            self._remove_summon(creature_id)
        else:
            # Regular summon: just remove
            self._remove_summon(creature_id)

    def _cleanup_concentration_summons(self) -> None:
        """Remove concentration-linked summons whose summoner lost concentration.

        Only summons in ``concentration_summons`` are checked — non-concentration
        summons (e.g. Find Familiar) persist until killed or dismissed.
        """
        from arena.models.conditions import Condition
        from arena.combat.conditions import has_condition

        to_remove = []
        for summon_id in list(self.concentration_summons):
            if summon_id not in self.summon_links:
                # Already removed
                self.concentration_summons.discard(summon_id)
                continue
            summoner_id = self.summon_links[summon_id]
            summoner = self.combatants.get(summoner_id)
            if summoner is None or not has_condition(summoner.creature, Condition.CONCENTRATING):
                to_remove.append(summon_id)

        for summon_id in to_remove:
            self.concentration_summons.discard(summon_id)
            self._remove_summon(summon_id)

    # ------------------------------------------------------------------
    # Teleportation
    # ------------------------------------------------------------------

    def execute_teleport(
        self, target_hex: HexCoord, passenger_id: str | None = None,
    ) -> ActionResult | None:
        """Teleport the active combatant to *target_hex*.

        Key differences from :meth:`try_move`:
        - No pathfinding required (direct placement).
        - No opportunity attacks triggered.
        - No movement cost deducted from :class:`MovementTracker`.

        If the selected action has ``teleport_passenger`` set and
        *passenger_id* is provided, the ally also teleports to an
        adjacent hex at the destination.

        If ``teleport_origin_effect`` is set, enemies near the caster's
        **origin** position must make a saving throw or take damage.

        Args:
            target_hex: Destination hex for the caster.
            passenger_id: Optional ally creature_id to bring along.

        Returns:
            :class:`ActionResult`, or ``None`` if the teleport is invalid.
        """
        from arena.combat.actions import (
            check_resource_cost, deduct_resource_cost, resolve_saving_throw,
        )
        from arena.combat.damage import apply_damage
        from arena.grid.footprint import min_distance_between

        combatant = self.active_combatant
        if combatant is None or self.grid is None:
            return None

        action = self.selected_action
        if action is None or action.teleport_range is None:
            return None

        origin = combatant.position
        if origin is None:
            return None

        # ── Validate destination ─────────────────────────────────────
        cell = self.grid.get_cell(target_hex)
        if cell is None or not self.grid.is_passable(target_hex):
            return None

        if cell.occupant_id is not None:
            events = [CombatEvent(
                event_type=CombatEventType.INFO,
                message="Cannot teleport there — hex is occupied!",
                source_id=combatant.creature_id,
            )]
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)

        # Range check
        dist_feet = min_distance_between(
            origin, combatant.creature.size, target_hex, 1,
        ) * 5
        if dist_feet > action.teleport_range:
            events = [CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"Target hex is out of teleport range for {action.name}!",
                source_id=combatant.creature_id,
            )]
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)

        # ── Resource cost ────────────────────────────────────────────
        can_use, reason = check_resource_cost(combatant.creature, action)
        if not can_use:
            events = [CombatEvent(
                event_type=CombatEventType.INFO,
                message=reason,
                source_id=combatant.creature_id,
            )]
            for e in events:
                self.log.add(e)
            return ActionResult(events=events, success=False)
        deduct_resource_cost(combatant.creature, action)

        events: list[CombatEvent] = []

        # ── Move caster ─────────────────────────────────────────────
        self.grid.remove_creature(origin, combatant.creature.size)
        self.grid.place_creature(target_hex, combatant.creature_id, combatant.creature.size)
        combatant.position = target_hex

        events.append(CombatEvent(
            event_type=CombatEventType.TELEPORT,
            message=f"{combatant.creature.name} teleports via {action.name}!",
            source_id=combatant.creature_id,
            details={
                "action_name": action.name,
                "animation": action.animation,
                "teleport": True,
                "from_hex": (origin.q, origin.r),
                "to_hex": (target_hex.q, target_hex.r),
            },
        ))

        # ── Passenger (Dimension Door) ──────────────────────────────
        if action.teleport_passenger and passenger_id:
            passenger = self.combatants.get(passenger_id)
            if passenger and passenger.position:
                passenger_origin = passenger.position
                dest = self._find_passenger_destination(target_hex)
                if dest:
                    self.grid.remove_creature(
                        passenger_origin, passenger.creature.size,
                    )
                    self.grid.place_creature(
                        dest, passenger_id, passenger.creature.size,
                    )
                    passenger.position = dest
                    events.append(CombatEvent(
                        event_type=CombatEventType.TELEPORT,
                        message=(
                            f"{passenger.creature.name} teleports along with "
                            f"{combatant.creature.name}!"
                        ),
                        source_id=combatant.creature_id,
                        target_id=passenger_id,
                        details={
                            "teleport": True,
                            "from_hex": (passenger_origin.q, passenger_origin.r),
                            "to_hex": (dest.q, dest.r),
                            "is_passenger": True,
                        },
                    ))

        # ── Origin damage (Thunder Step) ─────────────────────────────
        if action.teleport_origin_effect and action.saving_throw:
            from arena.util.dice import roll_expression

            save = action.saving_throw
            origin_radius = action.area_size or 10  # feet

            # Find enemies within radius of the *origin* position
            for cid, c in list(self.combatants.items()):
                if cid == combatant.creature_id:
                    continue
                if c.team == combatant.team:
                    continue
                if c.position is None or not c.creature.is_conscious:
                    continue

                dist = min_distance_between(
                    origin, 1, c.position, c.creature.size,
                ) * 5
                if dist > origin_radius:
                    continue

                # Saving throw
                success, save_event = resolve_saving_throw(
                    c.creature, cid, save.ability, save.dc or 10,
                )
                events.append(save_event)

                # Roll damage
                total, _rolls = roll_expression(action.teleport_origin_effect)
                if success and save.damage_on_success == "half":
                    total = total // 2
                elif success and save.damage_on_success == "none":
                    total = 0

                if total > 0:
                    dmg_type = action.teleport_origin_damage_type or "thunder"
                    # Teleport-origin bursts are spell damage → magical
                    from arena.combat.damage import DamagePacket
                    dmg_event, dp_events = apply_damage(
                        c.creature,
                        [DamagePacket(amount=total, dtype=dmg_type,
                                      source=action.name, tags={"magical"})],
                        creature_id=cid,
                    )
                    dmg_event.source_id = combatant.creature_id
                    dmg_event.target_id = cid
                    events.append(dmg_event)
                    events.extend(dp_events)

                    if not c.creature.is_conscious:
                        events.append(CombatEvent(
                            event_type=CombatEventType.CREATURE_DOWNED,
                            message=f"{c.creature.name} falls unconscious!",
                            source_id=combatant.creature_id,
                            target_id=cid,
                        ))

            # Visual effect for origin blast
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message="",
                details={
                    "aoe_center_hex": (origin.q, origin.r),
                    "area_size": origin_radius,
                    "aoe_damage_type": action.teleport_origin_damage_type or "thunder",
                },
            ))

        # ── Concentration ────────────────────────────────────────────
        if action.requires_concentration:
            from arena.combat.concentration import start_concentrating
            conc_events = start_concentrating(
                combatant.creature, combatant.creature_id,
                action.name, combatants=self.combatants,
            )
            events.extend(conc_events)

        # ── Zone entry at destination ────────────────────────────────
        if self.active_zones:
            from arena.combat.zones import process_zone_entry
            zone_events = process_zone_entry(
                self.active_zones, combatant.creature_id,
                self.combatants, self.grid,
            )
            for ze in zone_events:
                events.append(ze)
            self._cleanup_orphaned_zones()

        # If passenger was moved, check zone entry for them too
        if action.teleport_passenger and passenger_id:
            passenger = self.combatants.get(passenger_id)
            if passenger and passenger.position and self.active_zones:
                from arena.combat.zones import process_zone_entry
                pz_events = process_zone_entry(
                    self.active_zones, passenger_id,
                    self.combatants, self.grid,
                )
                for pze in pz_events:
                    events.append(pze)
                self._cleanup_orphaned_zones()

        # ── Finalize ─────────────────────────────────────────────────
        self._mark_action_type_used(action)
        self.selected_action = None
        self._cast_level = None
        self.turn_phase = TurnPhase.AWAITING_ACTION

        for e in events:
            self.log.add(e)

        self._check_victory()
        return ActionResult(events=events, success=True)

    def _find_passenger_candidates(
        self, caster_id: str, caster_pos: HexCoord,
    ) -> list[str]:
        """Return creature IDs of allies within 5 ft of the caster."""
        from arena.grid.footprint import min_distance_between

        candidates: list[str] = []
        caster = self.combatants.get(caster_id)
        if caster is None:
            return candidates

        for cid, c in self.combatants.items():
            if cid == caster_id:
                continue
            if c.team != caster.team:
                continue
            if c.position is None or not c.creature.is_conscious:
                continue
            dist = min_distance_between(
                caster_pos, caster.creature.size,
                c.position, c.creature.size,
            ) * 5
            if dist <= 5:
                candidates.append(cid)

        return candidates

    def _find_passenger_destination(
        self, destination: HexCoord,
    ) -> HexCoord | None:
        """Find an unoccupied passable hex adjacent to *destination*."""
        for neighbor in destination.neighbors():
            if not self.grid.is_valid(neighbor):
                continue
            if not self.grid.is_passable(neighbor):
                continue
            cell = self.grid.get_cell(neighbor)
            if cell and cell.occupant_id is None:
                return neighbor
        return None

    # ------------------------------------------------------------------
    # Zone Movement
    # ------------------------------------------------------------------

    def move_zone(self, target_hex: HexCoord, move_cost: str) -> ActionResult | None:
        """Move the active combatant's zone to a new hex.

        Per 5e rules, moving a zone onto a creature does NOT count as
        the creature "entering" the zone.  Damage is applied when the
        creature starts its turn inside the zone (handled by
        ``process_zone_start_of_turn``) or voluntarily moves into the
        zone on its own turn (handled by ``process_zone_entry``).

        Args:
            target_hex: New center for the zone.
            move_cost: ``"action"`` or ``"bonus_action"`` — economy slot to spend.

        Returns:
            ActionResult, or None if invalid.
        """
        combatant = self.active_combatant
        if combatant is None or self.grid is None:
            return None

        # Find the caster's active zone
        caster_zones = [z for z in self.active_zones if z.caster_id == combatant.creature_id]
        if not caster_zones:
            return None
        zone = caster_zones[0]

        # Validate action economy
        if move_cost == "bonus_action":
            if self.turn_resources.has_used_bonus_action:
                return None
        else:
            if self.turn_resources.has_used_action:
                return None

        # Validate range — target hex must be within spell range of caster
        from arena.grid.footprint import min_distance_between
        dist_feet = min_distance_between(
            combatant.position, combatant.creature.size,
            target_hex, 1,
        ) * 5
        # Use the original spell's range — find it from the creature's actions
        max_range = zone.radius_feet * 2  # Generous fallback
        for a in combatant.creature.actions:
            if a.zone_move_cost and a.name.lower().replace(" ", "_") in zone.zone_id:
                max_range = a.range
                break
        if dist_feet > max_range:
            return None

        events: list[CombatEvent] = []

        # Move the zone
        zone.follows_caster = False
        zone.center = target_hex

        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{combatant.creature.name} moves {zone.name}!",
            source_id=combatant.creature_id,
        ))

        # Deduct action economy
        if move_cost == "bonus_action":
            self.turn_resources.has_used_bonus_action = True
        else:
            self.turn_resources.has_used_action = True

        for e in events:
            self.log.add(e)

        self._cleanup_orphaned_zones()

        return ActionResult(events=events, success=True)

    def _apply_pending_forced_movement(
        self,
        events: list[CombatEvent],
        source_id: str,
        source_pos: HexCoord,
    ) -> list[CombatEvent]:
        """Scan events for pending forced movement markers and execute them.

        Called by execute_attack(), complete_attack(), and execute_effect()
        after resolution returns.  Processes each marker by calling
        resolve_forced_movement() and returns additional events.
        """
        from arena.combat.forced_movement import resolve_forced_movement
        from arena.combat.zones import process_zone_entry

        new_events: list[CombatEvent] = []
        markers_to_remove: list[CombatEvent] = []

        for event in events:
            if event is None or not event.details.get("pending_forced_movement"):
                continue

            markers_to_remove.append(event)

            target_id = event.details["fm_target_id"]
            target_c = self.combatants.get(target_id)
            if target_c is None or target_c.position is None:
                continue
            if not target_c.creature.is_conscious:
                continue

            result = resolve_forced_movement(
                source_id=source_id,
                source_pos=source_pos,
                target_id=target_id,
                target_pos=target_c.position,
                movement_type=event.details["fm_type"],
                distance_feet=event.details["fm_distance"],
                grid=self.grid,
                combatants=self.combatants,
                target_creature=target_c.creature,
                knock_prone=event.details.get("fm_prone", False),
            )

            # Update combatant position
            target_c.position = result.destination_hex
            new_events.extend(result.events)

            # Zone entry at new position
            if self.active_zones and result.distance_moved > 0:
                zone_events = process_zone_entry(
                    self.active_zones, target_id,
                    self.combatants, self.grid,
                )
                new_events.extend(zone_events)

        # Remove marker events from the original list
        for marker in markers_to_remove:
            events.remove(marker)

        return new_events

    def _cleanup_orphaned_zones(self) -> None:
        """Remove zones whose caster is no longer concentrating.

        Called after any action that could cause concentration to drop
        (attacks dealing damage, new concentration spells, Drop Concentration).
        Also cleans up concentration-linked summons.
        """
        # Clean up concentration-linked summons
        if self.summon_links:
            self._cleanup_concentration_summons()

        if self.active_zones:
            from arena.models.conditions import Condition
            from arena.combat.conditions import has_condition
            to_remove = []
            for zone in self.active_zones:
                if not zone.concentration_linked:
                    continue
                caster = self.combatants.get(zone.caster_id)
                if caster is None or not has_condition(caster.creature, Condition.CONCENTRATING):
                    to_remove.append(zone)
            for zone in to_remove:
                self.active_zones.remove(zone)
                self.log.add(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{zone.name} zone fades away.",
                    source_id=zone.caster_id,
                ))

        # Clean up concentration-linked terrain modifications
        if self.active_terrain_mods:
            from arena.combat.terrain_effects import cleanup_terrain_modifications
            self.active_terrain_mods, terrain_events = cleanup_terrain_modifications(
                self.active_terrain_mods, self.combatants, self.grid,
            )
            for e in terrain_events:
                self.log.add(e)

        # Clean up concentration-linked walls
        if self.active_walls:
            from arena.models.conditions import Condition as _WallCond
            from arena.combat.conditions import has_condition as _wall_has_cond
            walls_to_remove = []
            for wall in self.active_walls:
                if not wall.concentration_linked:
                    continue
                caster = self.combatants.get(wall.source_id)
                if caster is None or not _wall_has_cond(caster.creature, _WallCond.CONCENTRATING):
                    walls_to_remove.append(wall)
            for wall in walls_to_remove:
                self.active_walls.remove(wall)
                self.log.add(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=f"{wall.name} dissipates.",
                    source_id=wall.source_id,
                ))

    # ------------------------------------------------------------------
    # Recurring Actions
    # ------------------------------------------------------------------

    def _maybe_create_recurring_action(
        self, action: Action, source_id: str, target_id: str,
    ) -> None:
        """Create and register a recurring action if the spell supports it.

        Also links concentration-based recurring actions so they are
        removed when concentration ends.
        """
        if not action.recurring_action_type:
            return

        # Remove any existing recurring action for this creature first
        self.active_recurring_actions = [
            r for r in self.active_recurring_actions
            if r.source_id != source_id
        ]

        recurring = create_recurring_action(action, target_id)
        if recurring is None:
            return

        # Stamp the source creature ID onto the recurring action
        recurring.source_id = source_id

        self.active_recurring_actions.append(recurring)
        self.log.add(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{action.name} can be used again on subsequent turns.",
            source_id=source_id,
        ))

    def get_recurring_action_for(self, creature_id: str) -> ActiveRecurringAction | None:
        """Return the active recurring action for a creature, if any."""
        for r in self.active_recurring_actions:
            if r.source_id == creature_id:
                return r
        return None

    def execute_recurring_action(self, target_id: str) -> ActionResult | None:
        """Execute a creature's recurring action against a target.

        For auto-hit recurring actions (Witch Bolt), applies damage directly.
        For save-based recurring actions (Call Lightning, Sunbeam), resolves
        a saving throw against the target.

        Args:
            target_id: creature_id of the target.

        Returns:
            ActionResult with events, or None if invalid.
        """
        from arena.combat.actions import resolve_saving_throw
        from arena.combat.damage import apply_damage
        from arena.util.dice import roll_expression

        combatant = self.active_combatant
        if combatant is None or self.grid is None:
            return None

        recurring = self.get_recurring_action_for(combatant.creature_id)
        if recurring is None:
            return None

        # Check action economy
        action_available = not self.turn_resources.has_used_action
        bonus_available = not self.turn_resources.has_used_bonus_action
        if not can_use_recurring_action(recurring, action_available, bonus_available):
            return None

        target_combatant = self.combatants.get(target_id)
        if target_combatant is None:
            return None

        events: list[CombatEvent] = []
        damage_dice, damage_type = get_recurring_damage(recurring)

        if recurring.auto_hit:
            # Auto-hit path (Witch Bolt): just roll and apply damage
            if damage_dice and damage_type:
                total, rolls = roll_expression(damage_dice)
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    source_id=combatant.creature_id,
                    target_id=target_id,
                    message=(
                        f"{combatant.creature.name} uses {recurring.action_name} "
                        f"(recurring) on {target_combatant.creature.name} — "
                        f"auto-hit for {damage_dice} {damage_type} damage."
                    ),
                ))
                # Recurring spell damage (Witch Bolt) is magical
                from arena.combat.damage import DamagePacket
                dmg_event, extra_events = apply_damage(
                    target_combatant.creature,
                    [DamagePacket(amount=total, dtype=damage_type,
                                  source=recurring.action_name,
                                  tags={"magical"})],
                    creature_id=target_id,
                )
                events.append(dmg_event)
                events.extend(extra_events)

                # Concentration check on the target
                if total > 0:
                    from arena.combat.concentration import check_concentration
                    conc_events = check_concentration(
                        target_combatant.creature, target_id, total, self.combatants,
                    )
                    events.extend(conc_events)

            success = True
        else:
            # Save-based path (Call Lightning, Sunbeam)
            source_action = recurring.source_action
            if source_action.saving_throw and damage_dice and damage_type:
                save_info = source_action.saving_throw
                dc = save_info.dc or 10

                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    source_id=combatant.creature_id,
                    target_id=target_id,
                    message=(
                        f"{combatant.creature.name} uses {recurring.action_name} "
                        f"(recurring) on {target_combatant.creature.name}."
                    ),
                ))

                save_success, save_event = resolve_saving_throw(
                    target_combatant.creature, target_id,
                    save_info.ability, dc,
                )
                events.append(save_event)

                total, rolls = roll_expression(damage_dice)
                if save_success and save_info.damage_on_success == "half":
                    total = total // 2
                elif save_success and save_info.damage_on_success == "none":
                    total = 0

                if total > 0:
                    # Recurring spell damage (Call Lightning, Sunbeam) is magical
                    from arena.combat.damage import DamagePacket
                    dmg_event, extra_events = apply_damage(
                        target_combatant.creature,
                        [DamagePacket(amount=total, dtype=damage_type,
                                      source=recurring.action_name,
                                      tags={"magical"})],
                        creature_id=target_id,
                    )
                    events.append(dmg_event)
                    events.extend(extra_events)

                    from arena.combat.concentration import check_concentration
                    conc_events = check_concentration(
                        target_combatant.creature, target_id, total, self.combatants,
                    )
                    events.extend(conc_events)

                success = True
            else:
                success = False

        if success:
            # Mark action economy slot used
            if recurring.action_type == "action":
                self.turn_resources.has_used_action = True
            elif recurring.action_type == "bonus_action":
                self.turn_resources.has_used_bonus_action = True

        for event in events:
            self.log.add(event)

        # Clean up orphaned zones/recurring after damage
        self._cleanup_orphaned_zones()
        self._cleanup_orphaned_recurring_actions()
        self._check_victory()

        return ActionResult(events=events, success=success)

    def _tick_recurring_actions(self, creature_id: str) -> None:
        """Tick duration for recurring actions owned by this creature.

        Called at the start of the creature's turn. Removes expired ones.
        """
        to_remove = []
        for recurring in self.active_recurring_actions:
            if recurring.source_id != creature_id:
                continue
            if recurring.remaining_rounds is not None:
                recurring.remaining_rounds -= 1
                if recurring.remaining_rounds <= 0:
                    to_remove.append(recurring)

        for recurring in to_remove:
            self.active_recurring_actions.remove(recurring)
            self.log.add(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{recurring.action_name} recurring effect has expired.",
                source_id=recurring.source_id,
            ))

    def _cleanup_orphaned_recurring_actions(self) -> None:
        """Remove recurring actions whose caster lost concentration.

        Called after any action that could cause concentration to drop.
        """
        if not self.active_recurring_actions:
            return

        from arena.models.conditions import Condition
        from arena.combat.conditions import has_condition

        to_remove = []
        for recurring in self.active_recurring_actions:
            if not recurring.linked_to_concentration:
                continue
            caster = self.combatants.get(recurring.source_id)
            if caster is None or not has_condition(caster.creature, Condition.CONCENTRATING):
                to_remove.append(recurring)

        for recurring in to_remove:
            self.active_recurring_actions.remove(recurring)
            self.log.add(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{recurring.action_name} recurring effect ends (concentration lost).",
                source_id=recurring.source_id,
            ))

    def _check_victory(self) -> bool:
        """Check if all creatures on one side are defeated.

        A player character at 0 HP is considered "still alive" as long as
        they haven't accumulated 3 death save failures (they might stabilize
        or be healed). Monsters/enemies are defeated when at 0 HP.

        Returns:
            True if combat has ended.
        """
        # Clean up downed summons before checking victory
        downed_summons = [
            sid for sid in list(self.summon_links)
            if sid in self.combatants and not self.combatants[sid].creature.is_conscious
        ]
        for sid in downed_summons:
            self._check_summon_death(sid)

        players_alive = any(
            self._is_still_fighting(c)
            for c in self.combatants.values()
            if c.team == "player"
        )
        enemies_alive = any(
            c.creature.is_conscious
            for c in self.combatants.values()
            if c.team == "enemy"
        )

        if not enemies_alive:
            self.winner = "player"
            self.state = CombatState.COMBAT_ENDED
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.COMBAT_END,
                    message="Victory! All enemies have been defeated!",
                )
            )
            return True
        elif not players_alive:
            self.winner = "enemy"
            self.state = CombatState.COMBAT_ENDED
            self.log.add(
                CombatEvent(
                    event_type=CombatEventType.COMBAT_END,
                    message="Defeat! All player characters have fallen!",
                )
            )
            return True

        return False

    def _is_still_fighting(self, combatant: Combatant) -> bool:
        """Check if a combatant is still in the fight.

        A conscious creature is always fighting. An unconscious PC (0 HP)
        is still fighting as long as they haven't accumulated 3 death save
        failures — they could stabilize or be healed. Monsters at 0 HP
        are always defeated.

        Exception: in solo handoff play (``solo_defeat_when_downed``) a downed PC
        has no allies to revive them, so unconscious counts as out of the fight —
        ending combat promptly instead of stalling in a death-save vacuum.
        """
        if combatant.creature.is_conscious:
            return True
        if self.solo_defeat_when_downed:
            return False
        # Check if this is a PC who is dying but not yet dead
        failures = getattr(combatant.creature, "death_save_failures", 3)
        return failures < 3

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_creature(self, creature_id: str) -> Combatant | None:
        """Get a combatant by ID."""
        return self.combatants.get(creature_id)

    def reset(self) -> None:
        """Reset for a new combat."""
        self.state = CombatState.NOT_STARTED
        self.turn_phase = TurnPhase.START_OF_TURN
        self.initiative.reset()
        self.combatants.clear()
        self.log.clear()
        self.grid = None
        self.winner = None
        self.turn_resources = TurnResources()
        self.reaction_used = {}
        self._pending_damage_reduction = None
        self.readied_actions = {}
        self.selected_action = None
        self._cast_level = None
        self.legendary_points = {}
        self._legendary_queue = []
        self._legendary_actor_id = None
