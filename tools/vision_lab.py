"""Shortcut for `python tools/lab.py vision_lab` — the P-VISION-LIGHT test bed.

See tools/lab.py for the generic launcher and what each foe in the Vision Lab
demonstrates (fog cancel, blindsight one-sided disadvantage, truesight piercing
darkness, daylight dispel).
"""
from tools.lab import main

if __name__ == "__main__":
    main("vision_lab")
