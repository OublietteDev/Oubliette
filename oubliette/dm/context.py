"""Per-turn state/scene context for the DM (fix for harness gap G2).

The model can't set a fair DC "by the NPC's shrewdness" or resolve a sale without
knowing who's present, their disposition, and the party's resources. This builds
a compact, readable snapshot injected into both the assess and resolve prompts.
It reads OPEN flavor (dispositions) + the protected sheet essentials — never
exposes internals the model shouldn't reason about as numbers it owns.
"""

from __future__ import annotations

from ..canon.models import CanonRecord
from ..coin import format_cp
from ..enums import Ability, Skill
from ..rules import attune as attune_rules
from ..rules.derive import (class_resources, save_modifier, skill_modifier,
                            spell_attack_bonus, spell_save_dc, spell_slots)
from ..state.repository import Repository

LORE_MAX = 3        # most lore entries surfaced in one turn's context
LORE_CHARS = 1200   # per-entry budget — generous (lore is meant to be retold, not clipped)
FEATURE_CAP = 14    # features listed by name before a "+N more" tail (keep the card bounded)


def _mod(n: int) -> str:
    return f"{n:+d}"


def _ord(n: int) -> str:
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def _character_cards(repo: Repository, ruleset, mechanics: dict | None = None) -> list[str]:
    """A compact mechanical 'card' per sheeted PC (CS6): who they are, what they're
    trained in, their features/spells/resources — names and key numbers, never the
    full rulebook prose. The point is for the DM to call for the RIGHT check/save
    and narrate rules-aware, NOT to own any number: code still rolls and owns state.

    Sheet-less quick-start heroes get nothing here (the PARTY line already covers
    their basics). Reuses `rules/derive` so the numbers match the read-only sheet
    (CS3) exactly. `ruleset` may be None (custom seeds / tests): abilities, skills,
    saves, features and the spell save DC still render; slot pools and class
    resources, which need the ruleset to derive, are simply omitted."""
    def nm(table_attr: str, ident):
        if ident is None:
            return None
        if ruleset is None:
            return ident
        ent = getattr(ruleset, table_attr, {}).get(ident)
        return ent.name if ent is not None else ident

    def spell_nm(spell_id: str) -> str:
        ent = ruleset.spells.get(spell_id) if ruleset is not None else None
        return ent.name if ent is not None else spell_id

    pcs = [c for c in repo.party() if c.sheet is not None]
    if not pcs:
        return []
    out = [
        "CHARACTER SHEET (mechanical reference — use it to call for the RIGHT check or "
        "save and to skip rolls the character handles trivially or via a feature/spell; "
        "you never roll, code applies these modifiers and owns all state):"
    ]
    for pc in pcs:
        sheet = pc.sheet
        race = nm("races", sheet.race)
        subrace = nm("subraces", sheet.subrace)
        race_label = f"{race} ({subrace})" if subrace else race
        klass = nm("classes", sheet.char_class)
        subclass = nm("subclasses", sheet.subclass)
        class_label = f"{klass}/{subclass}" if subclass else klass
        ident = f"  {pc.name} — level {pc.level} {race_label} {class_label}"
        tail = ", ".join(p for p in [nm("backgrounds", sheet.background), sheet.alignment or None] if p)
        out.append(ident + (f", {tail}" if tail else ""))
        out.append("    Abilities: " + ", ".join(
            f"{a.value.upper()} {_mod(pc.ability_mod(a))}" for a in Ability))
        prof_skills = [
            f"{s.value.replace('_', ' ').title()} {_mod(skill_modifier(pc, s))}"
            f"{' (expertise)' if s in sheet.expertise else ''}"
            for s in Skill if s in pc.skill_proficiencies
        ]
        if prof_skills:
            out.append("    Proficient skills: " + ", ".join(prof_skills) + ".")
        if sheet.saving_throw_proficiencies:
            out.append("    Saving throws: " + ", ".join(
                f"{a.value.upper()} {_mod(save_modifier(pc, a))}"
                for a in Ability if a in sheet.saving_throw_proficiencies) + ".")
        train = []
        for label, vals in (("armor", sheet.armor_proficiencies),
                            ("weapons", sheet.weapon_proficiencies),
                            ("tools", sheet.tool_proficiencies),
                            ("languages", sheet.languages)):
            if vals:
                train.append(f"{label}: " + ", ".join(vals))
        if train:
            out.append("    Trained — " + "; ".join(train) + ".")
        feats = [f.name for f in sheet.features]
        if feats:
            shown = feats[:FEATURE_CAP]
            more = len(feats) - len(shown)
            out.append("    Features: " + ", ".join(shown) + (f" (+{more} more)." if more else "."))
        if sheet.spellcasting_ability is not None:
            bits = [f"Spellcasting ({sheet.spellcasting_ability.value.upper()})"]
            dc, atk = spell_save_dc(pc), spell_attack_bonus(pc)
            if dc is not None:
                bits.append(f"save DC {dc}, attack {_mod(atk)}")
            if ruleset is not None:
                slots = spell_slots(pc, ruleset)
                if slots:
                    bits.append("slots " + ", ".join(
                        f"{lvl}{_ord(lvl)}: {n}" for lvl, n in sorted(slots.items())))
            if sheet.cantrips_known:
                bits.append("cantrips " + ", ".join(spell_nm(s) for s in sheet.cantrips_known))
            leveled = sheet.spells_prepared or sheet.spells_known
            if leveled:
                bits.append("spells " + ", ".join(spell_nm(s) for s in leveled))
            out.append("    " + "; ".join(bits) + ".")
        if ruleset is not None:
            res = class_resources(pc, ruleset)
            if res:
                out.append("    Resources: " + ", ".join(
                    f"{name} {'unlimited' if info.get('unlimited') else info.get('max')}"
                    f"/{info.get('recharge', 'long')} rest"
                    for name, info in res.items()) + ".")
        if pc.conditions:
            out.append("    Conditions: " + ", ".join(pc.conditions) + ".")
        # Attunement (multiplayer pre-work): the hero's live bonds, plus any
        # carried item that is INERT until attuned — so the DM never narrates a
        # dormant ring working, and can nudge the party toward a rest.
        def _item_nm(item_id: str) -> str:
            try:
                return repo.get_item(item_id).name
            except Exception:
                return item_id
        bonds = attune_rules.active_attuned(pc)
        dormant = [i for i in attune_rules.attunable_carried(pc, mechanics)
                   if i not in pc.attuned]
        if bonds or dormant:
            bits = [f"Attuned ({len(bonds)}/{attune_rules.MAX_ATTUNED}): "
                    + (", ".join(_item_nm(i) for i in bonds) or "nothing")]
            if dormant:
                bits.append("carried but NOT attuned (inert until attuned — "
                            "the ritual happens when the party rests): "
                            + ", ".join(_item_nm(i) for i in dormant))
            out.append("    " + "; ".join(bits) + ".")
    return out


