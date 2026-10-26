"""Independent player clients and launcher hand-off, without account secrets."""

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from .config import atomic_json, data_root, offline_uuid, validate_name


def clean_environment(overrides=None):
    env = os.environ.copy()
    for name in [
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "ENABLE_GAMESCOPE_WSI",
        "WAYLAND_DISPLAY",
        "SDL_GAMECONTROLLER_IGNORE_DEVICES",
        "SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT",
    ]:
        env.pop(name, None)
    env.update(
        SDL_JOYSTICK_DISABLE_UDEV="1",
        SDL_JOYSTICK_HIDAPI="0",
        SDL_JOYSTICK_LINUX_CLASSIC="1",
        SDL_LINUX_JOYSTICK_CLASSIC="1",
        SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD="1",
        SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS="1",
    )
    if overrides:
        env.update(overrides)
    return env


def sandbox(args, event_node, js_node, env=None):
    cmd = [
        "bwrap",
        "--die-with-parent",
        "--dev-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--dev-bind",
        "/dev/dri",
        "/dev/dri",
        "--dev-bind",
        event_node,
        event_node,
        "--dev-bind",
        js_node,
        js_node,
        "--tmpfs",
        "/run/udev",
    ]
    if Path("/dev/snd").exists():
        cmd += ["--dev-bind", "/dev/snd", "/dev/snd"]
    pipe = Path.home() / ".steam/steam.pipe"
    if pipe.exists():
        cmd += ["--bind", "/dev/null", str(pipe)]
    return cmd + ["--"] + list(args)


def prepare_directory(path, settings):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    mods = path / "mods"
    mods.mkdir(exist_ok=True)
    lock_file = data_root() / "mods.resolved.json"
    if not lock_file.exists():
        raise RuntimeError("Game files are not installed. Open Setup first.")
    lock = json.loads(lock_file.read_text())
    desired = {m["file"] for m in lock}
    marker = mods / ".minecraft-couch-managed.json"
    previous = json.loads(marker.read_text()) if marker.exists() else []
    for name in previous:
        if name not in desired and Path(name).name == name:
            (mods / name).unlink(missing_ok=True)
    for name in desired:
        if Path(name).name != name:
            raise ValueError("Invalid mod filename")
        src = data_root() / "mods" / name
        dest = mods / name
        if not dest.exists():
            try:
                os.link(src, dest)
            except OSError:
                import shutil

                shutil.copy2(src, dest)
    atomic_json(marker, sorted(desired))
    config = path / "config"
    config.mkdir(exist_ok=True)
    ctl = config / "controlify.json"
    data = json.loads(ctl.read_text()) if ctl.exists() else {"schema_version": 1}
    data.setdefault("profiles", [])
    data.setdefault("devices", {})
    data.setdefault("global", {}).update(
        out_of_focus_input=True,
        mixed_input=False,
        use_enhanced_steam_deck_driver=False,
        show_splitscreen_ad=False,
    )
    atomic_json(ctl, data)
    options = path / "options.txt"
    opts = (
        dict(l.split(":", 1) for l in options.read_text().splitlines() if ":" in l)
        if options.exists()
        else {}
    )
    opts.update(
        fullscreen="false",
        pauseOnLostFocus="false",
        maxFps=str(settings.fps),
        renderDistance=str(settings.render_distance),
        simulationDistance=str(settings.simulation_distance),
        guiScale="2",
        enableVsync="false",
        onboardAccessibility="false",
        soundCategory_music="0.0",
        narrator="0",
        autoJump="false",
    )
    options.write_text("".join(f"{k}:{v}\n" for k, v in opts.items()))
    return path


