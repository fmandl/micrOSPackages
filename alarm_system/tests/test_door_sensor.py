"""
alarm_system/door_sensor.py unit tests — runs on host CPython without hardware.

Run:
  cd /home/ealfnmo/smarthome/riaszto
  python3 -m pytest tests/test_door_sensor.py -v
"""

import unittest
import sys
import types
import time
import json
from unittest import mock
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package" / "alarm_system"
_MODULE_NAME = "door_sensor_under_test"


def _install_stubs():
    # Patch time module with MicroPython-specific functions
    if not hasattr(time, 'ticks_ms'):
        time.ticks_ms = lambda: int(time.time() * 1000)
        time.ticks_diff = lambda a, b: a - b

    if "machine" not in sys.modules:
        m = types.ModuleType("machine")

        class FakePin:
            IN = 0; OUT = 1; PULL_UP = 2; PULL_DOWN = 3
            IRQ_FALLING = 1; IRQ_RISING = 2
            def __init__(self, *a, **kw):
                self._value = 1
            def value(self, v=None):
                if v is not None:
                    self._value = v
                return self._value
            def irq(self, **kw):
                self._irq_handler = kw.get('handler')

        m.Pin = FakePin
        sys.modules["machine"] = m

    if "Common" not in sys.modules:
        stub = types.ModuleType("Common")
        stub.console = lambda *a, **kw: None
        stub.micro_task = mock.MagicMock()
        stub.data_dir = lambda f: f
        sys.modules["Common"] = stub

    if "Notify" not in sys.modules:
        stub = types.ModuleType("Notify")
        stub.Notify = type("Notify", (), {
            "notify": staticmethod(mock.MagicMock()),
        })
        sys.modules["Notify"] = stub

    if "microIO" not in sys.modules:
        stub = types.ModuleType("microIO")
        stub.bind_pin = lambda name, default: default
        stub.pinmap_search = lambda pins: {p: 0 for p in pins}
        sys.modules["microIO"] = stub


