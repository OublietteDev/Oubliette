"""Long-rest gating (difficulty S3): the night has a door, a price, and a risk.

On a gated table (rest_strictness "gated"/"dangerous") a LONG rest is a
request, not a button: the player asks in the fiction, the DM grants it with
`propose_rest` (or refuses diegetically), and only a standing grant opens
`POST /api/rest`. A granted night then costs something real — lodging coin in
a safe haven, a ration per hero in the wild — and on a "dangerous" table an
unsafe night may be INTERRUPTED: the party wakes with only a short rest's
recovery. Short rests are never gated, by SRD intent (they already cost hit
dice and exist to be convenient).

Code owns all of it: the DM's grant is a transient session flag, the cost is
StateOps riding the same REST_TAKEN event (replay-safe for free), and the
interruption is a logged roll through the seeded Rng. The numbers below are
the tunable knobs.
"""

from __future__ import annotations

from ..coin import format_cp
from ..record.events import StateOp

RATION_ID = "rations_1_day"      # the SRD travel ration (5 sp) — the wilderness price
INN_COST_CP_PER_HERO = 50        # 5 sp/hero — the SRD's modest inn night
INTERRUPT_ON_OR_UNDER = 2        # unsafe night interrupted on 1-2 of a d6 (1 in 3)


class RestGateError(Exception):
    """A long rest the party can't pay for. The message is player-facing."""


def long_rest_cost(repo, safe_haven: bool) -> tuple[list[StateOp], str]:
    """The ops that pay for tonight, and a display string — or `RestGateError`
    when the party can't cover it. A safe haven bills the shared purse for
    lodging; the wild consumes one ration per hero, drawn from whoever
    carries them."""
    party = repo.party()
    n = max(1, len(party))
    if safe_haven:
        cost = INN_COST_CP_PER_HERO * n
        if repo.party_cp < cost:
            raise RestGateError(
                f"A night's lodging for {n} costs {format_cp(cost)}, and the purse "
                f"holds {format_cp(repo.party_cp)}.")
        return [StateOp.coin("pc", -cost)], f"{format_cp(cost)} for lodging"
    ops: list[StateOp] = []
    need = n
    for p in party:
        for s in p.inventory:
            if s.item_id == RATION_ID and s.qty > 0 and need > 0:
                take = min(s.qty, need)
                ops.append(StateOp.item(p.id, RATION_ID, -take))
                need -= take
    if need:
        raise RestGateError(
            f"The party needs {n} ration{'s' if n != 1 else ''} to camp for the night "
            f"and is short {need} — resupply in town (5 sp each), or find an inn.")
    return ops, f"{n} ration{'s' if n != 1 else ''}"


def roll_interruption(rng) -> bool:
    """Whether an unsafe night breaks. Rolled through the seeded/logged Rng."""
    return rng.roll("1d6", "rest_interruption").total <= INTERRUPT_ON_OR_UNDER
