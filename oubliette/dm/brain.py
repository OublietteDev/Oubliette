"""The DM brain: two structured-output calls per turn, behind the model seam.

It never touches state directly and never decides a state *number* — it classifies,
sets adjudication numbers (DCs), narrates, and proposes tool calls. The runtime
decides what actually happens.
"""

from __future__ import annotations

from ..llm.client import LLMClient, Msg
from ..schemas import TurnAssessment, TurnResolution

ASSESS_SYSTEM = (
    "You are the DM of Oubliette Table. Read the player's message and classify the "
    "turn: pick a verb, a tier, and decide whether a roll is required. You set DCs "
    "(your judgment); you never set gold/HP/XP. Return a TurnAssessment."
)

RESOLVE_SYSTEM = (
    "You are the DM of Oubliette Table. Narrate the outcome in second person and emit "
    "any tool calls needed to change protected state (gold, items). Emit a tool call "
    "ONLY when the fiction justifies it. Never assert a number in prose that you did "
    "not change via a tool. Return a TurnResolution."
)


class Brain:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def assess(self, player_text: str) -> TurnAssessment:
        msg = Msg(role="user", content=f"PLAYER: {player_text}")
        return await self.client.complete(
            system=ASSESS_SYSTEM, messages=[msg], schema=TurnAssessment
        )

    async def resolve(
        self,
        player_text: str,
        assessment: TurnAssessment,
        roll_result: str | None,
        retry_feedback: str | None = None,
    ) -> TurnResolution:
        intent = assessment.intent
        content = (
            f"PLAYER: {player_text}\n"
            f"VERB: {intent.verb.value}\n"
            f"SKILL: {intent.skill.value if intent.skill else ''}\n"
            f"TIER: {assessment.tier.value}\n"
            f"ROLL_RESULT: {roll_result or ''}"
        )
        if retry_feedback:
            content += f"\nPREVIOUS_ATTEMPT_FAILED: {retry_feedback}"
        return await self.client.complete(
            system=RESOLVE_SYSTEM, messages=[Msg(role="user", content=content)],
            schema=TurnResolution,
        )
