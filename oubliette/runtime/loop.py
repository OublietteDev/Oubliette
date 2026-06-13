"""The turn loop. One public method: `take_turn`.

Flow (spec §12): emit the player message → assess → (combat branch | roll →
resolve) → record-and-apply via the Session → render. Every state change and
every roll becomes an event in the session's log; diagnostics (assessment,
narration, anomalies, swings) go to a separate, non-replayed debug log.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from ..combat import arena_launch
from ..combat.arena_launch import stage_combat
from ..combat.boundary import CombatError, result_to_ops
from ..combat.schemas import CombatResult
from ..dm.brain import Brain
from ..dm.context import build_context
from ..enums import SKILL_ABILITY, Tier, Verb
from ..record.events import EventKind, StateOp
from ..record.log import DebugLog
from ..record.rng import Rng, RollOutcome
from ..rules.checks import resolve_check
from ..schemas import Intent, RollRequest, TurnAssessment
from ..state.repository import StateError
from ..table import render_table_prompt
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
    combat_pending: bool = False           # a fight is staged, awaiting "⚔ Enter the Arena"
    trade_open: TradeState | None = None   # set when a trade window is summoned
    session_ended: bool = False            # the DM closed the game (end_session)


class TurnLoop:
    def __init__(self, session: Session, rng: Rng, brain: Brain,
                 debug: DebugLog | None = None, scene: str | None = None) -> None:
        self.session = session
        self.repo = session.repo
        self.rng = rng
        self.brain = brain
        self.debug = debug or DebugLog()
        # Scene/location live on the session (they change as the party travels); an
        # explicit scene arg still overrides the opening text if given.
        self._scene_override = scene
        self.dispatcher = Dispatcher(session.repo, session.canon, session.places,
                                     session.quests, ruleset=session.ruleset)
        self.history: list[str] = []   # short-term continuity beats (gap G5)

    async def take_turn(self, player_text: str, on_text=None, ooc: bool = False) -> TurnReport:
        # Retrieve relevant canon/lore by the player's words PLUS the situation —
        # the current location and who's here — so a place's history surfaces when
        # the party arrives, not only when someone names it.
        canon_hits = self.session.canon.search(self._retrieval_query(player_text))
        scene = self._scene_override if self._scene_override is not None else self.session.scene
        context = build_context(
            self.repo, scene, self.history[-HISTORY_IN_CONTEXT:], canon_hits,
            location=self.session.location, places=self.session.places,
            quests=self.session.quests.active(),
            time_of_day=self.session.time_of_day, weather=self.session.weather,
            ruleset=self.session.ruleset)
        # `ooc` is the player's explicit "out-of-character" signal (the composer
        # toggle). When set, the turn is table-talk — no model guessing, no combat
        # or trade — so in-character play is never mistaken for meta.
        if ooc:
            assessment = TurnAssessment(
                intent=Intent(raw_text=player_text, verb=Verb.META, ooc=True),
                tier=Tier.FREESTYLE, resolution_hint="Player is speaking out-of-character.")
        else:
            assessment = await self.brain.assess(player_text, context)
            # The OOC toggle is the SOLE signal for table-talk (the assess prompt
            # says so, but the model can disobey — e.g. a reflective in-character
            # remark after a fight, "What a happenstance!", gets mislabeled meta and
            # the DM answers out-of-character). Enforce it in code: an in-character
            # turn is never meta. Demote to a no-roll observation so it narrates
            # in-world (skill_check is the prompt's bucket for non-mechanical beats).
            if assessment.intent.verb == Verb.META:
                assessment.intent = assessment.intent.model_copy(update={"verb": Verb.SKILL_CHECK})
                self.debug.append("note", stage="assess", coerced="meta->skill_check (in-character)")
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

        # Combat and trade produce their narration whole (no resolve call) → emit it
        # to the stream in one shot. The normal path streams token-by-token.
        report: TurnReport | None = None
        if assessment.encounter is not None:
            report = self._run_combat(player_text, assessment)
        elif assessment.trade is not None:
            report = self._open_trade(assessment)
        if report is not None:
            if on_text is not None:
                on_text(report.narration)
        else:
            report = await self._resolve_turn(player_text, assessment, context, on_text=on_text)

        self._record_beat(report)
        return report

    def _retrieval_query(self, player_text: str) -> str:
        """Canon/lore search terms: the player's words + the situation. The location
        contributes its OWN name AND every area it sits inside (walking up the parent
        chain) — so a city's lore surfaces while the party stands in one of its
        districts, not only at the city level — plus who's present."""
        loc = self.session.location
        places = self.session.places
        area_names: list[str] = []
        cur, seen = loc, set()
        while cur in places and cur not in seen:      # current place + its ancestors
            seen.add(cur)
            area_names.append(places[cur].name)
            cur = places[cur].parent
        present = " ".join(n.name for n in self.repo.npcs()
                           if loc is None or n.home_location == loc)
        return " ".join(p for p in [player_text, *area_names, present] if p)

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
                            context: str, on_text=None) -> TurnReport:
        # --- roll, if the DM called for one. Model sets the DC; code sets the bonus.
        roll_outcome: RollOutcome | None = None
        roll_result: str | None = None
        if assessment.requires_roll and assessment.roll is not None:
            spec = self._build_spec(assessment.roll)
            roll_outcome = self.rng.roll(spec, assessment.roll.purpose)  # emits a ROLL event
            roll_result = resolve_check(roll_outcome.total, assessment.roll.dc)

        # --- resolve + apply, bounded by D6. Validate ALL tools before applying any.
        # The campaign's table contract (tone + content boundaries) rides the resolve
        # system prompt every turn, so the DM honors it without ever setting it.
        table_prompt = render_table_prompt(self.session.table)
        feedback: str | None = None
        narration = ""
        applied: list[ResolvedTool] = []
        success = False
        for attempt in range(MAX_TOOL_RETRIES + 1):
            # Stream only the first attempt; a retry would double-stream narration.
            try:
                resolution = await self.brain.resolve(
                    player_text, assessment, roll_result, context, feedback,
                    on_text=(on_text if attempt == 0 else None), table_prompt=table_prompt)
            except (ValidationError, RuntimeError) as e:
                # The model returned an empty/malformed resolution (e.g. an empty tool
                # call). Treat it like a failed attempt: feed it back and retry, rather
                # than crashing the player's turn.
                feedback = ("Your last reply was empty or malformed. Reply again with a "
                            "complete TurnResolution — narration is required.")
                self.debug.append("anomaly", stage="resolve", attempt=attempt, error=str(e))
                continue
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
                elif rt.travel_to is not None:
                    self.session.emit_travel(rt.travel_to, rt.reason)
                elif rt.end_session:
                    self.session.emit_end(rt.reason)
                elif rt.quest_start is not None:
                    self.session.emit_quest_start(
                        rt.quest_start.title, rt.quest_start.text, rt.reason)
                elif rt.quest_update is not None:
                    self.session.emit_quest_update(
                        rt.quest_update.quest_id, status=rt.quest_update.status,
                        note=rt.quest_update.note, reason=rt.reason)
                else:
                    self.session.emit_state(
                        EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
            applied = resolved
            # The DM reports the current environment each turn; record only an ACTUAL
            # change (it carries the values forward unchanged otherwise) so we don't log
            # every turn or needlessly re-cue the soundscape.
            s = self.session
            new_time = resolution.time_of_day if resolution.time_of_day and resolution.time_of_day != s.time_of_day else None
            new_weather = resolution.weather if resolution.weather and resolution.weather != s.weather else None
            if new_time or new_weather:
                s.emit_environment(new_time, new_weather, reason="dm report")
            success = True
            break

        meta_notice: str | None = None
        if not success:
            meta_notice = "the DM lost the thread — try rephrasing."
            if not narration:        # all attempts failed to produce usable narration
                narration = "The Phantom's gaze drifts a moment, the thread of the scene slipping."
            self.debug.append("anomaly", stage="turn", note="forced narration-only after retries")

        self.debug.append("narration", text=narration)
        return TurnReport(
            player_text=player_text, assessment=assessment, narration=narration,
            roll_outcome=roll_outcome, roll_result=roll_result, applied=applied,
            meta_notice=meta_notice,
            session_ended=any(rt.end_session for rt in applied),
        )

    def _run_combat(self, player_text: str, assessment: TurnAssessment) -> TurnReport:
        """Summoned-tool branch (§8). Stage the fight: a non-combat exit
        (parley/flee/bribe) resolves instantly; a real fight is STAGED — written
        to an encounter file and held on the session — and the turn returns with
        the "⚔ Enter the Arena" signal. The fight is played (and its single
        COMBAT_RESULT recorded) later, in `enter_combat`, when the player enters."""
        try:
            outcome = stage_combat(
                assessment.encounter, self.repo, self.session,
                assessment=assessment, player_text=player_text,
            )
        except CombatError as e:
            self.debug.append("anomaly", stage="combat", error=str(e))
            narration = "The threat dissolves into confusion before anything is struck."
            self.debug.append("narration", text=narration)
            return TurnReport(
                player_text=player_text, assessment=assessment, narration=narration,
                meta_notice=f"combat could not be staged: {e}",
            )

        # Non-combat exit — resolved without the Arena, recorded immediately.
        if outcome.result is not None:
            return self._emit_combat_result(outcome.result, player_text, assessment)

        # A real fight: hold it pending and prompt the player to enter the Arena.
        self.session.pending_combat = outcome.pending
        names = ", ".join(c.name_override for c in outcome.pending.plan.encounter.combatants
                          if c.team == "enemy")
        narration = (f"Steel rings out — the fight is upon you ({names}). "
                     "Enter the Arena to play it out.")
        self.debug.append("narration", text=narration)
        return TurnReport(
            player_text=player_text, assessment=assessment, narration=narration,
            combat_pending=True,
        )

    def _encountered_keys(self, assessment: TurnAssessment) -> list[str]:
        """The bestiary keys (`scope:id`) of the statblock-backed creatures the party
        just faced — recorded on the COMBAT_RESULT event so the bestiary knowledge
        gate can bring those entries online. Templates (ephemeral) and persistent
        NPCs aren't bestiary entries, so they're skipped. Read-only: resolves refs
        with the same matcher the staging path uses, without touching the export."""
        request = getattr(assessment, "encounter", None)
        if request is None:
            return []
        pack = getattr(self.session, "statblocks", ()) or ()
        keys: list[str] = []
        for ref in getattr(request, "enemies", ()) or ():
            sb = arena_launch._statblock_for(self.session, ref.ref)
            if sb is None:
                continue
            scope = "pack" if any(s is sb for s in pack) else "srd"
            key = f"{scope}:{sb.id}"
            if key not in keys:
                keys.append(key)
        return keys

    def _split_combat_xp(self, ops: list, xp_award: int) -> list:
        """RAW (5e DMG): combat XP is shared — total ÷ party size, with the remainder
        spread one-per-member so none is lost. `result_to_ops` credits the lead PC (the
        frozen Arena import is left untouched); here we replace that single XP op with a
        per-member share. A solo party keeps the lead's op as-is."""
        party = self.repo.party()
        if not xp_award or len(party) <= 1:
            return ops
        ops = [op for op in ops if op.op != "xp"]      # drop the lead-only combat XP op
        base, extra = divmod(xp_award, len(party))
        for i, c in enumerate(party):
            share = base + (1 if i < extra else 0)
            if share:
                ops.append(StateOp.xp(c.id, share))
        return ops

    def _emit_combat_result(
        self, result: CombatResult, player_text: str, assessment: TurnAssessment
    ) -> TurnReport:
        """Record a resolved fight as the ONE COMBAT_RESULT event (§8) and build
        its report. Shared by the instant non-combat-exit path and `enter_combat`."""
        ops = self._split_combat_xp(result_to_ops(result), result.xp_award)
        self.session.emit_state(
            EventKind.COMBAT_RESULT, ops, outcome=result.outcome,
            hp_final=result.hp_final, xp_award=result.xp_award,
            digest=result.narrative_digest,
            encountered=self._encountered_keys(assessment),
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

    async def enter_combat(self) -> TurnReport:
        """Play the staged fight: spawn The Arena (blocking, in a thread so the web
        server stays responsive), map the result back through the bridge, and record
        it as the single COMBAT_RESULT event. Clears the pending lock."""
        import asyncio

        pending = self.session.pending_combat
        if pending is None:
            raise CombatError("no combat is staged")
        loop = asyncio.get_running_loop()
        try:
            handoff = await loop.run_in_executor(None, arena_launch.run_arena, pending)
            result = arena_launch.resolve_to_combat_result(pending, handoff)
        except CombatError as e:
            # The Arena crashed or wrote no readable result. Never leave the turn
            # hanging or the browser locked: resolve as an unresolved break-off
            # (no state change) so play always continues.
            self.debug.append("anomaly", stage="combat", error=str(e))
            result = CombatResult(
                outcome="flee",
                narrative_digest="The clash breaks off unresolved; you step back into the story.",
            )
        finally:
            arena_launch.cleanup(pending)
            self.session.pending_combat = None

        report = self._emit_combat_result(
            result, pending.player_text or "⚔ (entered the Arena)", pending.assessment
        )
        self._record_beat(report)
        return report

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
            elif rt.travel_to is not None:
                parts.append(f"travelled to {rt.travel_to}")
            elif rt.quest_start is not None:
                parts.append(f"started quest '{rt.quest_start.title}'")
            elif rt.quest_update is not None:
                state = rt.quest_update.status or "updated"
                parts.append(f"quest {rt.quest_update.quest_id} → {state}")
            elif rt.end_session:
                parts.append("ended the session")
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

    @staticmethod
    def _check_modifier(char, ability, roll: RollRequest) -> int:
        mod = char.ability_mod(ability) if ability is not None else 0
        if roll.skill is not None and roll.skill in char.skill_proficiencies:
            mod += char.proficiency_bonus
        return mod

    def _best_roller(self, roll: RollRequest):
        """The party member most capable at this check — 'best member rolls': their
        ability modifier, plus proficiency if they have the skill. Ties keep the lead
        PC. Returns (character, modifier)."""
        ability = roll.ability or (SKILL_ABILITY[roll.skill] if roll.skill else None)
        lead = self.repo.pc()
        best, best_mod = lead, self._check_modifier(lead, ability, roll)
        for c in self.repo.party():
            if c.id == lead.id:
                continue
            m = self._check_modifier(c, ability, roll)
            if m > best_mod:
                best, best_mod = c, m
        return best, best_mod

    def _build_spec(self, roll: RollRequest) -> str:
        """Code supplies the modifier from the sheet (state-owned); the DM supplied
        the DC (model-set, D8). With a party, the most capable member makes the
        check ('best member rolls')."""
        _, mod = self._best_roller(roll)
        sign = "+" if mod >= 0 else "-"
        return f"{roll.base}{sign}{abs(mod)}"
