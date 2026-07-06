"""Rests (CS5): the recovery mechanics that work without a combat loop.

Pure functions that compute the protected-state `StateOp`s a rest produces, from
(character + ruleset). The caller records them in a REST_TAKEN event and applies
them — record-then-apply, replay-safe (the ops are absolute, D7). Short-rest
hit-die healing rolls through the seeded/logged `Rng` so replay never re-rolls;
the resulting HP is recorded as an absolute `hp_set`.

What a rest touches (SRD):
- **Long rest** — full HP; all spell slots back; every short/long-recharge class
  resource reset; regain hit dice up to half your total (min 1).
- **Short rest** — pact-magic (short-recharge) spell slots back; short-recharge
  resources reset; optionally spend hit dice to heal (roll + CON each).
"""

from __future__ import annotations

from ..enums import Ability
from ..record.events import StateOp, EventKind
from . import derive


def rest_interrupted_recently(events) -> bool:
    """Whether the party's latest rest was an INTERRUPTED night (S3) the DM
    hasn't yet had a turn to weave in — true iff the most recent REST_TAKEN
    carries interrupted=True and is more recent than the last in-character
    player message. Same replay-stable derivation as the reprepare window."""
    last_rest_seq, last_interrupted = -1, False
    last_msg = -1
    for e in events:
        if e.kind == EventKind.REST_TAKEN.value and e.seq > last_rest_seq:
            last_rest_seq = e.seq
            last_interrupted = bool(e.payload.get("interrupted"))
        elif e.kind == EventKind.PLAYER_MESSAGE.value:
            last_msg = max(last_msg, e.seq)
    return last_interrupted and last_rest_seq > last_msg


def reprepare_window_open(events) -> bool:
    """Whether prepared casters may currently re-prepare their spells (C5).

    The window opens on a LONG rest and closes once the party acts: a pure,
    replay-stable derivation — true iff the most recent long rest is more
    recent (higher seq) than the most recent in-character player message.
    Short rests don't open it; re-preparing doesn't close it (you can keep
    swapping until you take your first turn of the day)."""
    last_long = -1
    last_msg = -1
    for e in events:
        if e.kind == EventKind.REST_TAKEN.value and e.payload.get("rest") == "long":
            last_long = max(last_long, e.seq)
        elif e.kind == EventKind.PLAYER_MESSAGE.value:
            last_msg = max(last_msg, e.seq)
    return last_long > last_msg


def _class_hit_die(char, ruleset) -> int:
    cc = ruleset.classes.get(char.sheet.char_class) if char.sheet else None
    return cc.hit_die if cc else 8


def long_rest_ops(char, ruleset) -> list[StateOp]:
    ops: list[StateOp] = [
        StateOp.hp_set(char.id, char.max_hp),       # wake fully healed
        StateOp.slots_used(char.id, {}),            # all spell slots restored
    ]
    res = derive.class_resources(char, ruleset)
    new_used = dict(char.resources_used)
    for name, info in res.items():
        if info["recharge"] in ("short", "long"):   # a long rest restores both
            new_used[name] = 0
    ops.append(StateOp.resources_used(char.id, new_used))
    regain = max(1, char.level // 2)                 # half your hit dice, rounded down (min 1)
    ops.append(StateOp.hit_dice_used(char.id, max(0, char.hit_dice_used - regain)))
    return ops


def short_rest_ops(char, ruleset, spend_hit_dice: int = 0, rng=None) -> list[StateOp]:
    ops: list[StateOp] = []
    if derive.slots_recharge(char, ruleset) == "short":   # pact magic
        ops.append(StateOp.slots_used(char.id, {}))
    res = derive.class_resources(char, ruleset)
    new_used = dict(char.resources_used)
    touched = False
    for name, info in res.items():
        if info["recharge"] == "short":
            new_used[name] = 0
            touched = True
    if touched:
        ops.append(StateOp.resources_used(char.id, new_used))

    if spend_hit_dice > 0:
        available = max(0, char.level - char.hit_dice_used)
        spend = min(spend_hit_dice, available)
        if spend > 0:
            die = _class_hit_die(char, ruleset)
            con = char.ability_mod(Ability.CON)
            healed = 0
            for _ in range(spend):
                roll = rng.roll(f"1d{die}", "short_rest_hit_die").total if rng else (die // 2 + 1)
                healed += max(0, roll + con)         # a die never heals negative
            if healed > 0:
                ops.append(StateOp.hp_set(char.id, min(char.max_hp, char.hp + healed)))
            ops.append(StateOp.hit_dice_used(char.id, char.hit_dice_used + spend))
    return ops
