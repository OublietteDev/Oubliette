"""The combat boundary: the only door between the narrator and the subsystem.

`run_encounter` validates the request, instantiates combatants from templates +
live state (D5), resolves, and returns a `CombatResult` — it does NOT touch state.
`apply_result` is the single point that writes combat's truth back to authoritative
state and records ONE combat_result entry (the §8 single-event rule).
"""

from __future__ import annotations

from ..record.events import StateOp
from ..record.log import DebugLog
from ..record.rng import Rng
from ..state.repository import Repository, StateError
from ..tools.schemas import ValueEntry
from .engine import auto_resolve
from .schemas import Combatant, CombatResult, EncounterRequest, ExitKind
from .templates import ENEMY_TEMPLATES


class CombatError(Exception):
    """An invalid encounter request (unknown enemy, bad exit, ...)."""


_EXIT_DIGEST = {
    ExitKind.PARLEY: "Weapons lower. Words are exchanged instead of blows, and the moment cools.",
    ExitKind.FLEE: "You break away and put distance between yourself and the threat.",
    ExitKind.SURRENDER: "You raise empty hands and yield, trading the fight for whatever comes next.",
    ExitKind.BRIBE: "A few coins change hands and the hostility evaporates, for now.",
}


def _pc_combatant(repo: Repository) -> Combatant:
    pc = repo.pc()
    return Combatant(
        id=pc.id, name=pc.name, source="entity", entity_id=pc.id, is_pc=True,
        hp=pc.hp, max_hp=pc.max_hp, armor_class=pc.armor_class,
        attack_bonus=pc.attack_bonus, damage=pc.damage,
    )


def _instantiate_enemies(request: EncounterRequest, repo: Repository) -> list[Combatant]:
    out: list[Combatant] = []
    for ref in request.enemies:
        tmpl = ENEMY_TEMPLATES.get(ref.ref)
        if tmpl is not None:
            # Template → ephemeral combatants (D5): no entity row, discarded on close.
            for i in range(max(1, ref.count)):
                out.append(Combatant(
                    id=f"{ref.ref}#{i + 1}", name=tmpl.name, source="template",
                    hp=tmpl.hp, max_hp=tmpl.hp, armor_class=tmpl.armor_class,
                    attack_bonus=tmpl.attack_bonus, damage=tmpl.damage,
                    xp=tmpl.xp, loot=list(tmpl.loot),
                ))
            continue
        # Otherwise it must resolve to an existing persistent entity (recurring foe).
        try:
            ent = repo.get_character(ref.ref)
        except StateError as e:
            raise CombatError(f"enemy ref {ref.ref!r} is neither a template nor an entity") from e
        out.append(Combatant(
            id=ent.id, name=ent.name, source="entity", entity_id=ent.id,
            hp=ent.hp, max_hp=ent.max_hp, armor_class=ent.armor_class,
            attack_bonus=ent.attack_bonus, damage=ent.damage, xp=ent.xp,
        ))
    return out


def run_encounter(request: EncounterRequest, repo: Repository, rng: Rng, log: DebugLog) -> CombatResult:
    """Pure-ish: reads live state, rolls dice (logged), returns the truth object.
    Does NOT mutate authoritative state — that's `apply_result`."""
    log.append("combat_summon", encounter_kind=request.kind,
               enemies=[e.ref for e in request.enemies],
               chosen_exit=request.chosen_exit.value if request.chosen_exit else None)

    # Non-combat exit short-circuit — first-class, "talk the raiders down" wired in (§8).
    if request.chosen_exit is not None:
        if request.chosen_exit not in request.allow_exits:
            raise CombatError(f"exit {request.chosen_exit.value!r} not permitted this encounter")
        return CombatResult(
            outcome=request.chosen_exit.value,
            narrative_digest=_EXIT_DIGEST[request.chosen_exit],
        )

    if not request.enemies:
        raise CombatError("encounter has no enemies and no chosen exit")

    pc = _pc_combatant(repo)
    enemies = _instantiate_enemies(request, repo)
    combatants = [pc] + enemies
    outcome = auto_resolve(combatants, rng, log)

    # Persistent combatants get absolute write-backs (D7); ephemerals never do.
    hp_final = {c.entity_id: c.hp for c in combatants if c.source == "entity" and c.entity_id}

    loot: list[ValueEntry] = []
    xp_award = 0
    if outcome == "victory":
        for e in enemies:
            if e.hp <= 0:
                loot.extend(e.loot)
                xp_award += e.xp

    survivors = [c.id for c in combatants if c.source == "template" and c.hp > 0]
    fallen = [e.name for e in enemies if e.hp <= 0]
    if outcome == "victory":
        digest = (f"The fight ends in your favor. Fallen: {', '.join(fallen) or 'none'}. "
                  f"You take {xp_award} XP" + (f" and {loot_str(loot)}." if loot else "."))
    else:
        digest = "You are beaten down and fall. The encounter is lost."

    return CombatResult(
        outcome=outcome, hp_final=hp_final, conditions_final={}, loot=loot,
        xp_award=xp_award, narrative_digest=digest, ephemeral_survivors=survivors,
    )


def result_to_ops(result: CombatResult) -> list[StateOp]:
    """Decompose a CombatResult into replayable ops (absolute HP/conditions per D7,
    XP/loot to the PC). The runtime emits these as ONE COMBAT_RESULT event (§8) and
    the session applies them — same application path as replay."""
    ops: list[StateOp] = []
    for entity_id, hp in result.hp_final.items():
        ops.append(StateOp.hp_set(entity_id, hp))
    for entity_id, conditions in result.conditions_final.items():
        ops.append(StateOp.conditions_set(entity_id, conditions))
    if result.xp_award:
        ops.append(StateOp.xp("pc", result.xp_award))
    for entry in result.loot:
        if entry.gold is not None:
            ops.append(StateOp.gold("pc", entry.gold))
        else:
            ops.append(StateOp.item("pc", entry.item_id, entry.qty))
    # Consumables spent in the Arena (B1): debit each drinker's own stack. Safe by
    # the handoff entry invariant — the Arena can never report more used than the
    # quantity that was staged in from this same inventory.
    for used in result.items_consumed:
        ops.append(StateOp.item(used.char, used.item_id, -used.qty))
    return ops


def loot_str(loot: list[ValueEntry]) -> str:
    parts = []
    for e in loot:
        parts.append(f"{e.gold}g" if e.gold is not None else f"{e.qty}x {e.item_id}")
    return ", ".join(parts)
