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
from ..combat.budget import BudgetError, budget_for
from ..difficulty import DEFAULT_DIFFICULTY
from ..combat.schemas import CombatResult, EncounterRequest, EnemyRef
from ..dm.brain import Brain
from ..dm.context import build_context, story_so_far
from ..enums import SKILL_ABILITY, Tier, Verb
from ..record.events import EventKind, StateOp
from ..quest import offers
from ..record.log import DebugLog
from ..record.rng import Rng, RollOutcome
from ..rules.checks import resolve_check
from ..rules.rest import rest_interrupted_recently
from ..schemas import Intent, RollRequest, TurnAssessment
from ..state.repository import StateError
from ..table import render_table_prompt
from ..tools.dispatch import Dispatcher, ResolvedTool, ToolApplyError
from ..trade.schemas import TradeState
from ..trade.service import build_state, has_stock
from ..world import clock as world_clock
from ..world import events as timed_events
from ..world import factions as faction_standing
from ..world import keyed as keyed_triggers
from .session import Session
from .transcript import notebook_notes, recent_beats, session_notes, transcript_turns

MAX_TOOL_RETRIES = 2    # D6: after this, force a narration-only turn.
MIN_TURN_PROSE = 60     # under this many chars with tools applied → the story starved;
                        # run the narration-only follow-up pass (finding #1).
HISTORY_IN_CONTEXT = 8  # recent turns fed back to the DM for continuity (gap G5).
                        # Beats are compact (~60-80 tokens), so 8 costs a few hundred
                        # uncached tokens a turn and buys the conversational thread —
                        # the callback to what someone said five turns ago.
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
    wrap_pending: bool = False             # the DM proposed wrapping the session (player confirms)
    rest_pending: str | None = None        # the DM proposed a rest: "short"|"long" (player confirms)
    companion_pending: dict | None = None  # the DM proposed a recruit/dismissal (player confirms):
                                           # {action, char_id, name, kind, origin, reason}
    growth: list = field(default_factory=list)  # creature companions that grew THIS turn
                                           # (S2 story moment): [{char_id, name, from, to}]
    companion_deaths: list = field(default_factory=list)  # companions the fight truly took
                                           # (S3, companion_death ON): [{char_id, name}]
    session_force_ended: bool = False      # the DM terminally closed the game (force_end_session)


