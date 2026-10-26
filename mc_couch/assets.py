"""Install a vanilla/Fabric cache from publisher sources; never redistribute it."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from .config import atomic_json, data_root
from .downloads import fetch, fetch_many, read_json, request, safe_child, unpack_tar

VERSION_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_META = "https://meta.fabricmc.net/v2/versions/loader"


def rules_allow(rules):
    result = not rules
    arch = "amd64" if platform.machine() in ("x86_64", "AMD64") else "aarch64"
    for rule in rules:
        matches = True
        for key, value in rule.get("os", {}).items():
            actual = {"name": "linux", "arch": arch, "version": platform.release()}.get(
                key, ""
            )
            matches &= bool(re.search(value, actual))
        matches &= not bool(rule.get("features"))
        if matches:
            result = rule["action"] == "allow"
    return result


def maven_path(name):
    group, artifact, version, *classifier = name.split(":")
    suffix = "-" + classifier[0] if classifier else ""
    return "/".join(
        [
            group.replace(".", "/"),
            artifact,
            version,
            f"{artifact}-{version}{suffix}.jar",
        ]
    )


def selected_libraries(parent, child):
    result = {}
    for lib in parent.get("libraries", []) + child.get("libraries", []):
        if not rules_allow(lib.get("rules", [])):
            continue
        parts = lib["name"].split(":")
        key = ":".join(parts[:2] + parts[3:])
        result[key] = lib
    return list(result.values())


def mod_lock(settings):
    if settings.minecraft_version == "1.21.11":
        return json.loads(Path(__file__).with_name("mods.lock.json").read_text())
    result = []
    for project in ["controlify", "fabric-api", "yacl", "sodium", "ferrite-core"]:
        import urllib.parse

        query = urllib.parse.urlencode(
            {
                "game_versions": json.dumps([settings.minecraft_version]),
                "loaders": '["fabric"]',
            }
        )
        versions = read_json(
            "https://api.modrinth.com/v2/project/" + project + "/version?" + query
        )
        candidates = [v for v in versions if v["version_type"] == "release"]
        if not candidates:
            raise RuntimeError(
                f"{project} has no verified Fabric release for Minecraft {settings.minecraft_version}. Use 1.21.11."
            )
        version = candidates[0]
        file = next(f for f in version["files"] if f["primary"])
        result.append(
            {
                "project": project,
                "version_id": version["id"],
                "file": file["filename"],
                "url": file["url"],
                "sha512": file["hashes"]["sha512"],
            }
        )
    return result


def install_mods(settings, root=None, progress=lambda *_: None):
    root = Path(root or data_root())
    mods = root / "mods"
    lock = mod_lock(settings)
    fetch_many(
        [(m["url"], safe_child(mods, m["file"]), m["sha512"], "sha512") for m in lock],
        progress,
    )
    atomic_json(root / "mods.resolved.json", lock)
    return lock


def install_java(major, root=None, progress=lambda *_: None):
    root = Path(root or data_root())
    marker = root / "java" / f"{major}.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        java = Path(json.loads(marker.read_text())["path"])
        if java.is_file() and os.access(java, os.X_OK):
            return java
    arch = "x64" if platform.machine() in ("x86_64", "AMD64") else "aarch64"
    progress(0, 1, f"Downloading Java {major}")
    assets = read_json(
        f"https://api.adoptium.net/v3/assets/latest/{major}/hotspot?architecture={arch}&image_type=jre&os=linux&vendor=eclipse"
    )
    if not assets:
        raise RuntimeError("No compatible Java runtime was found.")
    package = assets[0]["binary"]["package"]
    archive = root / "downloads" / package["name"]
    fetch(package["link"], archive, package["checksum"])
    destination = root / "java" / assets[0]["release_name"]
    with tempfile.TemporaryDirectory(prefix="java-", dir=root / "java") as temp:
        unpack_tar(archive, temp)
        children = list(Path(temp).iterdir())
        if len(children) != 1 or not (children[0] / "bin/java").exists():
            raise RuntimeError("Unexpected Java archive layout.")
        if not destination.exists():
            shutil.move(str(children[0]), str(destination))
    java = destination / "bin/java"
    java.chmod(java.stat().st_mode | 0o111)
    atomic_json(
        marker,
        {
            "path": str(java),
            "release": assets[0]["release_name"],
            "sha256": package["checksum"],
        },
    )
    return java


def library_task(lib, root):
    artifact = lib.get("downloads", {}).get("artifact")
    if artifact:
        return (
            artifact["url"],
            safe_child(root / "libraries", artifact["path"]),
            artifact["sha1"],
            "sha1",
        )
    path = maven_path(lib["name"])
    url = lib.get("url", "https://libraries.minecraft.net/").rstrip("/") + "/" + path
    if lib.get("sha512"):
        return url, safe_child(root / "libraries", path), lib["sha512"], "sha512"
    if lib.get("sha256"):
        return url, safe_child(root / "libraries", path), lib["sha256"], "sha256"
    if lib.get("sha1"):
        return url, safe_child(root / "libraries", path), lib["sha1"], "sha1"
    for algorithm in ["sha256", "sha1"]:
        try:
            with urllib.request.urlopen(
                request(url + "." + algorithm), timeout=30
            ) as response:
                checksum = response.read(512).decode().split()[0]
            if re.fullmatch(
                r"[a-fA-F0-9]{" + str(hashlib.new(algorithm).digest_size * 2) + "}",
                checksum,
            ):
                return url, safe_child(root / "libraries", path), checksum, algorithm
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    raise RuntimeError("No publisher checksum was available for " + lib["name"])


def install_game(settings, progress=lambda *_: None, root=None):
    settings.validate()
    root = Path(root or data_root())
    game = root / "game"
    game.mkdir(parents=True, exist_ok=True)
    progress(0, 1, "Resolving Minecraft and Fabric")
    manifest = read_json(VERSION_MANIFEST)
    version = next(
        (v for v in manifest["versions"] if v["id"] == settings.minecraft_version), None
    )
    if not version:
        raise RuntimeError("Minecraft version was not found in the official manifest.")
    parent_file = game / "vanilla.json"
    fetch(version["url"], parent_file, version["sha1"], "sha1")
    parent = json.loads(parent_file.read_text())
    child = read_json(
        f"{FABRIC_META}/{settings.minecraft_version}/{settings.fabric_loader}/profile/json"
    )
    atomic_json(game / "fabric.json", child)
    libraries = selected_libraries(parent, child)
    lib_tasks = [library_task(lib, game) for lib in libraries]
    tasks = list(lib_tasks)
    client = parent["downloads"]["client"]
    tasks.append((client["url"], game / "client.jar", client["sha1"], "sha1"))
    logging = parent.get("logging", {}).get("client", {}).get("file")
    if logging:
        tasks.append(
            (
                logging["url"],
                safe_child(game / "log_configs", logging["id"]),
                logging["sha1"],
                "sha1",
            )
        )
    fetch_many(tasks, lambda i, n, name: progress(i, n, "Game libraries: " + name))
    index = parent["assetIndex"]
    index_file = safe_child(game / "assets/indexes", index["id"] + ".json")
    fetch(index["url"], index_file, index["sha1"], "sha1")
    assets = json.loads(index_file.read_text())
    hashes = {obj["hash"] for obj in assets["objects"].values()}
    tasks = [
        (
            f"https://resources.download.minecraft.net/{h[:2]}/{h}",
            safe_child(game / "assets/objects", h[:2] + "/" + h),
            h,
            "sha1",
        )
        for h in hashes
    ]
    fetch_many(tasks, lambda i, n, name: progress(i, n, "Minecraft assets"))
    install_mods(
        settings,
        root,
        lambda i, n, name: progress(i, n, "Controller and performance mods"),
    )
    major = parent.get("javaVersion", {}).get("majorVersion", 21)
    if not settings.java_path:
        settings.java_path = str(install_java(major, root, progress))
    atomic_json(
        game / "installed.json",
        {
            "minecraft_version": settings.minecraft_version,
            "fabric_loader": settings.fabric_loader,
            "libraries": [str(task[1]) for task in lib_tasks],
            "java_major": major,
        },
    )
    progress(1, 1, "Minecraft is ready")
    return game


def installed(settings, root=None):
    root = Path(root or data_root())
    marker = root / "game/installed.json"
    if not marker.exists():
        return False
    try:
        data = json.loads(marker.read_text())
        return (
            data["minecraft_version"] == settings.minecraft_version
            and data["fabric_loader"] == settings.fabric_loader
            and (root / "game/client.jar").exists()
        )
    except (ValueError, KeyError, OSError):
        return False
