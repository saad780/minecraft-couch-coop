"""Verified, atomic downloads and safe archive extraction."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import urllib.request

USER_AGENT = (
    "MinecraftCouchCoop/0.1.0 (+https://github.com/saad780/minecraft-couch-coop)"
)


def request(url):
    if not url.startswith("https://"):
        raise ValueError("Downloads must use HTTPS.")
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def read_json(url):
    with urllib.request.urlopen(request(url), timeout=40) as response:
        return json.load(response)


def digest(path, algorithm):
    result = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def fetch(url, destination, expected, algorithm="sha256"):
    destination = Path(destination)
    if not expected or len(expected) != hashlib.new(algorithm).digest_size * 2:
        raise ValueError("A valid expected download checksum is required.")
    if destination.exists() and digest(destination, algorithm) == expected.lower():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        fd, temp = tempfile.mkstemp(
            prefix=destination.name + ".", suffix=".part", dir=destination.parent
        )
        try:
            result = hashlib.new(algorithm)
            with (
                os.fdopen(fd, "wb") as output,
                urllib.request.urlopen(request(url), timeout=60) as response,
            ):
                while block := response.read(1024 * 1024):
                    result.update(block)
                    output.write(block)
            if result.hexdigest() != expected.lower():
                raise ValueError("Checksum mismatch for " + destination.name)
            os.replace(temp, destination)
            return destination
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
        finally:
            Path(temp).unlink(missing_ok=True)


def fetch_many(tasks, progress=lambda *_: None, workers=8):
    tasks = list(tasks)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch, *task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            path = future.result()
            progress(i, len(tasks), path.name)


def safe_child(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Download metadata contains an unsafe path.")
    return path


def unpack_tar(archive, destination):
    if not hasattr(tarfile, "data_filter"):
        raise RuntimeError(
            "Update Python to a version with safe tar extraction support."
        )
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as stream:
        stream.extractall(destination, filter="data")
