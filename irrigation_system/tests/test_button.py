import importlib.util
import sys
import types
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"


def _load_button():
    # Minimal stubs so button.py imports cleanly on CPython.
    if "machine" not in sys.modules:
        machine = types.ModuleType("machine")
        machine.Pin = None  # hardware disabled in this test
        sys.modules["machine"] = machine
    common = types.ModuleType("Common")
    common.micro_task = None       # no async runtime -> poll task is a no-op
    common.manage_task = None
    sys.modules["Common"] = common
    # irrigation_system package + monitoring submodule
    pkg = types.ModuleType("irrigation_system")
    pkg.__path__ = [str(PACKAGE_DIR)]
    sys.modules["irrigation_system"] = pkg
    mspec = importlib.util.spec_from_file_location(
        "irrigation_system.monitoring", PACKAGE_DIR / "monitoring.py")
    monitoring = importlib.util.module_from_spec(mspec)
    sys.modules["irrigation_system.monitoring"] = monitoring
    mspec.loader.exec_module(monitoring)
    pkg.monitoring = monitoring
    bspec = importlib.util.spec_from_file_location(
        "irrigation_system.button", PACKAGE_DIR / "button.py")
    button = importlib.util.module_from_spec(bspec)
    bspec.loader.exec_module(button)
    return button, monitoring


class FakeSM:
    def __init__(self, state="IDLE"):
        self._state = state
        self.events = []
    def snapshot(self):
        return {"state": self._state}
    def transition(self, event, **k):
        self.events.append(event)
        # emulate resulting state for chaining
        self._state = {"start": "RUNNING", "pause": "PAUSED",
                       "resume": "RUNNING", "stop": "IDLE"}.get(event, self._state)
        return {"state": True, "fsm_state": self._state}


class ButtonLogicTest(unittest.TestCase):
    def setUp(self):
        self.button, self.monitoring = _load_button()
        self.monitoring.CONFIG["btn_long_ms"] = 1500
        self.monitoring.CONFIG["btn_debounce_ms"] = 50
        self.sm = FakeSM("IDLE")
        self.btn = self.button.Button(state_machine=self.sm, config=self.monitoring.CONFIG)

    def _press(self, t):
        self.btn.on_edge(True, t)

    def _release(self, t):
        return self.btn.on_edge(False, t)

    def test_short_press_idle_starts(self):
        self._press(0)
        action = self._release(300)   # 300ms < 1500 -> short
        self.assertEqual(action, "start")
        self.assertEqual(self.sm.events, ["start"])

    def test_short_press_running_pauses(self):
        self.sm._state = "RUNNING"
        self._press(1000)
        self.assertEqual(self._release(1200), "pause")
        self.assertEqual(self.sm.events, ["pause"])

    def test_short_press_paused_resumes(self):
        self.sm._state = "PAUSED"
        self._press(0)
        self.assertEqual(self._release(200), "resume")
        self.assertEqual(self.sm.events, ["resume"])

    def test_long_press_fires_stop_during_hold_and_consumes_release(self):
        self.sm._state = "RUNNING"
        self._press(0)
        # poll task is a no-op here; simulate the poll calling check_long at threshold
        action = self.btn.check_long(1500)
        self.assertEqual(action, "stop")
        self.assertEqual(self.sm.events, ["stop"])
        # release after a long hold must NOT trigger another (short) action
        self.assertIsNone(self._release(1800))
        self.assertEqual(self.sm.events, ["stop"])   # unchanged

    def test_long_press_on_release_if_poll_missed(self):
        self.sm._state = "RUNNING"
        self._press(0)
        # no check_long call (poll missed) -> release beyond threshold still = stop
        self.assertEqual(self._release(2000), "stop")
        self.assertEqual(self.sm.events, ["stop"])

    def test_check_long_noop_before_threshold(self):
        self.sm._state = "IDLE"
        self._press(0)
        self.assertIsNone(self.btn.check_long(1000))   # < 1500
        self.assertEqual(self.sm.events, [])


if __name__ == "__main__":
    unittest.main()
