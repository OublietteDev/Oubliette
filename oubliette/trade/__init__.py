"""Trade window (summoned tool, spec §9).

A bounded UI that SHOWS state — the merchant's priced stock and their gold (which
caps what they can buy off the player) — instead of resolving trades in prose.
Browsing produces ordinary, code-validated `transact`s at merchant-set prices, so
the firewall holds for free: the player chooses from a list they don't control,
and code applies + records every exchange. Stock comes from the DB, not DM
invention. Trivial buys can still happen in chat; the window is for browsing.
"""
