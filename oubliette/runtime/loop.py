"""The turn loop. One public method: `take_turn`.

Flow (spec §12): emit the player message → assess → (combat branch | roll →
resolve) → record-and-apply via the Session → render. Every state change and
every roll becomes an event in the session's log; diagnostics (assessment,
narration, anomalies, swings) go to a separate, non-replayed debug log.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..combat.boundary import CombatError, result_to_ops, run_encounter
from ..combat.schemas import CombatResult
from ..dm.brain import Brain
from ..enums import SKILL_ABILITY
from ..record.events import EventKind
from ..record.log import DebugLog
from ..record.rng import Rng, RollOutcome
from ..rules.checks import resolve_check
from ..schemas import RollRequest, TurnAssessment
from ..tools.dispatch import Dispatcher, ResolvedTool, ToolApplyError
from .session import Session

MAX_TOOL_RETRIES = 2  # D6: after this, force a narration-only turn.


@dataclass
class TurnReport:
    player_text: str
    assessment: TurnAssessment
    narration: str
    roll_outcome: RollOutcome | None = None
    roll_result: str | None = None         # "success" | "failure" | None
    applied: list[ResolvedTool] = field(default_factory=list)
    meta_notice: str | None = None         # set when the D6 fallback fires
    combat_result: CombatResult | None = None


class TurnLoop:
    def __init__(self, session: Session, rng: Rng, brain: Brain, debug: DebugLog | None = None) -> None:
        self.session = session
        self.repo = session.repo
        self.rng = rng
        self.brain = brain
        self.debug = debug or DebugLog()
        self.dispatcher = Dispatcher(session.repo)

    async def take_turn(self, player_text: str) -> TurnReport:
        assessment = await self.brain.assess(player_text)
        # The PLAYER_MESSAGE event carries the raw text + the parsed intent (§4.1).
        self.session.emit_log(
            EventKind.PLAYER_MESSAGE, text=player_text,
            intent=assessment.intent.model_dump(mode="json"),
        )
        self.debug.append(
            "assessment", verb=assessment.intent.verb.value,
            tier=assessment.tier.value, requires_roll=assessment.requires_roll,
            summons_combat=assessment.encounter is not None,
        )

        if assessment.encounter is not None:
            return self._run_combat(player_text, assessment)

        # --- roll, if the DM called for one. Model sets the DC; code sets the bonus.
        roll_outcome: RollOutcome | None = None
        roll_result: str | None = None
        if assessment.requires_roll and assessment.roll is not None:
            spec = self._build_spec(assessment.roll)
            roll_outcome = self.rng.roll(spec, assessment.roll.purpose)  # emits a ROLL event
            roll_result = resolve_check(roll_outcome.total, assessment.roll.dc)

        # --- resolve + apply, bounded by D6. Validate ALL tools before applying any.
        feedback: str | None = None
        narration = ""
        applied: list[ResolvedTool] = []
        success = False
        for attempt in range(MAX_TOOL_RETRIES + 1):
            resolution = await self.brain.resolve(player_text, assessment, roll_result, feedback)
            narration = resolution.narration
            try:
                resolved = [self.dispatcher.resolve(c) for c in resolution.tool_calls]
            except ToolApplyError as e:
                feedback = str(e)
                self.debug.append("anomaly", stage="tool_resolve", attempt=attempt, error=str(e))
                continue
            # All valid → record-and-apply each as a TOOL_APPLIED event (atomic turn).
            for rt in resolved:
                self.session.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
            applied = resolved
            success = True
            break

        meta_notice: str | None = None
        if not success:
            meta_notice = "the DM lost the thread — try rephrasing."
            self.debug.append("anomaly", stage="turn", note="forced narration-only after retries")

        self.debug.append("narration", text=narration)
        return TurnReport(
            player_text=player_text, assessment=assessment, narration=narration,
            roll_outcome=roll_outcome, roll_result=roll_result, applied=applied,
            meta_notice=meta_notice,
        )

    def _run_combat(self, player_text: str, assessment: TurnAssessment) -> TurnReport:
        """Summoned-tool branch: live state in → CombatResult → ONE COMBAT_RESULT
        event applied via the session (§8). Engine internals are a placeholder."""
        try:
            result = run_encounter(assessment.encounter, self.repo, self.rng, self.debug)
        except CombatError as e:
            self.debug.append("anomaly", stage="combat", error=str(e))
            narration = "The threat dissolves into confusion before anything is struck."
            self.debug.append("narration", text=narration)
            return TurnReport(
                player_text=player_text, assessment=assessment, narration=narration,
                meta_notice=f"combat could not be staged: {e}",
            )

        ops = result_to_ops(result)
        self.session.emit_state(
            EventKind.COMBAT_RESULT, ops, outcome=result.outcome,
            hp_final=result.hp_final, xp_award=result.xp_award,
            digest=result.narrative_digest,
        )
        # D5 promotion hook: surviving ephemerals flagged significant would be
        # promoted via the canonization path (Phase 3). For now we only surface them.
        if result.ephemeral_survivors:
            self.debug.append("note", stage="combat", promotion_candidates=result.ephemeral_survivors)

        narration = result.narrative_digest  # Phase 1/2: digest IS the narration.
        self.debug.append("narration", text=narration)
        return TurnReport(
            player_text=player_text, assessment=assessment, narration=narration,
            combat_result=result,
        )

    def _build_spec(self, roll: RollRequest) -> str:
        """Code supplies the modifier from the sheet (state-owned); the DM supplied
        the DC (model-set, D8)."""
        pc = self.repo.pc()
        ability = roll.ability or (SKILL_ABILITY[roll.skill] if roll.skill else None)
        mod = pc.ability_mod(ability) if ability is not None else 0
        if roll.skill is not None and roll.skill in pc.skill_proficiencies:
            mod += pc.proficiency_bonus
        sign = "+" if mod >= 0 else "-"
        return f"{roll.base}{sign}{abs(mod)}"