def _load_module():
    _install_stubs()
    import importlib.util
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, str(PACKAGE_DIR / "door_sensor.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


sensor = _load_module()
Notify = sys.modules["Notify"].Notify


def _make_input(name="door", initial_value=1, callback=None):
    """Create a DebouncedInput with controllable pin value."""
    inp = sensor.DebouncedInput.__new__(sensor.DebouncedInput)
    from machine import Pin
    inp.pin = Pin()
    inp.pin._value = initial_value
    inp.name = name
    inp.callback = callback
    inp.last_irq_time = 0
    inp.last_reported_state = initial_value
    inp.tentative_state = initial_value
    inp.tentative_time = 0
    inp.event = False
    return inp


class TestDebouncedInputInit(unittest.TestCase):
    """Test DebouncedInput initialization."""

    def test_initial_state_reads_pin(self):
        inp = _make_input(initial_value=1)
        self.assertEqual(inp.last_reported_state, 1)

    def test_initial_state_low(self):
        inp = _make_input(initial_value=0)
        self.assertEqual(inp.last_reported_state, 0)

    def test_event_starts_false(self):
        inp = _make_input()
        self.assertFalse(inp.event)

    def test_callback_stored(self):
        cb = mock.MagicMock()
        inp = _make_input(callback=cb)
        self.assertIs(inp.callback, cb)

    def test_callback_none_by_default(self):
        inp = _make_input()
        self.assertIsNone(inp.callback)


class TestIrqHandler(unittest.TestCase):
    """Test IRQ debounce logic."""

    def test_irq_sets_event(self):
        inp = _make_input()
        inp.last_irq_time = 0
        inp._irq_handler(inp.pin)
        self.assertTrue(inp.event)

    def test_irq_stores_tentative_state(self):
        inp = _make_input()
        inp.pin._value = 0
        inp._irq_handler(inp.pin)
        self.assertEqual(inp.tentative_state, 0)

    def test_irq_debounce_rejects_fast(self):
        inp = _make_input()
        inp.last_irq_time = time.ticks_ms()
        inp.event = False
        inp._irq_handler(inp.pin)
        self.assertFalse(inp.event)

    def test_irq_debounce_accepts_after_delay(self):
        inp = _make_input()
        inp.last_irq_time = time.ticks_ms() - sensor.DEBOUNCE_MS - 1
        inp._irq_handler(inp.pin)
        self.assertTrue(inp.event)


class TestProcessIfNeeded(unittest.TestCase):
    """Test event confirmation logic."""

    def setUp(self):
        Notify.notify.reset_mock()

    def test_no_event_does_nothing(self):
        inp = _make_input()
        inp.event = False
        inp.process_if_needed()
        Notify.notify.assert_not_called()

    def test_too_young_event_waits(self):
        inp = _make_input()
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms()
        inp.process_if_needed()
        self.assertTrue(inp.event)
        Notify.notify.assert_not_called()

    def test_confirmed_event_reports(self):
        inp = _make_input(initial_value=1)
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms() - sensor.CONFIRM_MS - 1
        inp.pin._value = 0
        inp.process_if_needed()
        self.assertFalse(inp.event)
        self.assertEqual(inp.last_reported_state, 0)
        Notify.notify.assert_called_once()

    def test_confirmed_event_no_change_no_report(self):
        inp = _make_input(initial_value=0)
        inp.last_reported_state = 0
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms() - sensor.CONFIRM_MS - 1
        inp.pin._value = 0
        inp.process_if_needed()
        self.assertFalse(inp.event)
        Notify.notify.assert_not_called()

    def test_bounced_back_event_discarded(self):
        inp = _make_input(initial_value=1)
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms() - sensor.CONFIRM_MS - 1
        inp.pin._value = 1
        inp.process_if_needed()
        self.assertFalse(inp.event)
        Notify.notify.assert_not_called()


class TestPoll(unittest.TestCase):
    """Test rescue polling logic."""

    def setUp(self):
        Notify.notify.reset_mock()

    def test_no_change_does_nothing(self):
        inp = _make_input(initial_value=1)
        inp.pin._value = 1
        inp.poll()
        Notify.notify.assert_not_called()

    def test_change_with_pending_event_confirms(self):
        inp = _make_input(initial_value=1)
        inp.pin._value = 0
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms() - sensor.CONFIRM_MS - 1
        inp.poll()
        self.assertEqual(inp.last_reported_state, 0)
        Notify.notify.assert_called_once()

    def test_change_with_young_event_waits(self):
        inp = _make_input(initial_value=1)
        inp.pin._value = 0
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms()
        inp.poll()
        self.assertEqual(inp.last_reported_state, 1)
        Notify.notify.assert_not_called()

    def test_rescue_reports_after_timeout(self):
        inp = _make_input(initial_value=1)
        inp.pin._value = 0
        inp.last_irq_time = time.ticks_ms() - sensor.RESCUE_MS - 1
        inp.event = False
        inp.poll()
        self.assertEqual(inp.last_reported_state, 0)
        Notify.notify.assert_called_once()

    def test_no_rescue_if_irq_recent(self):
        inp = _make_input(initial_value=1)
        inp.pin._value = 0
        inp.last_irq_time = time.ticks_ms()
        inp.event = False
        inp.poll()
        self.assertTrue(inp.event)
        self.assertEqual(inp.tentative_state, 0)
        Notify.notify.assert_not_called()

    def test_same_state_clears_event(self):
        inp = _make_input(initial_value=1)
        inp.pin._value = 1
        inp.event = True
        inp.tentative_state = 0
        inp.poll()
        self.assertFalse(inp.event)
        self.assertIsNone(inp.tentative_state)


class TestReportState(unittest.TestCase):
    """Test notification content and callback invocation."""

    def setUp(self):
        Notify.notify.reset_mock()

    def test_triggered_message(self):
        inp = _make_input(name="door")
        inp._report_state(0)
        payload = Notify.notify.call_args[0][0]
        self.assertEqual(json.loads(payload), {"door": "triggered"})

    def test_reset_message(self):
        inp = _make_input(name="door")
        inp._report_state(1)
        payload = Notify.notify.call_args[0][0]
        self.assertEqual(json.loads(payload), {"door": "reset"})

    def test_tamper_triggered(self):
        inp = _make_input(name="tamper")
        inp._report_state(0)
        payload = Notify.notify.call_args[0][0]
        self.assertEqual(json.loads(payload), {"tamper": "triggered"})

    def test_topic_is_alarm_sensor(self):
        inp = _make_input(name="door")
        inp._report_state(0)
        self.assertEqual(Notify.notify.call_args[1]['topic'], "alarm/sensor")

    def test_report_updates_last_reported_state(self):
        inp = _make_input(initial_value=1)
        inp._report_state(0)
        self.assertEqual(inp.last_reported_state, 0)

    def test_callback_called_on_triggered(self):
        cb = mock.MagicMock()
        inp = _make_input(name="door", callback=cb)
        inp._report_state(0)
        cb.assert_called_once_with("door", "triggered")

    def test_callback_called_on_reset(self):
        cb = mock.MagicMock()
        inp = _make_input(name="tamper", callback=cb)
        inp._report_state(1)
        cb.assert_called_once_with("tamper", "reset")

    def test_no_callback_no_error(self):
        inp = _make_input(callback=None)
        inp._report_state(0)  # should not raise

    def test_callback_called_from_process_if_needed(self):
        cb = mock.MagicMock()
        inp = _make_input(initial_value=1, callback=cb)
        inp.event = True
        inp.tentative_state = 0
        inp.tentative_time = time.ticks_ms() - sensor.CONFIRM_MS - 1
        inp.pin._value = 0
        inp.process_if_needed()
        cb.assert_called_once_with("door", "triggered")

    def test_callback_called_from_poll_rescue(self):
        cb = mock.MagicMock()
        inp = _make_input(initial_value=1, callback=cb)
        inp.pin._value = 0
        inp.last_irq_time = time.ticks_ms() - sensor.RESCUE_MS - 1
        inp.event = False
        inp.poll()
        cb.assert_called_once_with("door", "triggered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
