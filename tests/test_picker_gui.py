import contextlib
import os
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
except (ImportError, ValueError):
    Gtk = None


class Proxy:
    event = js = None

    def __init__(self, *_):
        pass

    def ready(self):
        return True

    def reset(self):
        pass

    def close(self):
        pass


class Source:
    path = "/dev/null"

    def ungrab(self):
        pass

    def close(self):
        pass


def pump(seconds=0.06):
    # Style classes take effect on the next frame, so let the frame clock run
    # before measuring.
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not Gtk.main_iteration_do(False):
            time.sleep(0.002)


@unittest.skipUnless(
    Gtk is not None and os.environ.get("DISPLAY"),
    "requires GTK and an X11 display, e.g. xvfb-run",
)
class PickerTests(unittest.TestCase):
    @contextlib.contextmanager
    def lobby(self, profiles=None, **settings):
        """Real GTK windows and seat logic; only Linux devices are replaced."""
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
            from mc_couch.ui import install_css

            install_css()
            self.opened = []
            with (
                patch.object(session, "ROOT", Path(temp) / "data"),
                patch.object(session, "PadProxy", Proxy),
                patch.object(
                    session.Seat,
                    "attach",
                    lambda seat, _pad: setattr(seat, "source", Source()),
                ),
                patch.object(
                    session, "open_steam_keyboard", lambda: self.opened.append(1)
                ),
            ):
                app = session.Lobby(Settings(**settings), preview=True)
                if profiles:
                    for name in profiles:
                        app.profile_store.add_local(name)
                    app.profiles = [p["name"] for p in app.profile_store.visible()]
                try:
                    yield session, app
                finally:
                    app.cleanup()
                    app.base.destroy()

    @staticmethod
    def add(session, app, number):
        seat = session.Seat(app, number, {"key": f"test-{number}"})
        app.seats.append(seat)
        app.retile()
        return seat

    def test_four_remembered_profiles_join_via_the_actual_picker(self):
        with self.lobby() as (session, app):
            for n in range(1, 5):
                seat = session.Seat(app, n, {"key": f"test-{n}"})
                app.seats.append(seat)
                seat.chosen = n - 1
                seat.render()
            for n, seat in enumerate(app.seats, 1):
                seat.action("ok")
                self.assertEqual(seat.mode, "queued")
                self.assertEqual(seat.profile, f"Player{n}")
                pump()

    def test_every_panel_fits_its_screen_region(self):
        # A panel larger than its region makes GTK and the KWin layout script
        # fight over the window size: the old three/four-player keyboard flicker.
        names = ["Alex", "Steve", "Sunny", "Kai", "Noor", "Zara", "Ollie"]
        for width, height in [(1920, 1080), (1280, 800), (1280, 720)]:
            with self.lobby(names, width=width, height=height) as (session, app):
                for count in range(1, 5):
                    seat = self.add(session, app, count)
                    seat.show_error("That profile is already playing.")
                    for mode in ("menu", "edit", "steam", "queued", "disconnected"):
                        seat.mode, seat.disconnected = "menu", None
                        if mode in ("edit", "steam"):
                            seat.start_entry()
                            seat.steam_keys = mode == "steam"
                            seat.typed = "W" * 16
                            seat.show_error("Names can be up to 16 characters")
                        elif mode == "queued":
                            seat.mode, seat.profile = "queued", "Player1"
                        elif mode == "disconnected":
                            seat.disconnected = time.monotonic()
                        seat.render()
                        pump()
                        for each in app.seats:
                            if not each.window.get_visible():
                                continue
                            minimum, _ = each.window.get_preferred_size()
                            label = (
                                f"{width}x{height} {count}p seat {each.number} {mode}"
                            )
                            self.assertLessEqual(minimum.width, each.rect[2], label)
                            self.assertLessEqual(minimum.height, each.rect[3], label)
                        minimum, _ = app.base.get_preferred_size()
                        self.assertLessEqual(minimum.width, width)
                        self.assertLessEqual(minimum.height, height)
                    seat.leave_entry()
                    seat.profile, seat.disconnected = None, None
                    seat.mode = "menu"
                    seat.render()

    def test_name_entry_with_controller_and_keyboard(self):
        with self.lobby(["Steve"]) as (session, app):
            seat = self.add(session, app, 1)
            seat.choose(seat.choices().index("＋ New profile"))
            seat.action("ok")  # Steam keyboard closed: use the controller keys
            self.assertFalse(seat.steam_keys)
            seat.view.keyboard.place(1, 0)
            seat.action("ok")
            seat.action("right")
            seat.action("ok")
            self.assertEqual(seat.typed, "Qw")  # first letter auto-capitalized
            seat.action("x")
            seat.action("x")
            seat.action("ok")
            seat.action("ok")
            self.assertEqual(seat.typed, "QwWW")  # X twice is caps lock
            event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
            for char in "-9":
                event.keyval = Gdk.unicode_to_keyval(ord(char))
                seat.keyboard(seat.window, event)
            self.assertEqual(seat.typed, "QwWW9")  # "-" is rejected
            for _ in range(5):
                seat.action("back")
            self.assertEqual(seat.typed, "")
            seat.action("back")  # leaves name entry
            seat.action("back")  # mashed: must not also sit out
            self.assertEqual(seat.mode, "menu")
            seat.choose(seat.choices().index("＋ New profile"))
            seat.action("ok")
            seat.typed = "steve"
            seat.save_name()
            self.assertEqual(seat.mode, "menu")
            self.assertEqual(seat.choices()[seat.chosen], "Steve")
            seat.choose(seat.choices().index("＋ New profile"))
            seat.typed = "Alex_2"
            event.keyval = Gdk.KEY_Return
            seat.keyboard(seat.window, event)
            self.assertEqual(seat.mode, "queued")
            self.assertIn("Alex_2", app.profiles)

    def test_steam_keyboard_only_when_it_fits_the_player_region(self):
        with self.lobby() as (session, app):
            first = self.add(session, app, 1)
            first.choose(first.choices().index("＋ New profile"))
            self.assertTrue(first.steam_keys)
            self.assertEqual(len(self.opened), 1)
            self.assertIs(app.focus, first)
            second = self.add(session, app, 2)
            self.assertFalse(first.steam_keys)  # the screen split under it
            second.choose(second.choices().index("＋ New profile"))
            second.action("y")
            self.assertFalse(second.steam_keys)
            self.assertEqual(len(self.opened), 1)
            for rect in ([0, 0, 960, 540], [0, 540, 1920, 540], [0, 0, 1920, 540]):
                self.assertFalse(session.osk_fits(rect), rect)
            self.assertTrue(session.osk_fits([0, 0, 1920, 1080]))


if __name__ == "__main__":
    unittest.main()
