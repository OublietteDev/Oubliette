"""Wall spell mechanics — barrier creation, damage, and properties.

Wall of Fire, Wall of Force, Wall of Stone, etc.
Walls are placed on the hex grid as a series of hexes forming a line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.grid.coordinates import HexCoord
from arena.models.actions import Action


@dataclass
class WallPanel:
    """A single 10ft (2-hex) panel of a wall."""

    hexes: list[HexCoord] = field(default_factory=list)
    max_hp: int | None = None  # None = indestructible
    current_hp: int | None = None

    @property
    def is_destroyed(self) -> bool:
        if self.max_hp is None:
            return False
        return (self.current_hp or 0) <= 0


@dataclass
class ActiveWall:
    """A wall spell currently active on the battlefield."""

    name: str  # Action name (e.g., "Wall of Fire")
    source_id: str  # Creature ID of the caster
    panels: list[WallPanel] = field(default_factory=list)
    blocks_movement: bool = True
    blocks_los: bool = False
    damage_on_enter: str | None = None  # Dice expression
    damage_type: str | None = None
    damage_side: str | None = None  # "one_side" or None
    damage_side_hexes: set[HexCoord] = field(default_factory=set)
    concentration_linked: bool = False  # Removed when concentration ends
    occupied_hexes: set[HexCoord] = field(default_factory=set)

    def get_wall_hexes(self) -> set[HexCoord]:
        """Get all hexes occupied by non-destroyed panels."""
        hexes: set[HexCoord] = set()
        for panel in self.panels:
            if not panel.is_destroyed:
                hexes.update(panel.hexes)
        return hexes

    def is_blocking_hex(self, hex_coord: HexCoord) -> bool:
        """Check if a hex is blocked by this wall (for movement)."""
        if not self.blocks_movement:
            return False
        return hex_coord in self.get_wall_hexes()

    def is_blocking_los_hex(self, hex_coord: HexCoord) -> bool:
        """Check if a hex blocks line of sight."""
        if not self.blocks_los:
            return False
        return hex_coord in self.get_wall_hexes()

    def damage_panel(self, panel_index: int, damage: int) -> bool:
        """Apply damage to a specific panel. Returns True if panel is destroyed."""
        if panel_index >= len(self.panels):
            return False
        panel = self.panels[panel_index]
        if panel.max_hp is None:
            return False  # Indestructible
        panel.current_hp = max(0, (panel.current_hp or 0) - damage)
        return panel.is_destroyed


def create_wall(
    action: Action,
    caster_id: str,
    wall_hexes: list[HexCoord],
    damage_side_hexes: set[HexCoord] | None = None,
) -> ActiveWall | None:
    """Create an ActiveWall from an Action with wall properties.

    Args:
        action: The wall spell action.
        caster_id: ID of the casting creature.
        wall_hexes: List of hex coordinates forming the wall path.
        damage_side_hexes: Hexes on the damage side (for Wall of Fire).

    Returns:
        An ActiveWall instance, or None if the action isn't a wall spell.
    """
    if not action.is_wall:
        return None

    # Create panels (every 2 hexes = one 10ft panel)
    panels: list[WallPanel] = []
    panel_hexes: list[HexCoord] = []
    for i, hex_coord in enumerate(wall_hexes):
        panel_hexes.append(hex_coord)
        if len(panel_hexes) == 2 or i == len(wall_hexes) - 1:
            panel = WallPanel(
                hexes=list(panel_hexes),
                max_hp=action.wall_hp_per_panel,
                current_hp=action.wall_hp_per_panel,
            )
            panels.append(panel)
            panel_hexes = []

    return ActiveWall(
        name=action.name,
        source_id=caster_id,
        panels=panels,
        blocks_movement=action.wall_blocks_movement,
        blocks_los=action.wall_blocks_los,
        damage_on_enter=action.wall_damage_on_enter,
        damage_type=action.wall_damage_type,
        damage_side=action.wall_damage_side,
        damage_side_hexes=set(damage_side_hexes or set()),
        concentration_linked=action.requires_concentration,
        occupied_hexes=set(wall_hexes),
    )


# ------------------------------------------------------------------
# Entry / start-of-turn damage (D-WALL-1)
#
# Wall of Fire (and Thorns/Blade Barrier/Ice) deal damage to a creature that
# *enters* the wall's space or *ends its turn* there. We model this with no save
# — matching RAW's ongoing Wall-of-Fire damage — mirroring the Spike Growth
# movement-hazard tick (zones._apply_hazard_tick). The on-appear DEX save is
# simplified to a no-save tick applied to whoever the wall materialises on.
# The damage-side nuance (Wall of Fire burns only one chosen side) is deferred:
# being *inside* the wall always burns, which is the common play case.
# ------------------------------------------------------------------


def creature_in_wall(wall: ActiveWall, creature_comb) -> bool:
    """Whether *creature_comb*'s footprint overlaps this wall's live hexes."""
    pos = getattr(creature_comb, "position", None)
    if pos is None:
        return False
    from arena.grid.footprint import get_occupied_hexes

    occupied = set(get_occupied_hexes(pos, creature_comb.creature.size))
    return bool(occupied & wall.get_wall_hexes())


def _apply_wall_damage(
    wall: ActiveWall, creature_id: str, combatants: dict,
) -> list[CombatEvent]:
    """Deal one tick of a wall's ``damage_on_enter`` (no save) to a creature.

    Mirrors ``zones._apply_hazard_tick``: rolls the dice, applies a magical
    damage packet, and runs a concentration check. Returns [] for a 0 roll or a
    wall that deals no damage."""
    creature_comb = combatants.get(creature_id)
    if creature_comb is None or not wall.damage_on_enter:
        return []

    from arena.combat.actions import apply_damage
    from arena.combat.concentration import check_concentration
    from arena.combat.damage import DamagePacket
    from arena.util.dice import roll_expression

    total_dmg, _rolls = roll_expression(wall.damage_on_enter)
    if total_dmg <= 0:
        return []

    target = creature_comb.creature
    events: list[CombatEvent] = []
    packet = DamagePacket(
        amount=total_dmg, dtype=wall.damage_type or "fire",
        source=wall.name, tags={"magical"},
    )
    dmg_event, dp_events = apply_damage(target, [packet], creature_id=creature_id)
    dmg_event.source_id = wall.source_id
    dmg_event.target_id = creature_id
    dmg_event.message = f"{target.name} {dmg_event.message}"
    events.append(dmg_event)
    events.extend(dp_events)
    events.extend(check_concentration(
        target, creature_id, dmg_event.details.get("damage", total_dmg),
        combatants=combatants,
    ))
    return events


def process_wall_movement_step(
    walls: list[ActiveWall], creature_id: str, combatants: dict,
) -> list[CombatEvent]:
    """Damage a creature that just stepped into a damaging wall's space.

    Called after each 5-ft movement step (alongside the zone hazard hook). One
    tick per damaging wall the creature now overlaps; the wall's own caster is
    spared (mirrors the zone-hazard convention)."""
    events: list[CombatEvent] = []
    cc = combatants.get(creature_id)
    if cc is None:
        return events
    for wall in walls:
        if not wall.damage_on_enter or creature_id == wall.source_id:
            continue
        if creature_in_wall(wall, cc):
            events.extend(_apply_wall_damage(wall, creature_id, combatants))
            if not cc.creature.is_conscious:
                break
    return events


def process_wall_start_of_turn(
    walls: list[ActiveWall], creature_id: str, combatants: dict,
) -> list[CombatEvent]:
    """Damage a creature that starts its turn standing in a damaging wall.

    RAW Wall of Fire burns a creature that ends its turn inside/adjacent; we
    apply it at the start of the creature's own turn (same effect, simpler hook
    than tracking end-of-turn). One tick per damaging wall it overlaps."""
    return process_wall_movement_step(walls, creature_id, combatants)


def get_wall_at_hex(
    walls: list[ActiveWall], hex_coord: HexCoord
) -> ActiveWall | None:
    """Find a wall that occupies a specific hex."""
    for wall in walls:
        if hex_coord in wall.get_wall_hexes():
            return wall
    return None


def is_hex_blocked_by_wall(
    walls: list[ActiveWall], hex_coord: HexCoord
) -> bool:
    """Check if any wall blocks movement through a hex."""
    return any(wall.is_blocking_hex(hex_coord) for wall in walls)


def is_los_blocked_by_wall(
    walls: list[ActiveWall],
    from_hex: HexCoord,
    to_hex: HexCoord,
    path_hexes: list[HexCoord],
) -> bool:
    """Check if any wall blocks line of sight along a path.

    Simplified: checks if any hex in the path is a LOS-blocking wall hex.
    """
    for hex_coord in path_hexes:
        if hex_coord == from_hex or hex_coord == to_hex:
            continue
        for wall in walls:
            if wall.is_blocking_los_hex(hex_coord):
                return True
    return False
