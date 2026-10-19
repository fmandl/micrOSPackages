import importlib.util
import asyncio
import json
import os
import sys
import types
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"


def _install_stubs():
    machine = types.ModuleType("machine")
    machine.PINS = []

    class FakePin:
        OUT = 1

        def __init__(self, pin, mode=None):
            self.pin = pin
            self.mode = mode
            self.values = []
            self._value = 0
            machine.PINS.append(self)

        def value(self, value=None):
            if value is not None:
                self._value = value
                self.values.append(value)
            return self._value

    machine.Pin = FakePin
    sys.modules["machine"] = machine

    common = types.ModuleType("Common")
    common.ENDPOINTS = {}
    common.TASKS = {}

    def web_endpoint(endpoint, callback, method="GET"):
        common.ENDPOINTS[(endpoint, method)] = callback
        return True

    common.web_endpoint = web_endpoint

    class DoneFlag:
        def __init__(self):
            self.value = False

        def is_set(self):
            return self.value

        def set(self):
            self.value = True

        def clear(self):
            self.value = False

    class FakeTask:
        def __init__(self, tag, coroutine=None):
            self.tag = tag
            self.coroutine = coroutine
            self.done = DoneFlag()
            self.out = ""
            self.feed_ms = []

        def __enter__(self):
            self.done.clear()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.done.set()

        async def feed(self, sleep_ms=1):
            self.feed_ms.append(sleep_ms)

    def micro_task(tag, task=None, _wrap=False):
        if _wrap:
            def decorator(async_fn):
                task_tag = "{}._{}".format(tag, async_fn.__name__)

                def launcher(*args, **kwargs):
                    coroutine = async_fn(task_tag, *args, **kwargs)
                    return micro_task(task_tag, task=coroutine)

                return launcher
            return decorator
        if task is not None:
            active = common.TASKS.get(tag)
            if active is not None and not active.done.is_set():
                return {tag: "Already running"}
            common.TASKS[tag] = FakeTask(tag, task)
            return {tag: "Starting"}
        return common.TASKS.get(tag)

    def manage_task(tag, operation):
        task = common.TASKS.get(tag)
        if operation == "kill" and task is not None:
            task.done.set()
            if task.coroutine is not None:
                task.coroutine.close()
            return True, "Kill: {}".format(tag)
        return False, "No task found: {}".format(tag)

    common.manage_task = manage_task
    common.micro_task = micro_task
    import tempfile as _tf
    _data_root = _tf.mkdtemp()
    common.data_dir = lambda f=None: os.path.join(_data_root, f) if f else _data_root
    sys.modules["Common"] = common

    types_mod = types.ModuleType("Types")
    types_mod.resolve = lambda value, **kwargs: value
    sys.modules["Types"] = types_mod

    micro_io = types.ModuleType("microIO")
    micro_io.BOUND = []
    micro_io.MAP = {}
    micro_io.DEFAULTS = {"aqua_pump": 26}
    micro_io.FAIL_BIND = None

    def bind_pin(tag, number=None):
        if micro_io.FAIL_BIND is not None:
            raise RuntimeError(micro_io.FAIL_BIND)
        micro_io.BOUND.append((tag, number))
        if number is None:
            return micro_io.MAP.get(tag, micro_io.DEFAULTS.get(tag))
        if not isinstance(number, int):
            raise RuntimeError("pin must be integer")
        micro_io.MAP[tag] = number
        return number

    def pinmap_search(keys):
        if isinstance(keys, str):
            keys = [keys]
        return {key: micro_io.MAP.get(key, micro_io.DEFAULTS.get(key)) for key in keys}

    micro_io.bind_pin = bind_pin
    micro_io.pinmap_search = pinmap_search
    sys.modules["microIO"] = micro_io


