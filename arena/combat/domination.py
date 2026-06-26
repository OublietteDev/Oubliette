"""Dominate Person/Beast/Monster — taking control of a creature (P-CONTROL).

On a failed Wisdom save the target is flipped to the *caster's* side: its team
and is_player_controlled change so whoever controls the caster drives it (via the
radial, using the creature's own actions). The DOMINATED condition stashes the
original team + control flag + the re-save DC, so reversion is exact and can be
triggered by any path:

  * the caster losing concentration (end_concentration calls end_domination on
    its "dominated" links), or
  * the dominated creature succeeding a Wisdom save when it takes damage.

State lives on the condition's extra_data — no manager-side bookkeeping — so the
Arena's transient-subprocess model stays clean.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.combat.conditions import apply_condition, remove_condition, has_condition
from arena.combat.events import CombatEvent, CombatEventType

if TYPE_CHECKING:
    from arena.combat.manager import Combatant


def is_dominated(creature: Creature) -> bool:
    return has_condition(creature, Condition.DOMINATED)


def _domination_data(creature: Creature) -> dict | None:
    for ac in creature.active_conditions:
        if ac.condition == Condition.DOMINATED:
            return ac.extra_data
    return None


def start_domination(
    target: Creature,
    target_id: str,
    caster: Creature,
    caster_id: str,
    combatants: dict[str, "Combatant"],
    dc: int,
) -> list[CombatEvent]:
    """Flip ``target`` to the caster's control. Returns events."""
    events: list[CombatEvent] = []
    target_cb = combatants.get(target_id)
    caster_cb = combatants.get(caster_id)
    caster_team = caster_cb.team if caster_cb else "player"

    original_team = target_cb.team if target_cb else "enemy"
    original_control = target.is_player_controlled

    ev = apply_condition(
        target, target_id, Condition.DOMINATED, source=caster.name,
        duration_type="indefinite",
        extra_data={
            "controller_id": caster_id,
            "original_team": original_team,
            "original_is_player_controlled": original_control,
            "save_dc": dc,
        },
    )
    if ev:
        events.append(ev)

    # Whoever controls the caster now controls the puppet, on the caster's team.
    if target_cb is not None:
        target_cb.team = caster_team
    target.is_player_controlled = caster.is_player_controlled

    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{target.name} is dominated by {caster.name} — it fights for them now!",
        source_id=caster_id, target_id=target_id,
        details={"dominated": True, "domination_started": True},
    ))
    return events


def end_domination(
    target: Creature,
    target_id: str,
    combatants: dict[str, "Combatant"],
) -> list[CombatEvent]:
    """Revert a dominated creature to its original team/control and clear it."""
    events: list[CombatEvent] = []
    data = _domination_data(target)
    if data is not None:
        target_cb = combatants.get(target_id)
        if target_cb is not None and "original_team" in data:
            target_cb.team = data["original_team"]
        if "original_is_player_controlled" in data:
            target.is_player_controlled = bool(data["original_is_player_controlled"])

    ev = remove_condition(target, target_id, Condition.DOMINATED)
    if ev:
        events.append(ev)
    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{target.name} breaks free of the domination!",
        target_id=target_id,
        details={"domination_ended": True},
    ))
    return events


def check_domination_on_damage(
    target: Creature,
    target_id: str,
    combatants: dict[str, "Combatant"],
) -> list[CombatEvent]:
    """RAW re-save: a dominated creature that takes damage may shake free.

    Wisdom save vs the caster's DC; success ends the domination.
    """
    data = _domination_data(target)
    if data is None:
        return []
    dc = int(data.get("save_dc", 10))

    from arena.combat.actions import resolve_saving_throw  # local: avoid cycle
    # Dominate is a charm spell → Magic Resistance and Fey Ancestry apply.
    success, save_event = resolve_saving_throw(
        target, target_id, "wisdom", dc,
        is_spell_save=True, imposes_conditions=["charmed"],
    )
    save_event.message = f"Domination check: {save_event.message}"
    save_event.details["domination_check"] = True
    events: list[CombatEvent] = [save_event]
    if success:
        events.extend(end_domination(target, target_id, combatants))
    return events
