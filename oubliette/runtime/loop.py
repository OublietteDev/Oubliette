"""The turn loop. One public method: `take_turn`.

Flow (spec §12): parse/route (assess) -> roll if the DM called for one ->
resolve (narrate + emit tools) -> validate & apply each tool, bounded by D6 ->
record -> return a report the UI renders from authoritative state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..combat.boundary import CombatError, apply_result, run_encounter
from ..combat.schemas import CombatResult
from ..dm.brain import Brain
from ..enums import SKILL_ABILITY
from ..record.log import DebugLog
from ..record.rng import Rng, RollOutcome
from ..rules.checks import resolve_check
from ..schemas import RollRequest, TurnAssessment
from ..state.repository import Repository
from ..tools.dispatch import AppliedTool, Dispatcher, ToolApplyError

MAX_TOOL_RETRIES = 2  # D6: after this, force a narration-only turn.


@dataclass
class TurnReport:
    player_text: str
    assessment: TurnAssessment
    narration: str
    roll_outcome: RollOutcome | None = None
    roll_result: str | None = None         # "success" | "failure" | None
    applied: list[AppliedTool] = field(default_factory=list)
    meta_notice: str | None = None         # set when the D6 fallback fires
    combat_result: CombatResult | None = None   # set when the turn summoned combat


class TurnLoop:
    def __init__(self, repo: Repository, rng: Rng, log: DebugLog, brain: Brain) -> None:
        self.repo = repo
        self.rng = rng
        self.log = log
        self.brain = brain
        self.dispatcher = Dispatcher(repo, log)

    async def take_turn(self, player_text: str) -> TurnReport:
        self.log.append("player_message", text=player_text)

        assessment = await self.brain.assess(player_text)
        self.log.append(
            "assessment",
            verb=assessment.intent.verb.value,
            skill=assessment.intent.skill.value if assessment.intent.skill else None,
            tier=assessment.tier.value,
            requires_roll=assessment.requires_roll,
            summons_combat=assessment.encounter is not None,
        )

        # --- combat branch: the narrator detected hostility (§8/§12) -------------
        if assessment.encounter is not None:
            return self._run_combat(player_text, assessment)

        # --- roll, if the DM called for one. Model sets the DC; code sets the bonus.
        roll_outcome: RollOutcome | None = None
        roll_result: str | None = None
        if assessment.requires_roll and assessment.roll is not None:
            spec = self._build_spec(assessment.roll)
            roll_outcome = self.rng.roll(spec, assessment.roll.purpose)
            roll_result = resolve_check(roll_outcome.total, assessment.roll.dc)

        # --- resolve + apply tools, bounded by D6 ---------------------------------
        feedback: str | None = None
        narration = ""
        applied: list[AppliedTool] = []
        success = False
        for attempt in range(MAX_TOOL_RETRIES + 1):
            resolution = await self.brain.resolve(
                player_text, assessment, roll_result, feedback
            )
            narration = resolution.narration
            applied = []
            error: ToolApplyError | None = None
            for call in resolution.tool_calls:
                try:
                    applied.append(self.dispatcher.apply(call))
                except ToolApplyError as e:
                    error = e
                    self.log.append("anomaly", stage="tool_apply", attempt=attempt,
                                    tool=call.tool, error=str(e))
                    break
            if error is None:
                success = True
                break
            feedback = str(error)
            if applied:
                # Partial application already happened this turn; retrying would
                # double-apply. Phase 0 limitation — Phase 2's transactional event
                # log makes the whole turn atomic. Bail to the fallback.
                break

        meta_notice: str | None = None
        if not success:
            # D6 fallback: narration only, surface an OOC notice to the player.
            applied = []
            meta_notice = "the DM lost the thread — try rephrasing."
            self.log.append("anomaly", stage="turn", note="forced narration-only after retries")

        self.log.append("narration", text=narration)
        return TurnReport(
            player_text=player_text,
            assessment=assessment,
            narration=narration,
            roll_outcome=roll_outcome,
            roll_result=roll_result,
            applied=applied,
            meta_notice=meta_notice,
        )

    def _run_combat(self, player_text: str, assessment: TurnAssessment) -> TurnReport:
        """Summoned-tool branch: live state in → CombatResult out → applied as one
        recorded result (§8). The engine internals are a Phase 1 placeholder."""
        try:
            result = run_encounter(assessment.encounter, self.repo, self.rng, self.log)
            apply_result(result, self.repo, self.log)
        except CombatError as e:
            self.log.append("anomaly", stage="combat", error=str(e))
            narration = "The threat dissolves into confusion before anything is struck."
            self.log.append("narration", text=narration)
            return TurnReport(
                player_text=player_text, assessment=assessment, narration=narration,
                meta_notice=f"combat could not be staged: {e}",
            )
        # Phase 1: the digest IS the narration; Phase 2 feeds it to the DM for prose.
        narration = result.narrative_digest
        self.log.append("narration", text=narration)
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
