#!/usr/bin/env python3
"""Build a source-only installer archive; never include local game/account data."""

import hashlib
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mc_couch import __version__

destination = ROOT / "dist"
destination.mkdir(exist_ok=True)
name = "minecraft-couch-coop-" + __version__
archive = destination / (name + ".tar.gz")
include = [
    "mc_couch",
    "resources",
    "docs",
    "scripts",
    "tests",
    "minecraft-couch",
    "session-entry.py",
    "prism-wrapper.py",
    "install.sh",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
]
with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as stream:
    for item in include:
        path = ROOT / item
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            if (
                not file.is_file()
                or "__pycache__" in file.parts
                or file.suffix == ".pyc"
            ):
                continue
            if file.suffix.lower() in (".jar", ".appimage", ".key"):
                raise RuntimeError("Refusing to package external binaries or keys")
            info = stream.gettarinfo(
                str(file), arcname=name + "/" + str(file.relative_to(ROOT))
            )
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o755 if file.stat().st_mode & 0o111 else 0o644
            with file.open("rb") as source:
                stream.addfile(info, source)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(destination / "SHA256SUMS").write_text(checksum + "  " + archive.name + "\n")
print(archive)
print(checksum)
