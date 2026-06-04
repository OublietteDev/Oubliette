"""A scripted, deterministic LLMClient — the Phase 0 dev/test double.

It is NOT intelligent: it pattern-matches the four-step §14.1 acceptance
transcript (and degrades to an honest notice on anything else). Its whole job is
to prove the *plumbing* — state, tools, rolls, routing, the loop — runs end to
end with no API key. Swap in `AnthropicLLMClient` for an actual DM.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..combat.schemas import EncounterRequest, EnemyRef, ExitKind, TerrainSpec
from ..enums import Ability, Skill, Tier, Verb, may_canonize
from ..schemas import Intent, RollRequest, TurnAssessment, TurnResolution
from ..tools.schemas import CreateEntity, Transact, ValueEntry
from ..trade.schemas import TradeRequest
from .client import Msg


def _joined(messages: list[Msg]) -> str:
    return "\n".join(m.content for m in messages)


def _field(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.upper().startswith(key.upper() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


class ScriptedLLMClient:
    """Implements the `LLMClient` protocol with canned, deterministic output."""

    async def complete(self, *, system: str, messages: list[Msg], schema: type[BaseModel]) -> BaseModel:
        text = _joined(messages)
        if schema is TurnAssessment:
            return self._assess(text)
        if schema is TurnResolution:
            return self._resolve(text)
        raise NotImplementedError(f"ScriptedLLMClient has no script for {schema.__name__}")

    # --- first call: classify + decide on a roll -----------------------------
    def _assess(self, text: str) -> TurnAssessment:
        player = _field(text, "PLAYER").lower()

        def assessment(verb, tier, *, skill=None, ooc=False, roll=None, hint="",
                       encounter=None, trade=None):
            return TurnAssessment(
                intent=Intent(raw_text=_field(text, "PLAYER"), verb=verb, skill=skill, ooc=ooc),
                tier=tier,
                resolution_hint=hint,
                requires_roll=roll is not None,
                roll=roll,
                encounter=encounter,
                trade=trade,
            )

        # Trade — browse the merchant's wares (opens the trade window).
        if any(p in player for p in ("wares", "what do you have", "what are you selling",
                                     "show me your", "for sale", "your stock", "your goods",
                                     "browse", "see what you")):
            return assessment(Verb.TRADE, Tier.AUTHORED, hint="Open the trade window.",
                              trade=TradeRequest(merchant_id="merchant_thom"))

        # Non-combat exit: talk the raiders down (Phase 1 parley exit, §8).
        if (("talk" in player and "down" in player) or "parley" in player
                or "negotiate" in player or "stand down" in player) and \
                any(w in player for w in ("bandit", "them", "raider", "wolf")):
            return assessment(
                Verb.SKILL_CHECK, Tier.RECOMBINED, skill=Skill.PERSUASION,
                hint="Player tries to defuse the standoff; resolve via the parley exit.",
                encounter=EncounterRequest(
                    kind="standoff", enemies=[EnemyRef(ref="bandit", count=2)],
                    terrain=TerrainSpec(kind="open"),
                    allow_exits=[ExitKind.PARLEY, ExitKind.FLEE, ExitKind.BRIBE],
                    chosen_exit=ExitKind.PARLEY,
                ),
            )

        # Hostility: the narrator emits an encounter request (§8/§10).
        if any(w in player for w in ("attack", "strike", "fight", "swing at", "stab", "kill")) \
                and any(w in player for w in ("bandit", "them", "raider", "wolf", "enemy")):
            enemy = "wolf" if "wolf" in player else "bandit"
            return assessment(
                Verb.ATTACK, Tier.RECOMBINED,
                hint="Player initiates combat; stage the encounter from live state.",
                encounter=EncounterRequest(
                    kind="brawl", enemies=[EnemyRef(ref=enemy, count=1)],
                    terrain=TerrainSpec(kind="open"),
                    allow_exits=[ExitKind.FLEE, ExitKind.PARLEY],
                ),
            )

        # Step 4 — the fiat. No fiction, no roll: a diegetic refusal.
        if ("10,000" in player or "10000" in player or
                ("i now have" in player and "gold" in player)):
            return assessment(Verb.META, Tier.DENIED, ooc=True,
                              hint="Bald assertion of wealth; refuse in-world.")

        # Step 3 — closing the deal.
        if any(w in player for w in ("sold", "it's a deal", "deal", "i accept", "agreed")):
            return assessment(Verb.TRADE, Tier.RECOMBINED,
                              hint="Player accepts the haggled price; settle the exchange.")

        # Step 2 — the con. The DM calls a deception check and sets the DC (D8).
        if any(w in player for w in ("heirloom", "priceless", "deceiv", "lie", "con ", "bluff")) \
                or ("tell" in player and "merchant" in player) \
                or ("boots" in player and "merchant" in player):
            return assessment(
                Verb.SKILL_CHECK, Tier.RECOMBINED, skill=Skill.DECEPTION,
                hint="Convince Thom the boots are precious; DC by his shrewdness.",
                roll=RollRequest(skill=Skill.DECEPTION, ability=Ability.CHA, dc=15,
                                 purpose="skill_check.deception"),
            )

        # Canon — introducing a new NPC the world hasn't established yet.
        if "old woman" in player:
            return assessment(Verb.SKILL_CHECK, Tier.FREESTYLE, skill=Skill.PERCEPTION,
                              hint="A previously-unestablished NPC; introduce as provisional canon.")

        # Step 1 — looking around. Trivial perception: the DM judges no roll needed.
        if any(w in player for w in ("look", "examine", "inspect", "survey", "glance")):
            return assessment(Verb.SKILL_CHECK, Tier.FREESTYLE, skill=Skill.PERCEPTION,
                              hint="Trivial observation; describe the scene, no roll.")

        # Fallback: scripted double doesn't understand free input.
        return assessment(Verb.META, Tier.FREESTYLE, ooc=True,
                          hint="Unscripted input for the demo double.")

    # --- second call: narrate + emit tool calls ------------------------------
    def _resolve(self, text: str) -> TurnResolution:
        verb = _field(text, "VERB")
        skill = _field(text, "SKILL")
        tier = _field(text, "TIER")
        roll_result = _field(text, "ROLL_RESULT")  # "success" | "failure" | ""
        player = _field(text, "PLAYER").lower()

        # Canon — introduce the old woman as provisional world content.
        if "old woman" in player:
            return TurnResolution(
                narration=("By the well, a weathered old woman looks up from a spread of cards, "
                           "her eyes sharp as flint. 'A name? Names have prices, dear.'"),
                tool_calls=[CreateEntity(
                    entity_type="npc", name="the old woman at the well",
                    text=("A weathered fortune-teller who tends the well in Brightvale's market "
                          "square; speaks in riddles and trades names for coin."),
                    reason="Player approached a previously-unestablished NPC at the well.",
                )],
            )

        if tier == Tier.DENIED.value:
            return TurnResolution(narration=(
                "You announce your sudden fortune to the rafters. The rafters, and "
                "your purse, remain unmoved — coin does not come from saying so."
            ))

        if verb == Verb.TRADE.value:
            return TurnResolution(
                narration=(
                    "Thom counts out the coins one reluctant stack at a time, still "
                    "half-convinced he's been clever. The boots vanish under his counter."
                ),
                tool_calls=[Transact(
                    from_="pc", counterparty="merchant_thom",
                    give=[ValueEntry(item_id="boots", qty=1)],
                    receive=[ValueEntry(gold=250)],
                    reason="Sold the worn boots to Thom as 'dwarven heirlooms' after a successful con.",
                )],
            )

        if verb == Verb.SKILL_CHECK.value and skill == Skill.DECEPTION.value:
            if roll_result == "success":
                return TurnResolution(narration=(
                    "Thom turns the boots over, frowning at the honest wear as if it were "
                    "patina. 'Dwarven, you say...' Greed wins. 'I could go as high as 250.'"
                ))
            return TurnResolution(narration=(
                "Thom snorts and drops the boots back on the counter. 'Heirlooms. Right. "
                "And I'm the Duke of Brightvale.' He isn't buying it — or them."
            ))

        if verb == Verb.SKILL_CHECK.value and skill == Skill.PERCEPTION.value:
            return TurnResolution(narration=(
                "The market is a press of bodies and bartering. Thom's stall sits to your "
                "left, hung with belts and boots; a brazier smokes; somewhere a lute is "
                "losing an argument with a goat."
            ))

        return TurnResolution(narration=(
            "[scripted DM] I only know the demo transcript. Set ANTHROPIC_API_KEY and "
            "use the real adapter for open-ended play."
        ))