def local_command(name, settings, directory=None):
    name = validate_name(name)
    root = data_root()
    game = root / "game"
    marker = game / "installed.json"
    if not marker.exists():
        raise RuntimeError("Open Setup and install Minecraft first.")
    installed = json.loads(marker.read_text())
    if (
        installed["minecraft_version"] != settings.minecraft_version
        or installed["fabric_loader"] != settings.fabric_loader
    ):
        raise RuntimeError(
            "Game versions changed. Run the game installer in Setup again."
        )
    parent = json.loads((game / "vanilla.json").read_text())
    fabric = json.loads((game / "fabric.json").read_text())
    directory = prepare_directory(directory or root / "players" / name, settings)
    natives = directory / "natives"
    natives.mkdir(exist_ok=True)
    java = Path(settings.java_path)
    if not java.is_file() or not os.access(java, os.X_OK):
        raise RuntimeError("Java is missing. Run Setup to install it.")
    cp = list(installed["libraries"]) + [str(game / "client.jar")]
    if not all(Path(p).exists() for p in cp):
        raise RuntimeError("Game libraries are missing. Run Setup to repair them.")
    args = [
        str(java),
        "-Xms384M",
        f"-Xmx{settings.heap_mb}M",
        "-XX:+UseG1GC",
        "-XX:ActiveProcessorCount=3",
        "-XX:MaxGCPauseMillis=100",
        "-Djava.net.preferIPv4Stack=true",
        "-Djava.library.path=" + str(natives),
        "-Djna.tmpdir=" + str(natives),
        "-Dorg.lwjgl.system.SharedLibraryExtractPath=" + str(natives),
        "-Dio.netty.native.workdir=" + str(natives),
        "-Dminecraft.client.jar=" + str(game / "client.jar"),
    ]
    logging = parent.get("logging", {}).get("client")
    if logging:
        args.append(
            logging["argument"].replace(
                "${path}", str(game / "log_configs" / logging["file"]["id"])
            )
        )
    args += [
        "-cp",
        ":".join(cp),
        fabric["mainClass"],
        "--username",
        name,
        "--uuid",
        offline_uuid(name).hex,
        "--accessToken",
        "-",
        "--clientId",
        "0",
        "--xuid",
        "0",
        "--version",
        fabric["id"],
        "--versionType",
        "release",
        "--gameDir",
        str(directory),
        "--assetsDir",
        str(game / "assets"),
        "--assetIndex",
        parent["assetIndex"]["id"],
        "--width",
        "960",
        "--height",
        "540",
        "--quickPlayPath",
        str(directory / "quickplay.json"),
        "--quickPlayMultiplayer",
        settings.server,
    ]
    return args, directory


class DirectGame:
    def __init__(self, args, directory, proxy):
        self.directory = Path(directory)
        (self.directory / "quickplay.json").unlink(missing_ok=True)
        self.output = (self.directory / "couch-launch.log").open("a", buffering=1)
        try:
            self.process = subprocess.Popen(
                sandbox(args, proxy.event, proxy.js),
                cwd=directory,
                env=clean_environment(),
                stdout=self.output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            self.output.close()
            raise
        self.pid = self.process.pid
        self.started = time.monotonic()

    def poll(self):
        return self.process.poll()

    def java_pid(self):
        try:
            p = Path(f"/proc/{self.pid}")
            if (p / "comm").read_text().strip() == "java":
                return self.pid
            for child in (p / "task" / str(self.pid) / "children").read_text().split():
                if Path(f"/proc/{child}/comm").read_text().strip() == "java":
                    return int(child)
        except OSError:
            pass
        return None

    def terminate(self):
        if self.poll() is None:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def kill(self):
        if self.poll() is None:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def reap(self):
        self.terminate()
        try:
            self.process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.kill()
            self.process.wait(timeout=3)
        self.output.close()


def start_game(profile, settings, proxy, slot):
    if profile["kind"] == "microsoft":
        from .prism import PrismGame

        return PrismGame(profile, settings, proxy, slot)
    args, directory = local_command(profile["name"], settings)
    return DirectGame(args, directory, proxy)


def reap_async(game, done=lambda: None):
    # Leaving one seat must never block input for the remaining seats.
    def run():
        try:
            game.reap()
        finally:
            done()

    thread = threading.Thread(target=run, name="minecraft-couch-reaper", daemon=False)
    thread.start()
    return thread
