"""Delegate Microsoft authentication and refresh to the official Prism Launcher.

Only public profile names/UUIDs are imported. Tokens and passwords stay in
Prism's account store and are never copied into couch configuration or logs.
The wrapper runs around the actual Java process, so a pre-existing Prism GUI
cannot bypass per-seat controller isolation or use the wrong display.
"""

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import uuid
from .config import atomic_json, data_root, runtime_root, validate_name
from .downloads import fetch
from .game import clean_environment, prepare_directory, sandbox

PRISM_VERSION = "11.1.1"
PRISM_URL = f"https://github.com/PrismLauncher/PrismLauncher/releases/download/{PRISM_VERSION}/PrismLauncher-Linux-x86_64.AppImage"
PRISM_SHA256 = "bb81038c56a09e944659e4b808dbfbc52d52d5e3a3ffe32216689a3ca1508d3d"


def prism_root():
    return data_root() / "prism"


def install_prism(settings, progress=lambda *_: None):
    import platform

    if platform.machine() not in ("x86_64", "AMD64"):
        raise RuntimeError(
            "Managed Prism installation currently supports x86_64 Linux."
        )
    path = data_root() / "launcher/PrismLauncher.AppImage"
    progress(0, 1, "Downloading official Prism Launcher")
    fetch(PRISM_URL, path, PRISM_SHA256)
    path.chmod(0o755)
    settings.prism_path = str(path)
    root = prism_root()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    cfg = root / "prismlauncher.cfg"
    if not cfg.exists():
        cfg.write_text(
            "[General]\nLanguage=en_US\nAutomaticJava=true\nAutoUpdateJava=true\nHideOnLaunch=true\nCloseAfterLaunch=false\nQuitAfterGameStop=false\n"
        )
    progress(1, 1, "Prism Launcher is ready")


def executable(settings):
    path = Path(settings.prism_path).expanduser()
    if not settings.prism_path or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError("Prism Launcher is missing. Install it from Setup.")
    return [str(path), "--dir", str(prism_root())]


