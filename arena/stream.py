"""The Arena's side of the multiplayer frame bridge (S2 — "frames in, clicks back").

When Oubliette hosts a table, every browser should see the fight and be able to
click it. The pygame Arena stays exactly what it is — a desktop window on the
host — and this module streams it: the rendered screen is captured a few times a
second, JPEG-compressed, and pushed to the app server over one websocket; remote
players' clicks come back down the same socket as small JSON messages and are
replayed into the pygame event queue as if the host had made them.

Activation is entirely environmental: the app server sets
``OUBLIETTE_ARENA_BRIDGE`` (a ``ws://127.0.0.1:<port>/ws/arena?token=…`` URL) in
its own environment, the Arena subprocess inherits it, and ``Bridge.from_env()``
picks it up. Solo play without the variable — or any connect/stream failure —
leaves the fight completely untouched: streaming is a luxury, never a
dependency. The subprocess contract (encounter.json → result.json) is blind to
all of this.

Threading shape: the main pygame loop calls ``offer()`` (capture) and
``take_events()`` (input replay) — everything websocket lives on two daemon
threads (a receive loop and a send loop) that die with the fight.

Remote input replays through ``pygame.mouse.set_pos`` BEFORE the synthesized
event is dispatched: several panels (the action bar's click gate, wheel-target
checks, tooltips) read the live cursor via ``mouse.get_pos()`` rather than
``event.pos``, so a remote click must move the one true cursor to land. That is
also the honest picture of the table: one shared cursor, whoever moved last.
"""

from __future__ import annotations

import json
import os
import threading
import time
import zlib
from collections import deque
from io import BytesIO

import pygame

ENV_VAR = "OUBLIETTE_ARENA_BRIDGE"
FRAME_EVERY = 3      # capture every Nth rendered frame — 60fps loop → ~20fps stream
JPEG_QUALITY = 70    # plenty for a tactical board; ~60-90KB per 1280×720 frame

# The live bridge, if any — so the sound manager can emit audio cues (S3)
# without threading a reference through the GUI. Set by start(), cleared by
# stop(); emit_cue() is a no-op the rest of the time.
_ACTIVE: "Bridge | None" = None


def emit_cue(cue: dict) -> None:
    """Send a small JSON cue (music started/stopped, a stinger fired) up the
    live bridge, from any thread — the websockets sync connection serializes
    concurrent sends internally. Audio is a luxury like frames: any failure
    is swallowed and the fight plays on.

    The fight's OPENING cues race the websocket handshake (the encounter loads
    while the bridge is still connecting). A music-state cue is remembered and
    flushed on connect — the soundtrack must survive the race; a stinger fired
    before anyone was watching honestly doesn't matter."""
    b = _ACTIVE
    if b is None:
        return
    if not b.alive or b._ws is None:
        if cue.get("t") in ("music", "music_stop"):
            b._pending_music = cue
        return
    try:
        b._ws.send(json.dumps(cue))
    except Exception:
        pass


def _encode_jpeg(raw: bytes, size: tuple[int, int]) -> bytes:
    """RGB bytes → JPEG. Pillow when present (declared in the arena extra;
    quality-controlled), else pygame's own encoder (no quality knob — an old
    install that never re-ran setup still streams, just heavier)."""
    buf = BytesIO()
    try:
        from PIL import Image
        Image.frombytes("RGB", size, raw).save(buf, "JPEG", quality=JPEG_QUALITY)
    except ImportError:
        surf = pygame.image.frombytes(raw, size, "RGB")
        pygame.image.save(surf, buf, "frame.jpg")
    return buf.getvalue()


