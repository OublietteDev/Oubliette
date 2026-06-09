"""Map combat events to sound effect IDs."""

from __future__ import annotations

from typing import Any

from arena.combat.events import CombatEventType
from arena.audio.manager import get_sound_manager

# Maps each combat event type to a sound file name (without extension).
# The SoundManager looks for assets/sounds/{name}.wav, .ogg, or .mp3.
EVENT_SOUNDS: dict[CombatEventType, str] = {
    CombatEventType.COMBAT_START: "combat_start",
    CombatEventType.ROUND_START: "round_start",
    CombatEventType.TURN_START: "turn_start",
    CombatEventType.TURN_END: "turn_end",
    CombatEventType.MOVEMENT: "movement",
    CombatEventType.ATTACK_ROLL: "attack_roll",
    CombatEventType.DAMAGE: "damage_hit",
    CombatEventType.CREATURE_DOWNED: "creature_downed",
    CombatEventType.COMBAT_END: "combat_end",
    CombatEventType.INFO: "info",
    CombatEventType.SAVING_THROW: "saving_throw",
    CombatEventType.CONDITION_APPLIED: "condition_applied",
    CombatEventType.CONDITION_REMOVED: "condition_removed",
    CombatEventType.DEATH_SAVE: "death_save",
    CombatEventType.HEALING: "healing",
    CombatEventType.REACTION: "reaction",
    CombatEventType.AI_THINKING: "ai_thinking",
    CombatEventType.TELEPORT: "teleport",
    CombatEventType.FORCED_MOVEMENT: "forced_movement",
    CombatEventType.TERRAIN_MODIFICATION: "terrain_modification",
}


def play_event_sound(
    event_type: CombatEventType,
    details: dict[str, Any] | None = None,
) -> None:
    """Play the sound associated with a combat event type.

    For ATTACK_ROLL events, plays ``combat_hit`` or ``combat_miss``
    based on the ``hit`` flag in *details*.  Falls back to the generic
    ``attack_roll`` sound if details are unavailable.

    Does nothing if the event type has no mapping or the sound
    file is missing.
    """
    # Attack rolls use hit/miss-specific sounds
    if event_type == CombatEventType.ATTACK_ROLL and details is not None:
        hit = details.get("hit", None)
        if hit is True:
            get_sound_manager().play_sfx("combat_hit")
            return
        if hit is False:
            get_sound_manager().play_sfx("combat_miss")
            return

    sound_id = EVENT_SOUNDS.get(event_type)
    if sound_id:
        get_sound_manager().play_sfx(sound_id)
