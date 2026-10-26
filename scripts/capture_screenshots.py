#!/usr/bin/env python3
"""Capture real GTK windows with synthetic seat attachments, never gameplay.

Run: xvfb-run -a -s '-screen 0 1440x1000x24' python3 scripts/capture_screenshots.py
The temporary configuration contains only example.net and Player1..Player4.
"""

import os
from pathlib import Path
import sys
import tempfile
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
from mc_couch.session import Lobby, Seat

Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
settings = Settings(server="play.example.net:25565", width=1280, height=800)
settings.save()
destination = ROOT / "docs/screenshots"
destination.mkdir(parents=True, exist_ok=True)


def capture(window, filename):
    native = window.get_window()
    width, height = window.get_size()
    image = Gdk.pixbuf_get_from_window(native, 0, 0, width, height)
    if image is None:
        raise RuntimeError("GTK window capture failed")
    image.savev(str(destination / filename), "png", [], [])
    print(filename, width, height)


setup = SetupWindow()
setup.window.show_all()


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


def lobby_capture():
    capture(setup.window, "setup.png")
    setup.window.destroy()
    css = Gtk.CssProvider()
    css.load_from_data(
        b"window {background:#172624;color:#eef4e9;font-family:sans-serif;font-size:17px} button {background:#29433a;color:#eef4e9;border:2px solid #496358;border-radius:5px;padding:3px 8px;min-height:18px} button.selected {background:#4f7b39;border-color:#c0ed8b;color:white} .title {font-size:72px;font-weight:bold} .heading {font-size:24px;font-weight:bold;color:#c0ed8b} .hint {color:#c0cbbf;font-size:14px} .name {font-size:24px}"
    )
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    lobby = Lobby(settings, preview=True)
    lobby.base.resize(1280, 800)
    lobby.base.move(0, 0)

    def seats_capture():
        capture(lobby.base, "lobby.png")
        with (
            patch("mc_couch.session.PadProxy", PreviewPad),
            patch.object(Seat, "attach", lambda *_: None),
        ):
            for number in range(1, 5):
                seat = Seat(lobby, number, {"key": "preview-" + str(number)})
                seat.chosen = number - 1
                lobby.seats.append(seat)
                seat.render()
        lobby.retile()

        def finish():
            root = Gdk.get_default_root_window()
            image = Gdk.pixbuf_get_from_window(root, 0, 0, 1280, 800)
            image.savev(str(destination / "profile-picker.png"), "png", [], [])
            print("profile-picker.png", 1280, 800)
            lobby.cleanup()
            lobby.base.destroy()
            Gtk.main_quit()
            return False

        GLib.timeout_add(600, finish)
        return False

    GLib.timeout_add(500, seats_capture)
    return False


GLib.timeout_add(600, lobby_capture)
Gtk.main()
