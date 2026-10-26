"""User configuration and paths, independent of a particular machine or launcher."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
import hashlib
import ipaddress

APP_ID = "io.github.saad780.MinecraftCouch"
APP_NAME = "Minecraft Couch Co-op"


def data_root():
    return Path(
        os.environ.get(
            "MC_COUCH_DATA",
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            / "minecraft-couch-coop",
        )
    ).expanduser()


def config_path():
    return Path(
        os.environ.get(
            "MC_COUCH_CONFIG",
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "minecraft-couch-coop/config.json",
        )
    ).expanduser()


def runtime_root():
    base = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    result = base / f"minecraft-couch-{os.getuid()}"
    result.mkdir(parents=True, exist_ok=True, mode=0o700)
    if result.stat().st_uid != os.getuid() or result.is_symlink():
        raise RuntimeError("The runtime directory is not owned by this user.")
    result.chmod(0o700)
    return result


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def validate_server(value):
    value = value.strip()
    if (
        not value
        or len(value) > 300
        or any(c.isspace() for c in value)
        or any(c in value for c in "/\\?#@\x00")
    ):
        raise ValueError("Enter a server hostname or IP, optionally followed by :port.")
    if value.startswith("["):
        match = re.fullmatch(r"\[([0-9a-fA-F:]+)\](?::(\d+))?", value)
        if not match:
            raise ValueError("Use [IPv6 address]:port for IPv6 servers.")
        host, port = match.groups()
        try:
            ipaddress.IPv6Address(host)
        except ValueError as error:
            raise ValueError("Enter a valid IPv6 address.") from error
    else:
        parts = value.rsplit(":", 1)
        host, port = (parts[0], parts[1]) if len(parts) == 2 else (value, None)
        if len(parts) == 2 and not port:
            raise ValueError("Enter a port after the colon, or remove the colon.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
            raise ValueError("The server hostname contains unsupported characters.")
    if port and (not port.isdecimal() or not 1 <= int(port) <= 65535):
        raise ValueError("The server port must be between 1 and 65535.")
    if not host:
        raise ValueError("Enter a server hostname or IP.")
    return value


def server_host_port(value):
    value = validate_server(value)
    if value.startswith("["):
        match = re.fullmatch(r"\[([^]]+)\](?::(\d+))?", value)
        return match[1], int(match[2] or 25565)
    parts = value.rsplit(":", 1)
    return (parts[0], int(parts[1])) if len(parts) == 2 else (value, 25565)


def validate_name(name):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
        raise ValueError("Player names use 1–16 letters, numbers, or underscores.")
    return name


def offline_uuid(name):
    validate_name(name)
    digest = hashlib.md5(
        ("OfflinePlayer:" + name).encode(), usedforsecurity=False
    ).digest()
    return uuid.UUID(bytes=digest, version=3)


@dataclass
class Settings:
    server: str = "localhost:25565"
    account_mode: str = "local"
    minecraft_version: str = "1.21.11"
    fabric_loader: str = "0.20.1"
    max_players: int = 4
    width: int = 1920
    height: int = 1080
    heap_mb: int = 2048
    fps: int = 30
    render_distance: int = 7
    simulation_distance: int = 5
    reconnect_seconds: int = 15
    join_delay_seconds: int = 5
    java_path: str = ""
    prism_path: str = ""
    setup_complete: bool = False

    def validate(self):
        self.server = validate_server(self.server)
        if self.account_mode not in ("local", "microsoft"):
            raise ValueError("Account mode must be local or microsoft.")
        if not re.fullmatch(r"\d+(?:\.\d+){1,2}", self.minecraft_version):
            raise ValueError("Use a released Minecraft version, such as 1.21.11.")
        if not re.fullmatch(r"\d+(?:\.\d+){1,2}", self.fabric_loader):
            raise ValueError("Enter a Fabric Loader version, such as 0.20.1.")
        for field, low, high in [
            ("max_players", 1, 4),
            ("width", 640, 7680),
            ("height", 400, 4320),
            ("heap_mb", 1024, 8192),
            ("fps", 15, 240),
            ("render_distance", 2, 32),
            ("simulation_distance", 2, 32),
            ("reconnect_seconds", 0, 120),
            ("join_delay_seconds", 0, 60),
        ]:
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not low <= value <= high
            ):
                raise ValueError(f"{field} must be between {low} and {high}.")
        if self.max_players >= 2 and self.height < 720:
            raise ValueError(
                "Two or more players need a display height of at least 720 pixels."
            )
        if self.max_players >= 3 and self.width < 1280:
            raise ValueError(
                "Three or four players need a display width of at least 1280 pixels."
            )
        return self

    @classmethod
    def load(cls, path=None):
        path = Path(path or config_path())
        data = json.loads(path.read_text()) if path.exists() else {}
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known}).validate()

    def save(self, path=None):
        self.validate()
        atomic_json(path or config_path(), asdict(self))
