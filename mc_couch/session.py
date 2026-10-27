#!/usr/bin/python3
"""Four-player couch lobby inside an isolated nested KWin session."""

import atexit
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gio
from .linux_input import InputDevice, E, enumerate_pads, VirtualGamepad as PadProxy
from .config import Settings, data_root, runtime_root, atomic_json
from .profiles import Profiles, selection_index
from .game import start_game, reap_async
from .ui import NEW, SIT_OUT, NAME_LIMIT, KEY_ROWS, SeatView, LobbyView, install_css

ROOT = data_root()

WIDTH, HEIGHT = 1920, 1080
NAME = re.compile(r"[A-Za-z0-9_]{1,16}")
# Linux gamepads report the left face button (X) as BTN_NORTH and the top one
# (Y) as BTN_WEST.
BUTTONS = {
    E.BTN_SOUTH: "ok",
    E.BTN_EAST: "back",
    E.BTN_START: "start",
    E.BTN_NORTH: "x",
    E.BTN_WEST: "y",
}
DPAD = {
    E.BTN_DPAD_UP: "up",
    E.BTN_DPAD_DOWN: "down",
    E.BTN_DPAD_LEFT: "left",
    E.BTN_DPAD_RIGHT: "right",
}
# Steam's keyboard is a fixed full-width panel along the bottom of the screen.
# It is only offered when it lands inside the typing player's own screen and
# still leaves room above it for the name field; otherwise our keyboard is used.
OSK_HEIGHT = float(os.environ.get("MC_COUCH_OSK_HEIGHT", "0.42"))
OSK_FIELD_ROOM = 0.14


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def osk_fits(rect):
    if not rect:
        return False
    x, y, width, height = rect
    return (
        x == 0
        and width >= WIDTH
        and y + height >= HEIGHT
        and height - OSK_HEIGHT * HEIGHT >= OSK_FIELD_ROOM * HEIGHT
    )


