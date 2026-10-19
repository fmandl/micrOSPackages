import tempfile
import unittest
from pathlib import Path

from _tools.unpack import unpack_package


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "irrigation_system"


class TestIrrigationUnpackLayout(unittest.TestCase):
    def test_package_named_web_subfolder_moves_to_web(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            unpack_package(PACKAGE_ROOT, target)

            self.assertTrue((target / "modules" / "LM_aqua.py").is_file())
            self.assertTrue((target / "web" / "irrigation_system" / "aqua.html").is_file())
            self.assertTrue((target / "web" / "irrigation_system" / "aqua.css").is_file())
            self.assertTrue((target / "web" / "irrigation_system" / "aqua.js").is_file())
            self.assertFalse((target / "lib" / "irrigation_system" / "irrigation_system" / "aqua.html").exists())
            self.assertTrue((target / "lib" / "irrigation_system" / "pacman.json").is_file())


if __name__ == "__main__":
    unittest.main()
