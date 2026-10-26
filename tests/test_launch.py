import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from mc_couch.assets import maven_path, rules_allow, selected_libraries
from mc_couch.config import Settings, atomic_json, runtime_root
from mc_couch.game import local_command, prepare_directory
from mc_couch.prism import wrapper_main
from mc_couch.steam import decode, encode, sync


class LibraryTests(unittest.TestCase):
    def test_linux_rules_and_fabric_override(self):
        parent = {
            "libraries": [
                {"name": "org.example:lib:1"},
                {"name": "org.example:lib:1:natives-linux"},
                {
                    "name": "org.example:windows:1",
                    "rules": [{"action": "allow", "os": {"name": "windows"}}],
                },
            ]
        }
        child = {"libraries": [{"name": "org.example:lib:2"}]}
        self.assertEqual(
            [x["name"] for x in selected_libraries(parent, child)],
            ["org.example:lib:2", "org.example:lib:1:natives-linux"],
        )
        self.assertFalse(
            rules_allow([{"action": "allow", "features": {"is_demo_user": True}}])
        )
        self.assertEqual(
            maven_path("a.b:lib:2:natives-linux"), "a/b/lib/2/lib-2-natives-linux.jar"
        )


class ClientTests(unittest.TestCase):
    def test_direct_launch_uses_configured_server_and_private_profile(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"MC_COUCH_DATA": temp}),
        ):
            root = Path(temp)
            game = root / "game"
            game.mkdir()
            (root / "mods.resolved.json").write_text("[]")
            for name, data in [
                (
                    "installed.json",
                    {
                        "minecraft_version": "1.21.11",
                        "fabric_loader": "0.20.1",
                        "libraries": [],
                    },
                ),
                ("vanilla.json", {"assetIndex": {"id": "29"}}),
                ("fabric.json", {"mainClass": "FabricMain", "id": "fabric-test"}),
            ]:
                (game / name).write_text(json.dumps(data))
            (game / "client.jar").touch()
            settings = Settings(server="play.example.net:25567", java_path="/bin/true")
            args, directory = local_command("Player1", settings)
            self.assertEqual(
                args[args.index("--quickPlayMultiplayer") + 1], settings.server
            )
            self.assertEqual(args[args.index("--username") + 1], "Player1")
            self.assertEqual(directory, root / "players/Player1")
            cfg = json.loads((directory / "config/controlify.json").read_text())
            self.assertTrue(cfg["global"]["out_of_focus_input"])
            self.assertIn("profiles", cfg)
            self.assertIn(
                "pauseOnLostFocus:false", (directory / "options.txt").read_text()
            )

    def test_mod_upgrade_only_removes_managed_files(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"MC_COUCH_DATA": temp}),
        ):
            root = Path(temp)
            (root / "mods").mkdir()
            (root / "mods/new.jar").write_bytes(b"new")
            (root / "mods.resolved.json").write_text(json.dumps([{"file": "new.jar"}]))
            directory = root / "players/Player1"
            mods = directory / "mods"
            mods.mkdir(parents=True)
            (mods / "old.jar").write_bytes(b"old")
            (mods / "personal.jar").write_bytes(b"keep")
            (mods / ".minecraft-couch-managed.json").write_text('["old.jar"]')
            prepare_directory(directory, Settings())
            self.assertFalse((mods / "old.jar").exists())
            self.assertTrue((mods / "personal.jar").exists())
            self.assertEqual((mods / "new.jar").read_bytes(), b"new")


class SteamMutationTests(unittest.TestCase):
    def test_preserves_other_games_and_backs_up_before_update(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"HOME": temp, "MC_COUCH_DATA": temp + "/couch"}),
            patch("mc_couch.steam.steam_running", return_value=False),
        ):
            config = Path(temp) / ".local/share/Steam/userdata/123/config"
            config.mkdir(parents=True)
            path = config / "shortcuts.vdf"
            original = {
                "shortcuts": {
                    "0": {"appname": "Keep me", "exe": "/bin/true", "appid": 123}
                }
            }
            before = encode(original)
            path.write_bytes(before)
            sync()
            added = decode(path.read_bytes())
            self.assertEqual(added["shortcuts"]["0"], original["shortcuts"]["0"])
            self.assertEqual(len(added["shortcuts"]), 2)
            self.assertEqual(next(config.glob("*.couch-backup-*")).read_bytes(), before)
            sync()
            self.assertEqual(len(decode(path.read_bytes())["shortcuts"]), 2)
            sync(remove=True)
            self.assertEqual(decode(path.read_bytes()), original)

    def test_running_steam_prevents_mutation(self):
        with (
            patch("mc_couch.steam.steam_running", return_value=True),
            patch("mc_couch.steam.steam_root") as root,
        ):
            with self.assertRaises(RuntimeError):
                sync()
            root.assert_not_called()


class PrismContractTests(unittest.TestCase):
    def test_stale_cancelled_and_nonprivate_requests_rejected(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": temp}),
        ):
            path = runtime_root() / "requests" / ("couch-" + "0" * 32 + ".json")
            base = {"owner": os.getpid(), "created": time.time()}
            for changes in [{"created": time.time() - 601}, {"cancelled": True}]:
                atomic_json(path, base | changes)
                with self.assertRaises(RuntimeError):
                    wrapper_main(["--instance", "couch-" + "0" * 32, "/bin/true"])
            atomic_json(path, base)
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                wrapper_main(["--instance", "couch-" + "0" * 32, "/bin/true"])

    def test_wrapper_preserves_launcher_stdin_and_sets_game_display(self):
        # Exercise a real child process, replacing only the kernel mounts/device
        # existence check. Prism sends its Java bootstrap launch script on stdin.
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": temp}),
        ):
            identity = "couch-" + "0" * 32
            path = runtime_root() / "requests" / (identity + ".json")
            status = path.with_suffix(".status.json")
            atomic_json(
                path,
                {
                    "owner": os.getpid(),
                    "created": time.time(),
                    "nonce": "test-nonce",
                    "event": "/dev/input/event99",
                    "js": "/dev/input/js99",
                    "status": str(status),
                    "environment": {"DISPLAY": ":321"},
                    "cancelled": False,
                },
            )
            code = """
import sys
from pathlib import Path
from unittest.mock import patch
import mc_couch.prism as p
real=Path.exists
with patch.object(Path,'exists',lambda s: True if str(s) in ['/dev/input/event99','/dev/input/js99'] else real(s)), patch.object(p,'sandbox',lambda args,*_:args):
    raise SystemExit(p.wrapper_main(sys.argv[1:]))
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    code,
                    "--instance",
                    identity,
                    sys.executable,
                    "-c",
                    'import os,sys;print(os.environ["DISPLAY"]+" "+sys.stdin.read())',
                ],
                input="prism-launch-script",
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), ":321 prism-launch-script")
            state = json.loads(status.read_text())
            self.assertEqual(state["exit_code"], 0)
            self.assertEqual(state["nonce"], "test-nonce")


if __name__ == "__main__":
    unittest.main()
