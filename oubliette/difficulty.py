"""Difficulty settings: how dangerous this campaign is allowed to be.

The player picks a PRESET at New Game (or later, in Settings); each preset is
nothing but a bundle of the three dial values — no hidden preset-only behavior.
The dials are what the engine reads:

  * `encounter_challenge` — the CR budget band for improvised encounters
  * `rest_strictness`     — the long-rest gating ladder (free / gated / dangerous)
  * death rules           — `pc_death` / `companion_death` toggles, and `hardcore`
                            (total party defeat truly ends the campaign)

Like the table contract, this is configuration, NOT state the DM owns: code
stores it (event-sourced, see `record/events.DIFFICULTY_SET`, last-write-wins)
and code enforces it — the DM is *informed* of the dials, never in charge of
them. The firewall holds.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

EncounterDial = Literal["gentle", "standard", "punishing"]
RestDial = Literal["free", "gated", "dangerous"]


class DifficultySettings(BaseModel):
    """A campaign's danger dials. `preset` is the label the player chose —
    "story" / "adventure" / "challenge" / "hardcore", or "custom" when the
    dials were set by hand; the dials themselves are the source of truth."""

    preset: str = "adventure"
    encounter_challenge: EncounterDial = "standard"
    rest_strictness: RestDial = "gated"
    pc_death: bool = False          # a downed PC can truly die
    companion_death: bool = False   # recruited companions can truly die
    hardcore: bool = False          # total party defeat ends the campaign


# Preset -> the dial bundle it stands for. A stored preset label always means
# exactly these values (normalize_difficulty snaps them), so "hardcore" on the
# save can never secretly play like "story".
PRESET_DIALS: dict[str, dict] = {
    "story": dict(encounter_challenge="gentle", rest_strictness="free",
                  pc_death=False, companion_death=False, hardcore=False),
    "adventure": dict(encounter_challenge="standard", rest_strictness="gated",
                      pc_death=False, companion_death=False, hardcore=False),
    "challenge": dict(encounter_challenge="punishing", rest_strictness="dangerous",
                      pc_death=True, companion_death=True, hardcore=False),
    "hardcore": dict(encounter_challenge="punishing", rest_strictness="dangerous",
                     pc_death=True, companion_death=True, hardcore=True),
}

# Player-facing one-liners for the pickers (New Game + Settings).
PRESET_BLURBS: dict[str, str] = {
    "story": "Here for the tale. Fights stay gentle, rest whenever you like, "
             "and nobody truly dies.",
    "adventure": "The standard game. Fair fights, and a night's rest needs a "
                 "plausible moment — and costs coin or rations.",
    "challenge": "Encounters punch at or above your weight, unsafe rests can be "
                 "interrupted, and death is real.",
    "hardcore": "Challenge, and then some: if the whole party falls, the DM "
                "writes the campaign's final chapter and the story ends.",
    "custom": "Set each dial yourself.",
}

DEFAULT_DIFFICULTY = DifficultySettings()


def preset_settings(name: str) -> DifficultySettings:
    """The full settings object a preset label stands for ('adventure' when
    the label is unknown)."""
    dials = PRESET_DIALS.get(name, PRESET_DIALS["adventure"])
    label = name if name in PRESET_DIALS else "adventure"
    return DifficultySettings(preset=label, **dials)


def normalize_difficulty(d: DifficultySettings) -> DifficultySettings:
    """Tidy settings for storage: a known preset label snaps the dials to its
    bundle (the label IS the promise); anything else stores as 'custom' with
    the dials exactly as sent — so what's on the save is always coherent."""
    if d.preset in PRESET_DIALS:
        return DifficultySettings(preset=d.preset, **PRESET_DIALS[d.preset])
    return DifficultySettings(
        preset="custom",
        encounter_challenge=d.encounter_challenge,
        rest_strictness=d.rest_strictness,
        pc_death=d.pc_death,
        companion_death=d.companion_death,
        hardcore=d.hardcore,
    )
