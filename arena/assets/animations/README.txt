==============================
  Custom Action Animations
==============================

This folder holds animation assets for combat actions (attacks, spells,
abilities).  Each animation is a subfolder containing numbered PNG frames.

HOW TO ADD A CUSTOM ANIMATION
------------------------------

1. Create a new folder here with the animation name (e.g. "sword_slash").
   Use lowercase letters, numbers, and underscores only.

2. Place your PNG frames inside, named sequentially:
       frame_001.png
       frame_002.png
       frame_003.png
       ...

   - Use RGBA PNGs (with transparency).
   - Recommended size: 128 x 128 pixels (they will be scaled automatically).
   - 4-8 frames is typical for impact effects.
   - 6-12 frames is typical for projectile + impact effects.
   - IMPORTANT: For ranged/projectile animations, draw the projectile
     sprite (frame_001) pointing RIGHT (→). The engine automatically
     rotates it to match the actual flight direction during combat.

3. (Optional) Add a sound file to play when the animation triggers:
       sound.ogg   (preferred — small file size, good quality)
       sound.wav   (also supported)
       sound.mp3   (also supported)

   Only one sound file is needed. The system checks for .ogg first,
   then .wav, then .mp3. Volume is controlled by the SFX volume setting.

4. (Optional) Add a meta.json file to customize playback speed:
       {
           "fps": 12
       }
   If omitted, the default is 12 frames per second.

5. In the Creature Builder, go to the Actions tab, select an action,
   and choose your animation from the "Animation" dropdown.

ANIMATION BEHAVIOR
-------------------

The animation's playback mode is determined automatically by the
action's attack type:

  - Melee attacks: All frames play at the TARGET's position.
  - Ranged attacks: The first frame travels from attacker to target
    (rotated to face the flight direction), then all frames play as
    an impact at the target.
  - Non-attack actions (healing, buffs): Frames play at the target
    (or caster for self-targeting actions).

Animations play on every attack (hits and misses alike).

EXAMPLE FOLDER STRUCTURE
-------------------------

  animations/
    sword_slash/
      frame_001.png
      frame_002.png
      frame_003.png
      frame_004.png
      frame_005.png
      frame_006.png
      sound.ogg
    firebolt/
      frame_001.png
      frame_002.png
      frame_003.png
      frame_004.png
      frame_005.png
      frame_006.png
      frame_007.png
      frame_008.png
      sound.ogg
      meta.json
    healing_glow/
      frame_001.png
      frame_002.png
      frame_003.png
      frame_004.png
      sound.ogg
