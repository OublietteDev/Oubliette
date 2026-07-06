"""The encounter budget (difficulty S2): how big an improvised fight the table allows.

Derived fresh every time from party strength × the campaign's
`encounter_challenge` dial — never stored, so it always reflects who is
actually traveling. Two caps, both riding the same idea (a monster's CR ≈ the
hero level it's a fair match for):

  * `single_cap` — the toughest single enemy allowed
                   (band multiplier × the party's average level)
  * `total_cap`  — the encounter's summed CR
                   (band multiplier × the party's summed levels ÷ 4,
                    the classic four-hero baseline)

Enforcement is prompt-first: the DM sees its budget in context (dm/context)
and is expected to improvise within it. `check_encounter` at the staging
funnel is the code backstop — a violation raises `BudgetError` and the
runtime bounces the encounter back to the DM to re-pick, invisibly
(runtime/loop). Persistent entities (recurring story foes) are exempt: they
are story, not improvisation. There is deliberately NO enforced floor — a
trivial fight the fiction wants (a rat in the cellar) must always stay
possible; the 'punishing' band's floor is prompt guidance only.

The band multipliers are the tunable heart — playtest numbers, not doctrine.
"""

from __future__ import annotations

from dataclasses import dataclass

from .boundary import CombatError


class BudgetError(CombatError):
    """An improvised encounter that exceeds the table's budget. The message is
    written FOR THE DM (it feeds the re-assess correction), naming each
    violation and restating the budget."""


@dataclass(frozen=True)
class Band:
    single_mult: float   # × the party's average level → single_cap
    total_mult: float    # × the party's summed levels / 4 → total_cap


# encounter_challenge dial -> band. Playtest-tunable in one place.
BANDS: dict[str, Band] = {
    "gentle": Band(single_mult=0.5, total_mult=1.5),
    "standard": Band(single_mult=1.0, total_mult=2.0),
    "punishing": Band(single_mult=1.5, total_mult=3.0),
}


def format_cr(cr: float) -> str:
    """A CR as players write it: 1/8, 1/4, 1/2, or a whole-ish number."""
    for frac, label in ((0.125, "1/8"), (0.25, "1/4"), (0.5, "1/2")):
        if abs(cr - frac) < 1e-9:
            return label
    return f"{cr:g}"


@dataclass(frozen=True)
class EncounterBudget:
    band: str            # the dial this budget came from
    party_size: int
    level_low: int
    level_high: int
    single_cap: float    # max CR of any ONE enemy
    total_cap: float     # max summed CR across all enemies

    def describe(self) -> str:
        return (f"toughest single foe CR ≤ {format_cr(self.single_cap)}, "
                f"all foes' CR summed ≤ {format_cr(self.total_cap)}")


def budget_for(party, dial: str) -> EncounterBudget:
    """The budget for THIS party at THIS dial. Companions count simply by being
    party members — a bigger party affords bigger fights (their soft cap)."""
    levels = [max(1, getattr(c, "level", 1)) for c in party] or [1]
    band = BANDS.get(dial, BANDS["standard"])
    avg = sum(levels) / len(levels)
    single = max(0.25, band.single_mult * avg)
    total = max(single, band.total_mult * sum(levels) / 4)
    return EncounterBudget(
        band=dial if dial in BANDS else "standard",
        party_size=len(levels), level_low=min(levels), level_high=max(levels),
        single_cap=single, total_cap=total,
    )


def check_encounter(instances, budget: EncounterBudget) -> None:
    """The code backstop at the staging funnel. `instances` are resolved
    `EnemyInstance`s (one per combatant). Raises `BudgetError` — with a
    DM-facing message — when the encounter exceeds the budget or fields a
    CR-less improvised creature (an unrated monster would be the loophole
    that defeats the cap). Persistent entities (entity_id set) are exempt."""
    problems: list[str] = []
    total = 0.0
    counted: dict[str, tuple[float, int]] = {}    # name -> (cr, how many)
    for inst in instances:
        if inst.entity_id is not None:
            continue                               # a recurring story foe: exempt
        name = inst.creature.name
        if inst.cr is None:
            problems.append(f"'{name}' has no challenge rating and cannot be "
                            "fielded on a budgeted table")
            continue
        total += inst.cr
        cr, n = counted.get(name, (inst.cr, 0))
        counted[name] = (cr, n + 1)
    for name, (cr, n) in counted.items():
        if cr > budget.single_cap:
            problems.append(f"'{name}' is CR {format_cr(cr)}, over the single-foe "
                            f"cap of CR {format_cr(budget.single_cap)}")
    if total > budget.total_cap:
        parts = ", ".join(f"{n}× {name} (CR {format_cr(cr)})"
                          for name, (cr, n) in counted.items())
        problems.append(f"the encounter sums to CR {format_cr(total)} ({parts}), "
                        f"over the total cap of CR {format_cr(budget.total_cap)}")
    if problems:
        raise BudgetError(
            "; ".join(problems) + f". This table's budget: {budget.describe()}.")