def _reachable(location: str | None, places: dict) -> list:
    """Places the party can travel to from `location`: its explicit exits, its
    sublocations (children), its siblings (same parent), its PARENT (you can always
    zoom back out of a district), and — from a top-level place — the other top-level
    places (roots are mutual siblings). Without those last two, a region with no
    authored exits is a one-way trap: drill into a city district and you could never
    leave the city, and a parentless region like Seraphel's Roost was unreachable
    from anywhere (v0.9 playtest). Returns PlaceNodes."""
    if location is None or location not in places:
        return []
    here = places[location]
    ids: set[str] = set(here.exits)
    ids |= {pid for pid, n in places.items() if n.parent == location}      # children
    if here.parent is not None:
        ids |= {pid for pid, n in places.items() if n.parent == here.parent}  # siblings
        ids.add(here.parent)                                               # zoom out
    else:
        ids |= {pid for pid, n in places.items() if n.parent is None}      # fellow roots
    ids.discard(location)
    return [places[i] for i in ids if i in places]


def region_root(location: str | None, places: dict) -> str | None:
    """The party's top-level enclosing area — walk up the parent chain to the outermost
    ancestor. This is "the area you're in" (a town and its districts resolve to one
    region), used to scope ambient quest awareness and the quest-card art."""
    cur, seen = location, set()
    while cur in places and cur not in seen:
        seen.add(cur)
        parent = places[cur].parent
        if not parent:
            break
        cur = parent
    return cur


