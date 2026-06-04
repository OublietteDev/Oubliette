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
from ..dm.context import build_context
from ..enums import SKILL_ABILITY
from ..record.events import EventKind
from ..record.log import DebugLog
from ..record.rng import Rng, RollOutcome
from ..rules.checks import resolve_check
from ..schemas import RollRequest, TurnAssessment
from ..seed import DEFAULT_SCENE
from ..state.repository import StateError
from ..tools.dispatch import Dispatcher, ResolvedTool, ToolApplyError
from ..trade.schemas import TradeState
from ..trade.service import build_state, has_stock
from .session import Session

MAX_TOOL_RETRIES = 2    # D6: after this, force a narration-only turn.
HISTORY_IN_CONTEXT = 4  # recent turns fed back to the DM for continuity (gap G5).
HISTORY_CAP = 8         # how many beats to retain in memory.


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
    trade_open: TradeState | None = None   # set when a trade window is summoned


class TurnLoop:
    def __init__(self, session: Session, rng: Rng, brain: Brain,
                 debug: DebugLog | None = None, scene: str = DEFAULT_SCENE) -> None:
        self.session = session
        self.repo = session.repo
        self.rng = rng
        self.brain = brain
        self.debug = debug or DebugLog()
        self.scene = scene
        self.dispatcher = Dispatcher(session.repo, session.canon)
        self.history: list[str] = []   # short-term continuity beats (gap G5)

    async def take_turn(self, player_text: str) -> TurnReport:
        # Retrieve world canon relevant to this turn → context (long-term memory, G4).
        canon_hits = self.session.canon.search(player_text)
        context = build_context(
            self.repo, self.scene, self.history[-HISTORY_IN_CONTEXT:], canon_hits)
        assessment = await self.brain.assess(player_text, context)
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
            report = self._run_combat(player_text, assessment)
        elif assessment.trade is not None and (report := self._open_trade(assessment)) is not None:
            pass  # trade window summoned
        else:
            report = await self._resolve_turn(player_text, assessment, context)

        self._record_beat(report)
        return report

    def _open_trade(self, assessment: TurnAssessment) -> TurnReport | None:
        """Summon the trade window for a valid merchant with something to browse.
        Returns None (→ fall back to a normal turn) if the merchant is unknown or
        has nothing for sale/buy. No model call — the window is the content."""
        merchant_id = assessment.trade.merchant_id
        try:
            merchant = self.repo.get_character(merchant_id)
        except StateError:
            return None
        if merchant.kind != "npc" or not has_stock(self.repo, merchant_id):
            return None
        state = build_state(self.repo, merchant_id)
        narration = f'{merchant.name} spreads his wares across the counter. "See anything you like?"'
        self.debug.append("narration", text=narration)
        return TurnReport(
            player_text=assessment.intent.raw_text, assessment=assessment,
            narration=narration, trade_open=state,
        )

    async def _resolve_turn(self, player_text: str, assessment: TurnAssessment,
                            context: str) -> TurnReport:
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
            resolution = await self.brain.resolve(
                player_text, assessment, roll_result, context, feedback)
            narration = resolution.narration
            try:
                resolved = [self.dispatcher.resolve(c) for c in resolution.tool_calls]
            except ToolApplyError as e:
                feedback = str(e)
                self.debug.append("anomaly", stage="tool_resolve", attempt=attempt, error=str(e))
                continue
            # All valid → record-and-apply each as its event (atomic turn).
            for rt in resolved:
                if rt.canon_create is not None:
                    self.session.emit_create_entity(rt.canon_create, rt.reason)
                elif rt.canon_promote is not None:
                    self.session.emit_promote(rt.canon_promote, rt.reason)
                else:
                    self.session.emit_state(
                        EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
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

    def _record_beat(self, report: TurnReport) -> None:
        """Append a compact, factual summary of the turn for short-term continuity."""
        parts = [f'Player: "{report.player_text.strip()}"']
        if report.roll_outcome is not None and report.assessment.roll is not None:
            parts.append(
                f"[{report.roll_outcome.purpose}: rolled {report.roll_outcome.total} "
                f"vs DC {report.assessment.roll.dc} → {report.roll_result}]")
        for rt in report.applied:
            if rt.canon_create is not None:
                parts.append(f"created {rt.canon_create.entity_type} '{rt.canon_create.name}' (provisional)")
            elif rt.canon_promote is not None:
                parts.append(f"promoted {rt.canon_promote} → confirmed")
            else:
                parts.append(f"effect({rt.tool}): {self._ops_summary(rt.ops)}")
        if report.combat_result is not None:
            parts.append(f"combat → {report.combat_result.outcome}")
        if report.trade_open is not None:
            parts.append(f"opened trade with {report.trade_open.merchant_name}")
        narr = " ".join(report.narration.split())
        if narr:
            parts.append(f'DM: "{narr[:140]}"')
        self.history.append(" | ".join(parts))
        if len(self.history) > HISTORY_CAP:
            self.history = self.history[-HISTORY_CAP:]

    @staticmethod
    def _ops_summary(ops) -> str:
        bits = []
        for o in ops:
            if o.op == "gold":
                bits.append(f"{o.char} {o.delta:+d}g")
            elif o.op == "item":
                bits.append(f"{o.char} {o.delta:+d} {o.item_id}")
            elif o.op == "hp_set":
                bits.append(f"{o.char} hp={o.value}")
            elif o.op == "xp":
                bits.append(f"{o.char} +{o.delta}xp")
            elif o.op == "conditions":
                bits.append(f"{o.char} conditions={o.conditions}")
        return ", ".join(bits) or "(none)"

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
