import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"


def _load_state_machine(data_root):
    common = types.ModuleType("Common")
    common.data_dir = lambda f=None: os.path.join(data_root, f) if f else data_root
    sys.modules["Common"] = common
    path = PACKAGE_DIR / "state_machine.py"
    spec = importlib.util.spec_from_file_location("aqua_sm_led", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeController:
    def __init__(self):
        self._elapsed = 0.0
        self.level_ok = True
        self.pump_l_hour = 300.0
        self.head_count = 4
    def now(self):
        return 0
    def elapsed_s(self):
        return self._elapsed
    def check_level(self, required_l=None):
        return {"ok": self.level_ok, "problems": [] if self.level_ok else ["tank_level_low"]}
    def plan(self, volume_l=None, per_head_l=None):
        vol = float(volume_l) if volume_l else (float(per_head_l) * self.head_count if per_head_l else 0.0)
        dur = 0.0 if vol <= 0 else vol * 3600.0 / self.pump_l_hour
        return {"duration_s": round(dur, 1), "volume_l": round(vol, 3),
                "per_head_l": round(vol / self.head_count, 3), "head_count": self.head_count}
    def pump_on(self, **k):
        pass
    def pump_off(self):
        pass


class FakeLed:
    def __init__(self):
        self.calls = []       # list of (state, fault_reason_or_None, error, run_mode)
        self.run_hint = None
    def set_run_hint(self, run):
        self.run_hint = run
    def on_state_change(self, state, fault=None, error=None):
        reason = fault.get("reason") if isinstance(fault, dict) else None
        mode = self.run_hint.get("mode") if isinstance(self.run_hint, dict) else None
        self.calls.append((state, reason, error, mode))


class StatusLedHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sm_mod = _load_state_machine(self.tmp)
        self.ctrl = FakeController()
        self.led = FakeLed()
        self.fsm = self.sm_mod.AquaStateMachine(self.ctrl, led=self.led)

    def last(self):
        return self.led.calls[-1]

    def test_initial_idle_notifies_led(self):
        # constructor fires one notify
        self.assertEqual(self.led.calls[0][0], "IDLE")

    def test_running_timed_vs_manual_mode_hint(self):
        self.fsm.transition("start", volume_l=1)
        self.assertEqual(self.last()[:2], ("RUNNING", None))
        self.assertEqual(self.last()[3], "timed")

        self.fsm.transition("stop")
        self.fsm.transition("start")  # manual
        self.assertEqual(self.last()[3], "manual")

    def test_low_water_sets_error_for_blink(self):
        self.fsm.transition("start", volume_l=1)
        self.fsm.transition("low_water")
        state, reason, error, _ = self.last()
        self.assertEqual(state, "PAUSED")
        self.assertEqual(reason, "low_water")   # fault present -> led blinks

    def test_pause_is_steady_not_warning(self):
        self.fsm.transition("start", volume_l=1)
        self.fsm.transition("pause")
        state, reason, error, _ = self.last()
        self.assertEqual(state, "PAUSED")
        self.assertIsNone(reason)               # intentional pause -> steady
        self.assertIsNone(error)

    def test_invalid_transition_not_a_warning(self):
        # pause from IDLE -> rejected, but must NOT be flagged as blink error
        self.fsm.transition("pause")
        state, reason, error, _ = self.last()
        self.assertEqual(state, "IDLE")
        self.assertIsNone(error)                # invalid_transition scrubbed

    def test_stop_returns_to_idle_steady(self):
        self.fsm.transition("start", volume_l=1)
        self.fsm.transition("stop")
        state, reason, error, _ = self.last()
        self.assertEqual(state, "IDLE")
        self.assertIsNone(reason)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
