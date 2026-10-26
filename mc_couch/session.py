#!/usr/bin/python3
"""Four-player couch lobby inside an isolated nested KWin session."""

import atexit
import json
import os
import signal
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Gio
from .linux_input import InputDevice, E, enumerate_pads, VirtualGamepad as PadProxy
from .config import Settings, data_root, runtime_root, atomic_json
from .profiles import Profiles
from .game import start_game, reap_async

ROOT = data_root()

WIDTH, HEIGHT = 1920, 1080
ALPHABET = list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_") + [
    "⌫",
    "✓",
    "✕",
]


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def label(text, style=None):
    obj = Gtk.Label(label=text)
    obj.set_line_wrap(True)
    obj.set_justify(Gtk.Justification.CENTER)
    if style:
        obj.get_style_context().add_class(style)
    return obj


class Seat:
    def __init__(self, app, number, pad):
        self.app, self.number, self.key = app, number, pad["key"]
        self.source = self.watch = None
        self.proxy = PadProxy(number)
        self.mode = "menu"
        self.profile = None
        self.proc = self.output = None
        self.chosen = 0
        self.held = set()
        self.chord_since = None
        self.disconnected = None
        self.last_nav = 0
        self.stop_deadline = None
        self.launched_at = None
        self.game_window_visible = False
        self.error = ""
        self.typed = ""
        self.window = Gtk.Window(title=f"MC Couch Seat {number}")
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.connect("delete-event", lambda *_: True)
        self.window.connect("key-press-event", self.keyboard)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.box.set_margin_top(8)
        self.box.set_margin_bottom(8)
        self.box.set_margin_start(12)
        self.box.set_margin_end(12)
        self.window.add(self.box)
        try:
            self.attach(pad)
            self.render()
        except Exception:
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
        if self.mode == "play":
            self.window.hide()
        else:
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
        self.proxy.reset()

    def read(self, fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            self.watch = None
            self.lost()
            return False
        try:
            for ev in self.source.read():
                if ev.type == E.EV_KEY:
                    if ev.value:
                        self.held.add(ev.code)
                    else:
                        self.held.discard(ev.code)
                    if self.mode in ("menu", "edit", "off") and ev.value == 1:
                        action = {
                            E.BTN_SOUTH: "ok",
                            E.BTN_EAST: "back",
                            E.BTN_START: "start",
                            E.BTN_DPAD_UP: "up",
                            E.BTN_DPAD_DOWN: "down",
                            E.BTN_DPAD_LEFT: "left",
                            E.BTN_DPAD_RIGHT: "right",
                        }.get(ev.code)
                        if action:
                            self.action(action)
                elif ev.type == E.EV_ABS and self.mode in ("menu", "edit"):
                    value = ev.value
                    if ev.code in (E.ABS_X, E.ABS_Y):
                        info = self.source.absinfo(ev.code)
                        value = (
                            (value - info.min) / max(1, info.max - info.min) - 0.5
                        ) * 2
                        value = 1 if value > 0.65 else -1 if value < -0.65 else 0
                    if value:
                        action = None
                        if ev.code in (E.ABS_HAT0Y, E.ABS_Y):
                            action = "down" if value > 0 else "up"
                        elif ev.code in (E.ABS_HAT0X, E.ABS_X):
                            action = "right" if value > 0 else "left"
                        if action and time.monotonic() - self.last_nav > 0.14:
                            self.last_nav = time.monotonic()
                            self.action(action)
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

    def lost(self):
        self.detach()
        self.disconnected = time.monotonic()
        self.held.clear()
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
            + (["＋ New profile"] if self.app.settings.account_mode == "local" else [])
            + ["Leave session"]
        )

    def action(self, action):
        if self.disconnected:
            return
        if self.mode == "off":
            if action in ("ok", "start"):
                self.mode = "menu"
                self.chosen = 0
                self.app.retile()
                self.render()
            elif action == "back" and all(s.mode == "off" for s in self.app.seats):
                self.app.quit()
            return
        if self.mode == "edit":
            if action in ("up", "down", "left", "right"):
                delta = {"up": -11, "down": 11, "left": -1, "right": 1}[action]
                self.chosen = (self.chosen + delta) % len(ALPHABET)
            elif action == "back":
                self.typed = self.typed[:-1]
            elif action == "start":
                self.save_name()
                return
            elif action == "ok":
                item = ALPHABET[self.chosen]
                if item == "✓":
                    self.save_name()
                    return
                if item == "✕":
                    self.mode, self.chosen = "menu", 0
                elif item == "⌫":
                    self.typed = self.typed[:-1]
                elif len(self.typed) < 16:
                    self.typed += item
            self.render()
            return
        if self.mode != "menu":
            return
        choices = self.choices()
        if action in ("up", "left", "down", "right"):
            self.chosen = (
                self.chosen + (1 if action in ("down", "right") else -1)
            ) % len(choices)
        elif action == "back":
            self.mode = "off"
            self.window.hide()
            self.app.retile()
            return
        elif action in ("ok", "start"):
            chosen = choices[self.chosen % len(choices)]
            if chosen == "＋ New profile":
                self.mode, self.chosen, self.typed = "edit", 0, ""
            elif chosen == "Leave session":
                self.mode = "off"
                self.window.hide()
                self.app.retile()
                return
            else:
                self.begin(chosen)
                return
        self.render()

    def save_name(self):
        name = self.typed.strip()
        if not name:
            self.error = "Enter a name first."
            self.render()
            return
        existing = next(
            (p for p in self.app.profiles if p.lower() == name.lower()), None
        )
        if existing:
            self.error = "That name already exists. Choose it from the list."
            self.mode, self.chosen = "menu", 0
            self.render()
            return
        try:
            self.app.profile_store.add_local(name)
        except ValueError as exc:
            self.error = str(exc)
            self.render()
            return
        self.app.profiles = [p["name"] for p in self.app.profile_store.visible()]
        self.begin(name)

    def keyboard(self, widget, event):
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

    def button(self, text, index, columns=None):
        item = Gtk.Button(label=text)
        item.set_can_focus(False)
        if index == self.chosen:
            item.get_style_context().add_class("selected")
        item.connect(
            "clicked", lambda *_: (setattr(self, "chosen", index), self.action("ok"))
        )
        if columns:
            columns.attach(item, index % 11, index // 11, 1, 1)
        else:
            self.box.pack_start(item, False, False, 0)

    def render(self):
        for obj in self.box.get_children():
            self.box.remove(obj)
        if self.mode == "off":
            self.window.hide()
            return
        self.box.pack_start(label(f"PLAYER {self.number}", "heading"), False, False, 0)
        if self.disconnected:
            text = "Controller disconnected\nReconnect to keep your screen."
            self.box.pack_start(label(text), True, True, 0)
        elif self.mode == "menu":
            self.box.pack_start(label("Choose your profile"), False, False, 0)
            choices = self.choices()
            self.chosen %= len(choices)
            # Keep long profile lists usable on a 540-pixel quadrant.
            first = max(0, min(self.chosen - 1, len(choices) - 4))
            for i in range(first, min(first + 4, len(choices))):
                text = choices[i]
                self.button(text, i)
            self.box.pack_start(
                label("D-pad: choose    A: join    B: sit out", "hint"), True, True, 0
            )
        elif self.mode == "edit":
            self.box.pack_start(label(self.typed + "▏", "name"), False, False, 0)
            grid = Gtk.Grid(column_spacing=3, row_spacing=3)
            grid.set_column_homogeneous(True)
            self.box.pack_start(grid, True, True, 0)
            for i, text in enumerate(ALPHABET):
                self.button(text, i, grid)
            self.box.pack_start(
                label(
                    "D-pad: move    A: type    B: erase    Start: save & join", "hint"
                ),
                False,
                False,
                0,
            )
        else:
            self.box.pack_start(
                label(
                    f"{self.profile or ''}\n"
                    + (
                        "Leaving the world…"
                        if self.mode == "stopping"
                        else "Waiting to join the server…"
                        if self.mode == "queued"
                        else "Starting Minecraft and joining the server…"
                    )
                ),
                True,
                True,
                0,
            )
            self.box.pack_start(
                label("Hold Back + Start for 2 seconds to leave your screen.", "hint"),
                False,
                False,
                0,
            )
        if self.error:
            self.box.pack_start(label(self.error, "error"), False, False, 0)
        self.window.show_all()

    def begin(self, name):
        if not self.proxy.ready():
            self.error = "Preparing controller. Press A again in a moment."
            self.render()
            return
        if any(
            s is not self
            and s.profile
            and s.mode in ("queued", "loading", "play", "stopping")
            and s.profile.lower() == name.lower()
            for s in self.app.seats
        ):
            self.error = "That profile is already playing."
            self.render()
            return
        self.profile, self.mode, self.error = name, "queued", ""
        for seat in self.app.seats:
            if seat is not self and seat.mode == "menu":
                seat.chosen = min(seat.chosen, len(seat.choices()) - 1)
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
            self.error = str(exc)
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
        if self.proc:
            status = self.proc.poll()
            if status is not None:
                log(f"Seat {self.number}: {self.profile} exited ({status})")
                reap_async(self.proc)
                self.proc = None
                self.output = None
                self.error = (
                    ""
                    if status in (0, 143, -15)
                    else "Minecraft closed. Press Start to try again."
                )
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
        self.closed = False
        self.launch_after = 0
        self.profile_store = Profiles(self.settings)
        self.profiles = [p["name"] for p in self.profile_store.visible()]
        self.last_profiles = self.profile_store.controllers
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None) if not preview else None
        self.script_path = runtime_root() / "layout.js"
        self.base = Gtk.Window(title="MC Couch Lobby")
        self.base.set_decorated(False)
        self.base.set_default_size(WIDTH, HEIGHT)
        self.base.connect("delete-event", lambda *_: (self.quit(), True)[1])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        self.base.add(box)
        box.pack_start(label("MINECRAFT", "title"), False, False, 0)
        box.pack_start(
            label("Couch multiplayer · Java Edition", "heading"), False, False, 0
        )
        box.pack_start(
            label(
                "Connect a controller to choose a profile.\nUp to 4 players can play together."
            ),
            False,
            False,
            0,
        )
        box.pack_start(
            label(
                "Already connected? Press Start to join.\nHold Back + Start for 2 seconds to leave your screen.\nWhen everyone has left, press B to return to Steam.",
                "hint",
            ),
            False,
            False,
            0,
        )
        exit_button = Gtk.Button(label="Return to Steam")
        exit_button.connect("clicked", lambda *_: self.quit())
        box.pack_start(exit_button, False, False, 0)
        self.base.show_all()
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
                if (
                    seat.disconnected
                    and now - seat.disconnected > self.settings.reconnect_seconds
                ):
                    seat.close()
                    self.seats.remove(seat)
                    self.retile()
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
        # Paper limits connections from one IP. Wait for the previous client to
        # finish joining, then leave a 5-second gap before starting the next.
        if not any(s.mode == "loading" for s in self.seats) and now > self.launch_after:
            queued = next(
                (s for s in self.seats if s.mode == "queued" and s.source), None
            )
            if queued:
                queued.launch()
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
            seat.window.resize(rect[2], rect[3])
            seat.window.move(rect[0], rect[1])
        js = (
            """const layout = %s;
for (const w of workspace.windowList()) {
  if (w.caption === 'MC Couch Lobby') {
    w.noBorder = true; w.keepBelow = true;
    w.frameGeometry = {x:0,y:0,width:WIDTH,height:HEIGHT};
  }
  for (const s of layout) {
    if (w.caption === s.title || (s.pid && w.pid === s.pid)) {
      w.noBorder = true; w.fullScreen = false;
      w.setMaximize(false, false);
      w.frameGeometry = {x:s.rect[0], y:s.rect[1], width:s.rect[2], height:s.rect[3]};
    }
  }
}
""".replace("WIDTH", str(WIDTH)).replace("HEIGHT", str(HEIGHT))
            % json.dumps(layout)
        )
        self.script_path.write_text(js)
        try:
            if self.preview:
                return
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
    css = Gtk.CssProvider()
    css.load_from_data(b"""
window { background: #172624; color: #eef4e9; font-family: sans-serif; font-size: 17px; }
button { background: #29433a; color: #eef4e9; border: 2px solid #496358; border-radius: 5px; padding: 3px 8px; min-height: 18px; }
button.selected { background: #4f7b39; border-color: #c0ed8b; color: white; }
.title { font-size: 72px; font-weight: bold; }
.heading { font-size: 24px; font-weight: bold; color: #c0ed8b; }
.name { font-size: 24px; }
.hint { color: #c0cbbf; font-size: 14px; }
.error { color: #ffb29c; }
""")
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    app = Lobby()
    app.started = time.monotonic()
    Gtk.main()


if __name__ == "__main__":
    main()
