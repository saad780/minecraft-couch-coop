"""User commands and the private nested compositor session."""

import argparse
import fcntl
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
from . import __version__
from .config import Settings, config_path, data_root, runtime_root


def launch():
    settings = Settings.load()
    if not settings.setup_complete:
        from .setup_ui import main

        main()
        settings = Settings.load()
        if not settings.setup_complete:
            return 0
    missing = [
        p
        for p in ["kwin_wayland", "Xwayland", "bwrap", "dbus-run-session", "xdotool"]
        if not shutil.which(p)
    ]
    if missing:
        raise RuntimeError(
            "Missing: "
            + ", ".join(missing)
            + ". Run minecraft-couch doctor; see README → Requirements."
        )
    with (runtime_root() / "session.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A couch session is already running.")
        from .game import clean_environment

        env = clean_environment()
        env.update(
            GDK_BACKEND="x11",
            NO_AT_BRIDGE="1",
            MC_COUCH_CONFIG=str(config_path()),
            MC_COUCH_DATA=str(data_root()),
        )
        if not env.get("DISPLAY"):
            raise RuntimeError(
                "Launch from Steam or a desktop session with an X11/Xwayland display."
            )
        # Steam's keyboard is requested from inside the nested session.
        env["MC_COUCH_STEAM_DISPLAY"] = env["DISPLAY"]
        compositor_config = data_root() / "compositor-config"
        compositor_config.mkdir(parents=True, exist_ok=True)
        env["XDG_CONFIG_HOME"] = str(compositor_config)
        # This code runs inside KWin's own Xwayland and private D-Bus session.
        inner = Path(__file__).resolve().parent.parent / "session-entry.py"
        command = [
            "dbus-run-session",
            "--",
            "kwin_wayland",
            "--x11-display",
            env["DISPLAY"],
            "--xwayland",
            "--socket",
            "minecraft-couch-coop",
            "--width",
            str(settings.width),
            "--height",
            str(settings.height),
            "--fullscreen",
            "true",
            "--no-lockscreen",
            "--no-global-shortcuts",
            "--no-kactivities",
            "--exit-with-session",
            shlex.join([sys.executable, str(inner)]),
        ]
        logs = data_root() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "session.log").open("a") as output:
            return subprocess.call(
                command, env=env, stdout=output, stderr=subprocess.STDOUT
            )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Minecraft Java couch multiplayer for SteamOS/KDE Linux."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    for name in ["setup", "doctor", "install-game", "accounts", "uninstall"]:
        commands.add_parser(name)
    steam = commands.add_parser(
        "steam-sync", help="Add the shortcut while Steam is fully closed"
    )
    steam.add_argument("--pending", action="store_true")
    steam.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            from .setup_ui import main as setup

            setup()
            return 0
        if args.command == "doctor":
            from .doctor import report

            return report()
        if args.command == "install-game":
            from .setup_ui import install_files

            settings = Settings.load()
            install_files(
                settings, lambda i, n, text: print(f"{i}/{n} {text}", flush=True)
            )
            settings.setup_complete = True
            settings.save()
            return 0
        if args.command == "accounts":
            from .prism import open_accounts

            open_accounts(Settings.load())
            return 0
        if args.command == "steam-sync":
            from .steam import sync

            if args.pending and not (data_root() / "steam-pending").exists():
                return 0
            print("Steam shortcut updated:", sync(remove=args.remove))
            return 0
        if args.command == "uninstall":
            from .installer import uninstall

            uninstall()
            return 0
        return launch()
    except (RuntimeError, ValueError, OSError) as error:
        print("Minecraft Couch Co-op:", error, file=sys.stderr)
        return 1
