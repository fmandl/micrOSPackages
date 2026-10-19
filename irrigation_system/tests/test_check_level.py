import importlib.util
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"


def _load_monitoring():
    path = PACKAGE_DIR / "monitoring.py"
    spec = importlib.util.spec_from_file_location("aqua_monitoring", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckLevelTest(unittest.TestCase):
    def setUp(self):
        self.m = _load_monitoring()
        # Reset to known manual config: water_distance_cm=7 => water_height=13 (>min 2) => OK
        self.m.CONFIG.update({
            "tank_width_cm": 40.0, "tank_depth_cm": 25.0, "tank_height_cm": 20.0,
            "water_distance_cm": 7.0, "min_level_cm": 2.0, "pump_l_hour": 300.0,
            "head_count": 4, "soil_sensor_count": 4, "level_module": "manual",
        })
        self.m.RUNTIME["last_level"] = None

    def test_ok_when_level_sufficient(self):
        res = self.m.check_level(required_l=1)
        self.assertTrue(res["ok"])
        self.assertEqual(res["problems"], [])

    def test_blocks_when_level_low(self):
        # water_distance close to full height -> water_height < min_level_cm
        self.m.CONFIG["water_distance_cm"] = 19.5  # height 20 -> water_height 0.5 < 2
        res = self.m.check_level(required_l=1)
        self.assertFalse(res["ok"])
        self.assertIn("tank_level_low", res["problems"])

    def test_blocks_when_not_enough_usable_water(self):
        res = self.m.check_level(required_l=999)  # way more than tank holds
        self.assertFalse(res["ok"])
        self.assertIn("not_enough_usable_water", res["problems"])

    def test_strict_blocks_on_unknown_level(self):
        # distance None -> water_height unknown -> warning in non-strict, block in strict
        self.m.CONFIG["water_distance_cm"] = None
        non_strict = self.m.check_level(measure=False)
        self.assertTrue(non_strict["ok"])
        self.assertIn("tank_level_unknown", non_strict["warnings"])

        strict = self.m.check_level(strict=True, measure=False)
        self.assertFalse(strict["ok"])
        self.assertIn("tank_level_unknown", strict["problems"])


if __name__ == "__main__":
    unittest.main()