def open_steam_keyboard():
    """Ask the running Steam client for its keyboard, as SteamOS's GTK input module does."""
    runtime = os.environ.get("STEAM_RUNTIME")
    candidates = [Path(runtime).parent / "steam"] if runtime else []
    candidates += [
        Path.home() / ".local/share/Steam/ubuntu12_32/steam",
        Path.home() / ".steam/root/ubuntu12_32/steam",
    ]
    exe = next((str(p) for p in candidates if p.exists()), "steam")
    env = os.environ.copy()
    env.pop("LD_PRELOAD", None)
    env.pop("LD_LIBRARY_PATH", None)
    env["DISPLAY"] = os.environ.get("MC_COUCH_STEAM_DISPLAY", ":1")
    try:
        proc = subprocess.Popen(
            [exe, "-if-running", "steam://open/keyboard"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        threading.Thread(target=proc.wait, daemon=True).start()
    except OSError as exc:
        log(f"Steam keyboard: {exc}")


class Seat:
    def __init__(self, app, number, pad):
        self.app, self.number, self.key = app, number, pad["key"]
        self.source = self.watch = None
        self.proxy = PadProxy(number)
        self.mode = "menu"
        self.profile = None
        self.proc = self.output = None
        self.chosen = 0
        self.menu_choices = []
        self.held = set()
        self.chord_since = None
        self.disconnected = None
        self.stop_deadline = None
        self.launched_at = None
        self.game_window_visible = False
        self.error = ""
        self.error_at = 0
        self.typed = ""
        self.shift = "once"
        self.steam_keys = False
        self.steam_opened = 0
        self.back_guard = 0
        self.rect = None
        self.directions = {}
        self.axes = {}
        self.nav = None
        self.nav_timer = None
        self.view = SeatView(
            number, self.row_clicked, self.key_clicked, self.field_clicked
        )
        self.view.set_geometry(WIDTH // 2, HEIGHT // 2)
        self.window = self.view.window
        self.window.connect("key-press-event", self.keyboard)
        try:
            self.attach(pad)
            self.render()
        except Exception:
            # A controller can vanish between the scan and the open.
            self.detach()
            self.proxy.close()
            self.window.destroy()
            raise

    def attach(self, pad):
        self.detach()
        self.source = InputDevice(pad["path"])
        self.source.grab()
        self.watch = GLib.io_add_watch(
            self.source.fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.read
        )
        self.disconnected = None
        self.held.clear()
        log(f"Seat {self.number}: {pad['name']} attached")
        if self.mode == "edit":
            self.app.request_focus(self)
        self.render()

    def detach(self):
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = None
        if self.source:
            try:
                self.source.ungrab()
            except OSError:
                pass
            self.source.close()
            self.source = None
        self.steer("all", None)
        self.proxy.reset()

    def read(self, fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            self.watch = None
            self.lost()
            return False
        try:
            for ev in self.source.read():
                navigating = self.mode in ("menu", "edit", "off")
                if ev.type == E.EV_KEY:
                    if ev.value:
                        self.held.add(ev.code)
                    else:
                        self.held.discard(ev.code)
                    if navigating and ev.code in DPAD:
                        if ev.value == 1:
                            self.steer("dpad", DPAD[ev.code])
                        elif (
                            ev.value == 0
                            and self.directions.get("dpad") == DPAD[ev.code]
                        ):
                            self.steer("dpad", None)
                    elif navigating and ev.value == 1 and ev.code in BUTTONS:
                        self.action(BUTTONS[ev.code])
                elif ev.type == E.EV_ABS and navigating:
                    self.axis(ev.code, ev.value)
                if self.mode in ("play", "loading"):
                    self.proxy.forward(ev, self.source)
        except BlockingIOError:
            pass
        except OSError as exc:
            log(f"Seat {self.number}: input disconnected ({exc})")
            self.watch = None
            self.lost()
            return False
        return True

    def axis(self, code, value):
        if code in (E.ABS_HAT0X, E.ABS_HAT0Y):
            self.axes[code] = (value > 0) - (value < 0)
            x, y = self.axes.get(E.ABS_HAT0X, 0), self.axes.get(E.ABS_HAT0Y, 0)
            source = "hat"
        elif code in (E.ABS_X, E.ABS_Y):
            info = self.source.absinfo(code)
            amount = ((value - info.min) / max(1, info.max - info.min) - 0.5) * 2
            # Hysteresis: a resting stick near the threshold must not chatter.
            if abs(amount) > 0.6:
                self.axes[code] = 1 if amount > 0 else -1
            elif abs(amount) < 0.35:
                self.axes[code] = 0
            x, y = self.axes.get(E.ABS_X, 0), self.axes.get(E.ABS_Y, 0)
            source = "stick"
        else:
            return
        if y:
            direction = "down" if y > 0 else "up"
        elif x:
            direction = "right" if x > 0 else "left"
        else:
            direction = None
        self.steer(source, direction)

    def steer(self, source, direction):
        """Fire on a new direction, then repeat while it is held."""
        if source == "all":
            self.directions.clear()
            self.axes.clear()
        else:
            self.directions[source] = direction
        current = next((d for d in self.directions.values() if d), None)
        if current == self.nav:
            return
        self.nav = current
        if self.nav_timer:
            GLib.source_remove(self.nav_timer)
            self.nav_timer = None
        if current:
            self.action(current)
            self.nav_timer = GLib.timeout_add(380, self.repeat_start)

    def repeat_start(self):
        self.nav_timer = GLib.timeout_add(110, self.repeat)
        return self.repeat()

    def repeat(self):
        if not self.nav or self.mode not in ("menu", "edit") or self.disconnected:
            self.nav_timer = None
            return False
        self.action(self.nav, repeat=True)
        return True

    def lost(self):
        self.detach()
        self.disconnected = time.monotonic()
        self.held.clear()
        if self.mode == "edit":
            self.app.release_focus(self)
        self.render()

    def choices(self):
        used = {
            s.profile.lower()
            for s in self.app.seats
            if s is not self
            and s.profile
            and s.mode in ("queued", "loading", "play", "stopping")
        }
        return (
            [p for p in self.app.profiles if p.lower() not in used]
            + ([NEW] if self.app.settings.account_mode == "local" else [])
            + [SIT_OUT]
        )

    def sync_selection(self):
        choices = self.choices()
        self.chosen = selection_index(self.menu_choices, choices, self.chosen)
        self.menu_choices = choices
        return choices

    def show_error(self, message):
        self.error, self.error_at = message, time.monotonic()

    def action(self, action, repeat=False):
        if self.disconnected:
            return
        if self.mode == "off":
            if action in ("ok", "start"):
                self.mode = "menu"
                self.app.retile()
                self.render()
            elif action == "back" and all(s.mode == "off" for s in self.app.seats):
                self.app.quit()
            return
        if self.mode == "edit":
            self.edit_action(action, repeat)
            return
        if self.mode != "menu":
            return
        choices = self.sync_selection()
        if action in ("up", "left", "down", "right"):
            step = 1 if action in ("down", "right") else -1
            if repeat and not 0 <= self.chosen + step < len(choices):
                return
            self.chosen = (self.chosen + step) % len(choices)
        elif action == "back":
            # Mashing B to erase a name must not also sit the player out.
            if time.monotonic() > self.back_guard:
                self.sit_out()
            return
        elif action in ("ok", "start"):
            self.choose(self.chosen)
            return
        self.render()

    def choose(self, index):
        choices = self.sync_selection()
        self.chosen = index % len(choices)
        chosen = choices[self.chosen]
        if chosen == NEW:
            self.start_entry()
        elif chosen == SIT_OUT:
            self.sit_out()
        else:
            self.begin(chosen)

    def sit_out(self):
        self.mode, self.error = "off", ""
        self.window.hide()
        self.app.retile()

    def start_entry(self):
        self.mode, self.typed, self.shift, self.error = "edit", "", "once", ""
        self.view.keyboard.place(1, 0)
        self.steam_keys = osk_fits(self.rect)
        # Keystrokes from Steam's keyboard or a USB keyboard go to the focused window.
        self.app.request_focus(self)
        if self.steam_keys:
            self.open_steam_keys()
        self.render()

    def open_steam_keys(self):
        now = time.monotonic()
        if now - self.steam_opened > 1.5:
            self.steam_opened = now
            open_steam_keyboard()

    def leave_entry(self):
        self.app.release_focus(self)
        self.mode, self.steam_keys = "menu", False
        self.back_guard = time.monotonic() + 0.6

    def edit_action(self, action, repeat=False):
        if self.steam_keys:
            # Controller input only reaches us once Steam's keyboard is closed.
            if action == "y":
                self.app.request_focus(self)
                self.open_steam_keys()
            elif action == "back":
                self.leave_entry()
            elif action == "start":
                self.save_name()
                return
            elif action in ("ok", "up", "down", "left", "right"):
                self.steam_keys = False
            self.render()
            return
        if action in ("up", "down", "left", "right"):
            self.view.keyboard.move(action, wrap=not repeat)
            return
        if action == "ok":
            self.press(self.view.keyboard.key())
            return
        if action == "back":
            if self.typed:
                self.erase()
            else:
                self.leave_entry()
        elif action == "x":
            self.toggle_shift()
        elif action == "y" and osk_fits(self.rect):
            self.steam_keys = True
            self.app.request_focus(self)
            self.open_steam_keys()
        elif action == "start":
            self.save_name()
            return
        self.render()

    def press(self, key):
        if key == "shift":
            self.toggle_shift()
        elif key == "erase":
            self.erase()
        elif key == "cancel":
            self.leave_entry()
        elif key == "done":
            self.save_name()
            return
        else:
            self.type_text(
                key if self.shift != "off" or not key.isalpha() else key.lower()
            )
            return
        self.render()

    def toggle_shift(self):
        self.shift = {"off": "once", "once": "lock", "lock": "off"}[self.shift]

    def erase(self):
        self.typed = self.typed[:-1]
        if not self.typed and self.shift == "off":
            self.shift = "once"
        self.error = ""

    def type_text(self, chars):
        for char in chars:
            if not NAME.fullmatch(char):
                self.show_error("Use letters, numbers or _")
                break
            if len(self.typed) >= NAME_LIMIT:
                self.show_error(f"Names can be up to {NAME_LIMIT} characters")
                break
            self.typed += char
            self.error = ""
            if self.shift == "once":
                self.shift = "off"
        self.render()

    def save_name(self):
        name = self.typed.strip()
        if not name:
            self.show_error("Type a name first")
            self.render()
            return
        existing = next(
            (p for p in self.app.profiles if p.lower() == name.lower()), None
        )
        if existing:
            self.leave_entry()
            choices = self.sync_selection()
            if existing in choices:
                self.chosen = choices.index(existing)
                self.show_error(f"{existing} already exists. Press A to play.")
            else:
                self.show_error(f"{existing} is already playing")
            self.render()
            return
        try:
            self.app.profile_store.add_local(name)
        except ValueError as exc:
            self.show_error(str(exc))
            self.render()
            return
        self.leave_entry()
        self.app.profiles = [p["name"] for p in self.app.profile_store.visible()]
        self.menu_choices = []
        self.chosen = self.choices().index(name)
        self.begin(name)

    def keyboard(self, widget, event):
        if self.mode == "edit" and not self.disconnected:
            if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.save_name()
            elif event.keyval == Gdk.KEY_BackSpace:
                self.erase()
                self.render()
            elif event.keyval == Gdk.KEY_Escape:
                self.leave_entry()
                self.render()
            elif not self.steam_keys and event.keyval in (
                Gdk.KEY_Up,
                Gdk.KEY_Down,
                Gdk.KEY_Left,
                Gdk.KEY_Right,
            ):
                self.view.keyboard.move(Gdk.keyval_name(event.keyval).lower())
            else:
                char = chr(Gdk.keyval_to_unicode(event.keyval) or 0)
                if char.isprintable() and char != "\0":
                    self.type_text(char)
                else:
                    return False
            return True
        action = {
            Gdk.KEY_Up: "up",
            Gdk.KEY_Down: "down",
            Gdk.KEY_Left: "left",
            Gdk.KEY_Right: "right",
            Gdk.KEY_Return: "ok",
            Gdk.KEY_Escape: "back",
        }.get(event.keyval)
        if action:
            self.action(action)
            return True
        return False

    def row_clicked(self, index):
        if self.mode == "menu" and not self.disconnected:
            self.choose(index)

    def key_clicked(self, row, index):
        if self.mode == "edit" and not self.disconnected:
            self.view.keyboard.place(row, index)
            self.press(KEY_ROWS[row][index][0])

    def field_clicked(self):
        if self.mode == "edit" and osk_fits(self.rect):
            self.steam_keys = True
            self.app.request_focus(self)
            self.open_steam_keys()
            self.render()

    def apply_rect(self, rect):
        if rect == self.rect:
            return
        self.rect = rect
        self.view.set_geometry(rect[2], rect[3])
        self.window.resize(rect[2], rect[3])
        self.window.move(rect[0], rect[1])
        if self.mode == "edit" and self.steam_keys and not osk_fits(rect):
            # The layout changed under Steam's keyboard; finish with ours.
            self.steam_keys = False
        self.render()

    def render(self):
        if self.mode == "off":
            self.window.hide()
            return
        view = self.view
        server = self.app.settings.server
        if self.disconnected:
            # Shown over a running game too, so the player knows why it stopped.
            left = self.app.settings.reconnect_seconds - (
                time.monotonic() - self.disconnected
            )
            view.show_status(
                None,
                "Controller disconnected",
                f"Reconnect within {max(0, int(left + 0.99))} s to keep your screen.",
                False,
            )
        elif self.mode == "play" or (
            self.mode == "loading" and self.game_window_visible
        ):
            self.window.hide()
            return
        elif self.mode == "menu":
            choices = self.sync_selection()
            view.show_menu(
                choices, self.chosen, self.app.last_profiles.get(self.key), self.error
            )
        elif self.mode == "edit":
            view.show_entry(
                self.typed,
                self.shift,
                self.steam_keys,
                osk_fits(self.rect),
                self.error,
            )
        elif self.mode == "queued":
            seats = self.app.seats
            ahead = sum(
                1
                for s in seats
                if s.mode == "loading"
                or (
                    s.mode == "queued"
                    and s.source
                    and seats.index(s) < seats.index(self)
                )
            )
            if not ahead:
                detail = "Starting now."
            elif ahead == 1:
                detail = "You are next."
            else:
                detail = f"{ahead} players ahead of you."
            view.show_status(
                self.profile,
                "Waiting for your turn",
                f"Players join one at a time. {detail}",
                True,
                self.error,
            )
        elif self.mode == "stopping":
            view.show_status(
                self.profile, "Leaving the world…", "Closing Minecraft.", True
            )
        else:
            view.show_status(
                self.profile,
                "Starting Minecraft…",
                f"Joining {server}.",
                True,
                self.error,
            )
        if not self.window.get_visible():
            self.window.show()

    def begin(self, name):
        if not self.proxy.ready():
            self.show_error("Preparing controller. Press A again in a moment.")
            self.render()
            return
        if any(
            s is not self
            and s.profile
            and s.mode in ("queued", "loading", "play", "stopping")
            and s.profile.lower() == name.lower()
            for s in self.app.seats
        ):
            self.show_error("That profile is already playing.")
            self.render()
            return
        self.profile, self.mode, self.error = name, "queued", ""
        for seat in self.app.seats:
            if seat is not self and seat.mode == "menu":
                seat.render()
        self.render()
        self.app.retile()

    def launch(self):
        try:
            name = self.profile
            self.proxy.reset()
            self.proc = start_game(
                self.app.profile_store.get(name),
                self.app.settings,
                self.proxy,
                self.number,
            )
            self.profile, self.mode, self.error = name, "loading", ""
            self.launched_at = time.monotonic()
            self.game_window_visible = False
            self.stop_deadline = None
            self.app.last_profiles[self.key] = name
            self.app.save_profiles()
            log(f"Seat {self.number}: launching {name}, supervisor PID {self.proc.pid}")
            self.render()
            self.app.retile()
        except Exception as exc:
            log(f"Seat {self.number}: launch failed: {exc}")
            self.show_error(str(exc))
            self.mode = "menu"
            self.render()

    def stop(self):
        self.proxy.reset()
        self.held.clear()
        self.chord_since = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.stop_deadline = time.monotonic() + 8
            self.mode = "stopping"
            self.render()
        else:
            self.mode = "off"
            self.window.hide()
            self.app.retile()

    def tick(self, now):
        if (
            self.mode in ("play", "loading", "queued")
            and {E.BTN_SELECT, E.BTN_START} <= self.held
        ):
            self.chord_since = self.chord_since or now
            if now - self.chord_since > 2:
                self.stop()
        else:
            self.chord_since = None
        if self.error and now - self.error_at > 6 and self.mode in ("menu", "edit"):
            self.error = ""
            self.render()
        if self.proc:
            status = self.proc.poll()
            if status is not None:
                log(f"Seat {self.number}: {self.profile} exited ({status})")
                reap_async(self.proc)
                self.proc = None
                self.output = None
                if status in (0, 143, -15):
                    self.error = ""
                else:
                    self.show_error("Minecraft closed. Press Start to try again.")
                self.mode = "off"
                self.window.hide()
                self.app.retile()
            elif self.stop_deadline and now > self.stop_deadline:
                self.proc.kill()
                self.stop_deadline = None

    def close(self):
        self.detach()
        if self.proc:
            reap_async(self.proc)
            self.proc = None
        self.proxy.close()
        self.window.destroy()


class Lobby:
    def __init__(self, settings=None, preview=False):
        self.settings = settings or Settings.load()
        self.preview = preview
        global WIDTH, HEIGHT
        WIDTH, HEIGHT = self.settings.width, self.settings.height
        ROOT.mkdir(parents=True, exist_ok=True)
        (ROOT / "logs").mkdir(exist_ok=True)
        self.seats = []
        self.last_scan = 0
        self.last_layout = 0
        self.last_script = 0
        self.script_signature = None
        self.focus = None
        self.closed = False
        self.launch_after = 0
        self.profile_store = Profiles(self.settings)
        self.profiles = [p["name"] for p in self.profile_store.visible()]
        self.last_profiles = self.profile_store.controllers
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None) if not preview else None
        self.script_path = runtime_root() / "layout.js"
        self.view = LobbyView(self.settings.server, self.quit)
        self.base = self.view.window
        self.base.set_default_size(WIDTH, HEIGHT)
        self.base.connect("delete-event", lambda *_: (self.quit(), True)[1])
        self.update_lobby()
        self.save_profiles()
        if not preview:
            GLib.timeout_add(50, self.tick)
        for signum in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self.quit)
        atexit.register(self.cleanup)
        log("Couch lobby ready; DISPLAY=" + os.environ.get("DISPLAY", ""))

    def save_profiles(self):
        self.profile_store.controllers = self.last_profiles
        self.profile_store.save()

    def request_focus(self, seat):
        self.focus = seat
        if not self.preview:
            seat.window.present()
        self.retile()

    def release_focus(self, seat):
        if self.focus is seat:
            self.focus = None
            self.retile()

    def tick(self):
        now = time.monotonic()
        if os.environ.get("MC_COUCH_TEST") == "1":
            test_file = ROOT / "test-actions.json"
            if test_file.exists():
                actions = json.loads(test_file.read_text())
                test_file.unlink()
                for action in actions:
                    seat = next(
                        (s for s in self.seats if s.number == action["slot"]), None
                    )
                    if seat:
                        if "profile" in action:
                            seat.mode = "menu"
                            seat.begin(action["profile"])
                        else:
                            seat.action(action["action"])
        if now - self.last_scan > 1:
            self.last_scan = now
            pads = enumerate_pads(os.environ.get("MC_COUCH_TEST") == "1")
            if (
                os.environ.get("MC_COUCH_TEST") == "1"
                and os.environ.get("MC_COUCH_TEST_ISOLATED") == "1"
            ):
                pads = [pad for pad in pads if pad["test"]]
            paths = {p["path"] for p in pads}
            for seat in list(self.seats):
                if seat.source and seat.source.path not in paths:
                    seat.lost()
                if seat.disconnected:
                    if now - seat.disconnected > self.settings.reconnect_seconds:
                        if self.focus is seat:
                            self.focus = None
                        seat.close()
                        self.seats.remove(seat)
                        self.retile()
                    else:
                        seat.render()
            for pad in pads:
                if any(s.source and s.source.path == pad["path"] for s in self.seats):
                    continue
                reconnect = next(
                    (s for s in self.seats if not s.source and s.key == pad["key"]),
                    None,
                )
                try:
                    if reconnect:
                        reconnect.attach(pad)
                        self.retile()
                    elif len(self.seats) < self.settings.max_players:
                        number = next(
                            i
                            for i in range(1, 5)
                            if all(s.number != i for s in self.seats)
                        )
                        seat = Seat(self, number, pad)
                        self.seats.append(seat)
                        choices = seat.choices()
                        remembered = self.last_profiles.get(pad["key"])
                        if remembered in choices:
                            seat.chosen = choices.index(remembered)
                        seat.render()
                        self.retile()
                except Exception as exc:
                    log(f"Controller attach failed: {exc}")
        for seat in list(self.seats):
            seat.tick(now)
        for seat in self.seats:
            if seat.mode == "menu" and seat.menu_choices != seat.choices():
                seat.render()
        # Paper limits connections from one IP. Wait for the previous client to
        # finish joining, then leave a 5-second gap before starting the next.
        if not any(s.mode == "loading" for s in self.seats) and now > self.launch_after:
            queued = next(
                (s for s in self.seats if s.mode == "queued" and s.source), None
            )
            if queued:
                queued.launch()
                for seat in self.seats:
                    if seat.mode == "queued":
                        seat.render()
        if now - self.last_layout > 1:
            self.retile()
        return True

    def call(self, path, interface, method, args=None):
        result = self.bus.call_sync(
            "org.kde.KWin",
            path,
            interface,
            method,
            args,
            None,
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        return result.unpack() if result else ()

    def retile(self):
        self.last_layout = time.monotonic()
        active = sorted(
            (s for s in self.seats if s.mode != "off"), key=lambda s: s.number
        )
        layout = []
        for i, seat in enumerate(active):
            if len(active) == 1:
                rect = [0, 0, WIDTH, HEIGHT]
            elif len(active) == 2:
                rect = [0, i * HEIGHT // 2, WIDTH, HEIGHT // 2]
            else:
                rect = [
                    (i % 2) * WIDTH // 2,
                    (i // 2) * HEIGHT // 2,
                    WIDTH // 2,
                    HEIGHT // 2,
                ]
            pid = seat.proc.java_pid() if seat.proc else None
            layout.append(
                {"title": f"MC Couch Seat {seat.number}", "pid": pid, "rect": rect}
            )
            # Only touch GTK geometry on change; resizing every second made panels jump.
            seat.apply_rect(rect)
        focus = None
        if self.focus and self.focus.mode == "edit":
            focus = f"MC Couch Seat {self.focus.number}"
        self.update_lobby(len(active))
        signature = json.dumps([layout, focus])
        # The script stays loaded and places windows as they appear, so it only
        # needs reloading when the layout changes, plus a slow safety re-apply.
        if (
            signature != self.script_signature
            or time.monotonic() - self.last_script > 5
        ):
            self.script_signature = signature
            self.last_script = time.monotonic()
            self.load_script(layout, focus)
        self.check_loading(active, layout)
        self.write_state()

    def load_script(self, layout, focus):
        js = """const layout = %s;
const focus = %s;
function place(w) {
  if (w.caption === 'MC Couch Lobby') {
    w.noBorder = true; w.keepBelow = true;
    w.frameGeometry = {x:0, y:0, width:%d, height:%d};
    return;
  }
  for (const s of layout) {
    if (w.caption === s.title || (s.pid && w.pid === s.pid)) {
      w.noBorder = true;
      if (w.fullScreen) w.fullScreen = false;
      w.setMaximize(false, false);
      const g = w.frameGeometry;
      if (g.x !== s.rect[0] || g.y !== s.rect[1] || g.width !== s.rect[2] || g.height !== s.rect[3])
        w.frameGeometry = {x:s.rect[0], y:s.rect[1], width:s.rect[2], height:s.rect[3]};
    }
  }
  if (focus && w.caption === focus && workspace.activeWindow !== w)
    workspace.activeWindow = w;
}
for (const w of workspace.windowList()) place(w);
workspace.windowAdded.connect(place);
""" % (json.dumps(layout), json.dumps(focus), WIDTH, HEIGHT)
        self.script_path.write_text(js)
        if self.preview:
            return
        try:
            self.call(
                "/Scripting",
                "org.kde.kwin.Scripting",
                "unloadScript",
                GLib.Variant("(s)", ("mc-couch-layout",)),
            )
            script_id = self.call(
                "/Scripting",
                "org.kde.kwin.Scripting",
                "loadScript",
                GLib.Variant("(ss)", (str(self.script_path), "mc-couch-layout")),
            )[0]
            self.call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
        except GLib.Error as exc:
            log("Window layout: " + exc.message)

    def check_loading(self, active, layout):
        # Show Minecraft as soon as its window exists, including any connection
        # error or controller prompt. Track actual world entry independently.
        for seat in active:
            if seat.mode == "loading" and seat.profile:
                entry = next(
                    e for e in layout if e["title"] == f"MC Couch Seat {seat.number}"
                )
                if entry["pid"] and not seat.game_window_visible:
                    found = subprocess.run(
                        [
                            "xdotool",
                            "search",
                            "--onlyvisible",
                            "--pid",
                            str(entry["pid"]),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if found.returncode == 0 and found.stdout.strip():
                        seat.game_window_visible = True
                        seat.window.hide()
                quickplay = seat.proc.directory / "quickplay.json"
                if quickplay.exists():
                    seat.mode = "play"
                    seat.window.hide()
                    self.launch_after = (
                        time.monotonic() + self.settings.join_delay_seconds
                    )
                elif seat.launched_at and time.monotonic() - seat.launched_at > 60:
                    log(
                        f"Seat {seat.number}: world entry not confirmed; leaving game visible for retry"
                    )
                    seat.mode = "play"
                    seat.window.hide()
                    self.launch_after = (
                        time.monotonic() + self.settings.join_delay_seconds
                    )

    def update_lobby(self, active=0):
        # The backdrop shows whatever the player screens leave uncovered.
        if active == 3:
            region = (WIDTH // 2, HEIGHT // 2, WIDTH // 2, HEIGHT // 2)
        else:
            region = (0, 0, WIDTH, HEIGHT)
        cards = []
        for n in range(1, 5):
            seat = next((s for s in self.seats if s.number == n), None)
            if n > self.settings.max_players:
                cards.append(("—", "Not used", False))
            elif not seat:
                cards.append(("Open", "Connect a controller", False))
            elif seat.disconnected:
                cards.append(
                    (seat.profile or f"Player {n}", "Controller reconnecting…", True)
                )
            elif seat.mode == "off":
                cards.append(
                    (f"Player {n}", seat.error or "Sitting out · press Start", True)
                )
            elif seat.mode in ("menu", "edit"):
                cards.append((f"Player {n}", "Choosing a profile", True))
            else:
                state = {
                    "queued": "Waiting to join",
                    "loading": "Joining…",
                    "stopping": "Leaving…",
                }.get(seat.mode, "Playing")
                cards.append((seat.profile, state, True))
        self.view.update(region, cards)

    def write_state(self):
        state = {
            "display": os.environ.get("DISPLAY"),
            "dbus": os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
            "xauthority": os.environ.get("XAUTHORITY"),
            "pid": os.getpid(),
            "players": [
                {
                    "slot": s.number,
                    "profile": s.profile,
                    "mode": s.mode,
                    "source": s.source.path if s.source else None,
                    "proxy": s.proxy.event,
                    "js": s.proxy.js,
                    "controller_ready": s.proxy.ready(),
                    "pid": s.proc.pid if s.proc else None,
                    "entry": (
                        {
                            "text": s.typed,
                            "keyboard": "steam" if s.steam_keys else "controller",
                        }
                        if s.mode == "edit"
                        else None
                    ),
                }
                for s in self.seats
            ],
        }
        atomic_json(runtime_root() / "state.json", state)

    def cleanup(self):
        if self.closed:
            return
        self.closed = True
        for seat in self.seats:
            seat.close()
        (runtime_root() / "state.json").unlink(missing_ok=True)
        log("Couch session closed")

    def quit(self):
        self.cleanup()
        Gtk.main_quit()
        return False


def main():
    install_css()
    app = Lobby()
    app.started = time.monotonic()
    Gtk.main()


if __name__ == "__main__":
    main()
