"""Coinage: ONE canonical unit (the copper piece) and the helpers that translate
between it and the human denominations (pp/gp/sp/cp, SRD rates: 1 pp = 10 gp,
1 gp = 10 sp, 1 sp = 10 cp).

Everything internal — wallets, prices, StateOp deltas — is an int of copper.
Denominations exist only at the edges: authored pack content (ints mean GOLD for
back-compat, strings like "5 sp" name their unit), the DM's tool fields
(gold/silver/copper), and display (`format_cp`). Display promotes to platinum
only for HOARD-sized amounts (100 gp and up, OublietteDev's call 2026-07-04): the
party's 309.99 gp purse reads "30 pp 9 gp 9 sp 9 cp", while a 15 gp longsword
stays "15 gp" — never "1 pp 5 gp". Keep `fmtCoin` in app/static/index.html in
step with any change here.
"""

from __future__ import annotations

import re

CP_PER = {"pp": 1000, "gp": 100, "ep": 50, "sp": 10, "cp": 1}

# "5 sp", "1gp 5sp", "2 pp", "10 gold", "3 silver pieces" — unit words tolerated.
_PART = re.compile(
    r"(-?\d[\d,]*)\s*(pp|gp|ep|sp|cp|platinum|gold|electrum|silver|copper)\b",
    re.IGNORECASE)
_WORD_UNIT = {"platinum": "pp", "gold": "gp", "electrum": "ep",
              "silver": "sp", "copper": "cp"}


def parse_coin(text: str, default_unit: str = "gp") -> int:
    """A coin string -> copper. Accepts one or more '<n> <unit>' parts; a bare
    number takes `default_unit`. Raises ValueError on anything else."""
    s = text.strip()
    if not s:
        raise ValueError("empty coin amount")
    if re.fullmatch(r"-?\d[\d,]*", s):
        return int(s.replace(",", "")) * CP_PER[default_unit]
    total = 0
    matched = 0
    for m in _PART.finditer(s):
        n = int(m.group(1).replace(",", ""))
        unit = m.group(2).lower()
        unit = _WORD_UNIT.get(unit, unit)
        total += n * CP_PER[unit]
        matched += 1
    leftovers = _PART.sub("", s).replace("pieces", "").replace("piece", "")
    if matched == 0 or leftovers.strip(" ,;and"):
        raise ValueError(f"cannot parse coin amount: {text!r}")
    return total


def authored_to_cp(value: "int | str | None", default_unit: str = "gp") -> int | None:
    """An authored price/wallet value -> copper. Plain ints keep their historical
    meaning (GOLD pieces) so every existing pack stays right; strings carry their
    own unit ("5 sp", "1 gp 5 sp", "2 pp")."""
    if value is None:
        return None
    if isinstance(value, int):
        return value * CP_PER[default_unit]
    return parse_coin(value, default_unit=default_unit)


def split_cp(cp: int) -> tuple[int, int, int]:
    """Copper -> (gp, sp, cp) for display. No platinum promotion."""
    sign = -1 if cp < 0 else 1
    cp = abs(cp)
    return (sign * (cp // 100), sign * ((cp % 100) // 10), sign * (cp % 10))


# Amounts this large (in cp) display with a platinum headline; below it, gold
# leads. 10_000 cp = 100 gp = 10 pp.
PP_DISPLAY_FLOOR = 10_000


def format_cp(cp: int, zero: str = "0 gp") -> str:
    """Copper -> a compact human string: 235 -> '2 gp 3 sp 5 cp'; 0 -> `zero`.
    Hoard-sized amounts (>= 100 gp) promote into platinum: 30_999 ->
    '30 pp 9 gp 9 sp 9 cp'; everyday sums stay gold-led."""
    if cp == 0:
        return zero
    sign = "-" if cp < 0 else ""
    rest = abs(cp)
    parts = []
    if rest >= PP_DISPLAY_FLOOR:
        pp, rest = divmod(rest, CP_PER["pp"])
        parts.append(f"{pp:,} pp")
    g, s, c = split_cp(rest)
    if g:
        parts.append(f"{g:,} gp")
    if s:
        parts.append(f"{s} sp")
    if c:
        parts.append(f"{c} cp")
    return sign + " ".join(parts)