@dataclass
class WrapReport:
    """The result of wrapping a session (W5): whether it wrapped, and the two-faced notes
    the DM authored (empty in Offline Mode, which writes none)."""
    wrapped: bool
    player_facing: str = ""
    dm_private: str = ""
    notice: str | None = None              # set when there was nothing to wrap yet


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
                                     session.quests, ruleset=session.ruleset,
                                     authored_quests=session.authored_quests, rng=rng,
                                     mechanics=(session.mechanics_catalog or None),
                                     factions=getattr(session, "factions", None))
        # Short-term continuity beats (gap G5). Rehydrated from the durable record on
        # construction (W3): a reload rebuilds the DM's recent memory of THIS session from
        # the stored beats, so it resumes with the same short-term context it had before —
        # not an empty head. Past sessions reach the DM as notes (W5), never as beats here.
        self.history: list[str] = recent_beats(session.store.read_all(), HISTORY_CAP)
        # Keyed encounters whose staging failed at the table (authoring drift the
        # lint didn't catch — e.g. a hand-edited pack): suppressed for THIS process
        # so a broken fight logs one anomaly, not one per turn. {(place, enc id)}
        self._keyed_broken: set = set()

    def _build_context(self, player_text: str = "", growth: list | None = None,
                       keyed=None, world_event: dict | None = None) -> str:
        """Assemble the per-turn DM context (state, scene, present NPCs, canon, quests,
        past-session notes, recent beats). Shared by `take_turn` and `wrap_session` so the
        DM writes its session notes with the same picture it plays from. Retrieves canon by
        the player's words PLUS the situation (location + who's here), so a place's history
        surfaces on arrival, not only when named."""
        canon_hits = self.session.canon.search(self._retrieval_query(player_text))
        scene = self._scene_override if self._scene_override is not None else self.session.scene
        # Authored-quest offers: chain-eligible set (replay-derived) and the subset whose
        # source is present right now (acceptable this turn). The dispatcher gates
        # accept_quest on `offered_here`; the context surfaces both tiers to the DM.
        authored, eligible, here = self._compute_offers()
        self.dispatcher.offered_here = here
        # Long-term memory note: the DM's private notes from PAST wrapped sessions (W5)
        # are NOT in this per-turn context — they're session-stable, so they ride
        # separately as `stable_context` (see _story_so_far) where providers with
        # prompt caching bill them at cache rates. The DM's own working notebook
        # (W4) IS here: it changes mid-session (dm_note entries).
        events = self.session.store.read_all()
        return build_context(
            self.repo, scene, self.history[-HISTORY_IN_CONTEXT:], canon_hits,
            location=self.session.location, places=self.session.places,
            quests=self.session.quests.active(),
            pending_rewards=self.session.quests.reward_pending(),
            time_of_day=self.session.time_of_day, weather=self.session.weather,
            ruleset=self.session.ruleset,
            authored_quests=authored, offerable=eligible, offered_here=here,
            notebook=notebook_notes(events),
            difficulty=getattr(self.session, "difficulty", DEFAULT_DIFFICULTY),
            rest_interrupted=rest_interrupted_recently(events),
            companion_growth=growth,
            keyed_directive=({"names": self._keyed_names(keyed),
                              "briefing": keyed.briefing}
                             if keyed is not None else None),
            factions=self._faction_context(),
            day=world_clock.current_day(events),
            world_event=world_event,
            mechanics=getattr(self.session, "mechanics_catalog", None))

    def _story_so_far(self) -> str:
        """The DM's cumulative past-session notes (W5) as the SESSION-STABLE context
        block. Passed to every brain call as `stable_context`, apart from the per-turn
        context, because it never changes while a session runs — providers with prompt
        caching (Anthropic today) bill it at cache rates, so a long campaign's growing
        memory doesn't grow the per-turn cost with it."""
        events = self.session.store.read_all()
        return story_so_far([n["dm_private"] for n in session_notes(events)])

    async def take_turn(self, player_text: str, on_text=None, ooc: bool = False) -> TurnReport:
        # A new in-character turn moves the fiction on: any standing rest grant
        # (S3) expires — the DM's "you may rest now" was for THAT moment, not a
        # coupon. Out-of-character table-talk leaves the offer standing.
        if not ooc:
            self.session.pending_rest = None
            self.session.pending_companion = None   # same contract: the proposal was
                                                    # for THAT moment, not a coupon
        # Companion growth (S2): an authored creature whose threshold the heroes just
        # crossed grows NOW — the stats apply this instant (event recorded below the
        # firewall), and the DM is handed a note to work the change into the story.
        # Growth that already happened at an endpoint (level-up, recruit) waits here
        # as a pending note: the player saw its card then; the DM learns of it now.
        growth = [] if ooc else self._check_companion_growth()
        notes = growth
        if not ooc and self.session.pending_growth_note:
            notes = self.session.pending_growth_note + growth
            self.session.pending_growth_note = []
        # Keyed encounter (living-world W1): evaluated in CODE at the top of every
        # in-character turn. If one is due, this turn's reply narrates the approach
        # (hard directive in the context) and the engine stages the fight itself
        # after the prose — the DM styles the moment, never decides it. The PLACE
        # is captured here, at evaluation: the DM may disobey the directive and
        # travel mid-turn, and the fired record must name the place that armed.
        keyed_due = None if ooc else self._due_keyed_encounter()
        keyed = keyed_due[1] if keyed_due else None
        # Timed world event (living-world W4): fired AFTER keyed evaluation (an
        # encounter it arms waits for the next turn's check) and BEFORE the
        # context builds — the DM narrates a world that has ALREADY changed.
        world_event = None if ooc else self._fire_world_event()
        context = self._build_context(player_text, growth=notes, keyed=keyed,
                                      world_event=world_event)
        # `ooc` is the player's explicit "out-of-character" signal (the composer
        # toggle). When set, the turn is table-talk — no model guessing, no combat
        # or trade — so in-character play is never mistaken for meta.
        if ooc:
            assessment = TurnAssessment(
                intent=Intent(raw_text=player_text, verb=Verb.META, ooc=True),
                tier=Tier.FREESTYLE, resolution_hint="Player is speaking out-of-character.")
        else:
            # Assess gets the same one-retry safety net the resolve loop has: a
            # single malformed model reply (or transient provider hiccup) must
            # not kill the player's turn outright.
            try:
                assessment = await self.brain.assess(player_text, context,
                                                     stable_context=self._story_so_far())
            except (ValidationError, RuntimeError) as e:
                self.debug.append("anomaly", stage="assess", attempt=0, error=repr(e))
                assessment = await self.brain.assess(player_text, context,
                                                     stable_context=self._story_so_far())
            # The OOC toggle is the SOLE signal for table-talk (the assess prompt
            # says so, but the model can disobey — e.g. a reflective in-character
            # remark after a fight, "What a happenstance!", gets mislabeled meta and
            # the DM answers out-of-character). Enforce it in code: an in-character
            # turn is never meta. Demote to a no-roll observation so it narrates
            # in-world (skill_check is the prompt's bucket for non-mechanical beats).
            if assessment.intent.verb == Verb.META:
                assessment.intent = assessment.intent.model_copy(update={"verb": Verb.SKILL_CHECK})
                self.debug.append("note", stage="assess", coerced="meta->skill_check (in-character)")
            if keyed is not None and (assessment.encounter is not None
                                      or assessment.trade is not None):
                # The authored fight outranks anything the model improvised this
                # turn: the reply is approach prose only — the engine stages the
                # real encounter below, whatever the assessment tried to summon.
                assessment = assessment.model_copy(update={"encounter": None, "trade": None})
                self.debug.append("note", stage="assess",
                                  coerced="encounter/trade suppressed (keyed encounter armed)")
        # The PLAYER_MESSAGE event carries the raw text + the parsed intent (§4.1).
        player_event = self.session.emit_log(
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
            report = await self._run_combat(player_text, assessment)
        elif assessment.trade is not None:
            report = self._open_trade(assessment)
        if report is not None:
            if on_text is not None:
                on_text(report.narration)
        else:
            report = await self._resolve_turn(player_text, assessment, context, on_text=on_text)

        if keyed_due is not None:
            report = self._stage_keyed(keyed_due[0], keyed_due[1], report,
                                       player_text, assessment)
        report.growth = growth
        self._record_beat(report, caused_by=player_event.seq)
        return report

    def _check_companion_growth(self) -> list[dict]:
        """Creature companions whose authored growth threshold the heroes have
        crossed grow into their next form NOW (companions S2): each hop emits a
        COMPANION_EVOLVED event (snapshot + stat-block remap) and is reported so
        the DM narrates the transformation this turn. Chains climb at most a few
        hops per turn (a late recruit catching up); people never pass through
        here — they level."""
        from ..combat.arena_launch import _statblock_for
        from ..rules.growth import eligible_stage, evolved_character
        hero_level = max((c.level for c in self.repo.party() if not c.companion),
                         default=1)
        grown: list[dict] = []
        for comp in list(self.repo.companions()):
            if comp.sheet is not None:
                continue
            worn: set[str] = set()          # forms this companion wore THIS turn
            for _hop in range(3):
                sb_id = self.session.npc_statblocks.get(comp.id)
                sb = _statblock_for(self.session, sb_id) if sb_id else None
                stage = eligible_stage(sb, hero_level) if sb is not None else None
                if stage is None:
                    break
                worn.add(sb.id)
                new_sb = _statblock_for(self.session, stage.to)
                if new_sb is None:
                    self.debug.append("anomaly", stage="growth",
                                      error=f"growth target {stage.to!r} is not a known "
                                            f"stat block (authoring gap); {comp.name} stays "
                                            f"a {sb.name}")
                    break
                if new_sb.id in worn:
                    # A growth CYCLE (the lint rejects these at load; this guards a
                    # pack loaded before the lint existed): never re-wear a form —
                    # each re-evolution would wake the companion whole, every turn.
                    self.debug.append("anomaly", stage="growth",
                                      error=f"growth cycle: {comp.name} would grow back "
                                            f"into {new_sb.name} — stopping (fix the "
                                            "pack's growth stages)")
                    break
                snap = evolved_character(self.repo.get_character(comp.id), new_sb)
                self.session.emit_companion_evolved(
                    snap, to_statblock=new_sb.id, from_name=sb.name, to_name=new_sb.name)
                grown.append({"char_id": comp.id, "name": comp.name,
                              "from": sb.name, "to": new_sb.name})
        return grown

    def _due_keyed_encounter(self):
        """`(place id, encounter)` for the keyed encounter that fires this turn at
        the party's location, or None (living-world W1). Pure derivation over the
        log + the PlaceNode's authored list; a fight already staged and awaiting
        the Arena defers any new ambush, and a staging-broken encounter stays
        suppressed. The place rides along so the fired record and the broken-set
        key name the place that ARMED, whatever the DM does mid-turn."""
        if getattr(self.session, "pending_combat", None) is not None:
            return None
        loc = self.session.location
        node = (self.session.places or {}).get(loc) if loc else None
        if node is None:
            return None
        wev = getattr(self.session, "world_events", None) or {}
        armed = (timed_events.armed_encounters(wev, self.session.store.read_all())
                 if wev else None)
        enc = keyed_triggers.due_encounter(
            node, self.session.store.read_all(),
            start_location=getattr(self.session, "start_location", None),
            time_of_day=self.session.time_of_day,
            party_level=max((c.level for c in self.repo.party() if not c.companion),
                            default=1),
            armed=armed)
        if enc is None or (loc, enc.id) in self._keyed_broken:
            return None
        return (loc, enc)

    def _keyed_names(self, enc) -> str:
        """Display names for a keyed encounter's enemies — resolved the same way
        staging will resolve them, so the DM narrates the right creatures."""
        parts: list[str] = []
        for e in enc.enemies:
            ent = arena_launch._try_entity(self.repo, e.ref)
            if ent is not None:
                parts.append(ent.name)
                continue
            sb = arena_launch._statblock_for(self.session, e.ref)
            name = sb.name if sb is not None else e.ref
            parts.append(f"{e.count} x {name}" if e.count > 1 else name)
        return ", ".join(parts)

    def _stage_keyed(self, place: str, enc, report: TurnReport, player_text: str,
                     assessment: TurnAssessment) -> TurnReport:
        """Stage an authored keyed encounter AFTER the approach narration. The
        code owns the fact of the fight: the authored enemies are staged
        budget-exempt (authored intent outranks the table's improvisation caps —
        min_party_level is the author's own gate). `place` is where the trigger
        ARMED, captured at evaluation — never the post-turn location, which a
        disobedient mid-turn travel can move. The fired record is NOT written
        here: it rides the pending fight and lands when the player actually
        enters the Arena, so a quit or crash at the ⚔ prompt re-stages the
        authored fight instead of silently spending it. A staging failure logs
        one anomaly and suppresses the encounter for this process; the
        narration stands and play continues."""
        request = EncounterRequest(
            kind="ambush",
            surprised="party" if getattr(enc, "ambush", False) else "none",
            enemies=[EnemyRef(ref=e.ref, count=e.count) for e in enc.enemies],
            allies=list(getattr(enc, "allies", None) or ()))
        # The post-combat report (bestiary keys, result prose) reads the turn's
        # assessment.encounter — hand the pending fight the AUTHORED request.
        assessment = assessment.model_copy(update={"encounter": request})
        try:
            outcome = stage_combat(request, self.repo, self.session,
                                   assessment=assessment, player_text=player_text,
                                   budget=None)
        except CombatError as e:
            self._keyed_broken.add((place, enc.id))
            self.debug.append("anomaly", stage="keyed_encounter",
                              encounter=enc.id, error=str(e))
            return report
        outcome.pending.keyed = (place, enc.id)
        self.session.pending_combat = outcome.pending
        staged_crs = {c.name_override: float(getattr(c.creature_data, "challenge_rating", 0) or 0)
                      for c in outcome.pending.plan.encounter.combatants if c.team == "enemy"}
        self.debug.append("combat_budget", stage="staged", enemies=staged_crs,
                          total_cr=round(sum(staged_crs.values()), 3),
                          budget=f"bypassed (authored keyed encounter {enc.id!r})")
        report.combat_pending = True
        return report

    def _fire_world_event(self) -> dict | None:
        """Fire the one due WorldEvent (living-world W4), if any: record it,
        apply its authored environment turn, and return the context payload.
        The record IS the state — standing shifts, armed fights, and quest
        moves all derive from it, so by the time the context builds this turn,
        the world has already changed."""
        wev = getattr(self.session, "world_events", None) or {}
        if not wev:
            return None
        events = self.session.store.read_all()
        day = world_clock.current_day(events)
        tiers = {fid: faction_standing.tier_for(s)
                 for fid, s in self._faction_scores().items()}
        ev = timed_events.due_event(wev, events, day=day, standing_tiers=tiers,
                                    quests=self.session.quests)
        if ev is None:
            return None
        # "Present" walks the parent chain: an event at Brightvale is witnessed
        # from any place inside Brightvale.
        places = self.session.places or {}
        present, cur, seen = False, self.session.location, set()
        while ev.place is not None and cur in places and cur not in seen:
            if cur == ev.place:
                present = True
                break
            seen.add(cur)
            cur = places[cur].parent
        self.session.emit_log(EventKind.WORLD_EVENT, event_id=ev.id, day=day,
                              place=ev.place, present=present)
        if ev.environment is not None:
            s = self.session
            nt = (ev.environment.time_of_day
                  if ev.environment.time_of_day and ev.environment.time_of_day != s.time_of_day
                  else None)
            nw = (ev.environment.weather
                  if ev.environment.weather and ev.environment.weather != s.weather
                  else None)
            if nt or nw:
                s.emit_environment(nt, nw, reason=f"world event {ev.id}")
        self.debug.append("world_event", event_id=ev.id, day=day,
                          place=ev.place, present=present)
        node = places.get(ev.place) if ev.place else None
        effects = []
        if ev.standing:
            effects.append("faction standing has shifted (already real — see FACTION STANDING)")
        if ev.encounter is not None:
            effects.append("a fight now lies in wait (secret — never announce it)")
        if ev.unlock_quest is not None:
            effects.append("a new opportunity has opened (see the quest offers)")
        if ev.retire_quest is not None:
            effects.append("an opportunity has closed — it can no longer be taken up")
        return {"announce": ev.announce, "briefing": ev.briefing,
                "place_name": (node.name if node else ev.place), "present": present,
                "effects": effects}

    def _compute_offers(self) -> tuple[dict, set, set]:
        """(authored defs, chain-eligible ids, offered-here ids) for this turn. Eligible is
        replay-derived from the log; here is eligible narrowed to quests whose source NPC is
        present or whose place is the party's location."""
        authored = self.session.authored_quests
        if not authored:
            return authored, set(), set()
        # Level-gate (difficulty S2): the strongest HERO's level opens a quest's
        # min_party_level door — gated quests stay invisible to the DM until then.
        # Companions are excluded: a creature's level tracks its form's CR (a
        # grown drake must not open doors the heroes haven't earned), and person
        # companions level at exact parity anyway.
        party_level = max((c.level for c in self.repo.party() if not c.companion),
                          default=1)
        eligible = offers.offerable_ids(authored, self.session.store.read_all(),
                                        self.session.quests, party_level=party_level)
        # Standing-gate (living-world W2): min_standing quests stay invisible until
        # the party's tier with that faction warms up — same lean-context contract.
        factions = getattr(self.session, "factions", None) or {}
        if factions:
            tiers = {fid: faction_standing.tier_for(score)
                     for fid, score in self._faction_scores().items()}
            eligible = faction_standing.filter_offerable(eligible, authored, tiers)
        # World-event overlay (living-world W4): a fired event can OPEN a quest
        # (explicit unlock outranks chain/level/standing gates — the author
        # scheduled it deliberately) or WITHDRAW one; retire always wins last.
        # Quests already taken never re-offer, unlocked or not.
        wev = getattr(self.session, "world_events", None) or {}
        if wev:
            unlocked, retired = timed_events.quest_overlay(
                wev, self.session.store.read_all())
            taken = offers.started_authored_ids(self.session.quests)
            eligible |= {qid for qid in unlocked if qid in authored and qid not in taken}
            eligible -= retired
        loc = self.session.location
        present = {n.id for n in self.repo.npcs() if loc is None or n.home_location == loc}
        return authored, eligible, offers.offered_here(eligible, authored, loc, present)

    def _faction_scores(self) -> dict:
        """{faction id: score} for this turn — the one derivation everything
        reads (context, offer gate); empty when the pack authors no factions."""
        factions = getattr(self.session, "factions", None) or {}
        if not factions:
            return {}
        events = self.session.store.read_all()
        wev = getattr(self.session, "world_events", None) or {}
        extra = (timed_events.standing_deltas(wev, factions, events)
                 if wev else None)
        return faction_standing.standing_map(
            factions, self.session.authored_quests, events,
            self.session.quests, extra=extra)

    def _faction_context(self) -> list[dict] | None:
        """The FACTION STANDING payload for build_context: every authored faction
        with its current tier, score, DM-secret agenda, and whether the PARTY
        knows it yet. None when the pack authors none (the section vanishes)."""
        factions = getattr(self.session, "factions", None) or {}
        if not factions:
            return None
        scores = self._faction_scores()
        known = faction_standing.known_ids(
            factions, self.session.authored_quests,
            self.session.store.read_all(), self.session.quests)
        return [{"id": fid, "name": f.name, "agenda": f.agenda,
                 "score": scores.get(fid, 0),
                 "tier": faction_standing.tier_for(scores.get(fid, 0)),
                 "known": fid in known}
                for fid, f in factions.items()]

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
                    on_text=(on_text if attempt == 0 else None), table_prompt=table_prompt,
                    stable_context=self._story_so_far())
            except (ValidationError, RuntimeError) as e:
                # The model returned an empty/malformed resolution (e.g. an empty tool
                # call). Treat it like a failed attempt: feed it back and retry, rather
                # than crashing the player's turn.
                feedback = ("Your last reply was empty or malformed. Reply again with a "
                            "complete TurnResolution — narration is required.")
                self.debug.append("anomaly", stage="resolve", attempt=attempt, error=str(e))
                continue
            narration = resolution.narration
            if getattr(resolution, "thinking", None):
                # Per-turn scratchpad (W4): the DM's hidden reasoning. Never shown to the
                # player; logged to the non-replayed debug channel so it's inspectable.
                self.debug.append("thinking", stage="resolve", text=resolution.thinking)
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
                elif rt.force_end_session:
                    self.session.emit_force_end(rt.reason)
                elif (rt.wrap_proposed or rt.rest_proposed is not None
                      or rt.recruit_proposed is not None or rt.dismiss_proposed is not None):
                    pass    # proposals only — nothing is recorded; the player confirms the
                            # wrap (POST /api/wrap), the rest (POST /api/rest), or the
                            # companion change (POST /api/companion). Surfaced below.
                elif rt.quest_start is not None:
                    self.session.emit_quest_start(
                        rt.quest_start.title, rt.quest_start.text, rt.reason)
                elif rt.quest_accept is not None:
                    self.session.emit_quest_accept(
                        self.session.authored_quests[rt.quest_accept.quest_id], rt.reason)
                elif rt.quest_update is not None:
                    self.session.emit_quest_update(
                        rt.quest_update.quest_id, status=rt.quest_update.status,
                        note=rt.quest_update.note, outcome=rt.quest_update.outcome,
                        reward_settled=rt.quest_update.reward_settled,
                        reason=rt.reason)
                elif rt.env_time is not None or rt.env_weather is not None:
                    # set_environment (W6): the DM turned time/weather. Record only an
                    # ACTUAL change so we don't needlessly re-cue the soundscape.
                    s = self.session
                    nt = rt.env_time if rt.env_time and rt.env_time != s.time_of_day else None
                    nw = rt.env_weather if rt.env_weather and rt.env_weather != s.weather else None
                    if nt or nw:
                        s.emit_environment(nt, nw, reason=rt.reason)
                elif rt.note_text is not None:
                    self.session.emit_notebook_note(rt.note_text)   # dm_note (W4): durable DM memory
                elif rt.standing_faction is not None:
                    # adjust_standing (living-world W2): a bounded nudge (already
                    # clamped at resolution) — or, at delta 0, the reveal. The
                    # record is the state: standing derives from these on replay.
                    self.session.emit_log(
                        EventKind.FACTION_STANDING_CHANGED,
                        faction=rt.standing_faction, delta=rt.standing_delta,
                        reason=rt.reason)
                else:
                    self.session.emit_state(
                        EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
            applied = resolved
            success = True
            break

        meta_notice: str | None = None
        if not success:
            meta_notice = "the DM lost the thread — try rephrasing."
            if not narration:        # all attempts failed to produce usable narration
                narration = "The Phantom's gaze drifts a moment, the thread of the scene slipping."
            self.debug.append("anomaly", stage="turn", note="forced narration-only after retries")
        elif applied and len(narration.strip()) < MIN_TURN_PROSE:
            # The model did the state work but starved the story: under tool_choice:auto
            # (W6) it CAN spend its whole turn on tool calls and skip prose, and no prompt
            # fully prevents it (v0.9 playtest, finding #1 — a nat-20 landlord pitch and a
            # quest-reveal both landed as one bare travel line). Enforce in code: one
            # follow-up, narration-only pass. Context is REBUILT first, so a turn that
            # travelled now narrates the arrival with the destination's cast in hand
            # (finding #3) and a resolved roll gets its payoff on screen.
            narration = await self._narrate_followup(
                player_text, assessment, roll_result, narration, applied,
                table_prompt, on_text=on_text)
        if success and not narration.strip():
            # Last-resort floor (e.g. the follow-up itself failed): synthesize a brief
            # line so the player never gets an empty bubble.
            narration = self._narrate_applied(applied)

        self.debug.append("narration", text=narration)
        rest_pending = next((rt.rest_proposed for rt in applied
                             if rt.rest_proposed is not None), None)
        if rest_pending is not None:
            # The DM's grant (S3): on a gated table this is what opens /api/rest.
            self.session.pending_rest = rest_pending
        companion_pending = self._companion_pending(applied)
        if companion_pending is not None:
            # The DM's companion proposal (companions S1): what opens /api/companion.
            self.session.pending_companion = companion_pending
        return TurnReport(
            player_text=player_text, assessment=assessment, narration=narration,
            roll_outcome=roll_outcome, roll_result=roll_result, applied=applied,
            meta_notice=meta_notice,
            wrap_pending=any(rt.wrap_proposed for rt in applied),
            rest_pending=rest_pending,
            companion_pending=companion_pending,
            session_force_ended=any(rt.force_end_session for rt in applied),
        )

    def _companion_pending(self, applied: list[ResolvedTool]) -> dict | None:
        """The turn's companion proposal (recruit or dismissal), shaped for the
        confirm bar + POST /api/companion. First one wins if the model somehow
        emitted both; `kind` tells the UI whether a person or a creature is at
        the door (a person carries a class sheet, a creature doesn't). A recruit
        the party PAID for this same turn (a purse debit rode along — the kennel
        was settled with transact) is recorded with origin 'purchased' (S3)."""
        paid = any(
            op.op == "coin" and (op.delta or 0) < 0
            and self.repo.get_character(op.char).kind == "pc"
            for rt in applied for op in rt.ops)
        for rt in applied:
            char_id = rt.recruit_proposed or rt.dismiss_proposed
            if char_id is None:
                continue
            char = self.repo.get_character(char_id)
            return {"action": "recruit" if rt.recruit_proposed else "dismiss",
                    "char_id": char.id, "name": char.name,
                    "kind": "person" if char.sheet is not None else "creature",
                    "origin": "purchased" if (paid and rt.recruit_proposed) else "recruited",
                    "reason": rt.reason}
        return None

    async def _run_combat(self, player_text: str, assessment: TurnAssessment) -> TurnReport:
        """Summoned-tool branch (§8). Stage the fight: a non-combat exit
        (parley/flee/bribe) resolves instantly; a real fight is STAGED — written
        to an encounter file and held on the session — and the turn returns with
        the "⚔ Enter the Arena" signal. The fight is played (and its single
        COMBAT_RESULT recorded) later, in `enter_combat`, when the player enters.

        The encounter budget (difficulty S2) guards this door: an improvised
        fight over the table's caps BOUNCES — the DM re-assesses the same turn
        with the violation spelled out, invisibly to the player, up to twice —
        before degrading to the no-fight narration. The developer codeword
        bypasses the budget entirely (the test hook stages anything)."""
        budget = None
        if "etteilbuo" not in player_text.lower():
            difficulty = getattr(self.session, "difficulty", DEFAULT_DIFFICULTY)
            budget = budget_for(self.repo.party() or [self.repo.pc()],
                                difficulty.encounter_challenge)
        outcome = None
        failure = "no stageable encounter"
        for attempt in range(3):            # the first try + up to two bounces
            try:
                outcome = stage_combat(
                    assessment.encounter, self.repo, self.session,
                    assessment=assessment, player_text=player_text, budget=budget,
                )
                break
            except BudgetError as e:
                failure = str(e)
                self.debug.append("anomaly", stage="combat_budget",
                                  attempt=attempt, error=str(e))
                if attempt == 2:
                    break
                correction = (
                    "\n\nENCOUNTER CORRECTION (system — the player never sees this): "
                    f"your previous encounter was rejected: {e} Re-assess the SAME "
                    "player turn and fill `encounter` again so it fits the budget — "
                    "fewer enemies, or a weaker creature serving the same fiction. "
                    "Do not narrate the rejected creatures.")
                try:
                    reassessed = await self.brain.assess(
                        player_text, self._build_context(player_text) + correction,
                        stable_context=self._story_so_far())
                except (ValidationError, RuntimeError) as err:
                    self.debug.append("anomaly", stage="combat_budget",
                                      attempt=attempt, error=repr(err))
                    break
                if reassessed.encounter is None:
                    break                    # the DM chose not to fight after all
                assessment = reassessed
            except CombatError as e:
                failure = str(e)
                self.debug.append("anomaly", stage="combat", error=str(e))
                break
        if outcome is None:
            narration = "The threat dissolves into confusion before anything is struck."
            self.debug.append("narration", text=narration)
            return TurnReport(
                player_text=player_text, assessment=assessment, narration=narration,
                meta_notice=f"combat could not be staged: {failure}",
            )

        # Non-combat exit — resolved without the Arena, recorded immediately.
        if outcome.result is not None:
            return self._emit_combat_result(outcome.result, player_text, assessment)

        # A real fight: hold it pending and prompt the player to enter the Arena.
        self.session.pending_combat = outcome.pending
        # Dev visibility (S2): the fight's CR arithmetic next to the budget it
        # passed — readable at GET /api/debug/log.
        staged_crs = {c.name_override: float(getattr(c.creature_data, "challenge_rating", 0) or 0)
                      for c in outcome.pending.plan.encounter.combatants if c.team == "enemy"}
        self.debug.append("combat_budget", stage="staged", enemies=staged_crs,
                          total_cr=round(sum(staged_crs.values()), 3),
                          budget=(budget.describe() if budget else "bypassed (dev codeword)"))
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
        per-member share. A solo party keeps the lead's op as-is.

        Person companions share at exact parity (companions S2 lock) — they level
        like anyone. CREATURE companions don't draw a share: a wolf can't spend XP,
        and letting it dilute the pool would tax the party for keeping a pet (its
        growth is authored tiers, not XP)."""
        party = [c for c in self.repo.party()
                 if not (c.companion and c.sheet is None)]
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

        deaths = self._companion_deaths(result)
        narration = result.narrative_digest  # Phase 1/2: digest IS the narration.
        for d in deaths:
            narration += (f"\n\n{d['name']} does not rise. On this table, the fallen "
                          "stay fallen — they will not travel with you again.")
        self.debug.append("narration", text=narration)
        return TurnReport(
            player_text=player_text, assessment=assessment, narration=narration,
            combat_result=result, companion_deaths=deaths,
        )

    def _companion_deaths(self, result: CombatResult) -> list[dict]:
        """Companion mortality (S3): with the table's `companion_death` dial ON, a
        companion the fight left at 0 HP truly dies — a COMPANION_DIED event removes
        them from the roster for good (revival is whatever the SRD offers anyone).
        With the dial off (the default), they get the same narrated 'out' a downed
        hero gets today: hp 0, story continues, nobody is taken from the player."""
        difficulty = getattr(self.session, "difficulty", DEFAULT_DIFFICULTY)
        if not difficulty.companion_death:
            return []
        deaths: list[dict] = []
        for comp in list(self.repo.companions()):
            if comp.id in result.hp_final and self.repo.get_character(comp.id).hp <= 0:
                self.session.emit_companion_died(comp.id, comp.name)
                deaths.append({"char_id": comp.id, "name": comp.name})
        return deaths

    async def enter_combat(self) -> TurnReport:
        """Play the staged fight: spawn The Arena (blocking, in a thread so the web
        server stays responsive), map the result back through the bridge, and record
        it as the single COMBAT_RESULT event. Clears the pending lock."""
        import asyncio

        pending = self.session.pending_combat
        if pending is None:
            raise CombatError("no combat is staged")
        # A keyed encounter is SPENT the moment the player commits to it
        # (living-world W1): the fired record lands here, not at staging, so a
        # quit or crash at the ⚔ prompt re-stages the authored fight on reload
        # instead of silently marking it fought.
        if getattr(pending, "keyed", None):
            place, enc_id = pending.keyed
            self.session.emit_log(EventKind.KEYED_ENCOUNTER_TRIGGERED,
                                  place=place, encounter_id=enc_id)
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
        # The campaign-over ritual (S4): on a hardcore table, a lost fight is the
        # end — all of the party fell. The DM writes the ending + the chronicle's
        # final entry, the notes seal like any wrap, and the table locks for good.
        difficulty = getattr(self.session, "difficulty", DEFAULT_DIFFICULTY)
        if result.outcome == "defeat" and difficulty.hardcore:
            report = await self._end_campaign(report)
        return report

    async def _end_campaign(self, report: TurnReport) -> TurnReport:
        """Hardcore TPK: run the campaign-over ritual. One model call (retried
        once) writes the ending; a failure still ends the campaign with a plain
        epitaph — the lock is the promise, the prose is best-effort."""
        events = self.session.store.read_all()
        turns = transcript_turns(events)
        transcript_text = "\n".join(
            f'{"PLAYER" if t["role"] == "player" else "DM"}: {t["text"]}' for t in turns)
        ending = None
        for attempt in range(2):
            try:
                ending = await self.brain.narrate_campaign_end(
                    transcript_text, self._build_context(),
                    table_prompt=render_table_prompt(self.session.table),
                    stable_context=self._story_so_far())
                break
            except Exception as e:
                self.debug.append("anomaly", stage="campaign_end", attempt=attempt,
                                  error=repr(e))
        if ending is None:
            from ..schemas import CampaignEnding
            ending = CampaignEnding(
                narration="Here the tale ends: the whole party has fallen, and on this "
                          "table the fallen stay fallen. Thank you for playing it out "
                          "to the last.",
                player_facing="The campaign ended with the party's fall in battle.",
                dm_private="Campaign ended: hardcore total party defeat.")
        # Seal the final notes like any wrap, then the terminal event + lock.
        self.session.emit_wrap(ending.player_facing, ending.dm_private,
                               reason="the campaign ended — the party fell")
        self.session.emit_campaign_end("tpk", ending.narration)
        self.debug.append("narration", text=ending.narration)
        return TurnReport(
            player_text=report.player_text, assessment=report.assessment,
            narration=f"{report.narration}\n\n{ending.narration}",
            combat_result=report.combat_result,
            session_force_ended=True,
        )

    async def wrap_session(self, write_notes: bool = True) -> WrapReport:
        """Wrap the session in progress (W5): the DM writes two-faced notes from the FULL
        session transcript (the one time it sees the whole thing, not just beats), records
        them on a wrap marker, and the beats window resets — the session is sealed into its
        note, and play resumes fresh as the next session. `write_notes=False` (Offline Mode)
        wraps with no notes rather than invoke a model. A note-writing failure is retried
        once, then REFUSES the wrap (the player can press Wrap again) — sealing a session
        with empty notes silently destroys its continuity (v0.9 playtest, finding #6).
        Refuses a wrap when nothing has happened yet."""
        events = self.session.store.read_all()
        turns = transcript_turns(events)
        if not turns:
            return WrapReport(wrapped=False, notice="there's nothing to wrap yet — play a little first")
        notes = None
        if write_notes:
            transcript_text = "\n".join(
                f'{"PLAYER" if t["role"] == "player" else "DM"}: {t["text"]}' for t in turns)
            table_prompt = render_table_prompt(self.session.table)
            last_err: Exception | None = None
            for attempt in range(2):
                try:
                    notes = await self.brain.write_session_notes(
                        transcript_text, self._build_context(), table_prompt=table_prompt,
                        stable_context=self._story_so_far())
                    break
                except Exception as e:
                    last_err = e
                    self.debug.append("anomaly", stage="wrap", attempt=attempt, error=str(e))
            if notes is None:
                # Don't seal: an empty note is a hole in the campaign's memory the player
                # can never refill. Leave the session open and let them wrap again.
                return WrapReport(
                    wrapped=False,
                    notice=f"the DM couldn't write this session's notes ({last_err}) — "
                           "nothing was lost; try wrapping again")
        pf = notes.player_facing if notes else ""
        dm = notes.dm_private if notes else ""
        self.session.emit_wrap(pf, dm)
        self.history = []    # seal the session; its beats now live on in the note, not the head
        self.debug.append("note", stage="wrap", wrote_notes=bool(notes))
        return WrapReport(wrapped=True, player_facing=pf, dm_private=dm)

    def _record_beat(self, report: TurnReport, caused_by: int | None = None) -> None:
        """Finalize a completed turn's memory: build the compact continuity beat, keep it
        in short-term memory, and record it durably alongside the verbatim narration (W2).
        This is the single choke point both turn paths (`take_turn`, `enter_combat`) pass
        through, so every narrated turn is captured exactly once. `caused_by` links the
        durable record to the PLAYER_MESSAGE that prompted it (None for Arena entry)."""
        if report.combat_pending:
            # A staged-but-unresolved fight: the transcript keeps the staging
            # line, but the continuity beat waits for the RESOLUTION report
            # that follows the Arena — otherwise every fight wrote TWO beats
            # for one player turn (the same player text twice), flooding the
            # DM's small recent-turns window with duplicates.
            self.session.emit_narration(report.narration, "", caused_by=caused_by)
            return
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
            elif rt.quest_accept is not None:
                parts.append(f"took up quest {rt.quest_accept.quest_id}")
            elif rt.quest_update is not None:
                state = rt.quest_update.status or "updated"
                parts.append(f"quest {rt.quest_update.quest_id} → {state}")
            elif rt.force_end_session:
                parts.append("force-ended the session")
            elif rt.wrap_proposed:
                parts.append("proposed wrapping the session")
            elif rt.rest_proposed is not None:
                parts.append(f"proposed a {rt.rest_proposed} rest")
            elif rt.env_time is not None or rt.env_weather is not None:
                parts.append("environment → " + ", ".join(
                    v for v in (rt.env_time, rt.env_weather) if v))
            elif rt.note_text is not None:
                parts.append("jotted a DM note")
            elif rt.standing_faction is not None:
                parts.append(f"standing[{rt.standing_faction}] "
                             f"{rt.standing_delta:+d}" if rt.standing_delta
                             else f"revealed faction {rt.standing_faction}")
            else:
                parts.append(f"effect({rt.tool}): {self._ops_summary(rt.ops)}")
        if report.combat_result is not None:
            parts.append(f"combat → {report.combat_result.outcome}")
        if report.trade_open is not None:
            parts.append(f"opened trade with {report.trade_open.merchant_name}")
        narr = " ".join(report.narration.split())
        if narr:
            parts.append(f'DM: "{narr[:140]}"')
        beat = " | ".join(parts)
        self.history.append(beat)
        if len(self.history) > HISTORY_CAP:
            self.history = self.history[-HISTORY_CAP:]
        # Durable capture: the full narration (rebuilds the player transcript) + the beat
        # (rehydrates this in-memory history on reload). Inert prose, no-op on replay (W2).
        self.session.emit_narration(report.narration, beat, caused_by=caused_by)

    async def _narrate_followup(self, player_text: str, assessment, roll_result,
                                first_pass: str, applied, table_prompt: str,
                                on_text=None) -> str:
        """The narration-only enforcement pass (finding #1): the model resolved the
        turn's state changes but wrote (almost) no prose. Ask it — with context REBUILT
        after the tools applied, so a travel turn now sees its destination's scene and
        cast — to write the turn's full narration. Its tool calls, if any, are DROPPED:
        everything is already applied, and a second application would double-charge.
        Falls back to whatever the first pass produced if this call fails too."""
        summary = "; ".join(f"{rt.tool} ({rt.reason})" for rt in applied) or "none"
        feedback = (
            f"You already resolved this turn's state changes — {summary} — but your reply "
            "carried almost no story text, so the player has seen NOTHING happen. Write this "
            "turn's FULL narration now, in prose: what the player did, the journey and the "
            "arrival scene (with the people present) if the party travelled, and the outcome "
            "of any roll. Do NOT emit tool calls — every state change is already applied.")
        try:
            resolution = await self.brain.resolve(
                player_text, assessment, roll_result, self._build_context(player_text),
                feedback, on_text=on_text, table_prompt=table_prompt,
                stable_context=self._story_so_far())
        except Exception as e:      # enforcement must never cost the player the turn
            self.debug.append("anomaly", stage="narrate_followup", error=str(e))
            return first_pass
        if resolution.tool_calls:
            self.debug.append(
                "anomaly", stage="narrate_followup",
                note=f"dropped {len(resolution.tool_calls)} tool call(s) — already applied")
        text = resolution.narration.strip()
        if not text:
            return first_pass
        self.debug.append("note", stage="narrate_followup", chars=len(text))
        return f"{first_pass.strip()}\n\n{text}" if first_pass.strip() else text

    def _narrate_applied(self, applied) -> str:
        """A minimal narration floor for a successful turn the model left wordless (W6:
        tool_choice:auto lets it emit tools with no text). Travel-aware so a bare `travel`
        still announces the move; otherwise a soft continuity line."""
        for rt in applied:
            if rt.travel_to is not None:
                node = self.session.places.get(rt.travel_to)
                return f"You make your way to {node.name if node is not None else 'your destination'}."
        return "You press on, the moment passing quietly."

    @staticmethod
    def _ops_summary(ops) -> str:
        bits = []
        for o in ops:
            if o.op == "coin":
                from ..coin import format_cp
                d = o.delta or 0
                bits.append(f"{o.char} {'+' if d >= 0 else '-'}{format_cp(abs(d))}")
            elif o.op == "gold":     # legacy op (pre-coin saves)
                bits.append(f"{o.char} {o.delta:+d} gp")
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