def _reward_text(repo: Repository, reward) -> str:
    """A short advisory reward line for the DM (the engine never auto-grants it)."""
    if reward is None:
        return ""
    bits: list[str] = []
    if reward.gold:
        bits.append(f"{reward.gold} gp" if isinstance(reward.gold, int) else str(reward.gold))
    if reward.item:
        try:
            name = repo.get_item(reward.item).name
        except Exception:
            name = reward.item
        bits.append(f"{reward.qty}x {name}")
    if reward.note:
        bits.append(reward.note)
    return ", ".join(bits)


# How the DM plays a faction's members at each standing tier (living-world W2).
_TIER_PLAY = {
    "hostile": "Members refuse the party trade, aid, and courtesy — and may move against them",
    "unfriendly": "Members are cold and unhelpful; favors cost extra, doors stay shut",
    "neutral": "",
    "friendly": "Members are warm and forthcoming; small favors come easily",
    "allied": "Members treat the party as their own — real aid, real trust, real secrets",
}


def story_so_far(past_notes: list[str] | None) -> str:
    """The DM's private notes from PAST wrapped sessions (W5), cumulative and
    oldest-first, as a STANDALONE block — deliberately not part of build_context.
    This is the one piece of the DM's picture that grows with a campaign yet never
    changes mid-session, so it rides to the model as `stable_context` (see
    LLMClient) where providers with prompt caching bill it at cache rates —
    long campaigns stay affordable. Empty string when there are no notes yet."""
    if not any(past_notes or []):
        return ""
    lines = ["STORY SO FAR (your PRIVATE notes from past sessions — cumulative memory, "
             "oldest first; the players do NOT see these — carry threads forward):"]
    # Numbered by session, empties skipped but never renumbered — "Session 3"
    # must keep meaning the third session even if the second wrote no note.
    for i, note in enumerate(past_notes, 1):
        if note:
            lines.append(f"  - Session {i}: {note}")
    return "\n".join(lines)


