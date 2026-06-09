"""Serialize and deserialize CombatManager state for save/load."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant, TurnResources
from arena.combat.initiative import InitiativeTracker, InitiativeEntry
from arena.combat.events import CombatLog, CombatEvent, CombatEventType
from arena.combat.movement import MovementTracker
from arena.combat.ready_action import ReadiedAction, TriggerType
from arena.grid.hexgrid import HexGrid, HexCell
from arena.grid.coordinates import HexCoord
from arena.models.character import Creature
from arena.models.actions import Action
from arena.models.encounter import TerrainType


def serialize_combat(cm: CombatManager) -> dict[str, Any]:
    """Serialize a CombatManager's full state to a JSON-compatible dict."""
    return {
        "version": 1,
        "timestamp": datetime.now().isoformat(),
        "state": cm.state.value,
        "turn_phase": cm.turn_phase.value,
        "winner": cm.winner,
        "grid": _serialize_grid(cm.grid) if cm.grid else None,
        "combatants": {
            cid: _serialize_combatant(c)
            for cid, c in cm.combatants.items()
        },
        "initiative": _serialize_initiative(cm.initiative),
        "turn_resources": _serialize_turn_resources(cm.turn_resources),
        "movement": _serialize_movement(cm.movement),
        "selected_action": (
            cm.selected_action.model_dump(mode="json")
            if cm.selected_action
            else None
        ),
        "reaction_used": dict(cm.reaction_used),
        "readied_actions": {
            cid: _serialize_readied_action(ra)
            for cid, ra in cm.readied_actions.items()
        },
        "legendary_points": dict(cm.legendary_points),
        "legendary_queue": list(cm._legendary_queue),
        "legendary_actor_id": cm._legendary_actor_id,
        "log": [_serialize_event(e) for e in cm.log.events],
    }


def deserialize_combat(data: dict[str, Any]) -> CombatManager:
    """Reconstruct a CombatManager from a serialized dict."""
    cm = CombatManager()

    cm.state = CombatState(data["state"])
    cm.turn_phase = TurnPhase(data["turn_phase"])
    cm.winner = data.get("winner")

    # Grid
    if data.get("grid"):
        cm.grid = _deserialize_grid(data["grid"])

    # Combatants
    cm.combatants = {
        cid: _deserialize_combatant(cdata)
        for cid, cdata in data["combatants"].items()
    }

    # Initiative
    cm.initiative = _deserialize_initiative(data["initiative"])

    # Turn resources
    cm.turn_resources = _deserialize_turn_resources(data["turn_resources"])

    # Movement
    cm.movement = _deserialize_movement(data["movement"])

    # Selected action
    if data.get("selected_action"):
        cm.selected_action = Action.model_validate(data["selected_action"])
    else:
        cm.selected_action = None

    # Reaction tracking
    cm.reaction_used = dict(data.get("reaction_used", {}))

    # Readied actions
    cm.readied_actions = {
        cid: _deserialize_readied_action(rdata)
        for cid, rdata in data.get("readied_actions", {}).items()
    }

    # Legendary action state
    cm.legendary_points = data.get("legendary_points", {})
    cm._legendary_queue = data.get("legendary_queue", [])
    cm._legendary_actor_id = data.get("legendary_actor_id")

    # Combat log
    cm.log = CombatLog()
    for edata in data.get("log", []):
        cm.log.add(_deserialize_event(edata))

    return cm


# -- Grid ------------------------------------------------------------------


def _serialize_grid(grid: HexGrid) -> dict[str, Any]:
    """Serialize a HexGrid to a dict."""
    terrain: dict[str, str] = {}
    occupants: dict[str, str] = {}

    for (q, r), cell in grid.cells.items():
        if cell.terrain != TerrainType.NORMAL:
            terrain[f"{q},{r}"] = cell.terrain.value
        if cell.occupant_id is not None:
            occupants[f"{q},{r}"] = cell.occupant_id

    return {
        "width": grid.width,
        "height": grid.height,
        "terrain": terrain,
        "occupants": occupants,
    }


def _deserialize_grid(data: dict[str, Any]) -> HexGrid:
    """Reconstruct a HexGrid from a dict."""
    grid = HexGrid(width=data["width"], height=data["height"])

    # Apply terrain
    for key, terrain_val in data.get("terrain", {}).items():
        q, r = (int(x) for x in key.split(","))
        coord = HexCoord(q, r)
        grid.set_terrain(coord, TerrainType(terrain_val))

    # Place occupants
    for key, creature_id in data.get("occupants", {}).items():
        q, r = (int(x) for x in key.split(","))
        coord = HexCoord(q, r)
        grid.place_creature(coord, creature_id)

    return grid


# -- Combatant --------------------------------------------------------------


def _serialize_combatant(c: Combatant) -> dict[str, Any]:
    """Serialize a Combatant to a dict."""
    return {
        "creature_id": c.creature_id,
        "team": c.team,
        "position": [c.position.q, c.position.r] if c.position else None,
        "creature": c.creature.model_dump(mode="json"),
    }


