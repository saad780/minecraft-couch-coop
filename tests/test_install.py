import os
from pathlib import Path
import subprocess
import tempfile
import unittest


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
            self.assertEqual(result.stdout.strip(), "0.1.0")
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
            removed = subprocess.run(
                [str(binary), "uninstall"], env=env, capture_output=True, text=True
            )
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertFalse(binary.exists())
            self.assertFalse((root / "data/app").exists())
            self.assertEqual(profile.read_text(), '{"keep":"my data"}')


if __name__ == "__main__":
    unittest.main()
