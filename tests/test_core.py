import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mc_couch.config import (
    Settings,
    offline_uuid,
    server_host_port,
    validate_name,
    validate_server,
)
from mc_couch.downloads import fetch, safe_child, unpack_tar
from mc_couch.game import reap_async, sandbox
from mc_couch.prism import accounts, wrapper_main
from mc_couch.steam import decode, encode


class ConfigTests(unittest.TestCase):
    def test_names_and_stable_local_identity(self):
        self.assertEqual(
            str(offline_uuid("Notch")), "b50ad385-829d-3141-a216-7e7d7539ba7f"
        )
        for name in ["", "../admin", "two players", "x" * 17, "玩家"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_name(name)

    def test_server_validation(self):
        self.assertEqual(
            server_host_port("play.example.net:25566"), ("play.example.net", 25566)
        )
        self.assertEqual(server_host_port("[::1]:25565"), ("::1", 25565))
        for server in [
            "https://example.net",
            "server:",
            "server:0",
            "server:65536",
            "[::::]",
            "a\nb",
        ]:
            with self.subTest(server=server), self.assertRaises(ValueError):
                validate_server(server)

    def test_limits_and_private_atomic_config(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            Settings(server="example.net").save(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(Settings.load(path).server, "example.net")
        for key, value in [
            ("max_players", 5),
            ("max_players", True),
            ("width", 200),
            ("heap_mb", 100),
            ("account_mode", "unknown"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                Settings(**{key: value}).validate()


class DownloadTests(unittest.TestCase):
    def test_verified_atomic_download_and_cache(self):
        data = b"publisher content"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache/file"
            with patch(
                "urllib.request.urlopen", return_value=io.BytesIO(data)
            ) as network:
                fetch(
                    "https://example.net/file", path, hashlib.sha256(data).hexdigest()
                )
                self.assertEqual(path.read_bytes(), data)
                fetch(
                    "https://example.net/file", path, hashlib.sha256(data).hexdigest()
                )
                self.assertEqual(network.call_count, 1)

    def test_bad_checksum_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "file"
            path.write_bytes(b"old")
            with (
                patch(
                    "urllib.request.urlopen",
                    side_effect=lambda *_a, **_k: io.BytesIO(b"corrupt"),
                ),
                patch("time.sleep"),
            ):
                with self.assertRaises(ValueError):
                    fetch("https://example.net/file", path, "0" * 64)
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(list(Path(temp).glob("*.part")), [])

    def test_path_and_tar_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                safe_child(temp, "../escape")
            archive = Path(temp) / "bad.tar"
            with tarfile.open(archive, "w") as output:
                item = tarfile.TarInfo("../escape")
                item.size = 1
                output.addfile(item, io.BytesIO(b"x"))
            with self.assertRaises(tarfile.FilterError):
                unpack_tar(archive, Path(temp) / "extract")


class AccountTests(unittest.TestCase):
    def test_only_public_microsoft_profile_metadata_imported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "accounts.json"
            path.write_text(
                json.dumps(
                    {
                        "formatVersion": 3,
                        "accounts": [
                            {
                                "type": "MSA",
                                "profile": {"name": "Player1", "id": "0" * 32},
                                "msa": {"token": "DO_NOT_COPY"},
                                "password": "DO_NOT_COPY",
                            },
                            {
                                "type": "Offline",
                                "profile": {"name": "Other", "id": "1" * 32},
                            },
                        ],
                    }
                )
            )
            result = accounts(path)
            self.assertEqual(
                result, [{"name": "Player1", "kind": "microsoft", "id": "0" * 32}]
            )
            self.assertNotIn("DO_NOT_COPY", json.dumps(result))

    def test_prism_wrapper_refuses_unrequested_game(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": temp}),
        ):
            with self.assertRaises(FileNotFoundError):
                wrapper_main(["--instance", "couch-" + "0" * 32, "/bin/true"])
            with self.assertRaises(ValueError):
                wrapper_main(["--instance", "../../elsewhere", "/bin/true"])


class LifecycleTests(unittest.TestCase):
    def test_slow_player_exit_does_not_block_shared_input_loop(self):
        started = threading.Event()
        release = threading.Event()

        class Game:
            def reap(self):
                started.set()
                release.wait(3)

        before = time.monotonic()
        thread = reap_async(Game())
        try:
            self.assertTrue(started.wait(0.5))
            self.assertLess(time.monotonic() - before, 0.5)
            self.assertTrue(thread.is_alive())
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_each_sandbox_has_only_its_assigned_input_nodes(self):
        command = sandbox(["/bin/true"], "/dev/input/event77", "/dev/input/js77")
        self.assertIn("/dev/input/event77", command)
        self.assertIn("/dev/input/js77", command)
        self.assertNotIn("/dev/input", command)
        self.assertIn("--dev", command)
        self.assertIn("/run/udev", command)


class SteamTests(unittest.TestCase):
    def test_roundtrip_preserves_existing_shortcut_and_uint32(self):
        value = {
            "shortcuts": {
                "0": {
                    "appid": 0xF1234567,
                    "appname": "Existing game",
                    "exe": '"/path with spaces/game"',
                    "tags": {"0": "Favorites"},
                }
            }
        }
        self.assertEqual(decode(encode(value)), value)

    def test_unfamiliar_or_truncated_file_rejected(self):
        for data in [b"\x03test\x00", b"\x00shortcuts\x00", b"\x08trailing"]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                decode(data)


if __name__ == "__main__":
    unittest.main()