class Bridge:
    """One fight's streaming link: frames up, remote input down."""

    def __init__(self, url: str):
        self.url = url
        self.alive = False               # a live websocket exists right now
        self._cond = threading.Condition()
        self._raw: tuple[bytes, tuple[int, int]] | None = None   # latest capture
        self._last_hash: int | None = None
        self._stop = False
        self._ws = None
        self._inputs: deque[dict] = deque()      # remote messages, receive → main loop
        self._buttons_down: set[int] = set()     # remote button state (motion events)
        self._last_pos = (0, 0)
        self._size = (1280, 720)                 # last captured size (coordinate clamp)
        self._pending_music: dict | None = None  # music cue that raced the connect

    @classmethod
    def from_env(cls) -> "Bridge | None":
        url = os.environ.get(ENV_VAR, "").strip()
        return cls(url) if url else None

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        global _ACTIVE
        _ACTIVE = self
        threading.Thread(target=self._run, name="arena-bridge", daemon=True).start()

    def stop(self) -> None:
        global _ACTIVE
        if _ACTIVE is self:
            _ACTIVE = None
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _run(self) -> None:
        """Connect (brief retries — the server is our own parent process on
        loopback), then receive remote input until the fight or the link ends."""
        from websockets.sync.client import connect
        for _ in range(5):
            if self._stop:
                return
            try:
                self._ws = connect(self.url, max_size=None)
                break
            except Exception:
                time.sleep(0.4)
        else:
            return                        # no stream today; the fight goes on
        self.alive = True
        cue, self._pending_music = self._pending_music, None
        if cue is not None:                # the soundtrack that raced the handshake
            try:
                self._ws.send(json.dumps(cue))
            except Exception:
                pass
        threading.Thread(target=self._send_loop, name="arena-bridge-send",
                         daemon=True).start()
        try:
            for msg in self._ws:
                if isinstance(msg, str):
                    try:
                        self._inputs.append(json.loads(msg))
                    except ValueError:
                        continue
        except Exception:
            pass
        finally:
            self.alive = False
            with self._cond:
                self._cond.notify_all()   # wake the sender so it can exit

    # --- frames (main loop → send thread) -----------------------------------

    def offer(self, surface: "pygame.Surface") -> None:
        """Called from the render loop every Nth frame: snapshot the screen if it
        changed since the last snapshot. The raw copy is cheap (~1-2ms); the JPEG
        encode happens on the send thread. Latest-wins — an unsent frame is
        simply replaced, so a slow link shows fresh pictures, not a backlog."""
        if not self.alive:
            return
        raw = pygame.image.tobytes(surface, "RGB")
        h = zlib.adler32(raw)
        if h == self._last_hash:
            return                        # idle board — no bytes on the wire
        self._last_hash = h
        self._size = surface.get_size()
        with self._cond:
            self._raw = (raw, self._size)
            self._cond.notify_all()

    def _send_loop(self) -> None:
        while True:
            with self._cond:
                while self._raw is None and not self._stop and self.alive:
                    self._cond.wait(1.0)
                if self._stop or not self.alive:
                    return
                raw, size = self._raw
                self._raw = None
            try:
                self._ws.send(_encode_jpeg(raw, size))
            except Exception:
                self.alive = False
                return

    # --- remote input (receive thread → main loop) ---------------------------

    def take_events(self) -> list["pygame.event.Event"]:
        """Drain remote input into synthesized pygame events, warping the real
        cursor first (see the module docstring). Called from the main loop only."""
        out: list[pygame.event.Event] = []
        while True:
            try:
                msg = self._inputs.popleft()
            except IndexError:
                break
            out.extend(self._events_for(msg))
        return out

    def _events_for(self, msg: dict) -> list["pygame.event.Event"]:
        k = msg.get("k")
        if k in ("down", "up", "move", "wheel"):
            w, h = self._size
            x = max(0, min(int(msg.get("x", 0)), w - 1))
            y = max(0, min(int(msg.get("y", 0)), h - 1))
            self._warp(x, y)
            if k in ("down", "up"):
                button = int(msg.get("b", 1))
                (self._buttons_down.add if k == "down"
                 else self._buttons_down.discard)(button)
                etype = pygame.MOUSEBUTTONDOWN if k == "down" else pygame.MOUSEBUTTONUP
                self._last_pos = (x, y)
                return [pygame.event.Event(etype, pos=(x, y), button=button, touch=False)]
            if k == "move":
                rel = (x - self._last_pos[0], y - self._last_pos[1])
                self._last_pos = (x, y)
                buttons = tuple(int(b in self._buttons_down) for b in (1, 2, 3))
                return [pygame.event.Event(pygame.MOUSEMOTION, pos=(x, y), rel=rel,
                                           buttons=buttons, touch=False)]
            dy = int(msg.get("dy", 0))
            self._last_pos = (x, y)
            return [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=dy, precise_x=0.0,
                                       precise_y=float(dy), flipped=False,
                                       touch=False)] if dy else []
        if k == "key":
            name = str(msg.get("key", ""))
            try:
                code = pygame.key.key_code(name)
            except (ValueError, pygame.error):
                return []
            uni = name if len(name) == 1 else ""
            return [pygame.event.Event(pygame.KEYDOWN, key=code, mod=0,
                                       unicode=uni, scancode=0),
                    pygame.event.Event(pygame.KEYUP, key=code, mod=0, scancode=0)]
        return []

    @staticmethod
    def _warp(x: int, y: int) -> None:
        try:
            pygame.mouse.set_pos((x, y))
        except pygame.error:
            pass                          # no window (headless tests) — events still flow
