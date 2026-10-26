"""Preserve Steam binary VDF files and defer edits until Steam has stopped."""

import os
from pathlib import Path
import struct
import subprocess
import time
import zlib
from .config import APP_NAME, data_root


def decode(data):
    offset = 0

    def string():
        nonlocal offset
        end = data.index(b"\0", offset)
        value = data[offset:end].decode("utf-8", "surrogateescape")
        offset = end + 1
        return value

    def object_():
        nonlocal offset
        result = {}
        while offset < len(data):
            kind = data[offset]
            offset += 1
            if kind == 8:
                return result
            key = string()
            if kind == 0:
                result[key] = object_()
            elif kind == 1:
                result[key] = string()
            elif kind == 2:
                if offset + 4 > len(data):
                    raise ValueError("Truncated Steam integer; file was not changed.")
                result[key] = struct.unpack_from("<I", data, offset)[0]
                offset += 4
            else:
                raise ValueError(
                    f"Unsupported Steam VDF field type {kind}; file was not changed."
                )
        raise ValueError("Truncated Steam VDF file; file was not changed.")

    value = object_()
    if offset != len(data):
        raise ValueError("Unexpected trailing Steam VDF data; file was not changed.")
    return value


def encode(value):
    output = bytearray()

    def string(text):
        return text.encode("utf-8", "surrogateescape") + b"\0"

    for key, item in value.items():
        if isinstance(item, dict):
            output += b"\0" + string(key) + encode(item)
        elif isinstance(item, str):
            output += b"\1" + string(key) + string(item)
        elif isinstance(item, int):
            output += b"\2" + string(key) + struct.pack("<I", item & 0xFFFFFFFF)
        else:
            raise ValueError("Unsupported VDF value")
    return bytes(output) + b"\10"


def steam_running():
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid == os.getuid() and (
                proc / "comm"
            ).read_text().strip() in ("steam", "steamwebhelper"):
                return True
        except OSError:
            pass
    return False


def steam_root():
    for root in [Path.home() / ".local/share/Steam", Path.home() / ".steam/steam"]:
        if (root / "userdata").is_dir():
            return root.resolve()
    raise RuntimeError("Open Steam and sign in once before adding the shortcut.")


def sync(remove=False):
    if steam_running():
        raise RuntimeError(
            "Steam is running. Exit Steam fully, then run minecraft-couch steam-sync."
        )
    root = steam_root()
    users = sorted(
        (
            p
            for p in (root / "userdata").iterdir()
            if p.name.isdecimal() and (p / "config").is_dir()
        ),
        key=lambda p: (p / "config").stat().st_mtime,
        reverse=True,
    )
    if not users:
        raise RuntimeError("No Steam user configuration was found.")
    # Configure the most recently used Steam user, never every account silently.
    target = users[0] / "config/shortcuts.vdf"
    original = target.read_bytes() if target.exists() else None
    value = decode(original) if original else {"shortcuts": {}}
    shortcuts = value.setdefault("shortcuts", {})
    binary = Path.home() / ".local/bin/minecraft-couch"
    exe = '"' + str(binary) + '"'
    existing = [
        key
        for key, item in shortcuts.items()
        if item.get("appname") == APP_NAME and item.get("exe") == exe
    ]
    for key in existing:
        del shortcuts[key]
    if not remove:
        key = str(max([-1] + [int(k) for k in shortcuts if k.isdecimal()]) + 1)
        shortcuts[key] = {
            "appid": zlib.crc32((exe + APP_NAME).encode()) | 0x80000000,
            "appname": APP_NAME,
            "exe": exe,
            "StartDir": '"' + str(binary.parent) + '"',
            "icon": str(data_root() / "app/resources/icon.svg"),
            "ShortcutPath": "",
            "LaunchOptions": "",
            "IsHidden": 0,
            "AllowDesktopConfig": 1,
            "AllowOverlay": 1,
            "OpenVR": 0,
            "Devkit": 0,
            "DevkitGameID": "",
            "LastPlayTime": 0,
            "tags": {"0": "Local multiplayer"},
        }
    if original:
        backup = target.with_name("shortcuts.vdf.couch-backup-" + str(time.time_ns()))
        backup.write_bytes(original)
    temporary = target.with_suffix(".couch-tmp")
    temporary.write_bytes(encode(value))
    temporary.replace(target)
    (data_root() / "steam-pending").unlink(missing_ok=True)
    return target


def queue():
    """SteamOS pre-start hook runs before Steam opens shortcuts.vdf."""
    data_root().mkdir(parents=True, exist_ok=True)
    (data_root() / "steam-pending").touch()
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            "steam-launcher.service",
            "--property=LoadState",
            "--value",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip() == "loaded":
        path = (
            Path.home()
            / ".config/systemd/user/steam-launcher.service.d/80-minecraft-couch.conf"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        executable = (
            str(Path.home() / ".local/bin/minecraft-couch")
            .replace("%", "%%")
            .replace('"', '\\"')
        )
        path.write_text(
            '[Service]\nExecStartPre=-"' + executable + '" steam-sync --pending\n'
        )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        return "Steam shortcut queued. It will be added at the next Steam start."
    return "Exit Steam fully, then run ~/.local/bin/minecraft-couch steam-sync and reopen Steam."
