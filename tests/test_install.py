import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from mc_couch import __version__


class InstallerTests(unittest.TestCase):
    def test_user_install_update_and_uninstall_keep_user_data(self):
        source = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = os.environ | {
                "HOME": temp,
                "XDG_DATA_HOME": str(root / "share"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "MC_COUCH_DATA": str(root / "data"),
                "MC_COUCH_CONFIG": str(root / "config/config.json"),
            }
            install = subprocess.run(
                ["sh", str(source / "install.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            binary = root / ".local/bin/minecraft-couch"
            result = subprocess.run(
                [str(binary), "--version"], env=env, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), __version__)
            self.assertTrue((root / "data/app/prism-wrapper.py").exists())
            profile = root / "data/profiles.json"
            profile.write_text('{"keep":"my data"}')
            update = subprocess.run(
                ["sh", str(source / "install.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(update.returncode, 0, update.stderr)
            self.assertTrue((root / "data/app.previous").is_dir())
            # This isolated HOME has no Steam installation. The host may be
            # running Steam, so mock only that external process check here.
            command = 'from unittest.mock import patch; from mc_couch.installer import uninstall; patcher=patch("mc_couch.steam.steam_running",return_value=False); patcher.start(); uninstall()'
            removed = subprocess.run(
                [sys.executable, "-c", command],
                env=env | {"PYTHONPATH": str(root / "data/app")},
                capture_output=True,
                text=True,
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(binary.exists())
            self.assertFalse((root / "data/app").exists())
            self.assertEqual(profile.read_text(), '{"keep":"my data"}')


if __name__ == "__main__":
    unittest.main()
