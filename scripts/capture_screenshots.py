#!/usr/bin/env python3
"""Capture real GTK windows with synthetic seat attachments, never gameplay.

Run: xvfb-run -a -s '-screen 0 1920x1080x24' python3 scripts/capture_screenshots.py
The temporary configuration contains only example.net and example profiles.
SteamOS renders with Adwaita Sans; install it locally for matching captures.
"""

import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory()
os.environ["MC_COUCH_DATA"] = temporary.name + "/data"
os.environ["MC_COUCH_CONFIG"] = temporary.name + "/config.json"
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from mc_couch.config import Settings
from mc_couch.setup_ui import SetupWindow
from mc_couch.ui import install_css
import mc_couch.session as session

Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
WIDTH, HEIGHT = 1920, 1080
settings = Settings(server="play.example.net:25565", width=WIDTH, height=HEIGHT)
settings.save()
destination = ROOT / "docs/screenshots"
destination.mkdir(parents=True, exist_ok=True)


class PreviewPad:
    event = js = None

    def __init__(self, *_):
        pass

    def ready(self):
        return True

    def reset(self):
        pass

    def close(self):
        pass


def capture(window, filename):
    native = window.get_window()
    width, height = window.get_size()
    image = Gdk.pixbuf_get_from_window(native, 0, 0, width, height)
    if image is None:
        raise RuntimeError("GTK window capture failed")
    image.savev(str(destination / filename), "png", [], [])
    print(filename, width, height)


def capture_screen(filename):
    root = Gdk.get_default_root_window()
    image = Gdk.pixbuf_get_from_window(root, 0, 0, WIDTH, HEIGHT)
    image.savev(str(destination / filename), "png", [], [])
    print(filename, WIDTH, HEIGHT)


def later(delay, step):
    GLib.timeout_add(delay, lambda: step() and False)


setup = SetupWindow()
setup.window.show_all()


def lobby_capture():
    capture(setup.window, "setup.png")
    setup.window.destroy()
    install_css()
    patches = [
        patch("mc_couch.session.PadProxy", PreviewPad),
        patch.object(session.Seat, "attach", lambda *_: None),
        patch("mc_couch.session.open_steam_keyboard", lambda: None),
    ]
    for item in patches:
        item.start()
    lobby = session.Lobby(settings, preview=True)
    for name in ["Alex", "Steve", "Sunny"]:
        lobby.profile_store.add_local(name)
    lobby.profiles = [p["name"] for p in lobby.profile_store.visible()]
    lobby.last_profiles["preview-2"] = "Steve"
    lobby.base.resize(WIDTH, HEIGHT)
    lobby.base.move(0, 0)
    seats = []

    def pickers():
        capture_screen("lobby.png")
        for number in range(1, 5):
            seat = session.Seat(lobby, number, {"key": f"preview-{number}"})
            lobby.seats.append(seat)
            seats.append(seat)
        for seat, name in zip(seats, ["Player1", "Steve", "Alex", "＋ New profile"]):
            seat.chosen = seat.choices().index(name)
            seat.render()
        lobby.retile()
        later(600, keyboards)

    def keyboards():
        capture_screen("profile-picker.png")
        first, second, third, fourth = seats
        first.start_entry()
        first.type_text("Alex_2")
        first.view.keyboard.place(2, 9)
        third.start_entry()
        third.view.keyboard.place(1, 4)
        fourth.disconnected = time.monotonic() - 3
        for seat in seats:
            seat.render()
        lobby.retile()
        later(600, finish)

    def finish():
        capture_screen("name-keyboard.png")
        lobby.cleanup()
        lobby.base.destroy()
        for item in patches:
            item.stop()
        Gtk.main_quit()

    later(500, pickers)


later(600, lobby_capture)
Gtk.main()
