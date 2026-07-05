# Sound Effects

Place `.wav` or `.ogg` sound files in this directory. The game will
automatically load and play them when the corresponding events occur.

If a file is missing, the game runs silently for that event.

## Expected File Names

### Combat Events

| File Name | Event |
|-----------|-------|
| `combat_start.wav` | Combat begins |
| `round_start.wav` | New round starts |
| `turn_start.wav` | Creature's turn begins |
| `turn_end.wav` | Turn ends |
| `movement.wav` | Creature moves |
| `attack_roll.wav` | Attack roll made |
| `damage_hit.wav` | Damage dealt |
| `creature_downed.wav` | Creature reaches 0 HP |
| `combat_end.wav` | Combat ends |
| `saving_throw.wav` | Saving throw rolled |
| `condition_applied.wav` | Condition applied |
| `condition_removed.wav` | Condition removed |
| `death_save.wav` | Death saving throw |
| `healing.wav` | Healing applied |
| `reaction.wav` | Reaction triggered |
| `ai_thinking.wav` | AI planning |
| `info.wav` | Generic info event |

### UI Events

| File Name | Event |
|-----------|-------|
| `button_click.wav` | Menu/action button clicked |
| `save_success.wav` | Combat state saved (Ctrl+S) |
| `victory.wav` | Player team wins |
| `defeat.wav` | Enemy team wins |

## Volume Control

Volume is controlled via Settings (master, SFX, and music sliders).
Effective SFX volume = (master / 100) * (sfx / 100).

## Supported Formats

- `.wav` (checked first)
- `.ogg` (fallback)