def _load_module():
    _install_stubs()
    for name in (
        "irrigation_system",
        "irrigation_system.actuators",
        "irrigation_system.monitoring",
        "irrigation_system.state_machine",
    ):
        sys.modules.pop(name, None)
    package = types.ModuleType("irrigation_system")
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules["irrigation_system"] = package
    spec = importlib.util.spec_from_file_location(
        "LM_aqua_under_test", str(PACKAGE_DIR / "LM_aqua.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["LM_aqua_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestAquaSkeleton(unittest.TestCase):
    def setUp(self):
        self.aqua = _load_module()

    def _install_distance_sensor(self, module_name, distance_cm):
        sensor = types.ModuleType(module_name)

        def measure_cm():
            sys.modules["microIO"].bind_pin("dist_trig", 32)
            sys.modules["microIO"].bind_pin("dist_echo", 35)
            return {"cm": distance_cm}

        sensor.measure_cm = measure_cm
        sys.modules[module_name] = sensor

    def tearDown(self):
        sys.modules.pop("LM_hcsr04", None)
        sys.modules.pop("LM_rcwl1670", None)
        sys.modules.pop("LM_aqua_under_test", None)
        sys.modules.pop("irrigation_system.actuators", None)
        sys.modules.pop("irrigation_system.monitoring", None)
        sys.modules.pop("irrigation_system", None)

    def test_help_keeps_public_commands_without_ui_annotations(self):
        entries = self.aqua.help()

        self.assertEqual(entries, (
            "load web=True pump_pin=None",
            "status",
            "tank",
            "flow",
            "pinmap",
            "soil",
            "sensor_distance module=None",
            "plan volume_l=1 per_head_l=None",
            "start volume_l=None per_head_l=None max_runtime_s=0",
            "BUTTON pause",
            "BUTTON resume",
            "BUTTON stop",
            "configure tank_width_cm=40 tank_depth_cm=25 tank_height_cm=20 water_distance_cm=7 min_level_cm=2 level_module=manual pump_l_hour=300 head_count=4 soil_sensor_count=4 pump_pin=3 checkpoint_interval_s=0 max_runtime_s=0 led_pin=6 led_count=1 led_brightness=100 led_blink_ms=400 btn_pin=45 btn_long_ms=1500 btn_debounce_ms=50",
            "set_level distance_cm=7 distance_mm=None measure=False module=None clear=False",
            "ready volume_l=None",
        ))
        for entry in entries:
            if entry in ("BUTTON pause", "BUTTON resume", "BUTTON stop"):
                continue
            self.assertNotIn(entry.split()[0], ("TEXTBOX", "STATUS", "BUTTON"))

    def test_default_status_has_tank_and_flow_math(self):
        data = self.aqua.status()

        self.assertEqual(data["endpoints"]["ui"], "/aqua")
        self.assertEqual(data["endpoints"]["api"], "/rest/aqua")
        self.assertEqual(data["endpoints"]["settings"], "/aqua/settings")
        self.assertNotIn("setting", data["endpoints"])
        self.assertNotIn("alias", data["endpoints"])
        self.assertEqual(data["config"]["level_module"], "manual")
        self.assertEqual(data["config"]["min_level_cm"], 2.0)
        self.assertEqual(data["level_sensor"]["source"], "manual")
        self.assertEqual(data["tank"]["capacity_l"], 20.0)
        self.assertEqual(data["tank"]["water_height_cm"], 13.0)
        self.assertEqual(data["tank"]["level_percent"], 65.0)
        self.assertEqual(data["tank"]["volume_l"], 13.0)
        self.assertEqual(data["tank"]["reserve_cm"], 2.0)
        self.assertEqual(data["tank"]["reserve_l"], 2.0)
        self.assertEqual(data["tank"]["usable_l"], 11.0)
        self.assertEqual(data["flow"]["head_count"], 4)
        self.assertEqual(data["flow"]["pump_l_hour"], 300.0)
        self.assertEqual(data["flow"]["head_l_hour"], 75.0)
        self.assertEqual(data["soil"]["count"], 4)
        self.assertEqual(data["soil"]["average_percent"], 49.0)
        self.assertEqual(len(data["soil"]["sensors"]), 4)
        self.assertTrue(data["ready"]["ok"])

    def test_configure_updates_dashboard_calculations(self):
        data = self.aqua.configure(
            tank_width_cm=50,
            tank_depth_cm=30,
            tank_height_cm=20,
            water_distance_cm=10,
            min_level_cm=4,
            pump_l_hour=300,
            head_count=6,
            soil_sensor_count=3,
        )

        self.assertEqual(data["tank"]["capacity_l"], 30.0)
        self.assertEqual(data["tank"]["water_height_cm"], 10.0)
        self.assertEqual(data["tank"]["level_percent"], 50.0)
        self.assertEqual(data["tank"]["volume_l"], 15.0)
        self.assertEqual(data["tank"]["reserve_cm"], 4.0)
        self.assertEqual(data["tank"]["reserve_l"], 6.0)
        self.assertEqual(data["tank"]["usable_l"], 9.0)
        self.assertEqual(data["flow"]["head_l_hour"], 50.0)
        self.assertEqual(data["config"]["head_count"], 6)
        self.assertEqual(data["level_sensor"]["source"], "manual_config")
        self.assertEqual(data["level_sensor"]["distance_cm"], 10)
        self.assertEqual(data["soil"]["count"], 3)
        self.assertEqual(data["soil"]["average_percent"], 46.7)

    def test_load_books_pump_pin_and_pinmap_reports_it(self):
        message = self.aqua.load(web=False, pump_pin=27)

        self.assertEqual(message, "Aqua irrigation system loaded. UI: /aqua API: /rest/aqua Settings: /aqua/settings")
        self.assertEqual(sys.modules["microIO"].BOUND, [("aqua_pump", 27)])
        self.assertEqual(self.aqua.pinmap(), {"aqua_pump": 27})
        self.assertEqual(self.aqua.status()["runtime"]["pump_pin"], 27)
        self.assertEqual(sys.modules["machine"].PINS[0].pin, 27)
        self.assertEqual(sys.modules["machine"].PINS[0].mode, sys.modules["machine"].Pin.OUT)
        self.assertEqual(sys.modules["machine"].PINS[0].values, [0])
        self.assertEqual(self.aqua.status()["runtime"]["pump_level"], 0)

    def test_load_without_pin_lets_bind_pin_resolve_tag(self):
        self.aqua.load(web=False)

        self.assertEqual(sys.modules["microIO"].BOUND, [("aqua_pump", None)])
        self.assertEqual(self.aqua.status()["runtime"]["pump_pin"], 26)
        self.assertEqual(sys.modules["machine"].PINS[0].pin, 26)

    def test_load_reinitializes_same_or_new_pump_pin(self):
        self.aqua.load(web=False, pump_pin=27)
        first_pin = sys.modules["machine"].PINS[-1]

        self.aqua.load(web=False, pump_pin=27)
        second_pin = sys.modules["machine"].PINS[-1]

        self.assertIsNot(first_pin, second_pin)
        self.assertEqual(sys.modules["microIO"].BOUND, [("aqua_pump", 27), ("aqua_pump", 27)])
        self.assertEqual(first_pin.values, [0, 0])
        self.assertEqual(second_pin.values, [0])
        self.assertFalse(self.aqua.status()["pump_on"])

        self.aqua.load(web=False, pump_pin=28)
        third_pin = sys.modules["machine"].PINS[-1]

        self.assertIsNot(second_pin, third_pin)
        self.assertEqual(third_pin.pin, 28)
        self.assertEqual(second_pin.values[-1], 0)
        self.assertEqual(self.aqua.status()["runtime"]["pump_pin"], 28)

    def test_load_bind_failure_fails_closed_and_later_retry_recovers(self):
        self.aqua.start()
        live_pin = sys.modules["machine"].PINS[-1]
        self.assertTrue(self.aqua.status()["pump_on"])
        self.assertEqual(live_pin.values[-1], 1)

        sys.modules["microIO"].FAIL_BIND = "pin busy"
        with self.assertRaises(RuntimeError):
            self.aqua.load(web=False, pump_pin=28)

        failed = self.aqua.status()
        self.assertFalse(failed["pump_on"])
        self.assertEqual(failed["runtime"]["pump_level"], 0)
        self.assertFalse(failed["runtime"]["pump_hw"])
        self.assertEqual(failed["runtime"]["last_action"], "load_failed")
        self.assertIn("pin busy", failed["runtime"]["pump_error"])
        self.assertEqual(live_pin.values[-1], 0)

        sys.modules["microIO"].FAIL_BIND = None
        self.aqua.load(web=False, pump_pin=28)
        recovered = self.aqua.status()

        self.assertFalse(recovered["pump_on"])
        self.assertTrue(recovered["runtime"]["pump_hw"])
        self.assertEqual(recovered["runtime"]["pump_pin"], 28)
        self.assertNotIn("pump_error", recovered["runtime"])

    def test_load_keeps_web_ui_available_when_pump_init_fails(self):
        sys.modules["microIO"].FAIL_BIND = "pin busy"

        message = self.aqua.load(pump_pin=28)
        data = self.aqua.status()

        self.assertIn("Pump init failed: pin busy", message)
        self.assertIn(("aqua", "GET"), sys.modules["Common"].ENDPOINTS)
        self.assertIn(("aqua/settings", "POST"), sys.modules["Common"].ENDPOINTS)
        self.assertFalse(data["runtime"]["pump_hw"])
        self.assertEqual(data["runtime"]["pump_pin"], 28)
        self.assertEqual(data["runtime"]["last_action"], "load_failed")

        sys.modules["microIO"].FAIL_BIND = None
        self.aqua.load(web=False, pump_pin=28)
        self.assertTrue(self.aqua.status()["runtime"]["pump_hw"])

    def test_settings_endpoint_retries_pump_init_with_saved_pin(self):
        self.aqua.load()
        callback = sys.modules["Common"].ENDPOINTS[("aqua/settings", "POST")]

        sys.modules["microIO"].FAIL_BIND = "pin busy"
        content_type, payload = callback({}, json.dumps({"config": {"pump_pin": 28}}).encode("utf-8"))
        failed = json.loads(payload)

        self.assertEqual(content_type, "application/json")
        self.assertEqual(failed["config"]["pump_pin"], 28)
        self.assertFalse(failed["runtime"]["pump_hw"])
        self.assertEqual(failed["runtime"]["last_action"], "configure_pump_failed")

        sys.modules["microIO"].FAIL_BIND = None
        content_type, payload = callback({}, json.dumps({"config": {"pump_pin": 28}}).encode("utf-8"))
        recovered = json.loads(payload)

        self.assertEqual(content_type, "application/json")
        self.assertEqual(recovered["runtime"]["pump_pin"], 28)
        self.assertTrue(recovered["runtime"]["pump_hw"])
        self.assertNotIn("pump_error", recovered["runtime"])

    def test_pinmap_reports_selected_water_level_distance_sensor_pins(self):
        expected = {
            "aqua_pump": 26,
            "dist_trig": 32,
            "dist_echo": 35,
        }
        for level_module, module_name, distance_cm in (
            ("hcsr04", "LM_hcsr04", 6),
            ("rcwl1670", "LM_rcwl1670", 8),
        ):
            with self.subTest(level_module=level_module):
                self._install_distance_sensor(module_name, distance_cm)
                self.aqua.configure(level_module=level_module)
                self.assertEqual(self.aqua.pinmap(), expected)

    def test_start_timed_sets_pump_and_state(self):
        result = self.aqua.start(per_head_l=0.25)

        self.assertTrue(result["state"])
        self.assertEqual(result["fsm_state"], "RUNNING")
        status = self.aqua.status()
        self.assertTrue(status["pump_on"])
        self.assertEqual(status["state"], "RUNNING")
        self.assertEqual(status["run"]["mode"], "timed")
        self.assertEqual(sys.modules["machine"].PINS[0].values[-1], 1)

        stopped = self.aqua.stop()
        self.assertTrue(stopped["state"])
        self.assertEqual(stopped["fsm_state"], "IDLE")
        self.assertFalse(self.aqua.status()["pump_on"])
        self.assertEqual(sys.modules["machine"].PINS[0].values[-1], 0)

    def test_start_manual_runs_until_stop(self):
        started = self.aqua.start()  # no volume -> manual, infinite
        self.assertTrue(started["state"])
        self.assertEqual(started["fsm_state"], "RUNNING")
        self.assertTrue(self.aqua.status()["pump_on"])
        self.assertEqual(self.aqua.status()["run"]["mode"], "manual")
        self.assertEqual(sys.modules["machine"].PINS[0].values[-1], 1)

        stopped = self.aqua.stop()
        self.assertEqual(stopped["fsm_state"], "IDLE")
        self.assertFalse(self.aqua.status()["pump_on"])
        self.assertEqual(sys.modules["machine"].PINS[0].values[-1], 0)

    def test_pause_resume_cycle(self):
        self.aqua.start(volume_l=1)
        paused = self.aqua.pause()
        self.assertTrue(paused["state"])
        self.assertEqual(paused["fsm_state"], "PAUSED")
        self.assertFalse(self.aqua.status()["pump_on"])

        resumed = self.aqua.resume()
        self.assertTrue(resumed["state"])
        self.assertEqual(resumed["fsm_state"], "RUNNING")
        self.assertTrue(self.aqua.status()["pump_on"])

        self.aqua.stop()

    def test_invalid_transition_rejected(self):
        # pause from IDLE is invalid
        res = self.aqua.pause()
        self.assertFalse(res["state"])
        self.assertEqual(res["error"], "invalid_transition")

    def test_low_tank_blocks_dummy_water(self):
        self.aqua.configure(water_distance_cm=19, min_level_cm=2)
        result = self.aqua.start(volume_l=1)

        self.assertFalse(result["state"])
        self.assertEqual(result["error"], "low_water")
        self.assertIn("tank_level_low", result["ready"]["problems"])

    def test_ultrasonic_measurement_updates_top_distance_when_selected(self):
        sensor = types.ModuleType("LM_rcwl1670")
        sensor.measure_cm = lambda: {"cm": 8}
        sys.modules["LM_rcwl1670"] = sensor

        data = self.aqua.configure(level_module="rcwl1670")

        self.assertEqual(data["tank"]["water_distance_cm"], 8)
        self.assertEqual(data["tank"]["water_height_cm"], 12)
        self.assertEqual(data["tank"]["level_percent"], 60.0)
        self.assertEqual(data["tank"]["volume_l"], 12.0)
        self.assertEqual(self.aqua.status()["runtime"]["last_level"]["module"], "LM_rcwl1670")

    def test_manual_distance_refresh_does_not_measure_without_sensor(self):
        sensor = types.ModuleType("LM_rcwl1670")
        sensor.measure_cm = lambda: {"cm": 5}
        sys.modules["LM_rcwl1670"] = sensor

        configured = self.aqua.configure(water_distance_cm=11)
        self.assertEqual(configured["tank"]["water_distance_cm"], 11)
        self.assertEqual(configured["tank"]["volume_l"], 9.0)
        self.assertEqual(configured["level_sensor"]["source"], "manual_config")
        self.assertEqual(configured["level_sensor"]["distance_cm"], 11)

        refreshed = self.aqua.status(measure=True)
        self.assertEqual(refreshed["tank"]["water_distance_cm"], 11)
        self.assertEqual(refreshed["tank"]["volume_l"], 9.0)
        self.assertEqual(refreshed["level_sensor"]["source"], "manual_config")

        measured = self.aqua.configure(level_module="rcwl1670")
        self.assertEqual(measured["tank"]["water_distance_cm"], 5)
        self.assertEqual(measured["tank"]["volume_l"], 15.0)
        self.assertEqual(measured["level_sensor"]["module"], "LM_rcwl1670")

    def test_real_sensor_mode_ignores_manual_distance_payload(self):
        sensor = types.ModuleType("LM_hcsr04")
        sensor.measure_cm = lambda: {"cm": 6}
        sys.modules["LM_hcsr04"] = sensor

        data = self.aqua.configure(level_module="hcsr04", water_distance_cm=11)

        self.assertEqual(data["tank"]["water_distance_cm"], 6)
        self.assertEqual(data["tank"]["volume_l"], 14.0)
        self.assertEqual(data["level_sensor"]["module"], "LM_hcsr04")

    def test_sensor_exception_reports_offline(self):
        sensor = types.ModuleType("LM_hcsr04")

        def fail():
            raise RuntimeError("no echo")

        sensor.measure_cm = fail
        sys.modules["LM_hcsr04"] = sensor

        data = self.aqua.configure(level_module="hcsr04")

        self.assertEqual(data["level_sensor"]["error"], "sensor_unavailable")
        self.assertEqual(data["level_sensor"]["module"], "LM_hcsr04")

    def test_disabled_level_module_keeps_manual_distance_on_refresh(self):
        sensor = types.ModuleType("LM_rcwl1670")
        sensor.measure_cm = lambda: {"cm": 5}
        sys.modules["LM_rcwl1670"] = sensor

        self.aqua.configure(level_module="manual", water_distance_cm=11)
        data = self.aqua.status(measure=True)

        self.assertEqual(data["tank"]["water_distance_cm"], 11)
        self.assertEqual(data["level_sensor"]["source"], "manual_config")

    def test_web_api_contract(self):
        self.aqua.load()
        endpoints = sys.modules["Common"].ENDPOINTS

        self.assertEqual(set(endpoints), {
            ("aqua", "GET"),
            ("aqua/settings", "GET"),
            ("aqua/settings", "POST"),
        })
        self.assertEqual(endpoints[("aqua", "GET")], "irrigation_system/aqua.html")
        self.assertNotIn(("aqua/ui", "GET"), endpoints)
        self.assertNotIn(("irrigation", "GET"), endpoints)
        self.assertNotIn(("aqua/api", "GET"), endpoints)
        self.assertNotIn(("aqua/api", "POST"), endpoints)
        self.assertNotIn(("irrigation/api", "GET"), endpoints)
        self.assertNotIn(("irrigation/api", "POST"), endpoints)

    def test_load_reregisters_web_endpoints_without_local_guard(self):
        self.aqua.load()
        first = dict(sys.modules["Common"].ENDPOINTS)

        self.aqua.load()

        self.assertEqual(sys.modules["Common"].ENDPOINTS, first)

    def test_settings_endpoint_syncs_config(self):
        self.aqua.load()
        endpoints = sys.modules["Common"].ENDPOINTS

        content_type, payload = endpoints[("aqua/settings", "GET")]({}, b"")
        data = json.loads(payload)

        self.assertEqual(content_type, "application/json")
        self.assertEqual(data["config"]["tank_width_cm"], 40.0)
        self.assertEqual(data["endpoints"]["settings"], "/aqua/settings")

        content_type, payload = endpoints[("aqua/settings", "POST")](
            {},
            json.dumps({
                "config": {
                    "tank_width_cm": 50,
                    "tank_depth_cm": 30,
                    "tank_height_cm": 20,
                    "water_distance_cm": 10,
                    "min_level_cm": 4,
                    "head_count": 6,
                },
            }).encode("utf-8"),
        )
        data = json.loads(payload)

        self.assertEqual(content_type, "application/json")
        self.assertEqual(data["config"]["tank_width_cm"], 50.0)
        self.assertEqual(data["config"]["min_level_cm"], 4.0)
        self.assertEqual(data["tank"]["capacity_l"], 30.0)
        self.assertEqual(data["tank"]["reserve_l"], 6.0)
        self.assertEqual(data["flow"]["head_count"], 6)

    def test_settings_endpoint_rejects_bad_payload(self):
        self.aqua.load()
        callback = sys.modules["Common"].ENDPOINTS[("aqua/settings", "POST")]

        content_type, payload = callback({}, b"{")
        data = json.loads(payload)

        self.assertEqual(content_type, "application/json")
        self.assertFalse(data["state"])
        self.assertEqual(data["error"], "invalid_json")

    def test_rest_command_targets_keep_api_contract(self):
        data = self.aqua.configure(
            tank_width_cm=40,
            tank_depth_cm=25,
            tank_height_cm=30,
            water_distance_cm=15,
            head_count=8,
            pump_l_hour=320,
            soil_sensor_count=5,
        )

        self.assertEqual(data["tank"]["capacity_l"], 30.0)
        self.assertEqual(data["tank"]["volume_l"], 15.0)
        self.assertEqual(data["flow"]["head_count"], 8)
        self.assertEqual(data["flow"]["head_l_hour"], 40.0)
        self.assertEqual(data["soil"]["count"], 5)


if __name__ == "__main__":
    unittest.main()
