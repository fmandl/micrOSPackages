import asyncio
import importlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"


class FakeDone:
    def __init__(self):
        self.v = False
    def is_set(self):
        return self.v
    def set(self):
        self.v = True
    def clear(self):
        self.v = False


class FakeTask:
    def __init__(self, tag, coroutine=None):
        self.tag = tag
        self.coroutine = coroutine
        self.done = FakeDone()
        self.out = ""
    def __enter__(self):
        self.done.clear()
        return self
    def __exit__(self, *a):
        self.done.set()
    async def feed(self, sleep_ms=1):
        # Real suspension point so the coroutine can be stepped one iteration
        # at a time via .send(None); time is advanced by the test via CLOCK.
        await asyncio.sleep(0)


def _install_env(data_root, clock):
    # machine.Pin stub
    machine = types.ModuleType("machine")
    class FakePin:
        OUT = 1
        def __init__(self, pin, mode=None):
            self.pin = pin
            self._v = 0
        def value(self, v=None):
            if v is not None:
                self._v = v
            return self._v
    machine.Pin = FakePin
    sys.modules["machine"] = machine

    # Common stub (tasks + data_dir)
    common = types.ModuleType("Common")
    common.TASKS = {}
    common.data_dir = lambda f=None: os.path.join(data_root, f) if f else data_root
    def micro_task(tag, task=None, _wrap=False):
        if _wrap:
            def deco(fn):
                task_tag = "{}._{}".format(tag, fn.__name__)
                def launcher(*a, **k):
                    coro = fn(task_tag, *a, **k)
                    return micro_task(task_tag, task=coro)
                return launcher
            return deco
        if task is not None:
            common.TASKS[tag] = FakeTask(tag, task)
            return {tag: "Starting"}
        return common.TASKS.get(tag)
    def manage_task(tag, op):
        t = common.TASKS.get(tag)
        if op == "kill" and t is not None:
            t.done.set()
            if t.coroutine is not None:
                try:
                    t.coroutine.close()
                except Exception:
                    pass
            common.TASKS.pop(tag, None)
            return True, "killed"
        return False, "none"
    common.micro_task = micro_task
    common.manage_task = manage_task
    sys.modules["Common"] = common

    # microIO stub
    micro_io = types.ModuleType("microIO")
    micro_io.MAP = {"aqua_pump": 26}
    def bind_pin(tag, number=None):
        return number if number is not None else micro_io.MAP.get(tag, 26)
    def pinmap_search(tag):
        return {tag: micro_io.MAP.get(tag)} if isinstance(tag, str) else {t: micro_io.MAP.get(t) for t in tag}
    micro_io.bind_pin = bind_pin
    micro_io.pinmap_search = pinmap_search
    sys.modules["microIO"] = micro_io

    # time stub with controllable clock
    utime = types.ModuleType("utime")
    utime.time = lambda: int(clock["ms"] / 1000)
    utime.ticks_ms = lambda: clock["ms"]
    utime.ticks_diff = lambda a, b: a - b
    sys.modules["utime"] = utime

    # 'irrigation_system' package mapping -> load monitoring + state_machine as submodules
    pkg = types.ModuleType("irrigation_system")
    pkg.__path__ = [str(PACKAGE_DIR)]
    sys.modules["irrigation_system"] = pkg

    def _load(name):
        path = PACKAGE_DIR / (name + ".py")
        spec = importlib.util.spec_from_file_location("irrigation_system." + name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["irrigation_system." + name] = mod
        spec.loader.exec_module(mod)
        setattr(pkg, name, mod)
        return mod

    monitoring = _load("monitoring")
    state_machine = _load("state_machine")
    actuators = _load("actuators")
    return monitoring, state_machine, actuators


class WatcherIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clock = {"ms": 0}
        self.monitoring, self.sm_mod, self.act = _install_env(self.tmp, self.clock)
        # known manual config: level OK, 1 L => 12 s
        self.monitoring.CONFIG.update({
            "tank_width_cm": 40.0, "tank_depth_cm": 25.0, "tank_height_cm": 20.0,
            "water_distance_cm": 7.0, "min_level_cm": 2.0, "pump_l_hour": 300.0,
            "head_count": 4, "soil_sensor_count": 4, "level_module": "manual",
            "checkpoint_interval_s": 0,
        })
        self.monitoring.RUNTIME["last_level"] = None
        self.ctrl = self.act.PumpController(state_machine=None)
        self.fsm = self.sm_mod.AquaStateMachine(self.ctrl)
        self.ctrl.bind_state_machine(self.fsm)

    def _run_file(self):
        return os.path.join(self.tmp, self.sm_mod.RUN_FILE)

    def _drive_watcher(self, max_iters=1000):
        """Step the watcher coroutine to completion with a hard iteration cap.

        If the loop does not exit within max_iters, fail loudly (catches hangs)
        instead of spinning forever.
        """
        task = sys.modules["Common"].TASKS.get(self.act.SM_TASK_TAG)
        if task is None or task.coroutine is None:
            return None
        coro = task.coroutine
        try:
            for _ in range(max_iters):
                coro.send(None)
            coro.close()
            self.fail("watcher did not terminate within {} iterations".format(max_iters))
        except StopIteration:
            pass
        return task

    def test_timed_run_expires_and_stops(self):
        res = self.fsm.transition("start", volume_l=1)  # 12 s
        self.assertTrue(res["state"])
        self.assertEqual(self.fsm.state, self.sm_mod.RUNNING)
        # advance clock past duration so the watcher sees remaining<=0
        self.clock["ms"] = 13_000
        self._drive_watcher()
        self.assertEqual(self.fsm.state, self.sm_mod.IDLE)   # timer_expired -> stop
        self.assertFalse(self.monitoring.CONFIG is None)
        self.assertFalse(os.path.exists(self._run_file()))

    def test_low_water_during_run_auto_pauses(self):
        self.fsm.transition("start", volume_l=1)
        # drop the level below reserve mid-run
        self.monitoring.CONFIG["water_distance_cm"] = 19.5  # water_height 0.5 < min 2
        self.clock["ms"] = 2_000
        self._drive_watcher()
        self.assertEqual(self.fsm.state, self.sm_mod.PAUSED)
        self.assertEqual(self.fsm.fault["reason"], "low_water")
        self.assertTrue(os.path.exists(self._run_file()))

    def test_checkpoint_written_only_when_interval_set(self):
        self.monitoring.CONFIG["checkpoint_interval_s"] = 5
        self.fsm.transition("start", volume_l=10)  # 120 s timed
        self.clock["ms"] = 6_000  # past the 5s interval, still running
        # single watcher pass: should checkpoint then keep running (remaining>0)
        task = sys.modules["Common"].TASKS.get(self.act.SM_TASK_TAG)
        coro = task.coroutine
        # step the coroutine once (one loop iteration) instead of running to completion
        coro.send(None)
        self.assertTrue(os.path.exists(self._run_file()))
        coro.close()
        self.assertEqual(self.fsm.state, self.sm_mod.RUNNING)

    def test_manual_run_infinite_no_checkpoint(self):
        self.monitoring.CONFIG["checkpoint_interval_s"] = 5
        self.fsm.transition("start")  # manual, infinite
        self.clock["ms"] = 10_000
        task = sys.modules["Common"].TASKS.get(self.act.SM_TASK_TAG)
        coro = task.coroutine
        coro.send(None)  # one iteration
        # manual mode must NOT write a periodic checkpoint
        self.assertFalse(os.path.exists(self._run_file()))
        coro.close()
        self.assertEqual(self.fsm.state, self.sm_mod.RUNNING)


if __name__ == "__main__":
    unittest.main()
