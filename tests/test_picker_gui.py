import os
import tempfile
import unittest
from unittest.mock import patch

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    Gtk = None


@unittest.skipUnless(
    Gtk is not None and os.environ.get("DISPLAY"),
    "requires GTK and an X11 display, e.g. xvfb-run",
)
class PickerTests(unittest.TestCase):
    def test_four_remembered_profiles_join_via_the_actual_picker(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(
                os.environ,
                {
                    "MC_COUCH_DATA": temp + "/data",
                    "MC_COUCH_CONFIG": temp + "/config.json",
                },
            ),
        ):
            from pathlib import Path
            import mc_couch.session as session
            from mc_couch.config import Settings

            class Proxy:
                def __init__(self, *_):
                    pass

                def ready(self):
                    return True

                def reset(self):
                    pass

                def close(self):
                    pass

            # Replace only Linux device attachment; use real GTK windows,
            # rendered choices, controller actions and profile claiming logic.
            with (
                patch.object(session, "ROOT", Path(temp) / "data"),
                patch.object(session, "PadProxy", Proxy),
                patch.object(session.Seat, "attach", lambda *_: None),
            ):
                app = session.Lobby(Settings(), preview=True)
                try:
                    for n in range(1, 5):
                        seat = session.Seat(app, n, {"key": f"test-{n}"})
                        app.seats.append(seat)
                        seat.chosen = n - 1
                        seat.render()
                    for n, seat in enumerate(app.seats, 1):
                        seat.action("ok")
                        self.assertEqual(seat.mode, "queued")
                        self.assertEqual(seat.profile, f"Player{n}")
                        while Gtk.events_pending():
                            Gtk.main_iteration_do(False)
                finally:
                    app.cleanup()
                    app.base.destroy()


if __name__ == "__main__":
    unittest.main()
