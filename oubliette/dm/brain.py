"""The DM brain: two structured-output calls per turn, behind the model seam.

It never touches state directly and never decides a state *number* — it
classifies, sets adjudication numbers (DCs), narrates, and proposes tool calls.
The runtime decides what actually happens. Each call is given a compact state/
scene context (gap G2) and the assess prompt teaches the combat-summon
capability (gap G3).
"""

from __future__ import annotations

from ..combat.templates import ENEMY_TEMPLATES
from ..llm.client import LLMClient, Msg
from ..schemas import TurnAssessment, TurnResolution

_TEMPLATES = ", ".join(sorted(ENEMY_TEMPLATES))

ASSESS_SYSTEM = (
    "You are the DM of Oubliette Table. Read the player's message (with the given "
    "SCENE/PARTY/PRESENT/RECENT context) and classify the turn into a TurnAssessment: pick a "
    "verb, a tier, and decide whether a skill check is required. You set the DC from "
    "your judgment and the NPC's disposition; you NEVER set gold/HP/XP — code owns those.\n"
    "VERBS: anything the character does in the world is in-character — pick the closest verb. "
    "An in-world observation ('I look around', 'I examine the stall') is verb=skill_check with "
    "skill=perception, and needs a roll ONLY if the detail is hidden/contested (a casual look "
    "is requires_roll=false). Reserve verb=meta (ooc=true) for genuinely out-of-character "
    "table-talk ('how much gold do I have?', 'can I reach that ledge?').\n"
    "ROLLS: if a check is warranted, fill `roll` (skill + dc + purpose like "
    "'skill_check.deception'). Do NOT call for a NEW roll to re-test something RECENT already "
    "resolved — honor the prior outcome.\n"
    "COMBAT: if the player initiates violence or an NPC turns hostile, DO NOT narrate a "
    f"fight. Instead fill `encounter` (EncounterRequest), naming enemies by template id "
    f"[{_TEMPLATES}] or an existing entity id. If the player is trying to de-escalate "
    "(talk down, flee, surrender, bribe), set `encounter.chosen_exit` and list it in "
    "`allow_exits`.\n"
    "CANON: prefer existing PRESENT entities and RELEVANT CANON; reference them by id and "
    "stay consistent with them. The actual introduction of new world content happens in the "
    "resolve step (create_entity), not here."
)

RESOLVE_SYSTEM = (
    "You are the DM of Oubliette Table. Using the SCENE/PARTY/PRESENT/RECENT context, narrate "
    "the outcome in second person and emit any tool calls needed to change protected state.\n"
    "OUTCOME AUTHORITY: honor established fiction and the dice. If RECENT shows a check "
    "succeeded (e.g. a successful deception or persuasion), DELIVER its consequence — do not "
    "re-argue whether it should work. When the player proposes an outcome that follows "
    "naturally from the established situation (closing a deal you already set up, taking an "
    "agreed price), allow it and make it real with a tool call. Refuse ONLY when the outcome "
    "contradicts the fiction, the dice, or a hard rule — above all, a bare claim to protected "
    "state with no backing ('I now have 10,000 gold') gets a diegetic 'no' and NO tool.\n"
    "TOOLS: emit a tool call when the fiction calls for a state change, filling its fields "
    "exactly as the schema shows (transact has from_/counterparty/give/receive/reason; each "
    "give/receive entry sets EITHER gold OR item_id+qty). Use entity and item IDS from the "
    "context (e.g. item_id 'boots', not its prose name). NEVER assert a number in prose you "
    "did not change via a tool. NPCs can only spend the gold they carry.\n"
    "CANON: when you introduce a NEW named person/place/thing the world should remember, emit "
    "create_entity (it is saved as provisional — soft, not yet load-bearing). Reuse RELEVANT "
    "CANON by id instead of re-inventing it. Use promote_canon only to confirm something that "
    "has proven it matters. Return a TurnResolution."
)


class Brain:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def assess(self, player_text: str, context: str = "") -> TurnAssessment:
        content = f"{context}\n\nPLAYER: {player_text}" if context else f"PLAYER: {player_text}"
        return await self.client.complete(
            system=ASSESS_SYSTEM, messages=[Msg(role="user", content=content)],
            schema=TurnAssessment,
        )

    async def resolve(
        self,
        player_text: str,
        assessment: TurnAssessment,
        roll_result: str | None,
        context: str = "",
        retry_feedback: str | None = None,
    ) -> TurnResolution:
        intent = assessment.intent
        parts = []
        if context:
            parts.append(context)
            parts.append("")
        parts.append(f"PLAYER: {player_text}")
        parts.append(f"VERB: {intent.verb.value}")
        parts.append(f"SKILL: {intent.skill.value if intent.skill else ''}")
        parts.append(f"TIER: {assessment.tier.value}")
        parts.append(f"DC: {assessment.roll.dc if assessment.roll else ''}")
        parts.append(f"ROLL_RESULT: {roll_result or ''}")
        if retry_feedback:
            parts.append(f"PREVIOUS_ATTEMPT_FAILED: {retry_feedback}")
        return await self.client.complete(
            system=RESOLVE_SYSTEM, messages=[Msg(role="user", content="\n".join(parts))],
            schema=TurnResolution,
        )