def build_context(repo: Repository, scene: str = "", recent: list[str] | None = None,
                  canon: list[CanonRecord] | None = None, location: str | None = None,
                  places: dict | None = None, quests: list | None = None,
                  time_of_day: str | None = None, weather: str | None = None,
                  ruleset=None, authored_quests: dict | None = None,
                  offerable: set | None = None, offered_here: set | None = None,
                  pending_rewards: list | None = None,
                  notebook: list[str] | None = None,
                  difficulty=None, rest_interrupted: bool = False,
                  companion_growth: list | None = None,
                  keyed_directive: dict | None = None,
                  factions: list | None = None,
                  day: int | None = None,
                  world_event: dict | None = None,
                  mechanics: dict | None = None,
                  seats: dict | None = None,
                  speaker: str | None = None,
                  seat_activity: dict | None = None) -> str:
    # Show the item id (tool calls need it, gap G2b) + an advisory value anchor for
    # the soft economy (the DM asked for a pricing reference; it's not enforced).
    def _item_label(item_id: str, qty: int) -> str:
        item = repo.get_item(item_id)
        worth = f", ~{format_cp(item.value_cp)}" if item.value_cp else ""
        return f"{qty}x {item.name} [id: {item_id}{worth}]"

    def _party_line(p) -> str:
        inv = ", ".join(_item_label(s.item_id, s.qty) for s in p.inventory) or "nothing"
        return f"{p.name} (id: {p.id}) — {p.hp}/{p.max_hp} HP, {p.xp} XP; carrying {inv}."

    lines: list[str] = []
    if scene:
        lines.append(f"SCENE: {scene}")
    if time_of_day or weather:
        # The day number (living-world W3) is CODE-OWNED: long rests and travel
        # move it, set_environment does not — the DM colors the hours, the
        # engine counts the days.
        day_label = f"Day {day} — " if day else ""
        lines.append(f"ENVIRONMENT: {day_label}it is {time_of_day or 'day'}, weather {weather or 'clear'} "
                     f"(these carry forward on their own; emit set_environment only when the story turns them"
                     + (", and the day number advances by itself when the party sleeps or travels)."
                        if day else ")."))
    if world_event is not None:
        # Timed world event (living-world W4): the ENGINE fired it — schedule
        # and conditions already checked, effects already real. The DM's job is
        # presentation: witnessed live, or arriving as news.
        wt = "WORLD EVENT — IT HAS JUST HAPPENED"
        if world_event.get("place_name"):
            wt += f" at {world_event['place_name']}"
        parts = [wt + f": {world_event.get('announce') or '(no public account — see the secret briefing)'}"]
        if world_event.get("briefing"):
            parts.append(f"The truth behind it (secret): {world_event['briefing']}")
        if world_event.get("present"):
            parts.append("The party is THERE. Weave it into this turn's narration — "
                         "they witness it with their own eyes.")
        elif world_event.get("place_name"):
            parts.append("It happened AWAY from the party. Do NOT narrate it before "
                         "their eyes — let the news arrive naturally (a traveler's "
                         "word, a notice, a rider on the road), this turn if it fits "
                         "or soon after. Distant things reach ears as rumor.")
        else:
            parts.append("The world has moved. Work the consequences into the "
                         "fiction where natural.")
        if world_event.get("effects"):
            parts.append("Already in force: " + "; ".join(world_event["effects"]) + ".")
        lines.append(" ".join(parts))
    if keyed_directive is not None:
        # Keyed encounter (living-world W1): the ENGINE decided this fight fires —
        # already evaluated, already certain. The DM's whole job this turn is the
        # approach prose; the fight is staged by code the moment the reply ends.
        briefing = keyed_directive.get("briefing") or ""
        lines.append(
            "AUTHORED ENCOUNTER — IT FIRES NOW. The world's author bound this fight "
            f"to this place, and its moment has come: {keyed_directive['names']}."
            + (f" Author's staging notes (secret): {briefing}" if briefing else "")
            + " Your reply NARRATES THE APPROACH ONLY — build to the instant violence "
            "becomes unavoidable and stop at that brink. Do not resolve any fighting "
            "in prose, do not fill `encounter` yourself, and do not move the party "
            "elsewhere: the engine has already staged this fight, and it begins the "
            "moment your narration ends.")
    party = repo.party()
    heroes = [p for p in party if not p.companion]
    companions = [p for p in party if p.companion]
    # The seated-table framing (multiplayer S1): you are the DM of a TABLE —
    # one chair or many — and the players at it speak for the heroes. When a
    # hosted table supplies a seat map, each hero line names its player and
    # each message names its speaker; solo play is simply a table of one.
    seat_of: dict[str, str] = {}
    for nm, ids in (seats or {}).items():
        for cid in ids:
            seat_of[cid] = nm

    def _seat_tag(p) -> str:
        if not seats:
            return ""
        owner = seat_of.get(p.id)
        return (f" [played by {owner}]" if owner
                else " [open seat — anyone at the table may act for this hero]")

    if len(heroes) == 1:
        lines.append(f"PARTY: {_party_line(heroes[0])}{_seat_tag(heroes[0])}")
    else:
        if seats:
            lines.append(
                "PARTY — this table seats several PLAYERS, and each message names its "
                "speaker. Address the speaker's own hero for personal beats and the whole "
                "table for shared ones; call for whoever's check fits, award XP/loot to "
                "each hero. Anyone may act for any hero — the seat tags say whose voice "
                "usually belongs to whom:")
        else:
            lines.append(
                "PARTY — one table, several heroes; the player at it speaks for them all "
                "(address heroes by name/id, call for whoever's check fits, and award "
                "XP/loot to each):")
        for p in heroes:
            lines.append(f"  - {_party_line(p)}{_seat_tag(p)}")
    if speaker:
        pcs = [p.name for p in heroes if seat_of.get(p.id) == speaker]
        lines.append(f"SPEAKING NOW: {speaker}"
                     + (f" (their hero: {', '.join(pcs)})" if pcs
                        else " (no claimed hero — a voice at the table)")
                     + " — answer them by name when it fits, as a DM does.")
    if seat_activity:
        # The spotlight meter: who has been quiet, counted in player messages
        # BEFORE this one (the SPEAKING NOW line covers the live turn).
        def _ago(n) -> str:
            if n is None:
                return "hasn't spoken yet this session"
            return "spoke last message" if n == 0 else f"last spoke {n + 1} messages ago"
        told = "; ".join(f"{nm} {_ago(n)}" for nm, n in seat_activity.items())
        lines.append(f"TABLE ACTIVITY (spotlight): {told}. When a player has been "
                     "quiet a while, draw their hero back in — a beat only that hero "
                     "can answer beats a lump address to the party.")
    if companions:
        lines.append("COMPANIONS (they TRAVEL with the party and fight at its side, "
                     "player-controlled — but they are still your characters to voice: "
                     "give each a presence, react through them, let them speak):")
        for c in companions:
            kind = "person" if c.sheet is not None else "creature"
            lines.append(f"  - {_party_line(c)} [{kind}, level {c.level}]")
    for g in companion_growth or ():
        # Companion growth (S2): the change is already real — code applied the new
        # form's numbers, and the player has already seen a Growth card. The DM's
        # job is the SCENE — but never at the expense of what the player is doing.
        lines.append(f"GROWTH: {g['name']} has just grown from {g['from']} into "
                     f"{g['to']} — the change is real and the player has been told. "
                     "Acknowledge it in the fiction when it fits this turn: if the "
                     "player's action leaves room, make it a small moment; if they're "
                     "busy with something else, a passing line is enough. Never derail "
                     "their intent for it.")
    # The party's money is ONE shared purse (coin ops on any PC land here).
    lines.append(f"PARTY PURSE: {format_cp(repo.party_cp)} "
                 "(shared — any hero spends from it; 1 gp = 10 sp = 100 cp).")
    # Difficulty S2: the party's strength at a glance + the table's encounter
    # budget, so the DM sizes improvised fights right the FIRST time (the
    # staging funnel enforces the same caps as a backstop).
    if difficulty is not None:
        from ..combat.budget import budget_for
        b = budget_for(party, difficulty.encounter_challenge)
        lvl = (f"level {b.level_low}" if b.level_low == b.level_high
               else f"levels {b.level_low}–{b.level_high}")
        strength = (f"PARTY STRENGTH: {b.party_size} hero{'es' if b.party_size != 1 else ''}, "
                    f"{lvl}. ENCOUNTER BUDGET ({difficulty.preset} table): improvised "
                    f"fights must fit it — {b.describe()}. Recurring foes already in "
                    "the story are exempt.")
        if difficulty.encounter_challenge == "punishing":
            strength += (" Keep fights AT or NEAR the party's weight — save trivial "
                         "encounters for when the fiction truly calls for one.")
        lines.append(strength)
        # Difficulty S3: long rests are gated — the DM is the door.
        if difficulty.rest_strictness != "free":
            rest_rule = (
                "LONG RESTS (table rule): gated — the party cannot simply sleep. A long "
                "rest happens ONLY when you offer it with propose_rest; when the player "
                "asks to rest, grant it if the fiction permits (a safe room, a quiet camp, "
                "no pursuit, night hours) and refuse in the fiction otherwise, saying why. "
                "A granted night costs the party lodging coin in a safe haven or a ration "
                "per hero in the wild — code settles the bill; never charge it yourself. "
                "Short rests need no grant.")
            if difficulty.rest_strictness == "dangerous":
                rest_rule += (" Camps outside a safe haven may be INTERRUPTED in the "
                              "night — code rolls it and tells the player.")
            lines.append(rest_rule)
    if rest_interrupted:
        lines.append(
            "IN THE NIGHT: the party's last rest was INTERRUPTED — they woke to trouble "
            "and got only a breather's worth of recovery (no spell slots or full healing "
            "back). You decide what broke the camp: weave it into your next narration — "
            "tracks at the treeline, a snuffed fire, something circling — and play out "
            "any consequence the fiction demands.")
    # CS6: the mechanical 'card(s)' — who the PC(s) are in rules terms, so the DM
    # calls for the right checks/saves and narrates rules-aware (reference only).
    lines.extend(_character_cards(repo, ruleset, mechanics))
    # Only NPCs whose home is the party's current location are "present" in the
    # scene — this keeps the prompt scoped as the cast grows. An NPC with no home
    # is "nowhere in particular" and isn't placed in any scene. Everyone remains
    # retrievable via canon search regardless of where they are. When no location
    # is known (e.g. a custom seed with no pack), fall back to showing all NPCs.
    npcs = repo.npcs()
    if location is not None:
        npcs = [n for n in npcs if n.home_location == location]
    if npcs:
        lines.append("PRESENT (NPCs you may reference by id):")
        faction_names = {f["id"]: f["name"] for f in factions or ()}
        for n in npcs:
            note = n.disposition or n.description or "no notes"
            if getattr(n, "faction", None) and n.faction in faction_names:
                note = f"[{faction_names[n.faction]}] {note}"
            # Surface a merchant's priced stock so the DM can negotiate (it was
            # "blind to the trade window contents" otherwise).
            stock = ""
            if n.price_list:
                in_stock = {s.item_id for s in n.inventory if s.qty > 0}
                items = [f"{repo.get_item(i).name} {format_cp(p)}"
                         for i, p in list(n.price_list.items())[:8] if i in in_stock]
                if items:
                    stock = "; sells " + ", ".join(items)
            lines.append(f"  - {n.name} (id: {n.id}) — {note}; "
                         f"carries {format_cp(n.coin)}{stock}.")
    # Faction standing (living-world W2): every authored faction, its code-owned
    # tier, and the DM's marching orders per tier. The party's own view (the
    # Factions panel) is redacted server-side; the DM sees everything, including
    # who the party hasn't met — so it can play a hidden hand without leaking it.
    if factions:
        lines.append(
            "FACTION STANDING (code-owned; play members TRUE to their tier; nudge with "
            "adjust_standing (±5) only when the fiction just earned it — authored quests "
            "make the big moves; delta 0 reveals a faction the party just learned of):")
        for f in factions:
            vis = ("known to the party" if f["known"] else
                   "UNKNOWN to the party (shows as ??? in their list — never speak of it "
                   "as familiar; adjust_standing delta 0 the moment they learn of it)")
            play = _TIER_PLAY.get(f["tier"], "")
            agenda = f" Agenda (secret): {f['agenda']}" if f.get("agenda") else ""
            lines.append(f"  - {f['name']} (id: {f['id']}) — {f['tier']} ({f['score']:+d}); "
                         f"{vis}.{' ' + play + '.' if play else ''}{agenda}")
    # Where the party can travel from here (exits, sublocations, neighbours). The DM
    # moves them with the travel tool, naming the destination by id.
    dests = _reachable(location, places or {})
    if dests:
        # The turn that TRAVELS somewhere is written with context built at the ORIGIN,
        # so the model can't see the destination's cast — it narrates arrivals thin and
        # invents stand-ins for authored NPCs (v0.9 playtest: "Old Pell" minted at the
        # dock where Captain Bromley lives). Name each destination's residents here so
        # an arrival is written with the authored cast in hand.
        by_home: dict[str, list] = {}
        for n in repo.npcs():
            if n.home_location:
                by_home.setdefault(n.home_location, []).append(n)
        lines.append("WHERE YOU CAN GO (travel here with the travel tool, by id):")
        for d in sorted(dests, key=lambda p: p.name):
            names = ", ".join(n.name for n in by_home.get(d.id, [])[:6])
            who = f" — found here: {names}" if names else ""
            lines.append(f"  - {d.name} (id: {d.id}){who}")
        lines.append(
            "  (These are the ways on from HERE — the wider world holds more. If the "
            "player names a place that is not listed, call the travel tool with that "
            "name anyway: it knows every place that truly exists and refuses unknown "
            "ones. NEVER create_entity a place the player claims exists — creation is "
            "only for genuinely NEW places born in this campaign's play.)")
    # Long-term memory: world canon relevant to this turn, retrieved by keyword
    # (gap G4). Stay consistent with these; provisional canon is soft.
    if canon:
        lore_hits = [r for r in canon if r.entity_type == "lore"]
        other = [r for r in canon if r.entity_type != "lore"]
        # Authored history/legend gets a generous budget (a few entries, near-full
        # text) so the DM can actually retell it, not a clipped snippet.
        if lore_hits:
            lines.append("WORLD LORE (established history/legend — treat as true; weave in as it fits):")
            for r in lore_hits[:LORE_MAX]:
                text = (r.text[:LORE_CHARS] + "…") if len(r.text) > LORE_CHARS else r.text
                lines.append(f"  - {r.name}: {text}")
        if other:
            lines.append("RELEVANT CANON (established world facts — stay consistent):")
            for r in other:
                text = (r.text[:160] + "…") if len(r.text) > 160 else r.text
                lines.append(f"  - [{r.status}] {r.entity_type} '{r.name}' (id: {r.id}){': ' + text if text else ''}")
    # Authored quest offers, two tiers. AT-SOURCE (full hook + secret briefing + reward +
    # outcomes; acceptable now) vs IN-REGION (a sparse signpost — count + place + rumor — so
    # the DM can point the party toward work without spoiling it).
    if authored_quests:
        here_ids = sorted(offered_here or set())
        npc_name = {n.id: n.name for n in repo.npcs()}
        npc_home = {n.id: n.home_location for n in repo.npcs()}
        if here_ids:
            lines.append("QUESTS OFFERED HERE (the party can take these up now — accept_quest by "
                         "id when they engage; tell the player the HOOK, never the BRIEFING):")
            for qid in here_ids:
                q = authored_quests[qid]
                src = (f"from {npc_name.get(q.giver_npc, q.giver_npc)}" if q.giver_npc is not None
                       else f"found here — {q.discovery}")
                lines.append(f"  - [{qid}] \"{q.title}\" ({src})")
                if q.hook:
                    lines.append(f"      HOOK (tell the player): {q.hook}")
                if q.briefing:
                    lines.append(f"      BRIEFING (secret — yours alone): {q.briefing}")
                reward = _reward_text(repo, q.reward)
                if reward:
                    lines.append(f"      REWARD (advisory — grant via give/transact, renegotiable): {reward}")
                if len(q.branches) > 1:        # only a genuine fork needs an outcome reported
                    lines.append("      OUTCOMES (on resolution, update_quest status=completed with "
                                 "outcome=<one label>): " + ", ".join(b.outcome for b in q.branches))
        # In-region: eligible elsewhere in the same top-level area, not present here.
        my_region = region_root(location, places or {})
        groups: dict[str, list] = {}
        for qid in (set(offerable or set()) - set(offered_here or set())):
            q = authored_quests.get(qid)
            if q is None:
                continue
            src_loc = q.giver_place if q.giver_place is not None else npc_home.get(q.giver_npc)
            if src_loc is None or region_root(src_loc, places or {}) != my_region:
                continue
            node = (places or {}).get(src_loc)
            groups.setdefault(node.name if node is not None else src_loc, []).append(q)
        if groups:
            total = sum(len(v) for v in groups.values())
            lines.append(f"WORK AVAILABLE IN THE REGION ({total} elsewhere in this area — use ONLY to "
                         "point the party toward where work is if they look for it; do NOT reveal "
                         "details or accept until they travel there):")
            for place in sorted(groups):
                qs = groups[place]
                lines.append(f"  - {place}: {len(qs)} available")
                for q in qs:
                    if q.rumor:
                        lines.append(f"      rumor: {q.rumor}")
    # Ongoing goals the code is tracking — so the DM stays consistent about what the
    # party is pursuing and advances them (update_quest) as the fiction develops.
    if quests:
        lines.append("ACTIVE QUESTS (the party's open goals — advance with update_quest as they develop):")
        for q in quests:
            text = (q.text[:200] + "…") if len(q.text) > 200 else q.text
            latest = f" — latest: {q.notes[-1]}" if q.notes else ""
            lines.append(f"  - [{q.id}] {q.title}{': ' + text if text else ''}{latest}")
            # For an accepted AUTHORED quest, keep its secret briefing + intended reward +
            # (for a fork) the outcome labels in view for the quest's whole life — not just at
            # the offer — so the DM resolves it as authored, with the right reward and branch.
            aq = (authored_quests or {}).get(q.authored_id)
            if aq is not None:
                if aq.briefing:
                    lines.append(f"      BRIEFING (secret — yours alone): {aq.briefing}")
                reward = _reward_text(repo, aq.reward)
                if reward:
                    lines.append(f"      INTENDED REWARD (hand over via give/transact when it "
                                 f"resolves; renegotiable): {reward}")
                if len(aq.branches) > 1:
                    lines.append("      TO ADVANCE THE CHAIN, complete with update_quest "
                                 "outcome=<one of>: " + ", ".join(b.outcome for b in aq.branches))
    # A completed quest's reward stays in view until the DM confirms the party was paid —
    # a reward promised now and handed over later (or renegotiated for gold/other goods)
    # would otherwise drop out of context the instant the quest left ACTIVE QUESTS, and
    # the DM would have to guess what it owed. Cleared by update_quest(reward_settled=true).
    if pending_rewards:
        lines.append("REWARDS PENDING (these quests are DONE but the party hasn't been "
                     "compensated yet — hand over the agreed reward via give/transact "
                     "(renegotiable), then clear it with update_quest reward_settled=true):")
        for q in pending_rewards:
            aq = (authored_quests or {}).get(q.authored_id)
            reward = _reward_text(repo, aq.reward) if aq is not None else ""
            if reward:
                hint = f"promised: {reward}"
            else:
                latest = (q.notes[-1] if q.notes else q.text) or "(recall what you offered them)"
                hint = (latest[:160] + "…") if len(latest) > 160 else latest
            lines.append(f"  - [{q.id}] {q.title} — {hint}")
    # NOTE: the STORY SO FAR block (past-session notes, W5) is deliberately NOT
    # built here anymore — it's session-stable, so it rides separately as the
    # cacheable `stable_context` (see story_so_far above and TurnLoop._story_so_far).
    # The DM's own working notebook for THIS session (the dm_note tool, W4): plans,
    # foreshadowing, an NPC's true intent, a lie left standing. The DM's private memory —
    # players never see it — oldest first. Prose only, never a source of protected-state
    # numbers. Resets at wrap (its threads carry forward via STORY SO FAR above).
    if notebook:
        lines.append("DM NOTEBOOK (your PRIVATE working notes this session — plans, secrets, "
                     "foreshadowing; the players do NOT see these; add to them with dm_note):")
        for note in notebook:
            lines.append(f"  - {note}")
    # Short-term continuity: what just happened, so the DM honors established
    # fiction and successful checks instead of re-litigating each turn (gap G5).
    if recent:
        lines.append("RECENT TURNS (oldest first — this already happened, treat as true):")
        for beat in recent:
            lines.append(f"  - {beat}")
    return "\n".join(lines)
