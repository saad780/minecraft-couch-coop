"""Reversible user-level installation. No root or SteamOS system changes."""

import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
from .config import APP_NAME, data_root


def install(source=None):
    source = Path(source or Path(__file__).resolve().parent.parent)
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "app"
    if source.resolve() == target.resolve():
        raise RuntimeError(
            "Run the installer from the extracted download, not from the installed app directory."
        )
    with tempfile.TemporaryDirectory(prefix="install-", dir=root) as temporary:
        stage = Path(temporary) / "app"
        stage.mkdir()
        for name in [
            "mc_couch",
            "resources",
            "minecraft-couch",
            "session-entry.py",
            "prism-wrapper.py",
            "LICENSE",
            "NOTICE.md",
        ]:
            src = source / name
            if src.is_dir():
                shutil.copytree(
                    src,
                    stage / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            else:
                shutil.copy2(src, stage / name)
        old = root / "app.previous"
        if old.exists():
            shutil.rmtree(old)
        if target.exists():
            target.rename(old)
        try:
            stage.rename(target)
        except OSError:
            if old.exists():
                old.rename(target)
            raise
    binary = Path.home() / ".local/bin/minecraft-couch"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        "#!/bin/sh\nexec "
        + shlex.join([sys.executable, str(target / "minecraft-couch")])
        + ' "$@"\n'
    )
    binary.chmod(0o755)
    desktop = (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "applications/io.github.saad780.MinecraftCouch.desktop"
    )
    desktop.parent.mkdir(parents=True, exist_ok=True)
    # Desktop Exec quoting is not shell quoting. Escape its four special characters.
    command = (
        str(binary)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName="
        + APP_NAME
        + '\nExec="'
        + command
        + '"\nIcon='
        + str(target / "resources/icon.svg")
        + '\nTerminal=false\nCategories=Game;\nActions=Setup;\n\n[Desktop Action Setup]\nName=Setup\nExec="'
        + command
        + '" setup\n'
    )
    print("Installed:", binary)
    print("Next: run " + str(binary) + " setup in Desktop Mode.")
    return binary


def uninstall():
    from .steam import steam_running, sync

    if steam_running():
        raise RuntimeError(
            "Exit Steam fully before uninstalling so its shortcut can be removed safely."
        )
    try:
        sync(remove=True)
    except RuntimeError:
        pass  # No Steam installation or signed-in user.
    dropin = (
        Path.home()
        / ".config/systemd/user/steam-launcher.service.d/80-minecraft-couch.conf"
    )
    if dropin.exists():
        dropin.unlink()
        import subprocess

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    (Path.home() / ".local/bin/minecraft-couch").unlink(missing_ok=True)
    desktop = (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "applications/io.github.saad780.MinecraftCouch.desktop"
    )
    desktop.unlink(missing_ok=True)
    for name in ["app", "app.previous"]:
        directory = data_root() / name
        if directory.exists():
            shutil.rmtree(directory)
    print(
        "Application and Steam shortcut removed. Game data, accounts and settings were kept at:",
        data_root(),
    )
