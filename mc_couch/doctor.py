"""Local readiness checks, with no credentials or controller identifiers."""

import os
from pathlib import Path
import platform
import shutil
from .config import Settings, config_path, data_root
from .linux_input import enumerate_pads


def checks():
    rows = []

    def add(ok, name, help_=""):
        rows.append((bool(ok), name, help_))

    add(
        platform.system() == "Linux" and platform.machine() in ("x86_64", "AMD64"),
        "Supported host: x86_64 Linux",
        "SteamOS/KDE is the initial target; other platforms are experimental.",
    )
    for binary in ["kwin_wayland", "Xwayland", "bwrap", "dbus-run-session", "xdotool"]:
        add(
            shutil.which(binary),
            binary,
            "See README → Requirements for your distribution.",
        )
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        ok = Gtk.MAJOR_VERSION == 3
    except (ImportError, ValueError):
        ok = False
    add(
        ok,
        "Python GTK 3 bindings",
        "Install python-gobject + gtk3 (Arch/SteamOS), or python3-gi + gir1.2-gtk-3.0 (Debian).",
    )
    add(
        Path("/dev/dri").exists(),
        "GPU device nodes",
        "A working Mesa/OpenGL driver is required.",
    )
    add(
        os.access("/dev/uinput", os.W_OK),
        "Writable /dev/uinput",
        "See README → Controller permissions. Restart your login session after changing groups.",
    )
    add(
        bool(list(Path("/sys/class/input").glob("js*"))),
        "Linux joystick devices",
        "Connect a controller. The joydev kernel module must be loaded.",
    )
    pads = enumerate_pads()
    add(
        bool(pads),
        f"{len(pads)} readable controller(s)",
        "Use a Gamepad template for this Steam shortcut.",
    )
    try:
        settings = Settings.load()
        add(True, "Configuration validates")
        from .assets import installed

        ready = (
            installed(settings)
            if settings.account_mode == "local"
            else (data_root() / "mods.resolved.json").exists()
        )
        add(ready, "Game files installed", "Run minecraft-couch setup.")
        if settings.account_mode == "microsoft":
            from .prism import accounts, executable

            executable(settings)
            add(
                bool(accounts()),
                "Microsoft profiles available",
                "Add licensed accounts through Prism in Setup, then refresh profiles.",
            )
    except (OSError, ValueError, RuntimeError) as error:
        add(False, "Configuration/game files", str(error))
    return rows


def report():
    rows = checks()
    for ok, name, hint in rows:
        print(("OK    " if ok else "CHECK ") + name)
        if not ok and hint:
            print("      " + hint)
    print("Config:", config_path())
    print("Data:  ", data_root())
    return 0 if all(row[0] for row in rows) else 1