def _deserialize_combatant(data: dict[str, Any]) -> Combatant:
    """Reconstruct a Combatant from a dict."""
    pos = None
    if data.get("position"):
        pos = HexCoord(data["position"][0], data["position"][1])

    return Combatant(
        creature_id=data["creature_id"],
        creature=Creature.model_validate(data["creature"]),
        team=data["team"],
        position=pos,
    )


# -- Initiative -------------------------------------------------------------


def _serialize_initiative(tracker: InitiativeTracker) -> dict[str, Any]:
    """Serialize an InitiativeTracker to a dict."""
    return {
        "entries": [
            {
                "creature_id": e.creature_id,
                "name": e.name,
                "initiative_roll": e.initiative_roll,
                "dexterity": e.dexterity,
                "is_player_controlled": e.is_player_controlled,
                "tiebreaker": e.tiebreaker,
            }
            for e in tracker.entries
        ],
        "current_index": tracker.current_index,
        "round_number": tracker.round_number,
    }


def _deserialize_initiative(data: dict[str, Any]) -> InitiativeTracker:
    """Reconstruct an InitiativeTracker from a dict."""
    tracker = InitiativeTracker()
    tracker.current_index = data["current_index"]
    tracker.round_number = data["round_number"]

    # Add entries directly without re-sorting (order is already correct)
    for edata in data["entries"]:
        entry = InitiativeEntry(
            creature_id=edata["creature_id"],
            name=edata["name"],
            initiative_roll=edata["initiative_roll"],
            dexterity=edata["dexterity"],
            is_player_controlled=edata["is_player_controlled"],
            tiebreaker=edata.get("tiebreaker", 0.0),
        )
        tracker.entries.append(entry)

    return tracker


# -- Turn Resources ---------------------------------------------------------


def _serialize_turn_resources(tr: TurnResources) -> dict[str, Any]:
    """Serialize TurnResources to a dict."""
    return {
        "has_used_action": tr.has_used_action,
        "has_used_bonus_action": tr.has_used_bonus_action,
        "has_used_reaction": tr.has_used_reaction,
        "free_actions_used": tr.free_actions_used,
        "free_action_limit": tr.free_action_limit,
        "is_disengaging": tr.is_disengaging,
    }


def _deserialize_turn_resources(data: dict[str, Any]) -> TurnResources:
    """Reconstruct TurnResources from a dict."""
    return TurnResources(
        has_used_action=data["has_used_action"],
        has_used_bonus_action=data["has_used_bonus_action"],
        has_used_reaction=data["has_used_reaction"],
        free_actions_used=data["free_actions_used"],
        free_action_limit=data["free_action_limit"],
        is_disengaging=data["is_disengaging"],
    )


# -- Movement ---------------------------------------------------------------


def _serialize_movement(mt: MovementTracker) -> dict[str, Any]:
    """Serialize MovementTracker to a dict."""
    return {
        "creature_id": mt.creature_id,
        "max_movement": mt.max_movement,
        "remaining_movement": mt.remaining_movement,
        "has_moved": mt.has_moved,
    }


def _deserialize_movement(data: dict[str, Any]) -> MovementTracker:
    """Reconstruct MovementTracker from a dict."""
    return MovementTracker(
        creature_id=data["creature_id"],
        max_movement=data["max_movement"],
        remaining_movement=data["remaining_movement"],
        has_moved=data.get("has_moved", False),
    )


# -- Combat Events ----------------------------------------------------------


def _serialize_event(event: CombatEvent) -> dict[str, Any]:
    """Serialize a CombatEvent to a dict."""
    return {
        "event_type": event.event_type.value,
        "message": event.message,
        "source_id": event.source_id,
        "target_id": event.target_id,
        "details": event.details,
    }


def _deserialize_event(data: dict[str, Any]) -> CombatEvent:
    """Reconstruct a CombatEvent from a dict."""
    # Handle both string enum values and auto() integer values
    event_type_val = data["event_type"]
    try:
        event_type = CombatEventType(event_type_val)
    except ValueError:
        # Fallback for any unknown event types
        event_type = CombatEventType.INFO

    return CombatEvent(
        event_type=event_type,
        message=data["message"],
        source_id=data.get("source_id"),
        target_id=data.get("target_id"),
        details=data.get("details", {}),
    )


# -- Readied Actions --------------------------------------------------------


def _serialize_readied_action(ra: ReadiedAction) -> dict[str, Any]:
    """Serialize a ReadiedAction to a dict."""
    return {
        "creature_id": ra.creature_id,
        "action": ra.action.model_dump(mode="json"),
        "trigger_type": ra.trigger_type.value,
        "trigger_target_id": ra.trigger_target_id,
        "description": ra.description,
    }


def _deserialize_readied_action(data: dict[str, Any]) -> ReadiedAction:
    """Reconstruct a ReadiedAction from a dict."""
    return ReadiedAction(
        creature_id=data["creature_id"],
        action=Action.model_validate(data["action"]),
        trigger_type=TriggerType(data["trigger_type"]),
        trigger_target_id=data.get("trigger_target_id"),
        description=data.get("description", ""),
    )
