"""S5: engine-owned time-of-day & weather, and the soundscape reacting to them.

The DM reports the current environment each turn; code records ENVIRONMENT_CHANGED so
it persists and replays (like LOCATION_CHANGED). The soundscape resolver then filters
cues by the live time/weather — an 'any' cue always plays, a 'night'/'storm' cue only
when it's night/storming.
"""

from __future__ import annotations

import os
import tempfile

# The server builds its game singleton at import against OUBLIETTE_DB. Point it at a
# throwaway BEFORE importing it (as test_server_frontend does), so importing server here
# never opens — or locks, or wipes — the real save.
os.environ["OUBLIETTE_DB"] = os.path.join(tempfile.mkdtemp(), "env-test.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)

from oubliette.app import server  # noqa: E402
from oubliette.content.loader import PlaceNode  # noqa: E402
from oubliette.record.store import SqliteEventStore  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402


def test_environment_defaults_and_survives_reload(tmp_path):
    db = str(tmp_path / "env.sqlite")
    s = Session.open(SqliteEventStore(db))
    assert (s.time_of_day, s.weather) == ("day", "clear")        # sensible defaults

    s.emit_environment(time_of_day="night", weather="storm", reason="dusk; a storm breaks")
    assert (s.time_of_day, s.weather) == ("night", "storm")
    # a None field leaves that aspect unchanged
    s.emit_environment(weather="clear", reason="the storm passes")
    assert (s.time_of_day, s.weather) == ("night", "clear")
    s.store.close()

    reloaded = Session.open(SqliteEventStore(db))                  # replays ENVIRONMENT_CHANGED
    assert (reloaded.time_of_day, reloaded.weather) == ("night", "clear")


def test_soundscape_filters_by_time_and_weather():
    bed = lambda f, t="any", w="any": {"file": f, "kind": "bed", "category": "sfx",
                                       "scope": "local", "time": t, "weather": w}
    node = PlaceNode("x", "X", "d", None, (),
                     sounds=(bed("theme.ogg"), bed("fire.ogg", t="night"), bed("rain.ogg", w="rain")))
    g = server.GAME
    keep = (g.session.places, g.session.location, g.session.time_of_day, g.session.weather)
    try:
        g.session.places = {"x": node}
        g.session.location = "x"
        g.session.time_of_day, g.session.weather = "day", "clear"
        assert {l["file"] for l in server._soundscape()} == {"theme.ogg"}          # only 'any'
        g.session.time_of_day = "night"
        assert {l["file"] for l in server._soundscape()} == {"theme.ogg", "fire.ogg"}
        g.session.weather = "rain"
        assert {l["file"] for l in server._soundscape()} == {"theme.ogg", "fire.ogg", "rain.ogg"}
    finally:
        (g.session.places, g.session.location, g.session.time_of_day, g.session.weather) = keep
