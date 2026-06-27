"""AI Controller — orchestrates the full decision pipeline for one turn.

Produces a TurnPlan (list of TurnSteps), which is a pure data structure.
Execution is handled separately by the executor module.

No Pygame dependency.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

from arena.ai.behavior import AIProfile, DEFAULT_PROFILES
from arena.ai.context import build_context, CombatContext, CreatureView, creature_distance
from arena.ai.evaluation import rank_targets
from arena.ai.pathfinding import (
    find_best_movement,
    find_retreat_destination,
    find_flee_destination,
)
from arena.ai.resources import should_use_limited_ability
from arena.ai.scoring import (
    generate_scored_actions, ScoredAction, estimate_damage, estimate_save_damage,
    _score_best_teleport, check_use_condition,
)
from arena.ai.tactics import check_retreat, check_focus_fire, check_protect_ally
from arena.models.actions import Action
from arena.combat.actions import is_in_range
from arena.combat.stat_modifiers import get_extra_attack_count

if TYPE_CHECKING:
    from arena.combat.manager import CombatManager


class TurnStepType(Enum):
    """Types of steps that make up an AI turn."""

    MOVE = auto()
    SELECT_ACTION = auto()
    EXECUTE_ATTACK = auto()
    EXECUTE_EFFECT = auto()
    EXECUTE_TELEPORT = auto()
    STANDARD_ACTION = auto()
    BONUS_ATTACK = auto()
    END_TURN = auto()
    LOG_THINKING = auto()
    EXECUTE_LEGENDARY = auto()
    PASS_LEGENDARY = auto()
    EXECUTE_SHOVE = auto()
    EXECUTE_LAIR = auto()
    PASS_LAIR = auto()


@dataclass
class TurnStep:
    """A single step in an AI turn plan."""

    step_type: TurnStepType
    target_hex: tuple[int, int] | None = None  # for MOVE
    action_name: str | None = None  # for SELECT_ACTION, STANDARD_ACTION
    target_id: str | None = None  # for EXECUTE_ATTACK, BONUS_ATTACK
    message: str | None = None  # for LOG_THINKING
    legendary_action: Action | None = None  # for EXECUTE_LEGENDARY
    lair_action: Action | None = None  # for EXECUTE_LAIR
    shove_choice: str | None = None  # for EXECUTE_SHOVE ("push" or "prone")
    target_ids: list[str] | None = None  # for EXECUTE_LAIR (multi-target)
    cast_level: int | None = None  # Spell slot level for upcast spells


@dataclass
class TurnPlan:
    """Complete plan for one AI turn — ordered list of steps."""

    steps: list[TurnStep] = field(default_factory=list)
    thinking_log: list[str] = field(default_factory=list)


class AIController:
    """Orchestrates AI decision-making for one turn.

    Usage:
        controller = AIController(randomness=0.1)
        plan = controller.plan_turn(manager)
        # Then pass plan to executor
    """

    def __init__(self, randomness: float = 0.1) -> None:
        """Initialize the controller.

        Args:
            randomness: Controls score noise.
                0.0 = deterministic (always picks highest score).
                Higher values add more Gaussian noise for variety.
        """
        self.randomness = randomness

    def plan_turn(self, manager: CombatManager) -> TurnPlan:
        """Plan the full turn for the active AI-controlled combatant.

        Steps:
        1. Build perception context
        2. Check tactical overrides (retreat)
        3. Rank targets
        4. Score actions
        5. Decide movement
        6. Assemble TurnPlan
        """
        plan = TurnPlan()

        # ── Build perception ──────────────────────────────────────────
        context = build_context(manager)
        if context is None:
            plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))
            return plan

        combatant = manager.active_combatant
        if combatant is None:
            plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))
            return plan

        profile = self._get_profile(combatant)
        in_melee = self._is_in_melee(context)
        min_enemy_dists = []
        for e in context.enemies:
            if e.position is not None and context.me.position is not None:
                d = creature_distance(context.me, e)
                min_enemy_dists.append(f"{e.creature_id}:{d}")
        plan.thinking_log.append(
            f"AI profile: {profile.name}, melee={in_melee}, "
            f"enemies=[{', '.join(min_enemy_dists)}]"
        )
        plan.steps.append(TurnStep(
            step_type=TurnStepType.LOG_THINKING,
            message=f"{combatant.creature.name} considers options...",
        ))

        # ── Frightened: flee the fear source (RAW: can't move closer) ─
        # Takes priority over normal planning — a turned/frightened creature
        # spends its turn getting away. If it's cornered (can't increase the
        # distance) this returns None and it falls through to a normal turn,
        # where it'll attack at disadvantage.
        flee_dest = self._frightened_flee_dest(context, manager)
        if flee_dest is not None:
            plan.steps.append(TurnStep(
                step_type=TurnStepType.LOG_THINKING,
                message=f"{combatant.creature.name} is frightened and flees!",
            ))
            plan.steps.append(TurnStep(
                step_type=TurnStepType.MOVE,
                target_hex=(flee_dest.q, flee_dest.r),
            ))
            plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))
            return plan

        # ── Check tactical overrides ──────────────────────────────────
        retreat_decision = check_retreat(profile, context)
        if retreat_decision is not None:
            plan.thinking_log.append(f"Tactical: {retreat_decision.reason}")
            plan.steps.append(TurnStep(
                step_type=TurnStepType.LOG_THINKING,
                message=retreat_decision.reason,
            ))
            self._plan_retreat(plan, profile, context, manager)
            return plan

        # ── Normal turn planning ──────────────────────────────────────
        self._plan_normal_turn(plan, profile, context, manager, combatant)

        # ── Emit thinking_log as visible LOG_THINKING steps ──────────
        # Insert each entry as its own step (after the first LOG_THINKING
        # step) so that long diagnostic text isn't truncated by the
        # combat-log panel's single-line clipping.
        if plan.thinking_log:
            # Find where to insert (after the first LOG_THINKING step)
            insert_idx = 1  # default: after first step
            for i, step in enumerate(plan.steps):
                if step.step_type == TurnStepType.LOG_THINKING:
                    insert_idx = i + 1
                    break

            for entry in plan.thinking_log:
                plan.steps.insert(insert_idx, TurnStep(
                    step_type=TurnStepType.LOG_THINKING,
                    message=entry,
                ))
                insert_idx += 1

        return plan

    def _frightened_flee_dest(self, context, manager):
        """If the active creature is frightened, the hex it should flee to
        (max distance from its fear source). None if not frightened, the source
        isn't on the board, or it's cornered (can't increase the distance)."""
        from arena.models.conditions import Condition
        combatant = manager.active_combatant
        if combatant is None or manager.grid is None or context.me.position is None:
            return None
        # The fear source is recorded as the condition's source (caster name).
        fear_source = next(
            (ac.source for ac in combatant.creature.active_conditions
             if ac.condition == Condition.FRIGHTENED),
            None,
        )
        if not fear_source:
            return None
        source_combatant = next(
            (c for c in manager.combatants.values()
             if c.creature.name == fear_source and c.position is not None),
            None,
        )
        if source_combatant is None:
            return None
        return find_flee_destination(
            manager.grid, context.me.position, source_combatant.position,
            context.remaining_movement,
            creature_size=context.me.size,
            creature_id=context.me.creature_id,
            dead_creature_ids=manager.movement.dead_creature_ids,
            blocked_hexes=manager.movement.blocked_hexes,
        )

    def _plan_retreat(
        self,
        plan: TurnPlan,
        profile: AIProfile,
        context: CombatContext,
        manager: CombatManager,
    ) -> None:
        """Plan a retreat turn: prefer teleport, fall back to disengage + flee."""
        combatant = manager.active_combatant
        if combatant is None:
            plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))
            return

        # ── Try teleport retreat ──────────────────────────────────────
        # Prefer bonus action teleport (saves the action for a parting shot)
        retreat_tp = self._find_retreat_teleport(
            combatant.creature.bonus_actions, profile, context, "bonus_teleport",
        )
        if retreat_tp is None and not context.has_used_action:
            # Fall back to regular action teleport
            retreat_tp = self._find_retreat_teleport(
                combatant.creature.actions, profile, context, "teleport",
            )

        if retreat_tp is not None:
            self._plan_action(plan, retreat_tp, profile, context)
            plan.thinking_log.append(
                f"Retreat via {retreat_tp.description}"
            )
            plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))
            return

        # ── Fall back: Disengage + walk ───────────────────────────────
        if not context.has_used_action:
            plan.steps.append(TurnStep(
                step_type=TurnStepType.STANDARD_ACTION,
                action_name="disengage",
            ))
            plan.thinking_log.append("Action: Disengage to avoid opportunity attacks")

        # Find retreat destination
        if manager.grid and context.me.position:
            dest = find_retreat_destination(
                context, manager.grid,
                context.me.position, context.remaining_movement,
                creature_size=context.me.size,
                creature_id=context.me.creature_id,
                dead_creature_ids=manager.movement.dead_creature_ids,
                blocked_hexes=manager.movement.blocked_hexes,
            )
            if dest is not None:
                plan.steps.append(TurnStep(
                    step_type=TurnStepType.MOVE,
                    target_hex=(dest.q, dest.r),
                ))
                plan.thinking_log.append(f"Move: retreat to ({dest.q}, {dest.r})")

        plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))

    def _plan_normal_turn(
        self,
        plan: TurnPlan,
        profile: AIProfile,
        context: CombatContext,
        manager: CombatManager,
        combatant,
    ) -> None:
        """Plan a normal (non-retreat) combat turn."""
        # ── Check focus fire / protect ally overrides ─────────────────
        focus_target_id = check_focus_fire(profile, context)
        protect_ally_id = check_protect_ally(profile, context)

        if focus_target_id:
            plan.thinking_log.append(
                f"Tactical: Focus fire on {focus_target_id} (nearly dead)"
            )
            plan.steps.append(TurnStep(
                step_type=TurnStepType.LOG_THINKING,
                message=f"Focusing fire on {focus_target_id}",
            ))

        if protect_ally_id:
            plan.thinking_log.append(
                f"Tactical: Protecting ally {protect_ally_id}"
            )

        # ── Rank targets ──────────────────────────────────────────────
        ranked = rank_targets(profile, context)
        if ranked:
            plan.thinking_log.append(
                f"Targets: {', '.join(f'{cid}({s:.0f})' for cid, s in ranked[:3])}"
            )

        # Determine preferred target for movement
        preferred_target = self._get_preferred_target(
            context, ranked, focus_target_id
        )

        # ── Build distance map ────────────────────────────────────────
        reachable_enemies = self._build_distance_map(context)

        # ── Score all actions ─────────────────────────────────────────
        creature = combatant.creature
        can_action = not context.has_used_action
        can_bonus = not context.has_used_bonus_action
        can_twf = manager.can_two_weapon_fight() if context.has_used_action else False

        scored_actions = generate_scored_actions(
            profile, context,
            creature.actions, creature.bonus_actions,
            can_action, can_bonus, can_twf,
            reachable_enemies,
            creature=creature,
        )

        # Filter limited-use abilities
        scored_actions = self._filter_limited_abilities(
            scored_actions, creature, profile, context
        )

        # Add noise for variety
        if self.randomness > 0 and scored_actions:
            scored_actions = self._apply_noise(scored_actions)

        # Override: if focus fire target exists, boost attacks on it
        if focus_target_id and scored_actions:
            scored_actions = self._boost_focus_target(
                scored_actions, focus_target_id
            )

        if scored_actions:
            plan.thinking_log.append(
                f"Top actions: {', '.join(f'{a.description}({a.score:.0f})' for a in scored_actions[:3])}"
            )

        # ── Decide: move first or act first? ──────────────────────────
        best_action = scored_actions[0] if scored_actions else None

        # Determine if we need to move closer for our best action
        needs_approach = False
        if best_action and best_action.action_category in ("attack", "effect"):
            target_dist = reachable_enemies.get(best_action.target_id)
            if target_dist is not None:
                action_range = self._get_action_range(
                    best_action.action_name, creature
                )
                if target_dist > action_range:
                    needs_approach = True

        # ── Movement ──────────────────────────────────────────────────
        if needs_approach or (not best_action) or best_action.action_category == "standard":
            # Move before acting
            self._plan_movement(
                plan, profile, context, manager, preferred_target
            )

        # ── Action ────────────────────────────────────────────────────
        if best_action:
            # Multiattack: a creature with extra attacks (a dragon's bite +
            # two claws, a martial's Extra Attack) gets to swing that many
            # times per Attack action. The engine already enforces the
            # action economy (only the final swing consumes the action);
            # the AI just has to plan all the swings instead of one.
            num_attacks = get_extra_attack_count(creature)
            self._plan_action(plan, best_action, profile, context, num_attacks)

        # ── Bonus action: teleport or TWF ────────────────────────────
        # Prioritize bonus action teleport (e.g. Misty Step) for casters
        # stuck in melee over TWF bonus attacks.
        bonus_teleports = [
            a for a in scored_actions
            if a.action_category == "bonus_teleport"
        ]
        used_bonus_teleport = False

        if (bonus_teleports
                and best_action
                and best_action.action_category != "teleport"):
            best_bonus_tp = bonus_teleports[0]
            # Decide whether to use the bonus teleport:
            # - Non-melee profiles in melee should escape (primary use case)
            # - Very high score means strong tactical reason (e.g., retreat)
            in_melee = self._is_in_melee(context)
            should_teleport = (
                (not profile.prefers_melee and in_melee)
                or best_bonus_tp.score > 70.0
            )
            if should_teleport and best_bonus_tp.score > 15.0:
                # Validate destination against the actual grid
                dest_ok = self._validate_teleport_dest(
                    best_bonus_tp.target_hex, manager
                )
                if dest_ok:
                    self._plan_action(plan, best_bonus_tp, profile, context)
                    plan.thinking_log.append(
                        f"Bonus: {best_bonus_tp.description} to {best_bonus_tp.target_hex}"
                    )
                    used_bonus_teleport = True
                else:
                    plan.thinking_log.append(
                        f"Bonus tp dest invalid: {best_bonus_tp.target_hex}"
                    )
            else:
                plan.thinking_log.append(
                    f"Bonus tp skip: melee={in_melee}, score={best_bonus_tp.score:.0f}, "
                    f"prefers_melee={profile.prefers_melee}"
                )
        elif not bonus_teleports:
            plan.thinking_log.append("No bonus teleport available")
        elif best_action and best_action.action_category == "teleport":
            plan.thinking_log.append("Main action is teleport, skip bonus tp")

        if not used_bonus_teleport:
            # ── Post-action movement (if we haven't moved yet) ───────
            if not needs_approach and best_action and best_action.action_category != "standard":
                self._plan_movement(
                    plan, profile, context, manager, preferred_target,
                    post_action=True,
                )

            # ── TWF bonus attack ──────────────────────────────────────
            # Check if there's a bonus attack available after the main action
            bonus_attacks = [
                a for a in scored_actions
                if a.action_category == "bonus_attack"
            ]
            if bonus_attacks:
                best_bonus = bonus_attacks[0]
                plan.steps.append(TurnStep(
                    step_type=TurnStepType.BONUS_ATTACK,
                    target_id=best_bonus.target_id,
                ))
                plan.thinking_log.append(
                    f"Bonus: Off-hand attack -> {best_bonus.target_id}"
                )

        plan.steps.append(TurnStep(step_type=TurnStepType.END_TURN))

    def _plan_movement(
        self,
        plan: TurnPlan,
        profile: AIProfile,
        context: CombatContext,
        manager: CombatManager,
        preferred_target: CreatureView | None,
        post_action: bool = False,
    ) -> None:
        """Add movement step to the plan if beneficial."""
        if manager.grid is None or context.me.position is None:
            return
        if context.remaining_movement <= 0:
            return

        # Don't add duplicate movement steps
        existing_moves = [s for s in plan.steps if s.step_type == TurnStepType.MOVE]
        if existing_moves:
            return

        goal = find_best_movement(
            profile, context, manager.grid,
            context.me.position, context.remaining_movement,
            preferred_target,
            creature_size=context.me.size,
            creature_id=context.me.creature_id,
            dead_creature_ids=manager.movement.dead_creature_ids,
            blocked_hexes=manager.movement.blocked_hexes,
        )

        if goal.purpose != "stay" and goal.target_hex != context.me.position:
            plan.steps.append(TurnStep(
                step_type=TurnStepType.MOVE,
                target_hex=(goal.target_hex.q, goal.target_hex.r),
            ))
            plan.thinking_log.append(
                f"Move: {goal.purpose} to ({goal.target_hex.q}, {goal.target_hex.r})"
            )

    def _plan_action(
        self,
        plan: TurnPlan,
        best_action: ScoredAction,
        profile: AIProfile,
        context: CombatContext,
        num_attacks: int = 1,
    ) -> None:
        """Add the chosen action to the plan.

        ``num_attacks`` is the creature's Extra Attack / Multiattack count;
        it only applies to the ``attack`` category. Each swing is a
        SELECT_ACTION + EXECUTE_ATTACK pair (the attack must be re-selected
        between swings because completing an attack clears the selection).
        Swings re-target onto a living foe at execution time if the chosen
        target drops mid-sequence (see executor `_execute_attack`).
        """
        if best_action.action_category == "attack":
            swings = max(1, num_attacks)
            for _ in range(swings):
                plan.steps.append(TurnStep(
                    step_type=TurnStepType.SELECT_ACTION,
                    action_name=best_action.action_name,
                    cast_level=best_action.cast_level,
                ))
                plan.steps.append(TurnStep(
                    step_type=TurnStepType.EXECUTE_ATTACK,
                    target_id=best_action.target_id,
                ))
            suffix = f" (x{swings})" if swings > 1 else ""
            plan.thinking_log.append(
                f"Action: {best_action.description}{suffix}"
            )

        elif best_action.action_category in ("heal", "effect"):
            plan.steps.append(TurnStep(
                step_type=TurnStepType.SELECT_ACTION,
                action_name=best_action.action_name,
                cast_level=best_action.cast_level,
            ))
            plan.steps.append(TurnStep(
                step_type=TurnStepType.EXECUTE_EFFECT,
                target_id=best_action.target_id,
                # Area bursts carry a center hex (placed on the enemy) so the
                # executor routes them through execute_effect_at_hex instead of
                # the caster-centered execute_effect. None for single-target
                # effects and self-centered auras — unchanged.
                target_hex=best_action.target_hex,
            ))
            plan.thinking_log.append(
                f"Action: {best_action.description}"
            )

        elif best_action.action_category == "terrain":
            plan.steps.append(TurnStep(
                step_type=TurnStepType.SELECT_ACTION,
                action_name=best_action.action_name,
                cast_level=best_action.cast_level,
            ))
            plan.steps.append(TurnStep(
                step_type=TurnStepType.EXECUTE_EFFECT,
                target_id=best_action.target_id,
                target_hex=best_action.target_hex,
            ))
            plan.thinking_log.append(
                f"Action: {best_action.description}"
            )

        elif best_action.action_category in ("teleport", "bonus_teleport"):
            plan.steps.append(TurnStep(
                step_type=TurnStepType.SELECT_ACTION,
                action_name=best_action.action_name,
                cast_level=best_action.cast_level,
            ))
            plan.steps.append(TurnStep(
                step_type=TurnStepType.EXECUTE_TELEPORT,
                target_hex=best_action.target_hex,
            ))
            plan.thinking_log.append(
                f"Action: {best_action.description}"
            )

        elif best_action.action_category == "shove":
            # action_name is "shove:<choice>" — extract the choice
            choice = best_action.action_name.split(":")[1] if ":" in best_action.action_name else "prone"
            plan.steps.append(TurnStep(
                step_type=TurnStepType.EXECUTE_SHOVE,
                target_id=best_action.target_id,
                shove_choice=choice,
            ))
            plan.thinking_log.append(
                f"Action: {best_action.description}"
            )

        elif best_action.action_category == "standard":
            plan.steps.append(TurnStep(
                step_type=TurnStepType.STANDARD_ACTION,
                action_name=best_action.action_name,
            ))
            plan.thinking_log.append(
                f"Action: {best_action.description}"
            )

    # ── Helper methods ────────────────────────────────────────────────

    def _get_profile(self, combatant) -> AIProfile:
        """Resolve the AIProfile for a combatant.

        A Forge-authored custom personality, baked on by the Oubliette bridge as
        a plain dict (`ai_profile_inline`), takes precedence. Otherwise the named
        `ai_profile` resolves against the built-in presets, falling back to the
        default monster."""
        inline = getattr(combatant.creature, "ai_profile_inline", None)
        if inline:
            try:
                return AIProfile(**inline)
            except (TypeError, ValueError):
                pass  # malformed custom profile — fall back to the named/default
        profile_name = getattr(combatant.creature, "ai_profile", "default_monster")
        if profile_name in DEFAULT_PROFILES:
            return DEFAULT_PROFILES[profile_name]
        return DEFAULT_PROFILES["default_monster"]

    def _get_preferred_target(
        self,
        context: CombatContext,
        ranked: list[tuple[str, float]],
        focus_target_id: str | None,
    ) -> CreatureView | None:
        """Get the preferred target for movement decisions."""
        target_id = focus_target_id
        if target_id is None and ranked:
            target_id = ranked[0][0]

        if target_id is None:
            return None

        for enemy in context.enemies:
            if enemy.creature_id == target_id:
                return enemy
        return None

    def _build_distance_map(
        self, context: CombatContext
    ) -> dict[str, int]:
        """Build a map of enemy_id -> distance in hexes from me (footprint-aware)."""
        distances: dict[str, int] = {}
        if context.me.position is None:
            return distances

        for enemy in context.enemies:
            if enemy.position is not None:
                distances[enemy.creature_id] = creature_distance(
                    context.me, enemy
                )
        return distances

    def _filter_limited_abilities(
        self,
        scored: list[ScoredAction],
        creature,
        profile: AIProfile,
        context: CombatContext,
    ) -> list[ScoredAction]:
        """Remove limited-use actions the AI decides not to spend."""
        result: list[ScoredAction] = []
        for sa in scored:
            # Standard actions and shove are never limited
            if sa.action_category in ("standard", "bonus_attack", "shove"):
                result.append(sa)
                continue

            # Find the matching action object
            action_obj = None
            for a in creature.actions:
                if a.name == sa.action_name:
                    action_obj = a
                    break
            if action_obj is None:
                for a in creature.bonus_actions:
                    if a.name == sa.action_name:
                        action_obj = a
                        break

            if action_obj is None:
                result.append(sa)
                continue

            # Check if we should use this limited ability
            if action_obj.uses_per_rest is not None:
                if not should_use_limited_ability(action_obj, profile, context):
                    continue  # skip this action

            result.append(sa)

        return result

    def _apply_noise(
        self, scored: list[ScoredAction]
    ) -> list[ScoredAction]:
        """Add Gaussian noise to scores for variety, then re-sort."""
        if not scored:
            return scored

        # Scale noise relative to the top score
        max_score = max(a.score for a in scored) if scored else 1.0
        noise_scale = max_score * self.randomness

        noisy: list[ScoredAction] = []
        for sa in scored:
            noise = random.gauss(0, noise_scale)
            new_score = max(sa.score + noise, 0.0)
            noisy.append(ScoredAction(
                action_name=sa.action_name,
                target_id=sa.target_id,
                score=new_score,
                action_category=sa.action_category,
                description=sa.description,
                target_hex=sa.target_hex,
                cast_level=sa.cast_level,
            ))

        noisy.sort(key=lambda x: x.score, reverse=True)
        return noisy

    def _boost_focus_target(
        self,
        scored: list[ScoredAction],
        focus_target_id: str,
    ) -> list[ScoredAction]:
        """Boost score for attacks targeting the focus fire target."""
        boosted: list[ScoredAction] = []
        for sa in scored:
            if sa.target_id == focus_target_id and sa.action_category == "attack":
                boosted.append(ScoredAction(
                    action_name=sa.action_name,
                    target_id=sa.target_id,
                    score=sa.score + 50.0,
                    action_category=sa.action_category,
                    description=sa.description,
                    target_hex=sa.target_hex,
                    cast_level=sa.cast_level,
                ))
            else:
                boosted.append(sa)

        boosted.sort(key=lambda x: x.score, reverse=True)
        return boosted

    @staticmethod
    def _is_in_melee(context: CombatContext) -> bool:
        """Check if the active creature is adjacent to any enemy."""
        if context.me.position is None:
            return False
        from arena.ai.context import creature_distance
        for enemy in context.enemies:
            if enemy.position is not None:
                if creature_distance(context.me, enemy) <= 1:
                    return True
        return False

    @staticmethod
    def _validate_teleport_dest(
        target_hex: tuple[int, int] | None,
        manager: CombatManager,
    ) -> bool:
        """Check if a teleport destination is valid on the actual grid.

        Verifies passability and vacancy.  This catches cases the pure
        scoring module can't detect (walls, pits, large-creature
        footprint overlaps, etc.).
        """
        if target_hex is None or manager.grid is None:
            return False
        from arena.grid.coordinates import HexCoord
        dest = HexCoord(target_hex[0], target_hex[1])
        cell = manager.grid.get_cell(dest)
        if cell is None:
            return False
        if not manager.grid.is_passable(dest):
            return False
        if cell.occupant_id is not None:
            return False
        return True

    def _find_retreat_teleport(
        self,
        action_list: list[Action],
        profile: AIProfile,
        context: CombatContext,
        category: str,
    ) -> ScoredAction | None:
        """Find the best teleport action for retreat from a list of actions.

        Returns a ScoredAction if a viable teleport escape is found, else None.
        """
        best: ScoredAction | None = None
        for action in action_list:
            if action.teleport_range is None:
                continue
            if not check_use_condition(action.ai_use_condition, context):
                continue

            result = _score_best_teleport(action, profile, context, category)
            if result is not None and result.score > 10.0:
                if best is None or result.score > best.score:
                    best = result
        return best

    def _get_action_range(self, action_name: str, creature) -> int:
        """Get the range of an action in hexes."""
        for a in creature.actions:
            if a.name == action_name:
                if a.attack:
                    if a.attack.range_normal:
                        return a.attack.range_normal // 5
                    return a.attack.reach // 5
                # Non-attack actions use the action's base range
                return a.range // 5
        return 1  # default melee

    # ------------------------------------------------------------------
    # Legendary Action Planning
    # ------------------------------------------------------------------

    def plan_legendary_action(self, manager: CombatManager) -> TurnPlan:
        """Plan whether to use a legendary action (and which one).

        Called when the manager is in LEGENDARY_ACTION_PHASE.
        Returns a TurnPlan with either EXECUTE_LEGENDARY or PASS_LEGENDARY.
        """
        plan = TurnPlan()

        actor_id = manager._legendary_actor_id
        if actor_id is None:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LEGENDARY))
            return plan

        actor = manager.combatants.get(actor_id)
        if actor is None:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LEGENDARY))
            return plan

        available = manager.get_available_legendary_actions(actor_id)
        if not available:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LEGENDARY))
            return plan

        profile = self._get_profile(actor)

        best_score = 0.0
        best_action: Action | None = None
        best_target_id: str | None = None

        for action in available:
            # Self-targeting actions (Detect, Move, etc.) don't need a target
            if action.target_type == "self":
                score = action.ai_priority * 5.0
                score /= action.legendary_action_cost
                if score > best_score:
                    best_score = score
                    best_action = action
                    best_target_id = actor_id
                continue

            for cid, combatant in manager.combatants.items():
                if cid == actor_id:
                    continue
                if not combatant.creature.is_conscious:
                    continue

                # Determine if this is a valid target for the action
                is_ally = combatant.team == actor.team
                if action.healing and not is_ally:
                    continue  # heal only allies
                if not action.healing and is_ally:
                    continue  # attacks/effects only against enemies

                # Range check: skip targets out of range
                if (actor.position is not None
                        and combatant.position is not None):
                    if not is_in_range(
                        actor.position, combatant.position, action,
                        actor.creature.size, combatant.creature.size,
                    ):
                        continue

                # Score based on action type
                if action.attack:
                    score = estimate_damage(action) * action.ai_priority
                elif action.saving_throw:
                    score = estimate_save_damage(action) * action.ai_priority
                elif action.healing:
                    hp_need = 1.0 - combatant.creature.hp_percent
                    score = action.ai_priority * hp_need * 10
                else:
                    score = action.ai_priority * 5.0

                # Cost efficiency: prefer cheaper actions when points are scarce
                score /= action.legendary_action_cost

                # Aggression weight
                if not action.healing:
                    score *= profile.aggression

                if score > best_score:
                    best_score = score
                    best_action = action
                    best_target_id = cid

        # Threshold: only use if score is meaningful
        if best_action is not None and best_score > 5.0 and best_target_id is not None:
            plan.steps.append(TurnStep(
                step_type=TurnStepType.LOG_THINKING,
                message=f"{actor.creature.name} uses legendary action: {best_action.name}",
            ))
            plan.steps.append(TurnStep(
                step_type=TurnStepType.EXECUTE_LEGENDARY,
                legendary_action=best_action,
                target_id=best_target_id,
            ))
        else:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LEGENDARY))

        return plan

    # ------------------------------------------------------------------
    # Lair Action Planning
    # ------------------------------------------------------------------

    def plan_lair_action(self, manager: CombatManager) -> TurnPlan:
        """Plan which lair action to use (and targets).

        Called when the lair pseudo-combatant's turn starts.
        Returns a TurnPlan with either EXECUTE_LAIR or PASS_LAIR.
        """
        plan = TurnPlan()

        available = manager.get_available_lair_actions()
        if not available:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LAIR))
            return plan

        # Identify player-side targets (conscious)
        player_targets = [
            cid for cid, c in manager.combatants.items()
            if c.team in ("player", "ally") and c.creature.is_conscious
        ]

        if not player_targets:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LAIR))
            return plan

        # Condition value weights for scoring
        LAIR_CONDITION_SCORES = {
            "paralyzed": 20, "stunned": 18, "restrained": 12,
            "blinded": 10, "frightened": 8, "grappled": 7,
            "poisoned": 6, "prone": 5,
        }

        # Score each available lair action
        best_action: Action | None = None
        best_score = 0.0

        for action in available:
            score = 0.0
            save = action.saving_throw

            # Damage component
            if save and save.damage_on_fail:
                per_target = estimate_save_damage(action)
                score += per_target * len(player_targets)

            # Conditions on failed save (fix: use save.conditions_on_fail)
            if save and save.conditions_on_fail:
                cond_value = sum(
                    LAIR_CONDITION_SCORES.get(c, 5)
                    for c in save.conditions_on_fail
                )
                score += cond_value * len(player_targets) * 0.5

            # Healing allies — scale with how wounded they are
            if action.healing:
                enemies = [
                    c for c in manager.combatants.values()
                    if c.team == "enemy" and c.creature.is_conscious
                ]
                if enemies:
                    avg_hp_pct = sum(
                        c.creature.current_hit_points / max(c.creature.max_hit_points, 1)
                        for c in enemies
                    ) / len(enemies)
                    # At 100% HP → 5.0;  at 50% HP → 17.5;  at 25% HP → 23.75
                    score += 5.0 + 25.0 * (1.0 - avg_hp_pct)

            # Temporary HP for allies — more useful when they're still healthy
            if action.grants_temporary_hp:
                score += 10.0

            # Summoning — diminishes if there are already many enemy creatures
            if action.summon_creature:
                enemy_count = sum(
                    1 for c in manager.combatants.values()
                    if c.team == "enemy" and c.creature.is_conscious
                )
                # 1 enemy → 20.0;  3 enemies → 12.0;  5+ enemies → 6.0
                score += max(6.0, 24.0 - enemy_count * 4.0)

            # Ensure a minimum baseline from priority, then scale
            if score == 0.0:
                score = action.ai_priority * 2.0
            else:
                score *= action.ai_priority / 5.0

            if score > best_score:
                best_score = score
                best_action = action

        if best_action is not None:
            plan.steps.append(TurnStep(
                step_type=TurnStepType.LOG_THINKING,
                message=f"Lair uses: {best_action.name}",
            ))
            plan.steps.append(TurnStep(
                step_type=TurnStepType.EXECUTE_LAIR,
                lair_action=best_action,
                target_ids=player_targets,
            ))
        else:
            plan.steps.append(TurnStep(step_type=TurnStepType.PASS_LAIR))

        return plan