def open_accounts(settings):
    return subprocess.Popen(
        executable(settings),
        env=clean_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def accounts(path=None):
    path = Path(path or prism_root() / "accounts.json")
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    version = data.get("formatVersion", 3)
    if version != 3:
        raise RuntimeError(
            "This Prism account-store version is unsupported. Use Prism 11.1.1."
        )
    profiles = []
    for account in data.get("accounts", []):
        if account.get("type") != "MSA":
            continue
        profile = account.get("profile", {})
        name = profile.get("name")
        identity = profile.get("id")
        if not name or not identity:
            continue
        try:
            validate_name(name)
            identity = uuid.UUID(identity).hex
        except (ValueError, AttributeError):
            continue
        # Deliberately select only these three fields, never serializing account.
        profiles.append({"name": name, "kind": "microsoft", "id": identity})
    return profiles


def instance_id(profile):
    return "couch-" + uuid.UUID(profile["id"]).hex


def instance_directory(profile):
    return prism_root() / "instances" / instance_id(profile) / ".minecraft"


def prepare_instance(profile, settings):
    identity = instance_id(profile)
    directory = instance_directory(profile)
    prepare_directory(directory, settings)
    root = directory.parent
    wrapper = Path(__file__).resolve().parent.parent / "prism-wrapper.py"
    if not wrapper.exists():
        raise RuntimeError(
            "The Prism game wrapper is missing. Reinstall Minecraft Couch Co-op."
        )
    command = shlex.join([sys.executable, str(wrapper), "--instance", identity])
    cfg = {
        "InstanceType": "OneSix",
        "name": profile["name"] + " — Minecraft Couch Co-op",
        "OverrideCommands": "true",
        "WrapperCommand": command,
        "PreLaunchCommand": "",
        "PostExitCommand": "",
        "OverrideMemory": "true",
        "MinMemAlloc": "384",
        "MaxMemAlloc": str(settings.heap_mb),
        "OverrideJavaArgs": "true",
        "JvmArgs": "-XX:ActiveProcessorCount=3 -XX:+UseG1GC -XX:MaxGCPauseMillis=100",
        "OverrideWindow": "true",
        "LaunchMaximized": "false",
        "MinecraftWinWidth": "960",
        "MinecraftWinHeight": "540",
        "OverrideConsole": "true",
        "ShowConsole": "false",
        "ShowConsoleOnError": "true",
        "AutoCloseConsole": "true",
    }
    if settings.java_path:
        cfg.update(OverrideJavaLocation="true", JavaPath=settings.java_path)
    (root / "instance.cfg").write_text(
        "[General]\n" + "".join(f"{k}={v}\n" for k, v in cfg.items())
    )
    atomic_json(
        root / "mmc-pack.json",
        {
            "formatVersion": 1,
            "components": [
                {"uid": "net.minecraft", "version": settings.minecraft_version},
                {
                    "uid": "net.fabricmc.fabric-loader",
                    "version": settings.fabric_loader,
                },
            ],
        },
    )
    return identity, directory


class PrismGame:
    def __init__(self, profile, settings, proxy, slot):
        self.started = time.monotonic()
        self.cancelled = False
        self.directory = instance_directory(profile)
        identity, self.directory = prepare_instance(profile, settings)
        self.request = runtime_root() / "requests" / (identity + ".json")
        self.status = self.request.with_suffix(".status.json")
        self.status.unlink(missing_ok=True)
        (self.directory / "quickplay.json").unlink(missing_ok=True)
        # Replace a previous run's log so world-entry detection cannot reuse it.
        latest = self.directory / "logs/latest.log"
        if latest.exists():
            latest.rename(latest.with_name("previous-couch.log"))
        self.nonce = uuid.uuid4().hex
        env = {
            k: v
            for k, v in clean_environment().items()
            if k
            in [
                "DISPLAY",
                "XAUTHORITY",
                "DBUS_SESSION_BUS_ADDRESS",
                "XDG_RUNTIME_DIR",
                "PULSE_SERVER",
                "PIPEWIRE_REMOTE",
            ]
        }
        atomic_json(
            self.request,
            {
                "nonce": self.nonce,
                "owner": os.getpid(),
                "created": time.time(),
                "event": proxy.event,
                "js": proxy.js,
                "environment": env,
                "status": str(self.status),
                "cancelled": False,
            },
        )
        output = data_root() / "logs"
        output.mkdir(parents=True, exist_ok=True)
        self.output = (output / f"prism-slot-{slot}.log").open("a", buffering=1)
        self.cli = subprocess.Popen(
            executable(settings)
            + [
                "--launch",
                identity,
                "--profile",
                profile["name"],
                "--server",
                settings.server,
            ],
            env=clean_environment(),
            stdout=self.output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def state(self):
        try:
            state = json.loads(self.status.read_text())
            return state if state.get("nonce") == self.nonce else {}
        except (OSError, ValueError):
            return {}

    @property
    def pid(self):
        return self.state().get("pid")

    def poll(self):
        cli_status = self.cli.poll()
        state = self.state()
        if "exit_code" in state:
            return state["exit_code"]
        if self.cancelled and not state.get("pid"):
            return 0
        if state.get("pid") and not Path("/proc/" + str(state["pid"])).exists():
            return 1
        if time.monotonic() - self.started > 600 and not self.pid:
            return 1
        if cli_status not in (None, 0) and not self.pid:
            return cli_status
        return None

    def java_pid(self):
        pid = self.pid
        if not pid:
            return None
        try:
            path = Path(f"/proc/{pid}")
            if (path / "comm").read_text().strip() == "java":
                return pid
            for child in (path / "task" / str(pid) / "children").read_text().split():
                if Path(f"/proc/{child}/comm").read_text().strip() == "java":
                    return int(child)
        except OSError:
            pass
        return None

    def terminate(self):
        self.cancelled = True
        try:
            request = json.loads(self.request.read_text())
            if request.get("nonce") == self.nonce:
                request["cancelled"] = True
                atomic_json(self.request, request)
        except (OSError, ValueError):
            pass
        pid = self.pid
        if pid and self.poll() is None:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def kill(self):
        pid = self.pid
        if pid and self.poll() is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def reap(self):
        self.terminate()
        deadline = time.monotonic() + 6
        while self.pid and self.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if self.pid and self.poll() is None:
            self.kill()
        self.output.close()


def wrapper_main(argv):
    import argparse

    parser = argparse.ArgumentParser(description="Prism per-player isolation wrapper")
    parser.add_argument("--instance", required=True)
    parser.add_argument("java", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if (
        not args.java
        or not args.instance.startswith("couch-")
        or len(args.instance) != 38
        or not all(c in "0123456789abcdef" for c in args.instance[6:])
    ):
        raise ValueError("Invalid Prism wrapper invocation.")
    request_path = runtime_root() / "requests" / (args.instance + ".json")
    request = json.loads(request_path.read_text())
    if request_path.stat().st_uid != os.getuid() or request_path.stat().st_mode & 0o077:
        raise RuntimeError("The game request must be private to its owner.")
    if (
        request.get("cancelled")
        or time.time() - request["created"] > 600
        or not Path(f"/proc/{request['owner']}").exists()
    ):
        raise RuntimeError("Start this instance from Minecraft Couch Co-op.")
    for key in ["event", "js"]:
        if (
            not request[key].startswith("/dev/input/")
            or not Path(request[key]).exists()
        ):
            raise RuntimeError("The assigned controller is no longer available.")
    status = Path(request["status"])
    if status.parent != request_path.parent:
        raise ValueError("Invalid game status path.")
    env = clean_environment(request["environment"])
    process = subprocess.Popen(
        sandbox(args.java, request["event"], request["js"]),
        env=env,
        start_new_session=True,
    )
    state = {"nonce": request["nonce"], "pid": process.pid, "started": time.time()}
    atomic_json(status, state)

    # A player can leave while Prism is downloading or spawning Java. Recheck
    # after publishing the PID so either side of that race stops the child.
    current = json.loads(request_path.read_text())
    if current.get("cancelled") or current.get("nonce") != request["nonce"]:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def stop(*_):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, stop)
    code = process.wait()
    state["exit_code"] = code
    atomic_json(status, state)
    return code
