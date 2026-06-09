"""AI decision making for NPCs and monsters."""

from .behavior import AIProfile, DEFAULT_PROFILES
from .context import CombatContext, CreatureView, build_context
from .controller import AIController, TurnPlan, TurnStep, TurnStepType
from .evaluation import evaluate_target, rank_targets
from .executor import execute_step, execute_full_plan
from .pathfinding import MovementGoal, find_best_movement, find_retreat_destination
from .resources import should_use_limited_ability, estimate_battle_progress
from .scoring import ScoredAction, generate_scored_actions
from .tactics import TacticalDecision, check_retreat, check_focus_fire, check_protect_ally

__all__ = [
    "AIProfile",
    "DEFAULT_PROFILES",
    "CombatContext",
    "CreatureView",
    "build_context",
    "AIController",
    "TurnPlan",
    "TurnStep",
    "TurnStepType",
    "evaluate_target",
    "rank_targets",
    "execute_step",
    "execute_full_plan",
    "MovementGoal",
    "find_best_movement",
    "find_retreat_destination",
    "should_use_limited_ability",
    "estimate_battle_progress",
    "ScoredAction",
    "generate_scored_actions",
    "TacticalDecision",
    "check_retreat",
    "check_focus_fire",
    "check_protect_ally",
]
