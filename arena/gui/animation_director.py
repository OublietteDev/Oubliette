"""Animation sequencing: play combat visuals in readable order.

The combat engine resolves actions instantly and appends events to the
CombatLog; the GUI used to spawn every visual for a batch of events in
the same frame (projectile launch, damage number, HP drop, KO slump —
all at once). The :class:`AnimationDirector` sits between the event
stream and the visual spawns: the combat screen groups events into
:class:`Beat` objects and the director fires them one after another,
so an attack reads as swing/travel → impact → next swing.

The director is pure GUI-side timing — it never touches combat state.
Beat durations are computed up front (animation lifetimes are
deterministic: travel time + frame count / fps), so the director is a
plain timer queue with no callbacks from the renderer.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

# A cue is fired once, when its beat starts. It receives the fire time
# (pygame.time.get_ticks()) so spawned visuals timestamp correctly.
Cue = Callable[[int], None]


@dataclass
class Beat:
    """One step in the visual sequence.

    Cues fire together when the beat starts; the beat then holds the
    queue for ``duration_ms`` before the next beat may begin. A beat
    stays mutable until it fires: the combat screen appends damage cues
    to a pending impact beat as the engine's events trickle in (e.g.
    across a reaction popup).
    """

    cues: list[Cue] = field(default_factory=list)
    duration_ms: int = 0
    fired: bool = False

    def add_cue(self, cue: Cue) -> bool:
        """Attach a cue if the beat hasn't fired yet.

        Returns False when the beat already fired — the caller should
        run the cue immediately instead.
        """
        if self.fired:
            return False
        self.cues.append(cue)
        return True


class AnimationDirector:
    """A timer queue that plays beats strictly in order."""

    def __init__(self) -> None:
        self._queue: deque[Beat] = deque()
        self._hold_until: int | None = None  # end of the current beat

    @property
    def is_busy(self) -> bool:
        """True while any beat is queued or still holding the stage."""
        return bool(self._queue) or self._hold_until is not None

    def enqueue(self, beat: Beat) -> Beat:
        """Add a beat to the end of the sequence."""
        self._queue.append(beat)
        return beat

    def update(self, now: int) -> None:
        """Fire every beat that is due at ``now``."""
        while True:
            if self._hold_until is not None:
                if now < self._hold_until:
                    return
                self._hold_until = None
            if not self._queue:
                return
            beat = self._queue.popleft()
            beat.fired = True
            for cue in beat.cues:
                cue(now)
            if beat.duration_ms > 0:
                self._hold_until = now + beat.duration_ms

    def clear(self, now: int) -> None:
        """Drop all pending beats, firing their cues first.

        Cues release visual holds (frozen HP bars, standing-corpse
        overrides), so they must run even when the sequence is being
        abandoned — otherwise a reset mid-flight would leak a hold.
        The visuals they spawn are harmless: the caller resets the
        visual lists right after.
        """
        while self._queue:
            beat = self._queue.popleft()
            beat.fired = True
            for cue in beat.cues:
                cue(now)
        self._hold_until = None
