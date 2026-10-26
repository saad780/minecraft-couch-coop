"""Desktop setup; downloaded files and game profiles belong to this app alone."""

import threading
from .config import APP_NAME, Settings


def install_files(settings, progress=lambda *_: None):
    if settings.account_mode == "microsoft":
        from .assets import install_mods
        from .prism import install_prism

        install_mods(settings, progress=progress)
        install_prism(settings, progress)
    else:
        from .assets import install_game

        install_game(settings, progress)


def main():
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    window = SetupWindow()
    window.window.connect("destroy", Gtk.main_quit)
    window.window.show_all()
    Gtk.main()


class SetupWindow:
    def __init__(self):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        self.settings = Settings.load()
        self.busy = False
        self.window = Gtk.Window(title=APP_NAME + " — Setup")
        self.window.set_default_size(800, 760)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.connect("delete-event", lambda *_: self.busy)
        scroll = Gtk.ScrolledWindow()
        self.window.add(scroll)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(24)
        scroll.add(outer)
        title = Gtk.Label()
        title.set_markup(
            '<span size="xx-large" weight="bold">Minecraft Couch Co-op</span>'
        )
        outer.pack_start(title, False, False, 0)
        subtitle = Gtk.Label(
            label="One screen. Up to four controllers. Your Java server."
        )
        outer.pack_start(subtitle, False, False, 0)
        grid = Gtk.Grid(column_spacing=18, row_spacing=10)
        outer.pack_start(grid, False, False, 0)
        self.fields = {}

        def row(name, widget, text):
            index = len(self.fields)
            label = Gtk.Label(label=text, xalign=0)
            grid.attach(label, 0, index, 1, 1)
            grid.attach(widget, 1, index, 1, 1)
            widget.set_hexpand(True)
            self.fields[name] = widget

        server = Gtk.Entry(text=self.settings.server)
        server.set_placeholder_text("play.example.net:25565")
        row("server", server, "1. Java server address")
        mode = Gtk.ComboBoxText()
        mode.append("local", "Local names · private servers that accept them")
        mode.append("microsoft", "Microsoft accounts · sign in through Prism")
        mode.set_active_id(self.settings.account_mode)
        row("account_mode", mode, "2. Player accounts")
        for key, text, low, high, step in [
            ("max_players", "Maximum local players", 1, 4, 1),
            ("width", "Screen width", 640, 7680, 80),
            ("height", "Screen height", 400, 4320, 40),
            ("heap_mb", "Memory per player (MiB)", 1024, 8192, 256),
            ("fps", "Frame limit per player", 15, 240, 5),
            ("render_distance", "Render distance (chunks)", 2, 32, 1),
            ("simulation_distance", "Simulation distance (chunks)", 2, 32, 1),
        ]:
            widget = Gtk.SpinButton.new_with_range(low, high, step)
            widget.set_value(getattr(self.settings, key))
            row(key, widget, text)
        self.notice = Gtk.Label(
            label="Local names work only on servers that explicitly accept them.\nMicrosoft mode needs a licensed Java account for each simultaneous player.\nMinecraft 1.21.11 + Fabric 0.20.1 · Java and mods download separately."
        )
        self.notice.set_line_wrap(True)
        self.notice.set_xalign(0)
        outer.pack_start(self.notice, False, False, 0)
        self.install = Gtk.Button(label="3. Save settings & install game files")
        self.install.connect("clicked", self.download)
        outer.pack_start(self.install, False, False, 0)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_text("Ready to set up")
        outer.pack_start(self.progress, False, False, 0)
        accounts = Gtk.Box(spacing=8)
        for text, callback in [
            ("Open Prism / add Microsoft accounts", self.open_accounts),
            ("Refresh profiles", self.refresh),
        ]:
            button = Gtk.Button(label=text)
            button.connect("clicked", callback)
            accounts.pack_start(button, True, True, 0)
        outer.pack_start(accounts, False, False, 0)
        bottom = Gtk.Box(spacing=8)
        steam = Gtk.Button(label="4. Add to Steam")
        steam.connect("clicked", self.add_steam)
        close = Gtk.Button(label="Done")
        close.connect(
            "clicked", lambda *_: self.window.destroy() if not self.busy else None
        )
        bottom.pack_start(steam, True, True, 0)
        bottom.pack_start(close, True, True, 0)
        outer.pack_start(bottom, False, False, 0)
        self.status = Gtk.Label(
            label="First-time setup works best in Desktop Mode with a keyboard or mouse."
        )
        self.status.set_line_wrap(True)
        self.status.set_selectable(True)
        outer.pack_start(self.status, False, False, 0)

    def read_settings(self):
        for key, widget in self.fields.items():
            value = (
                widget.get_active_id()
                if key == "account_mode"
                else widget.get_text()
                if key == "server"
                else widget.get_value_as_int()
            )
            setattr(self.settings, key, value)
        return self.settings.validate()

    def download(self, *_):
        from gi.repository import GLib

        if self.busy:
            return
        try:
            self.read_settings()
            self.settings.setup_complete = False
            self.settings.save()
        except ValueError as error:
            self.status.set_text(str(error))
            return
        self.busy = True
        self.install.set_sensitive(False)
        for widget in self.fields.values():
            widget.set_sensitive(False)

        def progress(i, total, message):
            def update():
                self.progress.set_fraction(i / max(1, total))
                self.progress.set_text(message)
                return False

            GLib.idle_add(update)

        def complete(message, success):
            self.busy = False
            self.install.set_sensitive(True)
            for widget in self.fields.values():
                widget.set_sensitive(True)
            self.status.set_text(message)
            if success:
                self.settings.setup_complete = True
                self.settings.save()
            return False

        def run():
            try:
                install_files(self.settings, progress)
                GLib.idle_add(
                    complete,
                    "Files are ready. Microsoft mode: add your accounts in Prism, then refresh profiles.",
                    True,
                )
            except Exception as error:
                GLib.idle_add(
                    complete,
                    "Setup failed: "
                    + str(error)
                    + "\nYou can retry; verified downloads are reused.",
                    False,
                )

        threading.Thread(target=run, name="couch-installer", daemon=False).start()

    def open_accounts(self, *_):
        if self.busy:
            return
        try:
            from .prism import open_accounts

            open_accounts(self.settings)
            self.status.set_text(
                "In Prism: Settings → Accounts → Add Microsoft. Finish sign-in, close Prism, then refresh profiles here."
            )
        except (OSError, RuntimeError) as error:
            self.status.set_text(str(error))

    def refresh(self, *_):
        if self.busy:
            return
        try:
            from .profiles import Profiles

            profiles = Profiles(self.read_settings()).visible()
            self.status.set_text(
                "Available profiles: "
                + (
                    ", ".join(p["name"] for p in profiles)
                    or "none — add accounts in Prism first"
                )
            )
        except (OSError, ValueError, RuntimeError) as error:
            self.status.set_text(str(error))

    def add_steam(self, *_):
        try:
            from .steam import queue, steam_running, sync

            self.status.set_text(
                queue() if steam_running() else "Steam shortcut added: " + str(sync())
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.status.set_text(str(error))
