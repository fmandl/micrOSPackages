import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"


def _load_state_machine(data_root):
    """Load state_machine.py with a stubbed Common.data_dir pointing at data_root."""
    common = types.ModuleType("Common")
    common.data_dir = lambda f_name=None: os.path.join(data_root, f_name) if f_name else data_root
    sys.modules["Common"] = common

    path = PACKAGE_DIR / "state_machine.py"
    spec = importlib.util.spec_from_file_location("aqua_state_machine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeController:
    def __init__(self, sm_module):
        self.sm = sm_module
        self.pump = False
        self._now = 1000
        self._elapsed = 0.0
        self.level_ok = True
        self.pump_on_calls = []
        self.pump_off_calls = 0
        # pump_l_hour=300, head_count=4 -> 1 L => 12 s
        self.pump_l_hour = 300.0
        self.head_count = 4

    def now(self):
        return self._now

    def elapsed_s(self):
        return self._elapsed

    def check_level(self, required_l=None):
        return {"ok": self.level_ok, "problems": [] if self.level_ok else ["tank_level_low"]}

    def plan(self, volume_l=None, per_head_l=None):
        vol = 0.0
        if volume_l:
            vol = float(volume_l)
        elif per_head_l:
            vol = float(per_head_l) * self.head_count
        duration = 0.0 if self.pump_l_hour <= 0 or vol <= 0 else vol * 3600.0 / self.pump_l_hour
        return {"duration_s": round(duration, 1), "volume_l": round(vol, 3),
                "per_head_l": round(vol / self.head_count, 3), "head_count": self.head_count}

    def pump_on(self, mode, remaining_s, max_runtime_s, elapsed_s):
        self.pump = True
        self.pump_on_calls.append({"mode": mode, "remaining_s": remaining_s,
                                   "max_runtime_s": max_runtime_s, "elapsed_s": elapsed_s})

    def pump_off(self):
        self.pump = False
        self.pump_off_calls += 1


class StateMachineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sm_mod = _load_state_machine(self.tmp)
        self.ctrl = FakeController(self.sm_mod)
        self.fsm = self.sm_mod.AquaStateMachine(self.ctrl)

    def _run_file(self):
        return os.path.join(self.tmp, self.sm_mod.RUN_FILE)

    # --- basic timed lifecycle ---

    def test_start_timed_computes_duration_and_runs(self):
        res = self.fsm.transition("start", volume_l=1)
        self.assertTrue(res["state"])
        self.assertEqual(self.fsm.state, self.sm_mod.RUNNING)
        self.assertTrue(self.ctrl.pump)
        self.assertEqual(self.fsm.run["mode"], "timed")
        self.assertAlmostEqual(self.fsm.run["duration_s"], 12.0, places=1)
        self.assertAlmostEqual(self.ctrl.pump_on_calls[-1]["remaining_s"], 12.0, places=1)

    def test_start_manual_when_no_volume(self):
        res = self.fsm.transition("start")  # no volume -> manual
        self.assertTrue(res["state"])
        self.assertEqual(self.fsm.run["mode"], "manual")
        self.assertIsNone(self.ctrl.pump_on_calls[-1]["remaining_s"])  # infinite

    def test_start_blocked_on_low_water(self):
        self.ctrl.level_ok = False
        res = self.fsm.transition("start", volume_l=1)
        self.assertFalse(res["state"])
        self.assertEqual(res["error"], "low_water")
        self.assertEqual(self.fsm.state, self.sm_mod.IDLE)
        self.assertFalse(self.ctrl.pump)

    def test_timer_expired_stops(self):
        self.fsm.transition("start", volume_l=1)
        res = self.fsm.transition("timer_expired")
        self.assertTrue(res["state"])
        self.assertTrue(res.get("done"))
        self.assertEqual(self.fsm.state, self.sm_mod.IDLE)
        self.assertFalse(self.ctrl.pump)
        self.assertFalse(os.path.exists(self._run_file()))

    # --- pause / resume with elapsed accounting ---

    def test_pause_persists_elapsed_then_resume_continues(self):
        self.fsm.transition("start", volume_l=1)  # duration 12s
        self.ctrl._elapsed = 5.0
        res = self.fsm.transition("pause")
        self.assertTrue(res["state"])
        self.assertEqual(self.fsm.state, self.sm_mod.PAUSED)
        self.assertFalse(self.ctrl.pump)
        self.assertTrue(os.path.exists(self._run_file()))
        self.assertAlmostEqual(self.fsm.run["elapsed_s"], 5.0, places=1)

        # resume continues with remaining = 12 - 5 = 7
        self.fsm.transition("resume")
        self.assertEqual(self.fsm.state, self.sm_mod.RUNNING)
        self.assertAlmostEqual(self.ctrl.pump_on_calls[-1]["remaining_s"], 7.0, places=1)
        self.assertFalse(os.path.exists(self._run_file()))  # cleared on resume

    def test_manual_hard_cap_counts_pause_time(self):
        # manual with 100s cap
        self.fsm.transition("start", max_runtime_s=100)
        self.assertEqual(self.fsm.run["mode"], "manual")
        self.assertAlmostEqual(self.ctrl.pump_on_calls[-1]["remaining_s"], 100.0, places=1)
        self.ctrl._elapsed = 30.0
        self.fsm.transition("pause")
        self.fsm.transition("resume")
        # remaining cap = 100 - 30 = 70 (pause time counted in)
        self.assertAlmostEqual(self.ctrl.pump_on_calls[-1]["remaining_s"], 70.0, places=1)

    # --- low water auto-pause ---

    def test_low_water_auto_pauses_and_keeps_remaining(self):
        self.fsm.transition("start", volume_l=1)
        self.ctrl._elapsed = 4.0
        res = self.fsm.transition("low_water")
        self.assertTrue(res["state"])
        self.assertEqual(res["error"], "low_water")
        self.assertEqual(self.fsm.state, self.sm_mod.PAUSED)
        self.assertFalse(self.ctrl.pump)
        self.assertEqual(self.fsm.fault["reason"], "low_water")
        self.assertTrue(os.path.exists(self._run_file()))

    def test_resume_blocked_if_level_still_low(self):
        self.fsm.transition("start", volume_l=1)
        self.fsm.transition("low_water")
        self.ctrl.level_ok = False
        res = self.fsm.transition("resume")
        self.assertFalse(res["state"])
        self.assertEqual(res["error"], "low_water")
        self.assertEqual(self.fsm.state, self.sm_mod.PAUSED)

    # --- invalid transitions ---

    def test_invalid_transitions_rejected(self):
        self.assertEqual(self.fsm.transition("pause")["error"], "invalid_transition")
        self.assertEqual(self.fsm.transition("resume")["error"], "invalid_transition")
        self.fsm.transition("start", volume_l=1)
        self.assertEqual(self.fsm.transition("start", volume_l=1)["error"], "invalid_transition")

    def test_stop_from_running_and_paused(self):
        self.fsm.transition("start", volume_l=1)
        self.assertTrue(self.fsm.transition("stop")["state"])
        self.assertEqual(self.fsm.state, self.sm_mod.IDLE)
        self.fsm.transition("start", volume_l=1)
        self.fsm.transition("pause")
        self.assertTrue(self.fsm.transition("stop")["state"])
        self.assertEqual(self.fsm.state, self.sm_mod.IDLE)
        self.assertFalse(os.path.exists(self._run_file()))

    # --- reboot safety ---

    def test_reboot_restores_as_paused(self):
        self.fsm.transition("start", volume_l=1)
        self.ctrl._elapsed = 3.0
        self.fsm.transition("pause")
        # simulate reboot: new machine instance reading the same data dir
        fsm2 = self.sm_mod.AquaStateMachine(FakeController(self.sm_mod))
        self.assertEqual(fsm2.state, self.sm_mod.PAUSED)
        self.assertAlmostEqual(fsm2.run["elapsed_s"], 3.0, places=1)

    def test_manual_reboot_goes_idle_and_drops_file(self):
        self.fsm.transition("start", max_runtime_s=100)  # manual
        self.ctrl._elapsed = 10.0
        self.fsm.transition("pause")  # writes a manual record
        self.assertTrue(os.path.exists(self._run_file()))
        # simulate reboot
        fsm2 = self.sm_mod.AquaStateMachine(FakeController(self.sm_mod))
        self.assertEqual(fsm2.state, self.sm_mod.IDLE)
        self.assertIsNone(fsm2.run)
        self.assertFalse(os.path.exists(self._run_file()))  # dropped on restore


if __name__ == "__main__":
    unittest.main()
