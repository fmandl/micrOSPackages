"""
Integration tests — full flow: sensor detection → zone_trigger → state machine → actions.

Run:
  cd /home/ealfnmo/smarthome/riaszto
  python3 -m pytest tests/test_integration.py -v
"""

import unittest
import sys
import types
import time
import json
import os
import tempfile
from unittest import mock
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"
_MODULE_NAME = "LM_alarm_system_integration"


def _install_stubs():
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
                pass

        m.Pin = FakePin
        sys.modules["machine"] = m

    if "Common" not in sys.modules:
        stub = types.ModuleType("Common")
        stub.console = lambda *a, **kw: None

        class FakeTaskCtx:
            async def feed(self, sleep_ms=0): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def _micro_task_side_effect(tag=None, task=None, _wrap=False):
            if task is not None:
                if hasattr(task, 'close'):
                    task.close()
                return {'tag': tag, 'state': 'created'}
            return FakeTaskCtx()

        stub.micro_task = mock.MagicMock(side_effect=_micro_task_side_effect)
        stub.data_dir = lambda f: os.path.join(tempfile.gettempdir(), f)
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

    if "Types" not in sys.modules:
        stub = types.ModuleType("Types")
        stub.resolve = lambda t, **kw: t
        sys.modules["Types"] = stub

    if str(PACKAGE_DIR) not in sys.path:
        sys.path.insert(0, str(PACKAGE_DIR))


def _load_module():
    _install_stubs()
    import importlib.util
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, str(PACKAGE_DIR / "LM_alarm_system.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


alarm = _load_module()
Notify = sys.modules["Notify"].Notify


def _reset():
    alarm._state = alarm.DISARMED
    alarm._arm_mode = None
    alarm._delay_task = None
    alarm._zones.clear()
    alarm._exit_delay = 30
    alarm._entry_delay = 15
    alarm._interval = 50
    alarm._config_file = None
    alarm._state_file = None
    Notify.notify.reset_mock()


def _get_actions():
    """Extract action payloads from Notify calls."""
    return [json.loads(c[0][0]) for c in Notify.notify.call_args_list
            if c[1].get('topic') == 'alarm/action']


def _get_state_notifications():
    """Extract state change notifications."""
    return [json.loads(c[0][0]) for c in Notify.notify.call_args_list
            if c[1].get('topic') == 'alarm/state']


def _get_sensor_notifications():
    """Extract sensor notifications."""
    return [json.loads(c[0][0]) for c in Notify.notify.call_args_list
            if c[1].get('topic') == 'alarm/sensor']


class TestFullArmDisarmCycle(unittest.TestCase):
    """Test complete arm → armed → disarm cycle."""

    def setUp(self):
        _reset()
        alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')
        alarm.add_sensor('tamper', pin=20, type='24h', group='always')

    def test_arm_full_cycle(self):
        # Arm
        result = alarm.arm(mode='full')
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertIn('Arming', result)

        # Simulate exit delay expiry
        alarm._transition_to(alarm.ARMED)
        self.assertEqual(alarm._state, alarm.ARMED)

        # Disarm
        result = alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Disarmed', result)

    def test_arm_produces_correct_action_sequence(self):
        alarm.arm(mode='full')
        actions = _get_actions()
        self.assertIn({"action": "buzzer_slow"}, actions)

        Notify.notify.reset_mock()
        alarm._transition_to(alarm.ARMED)
        actions = _get_actions()
        self.assertIn({"action": "buzzer_stop"}, actions)
        self.assertIn({"action": "led_red"}, actions)

        Notify.notify.reset_mock()
        alarm.disarm()
        actions = _get_actions()
        self.assertIn({"action": "all_stop"}, actions)
        self.assertIn({"action": "led_green"}, actions)


class TestDoorTriggerWhileArmed(unittest.TestCase):
    """Test door opens while armed → entry delay → alarm."""

    def setUp(self):
        _reset()
        alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')

    def test_door_trigger_starts_entry_delay(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)

    def test_door_trigger_sends_buzzer_fast(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        actions = _get_actions()
        self.assertIn({"action": "buzzer_fast"}, actions)

    def test_disarm_during_entry_delay(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)

        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)
        actions = _get_actions()
        self.assertIn({"action": "all_stop"}, actions)

    def test_entry_delay_expires_to_alarm(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)

        # Simulate entry delay expiry
        alarm._transition_to(alarm.ALARM)
        self.assertEqual(alarm._state, alarm.ALARM)
        actions = _get_actions()
        self.assertIn({"action": "siren_on"}, actions)


class TestInstantZoneTrigger(unittest.TestCase):
    """Test instant zone triggers immediate alarm."""

    def setUp(self):
        _reset()
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}

    def test_instant_zone_immediate_alarm(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('window', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)

    def test_instant_zone_sends_siren(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('window', 'triggered')
        actions = _get_actions()
        self.assertIn({"action": "siren_on"}, actions)


class TestTamperAlwaysTriggers(unittest.TestCase):
    """Test tamper (24h zone) triggers in any state."""

    def setUp(self):
        _reset()
        alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'ok'}

    def test_tamper_while_armed(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)

    def test_tamper_while_disarmed_silent(self):
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm._state, alarm.DISARMED)  # no state change
        actions = _get_actions()
        self.assertTrue(any('alert' in a for a in actions))

    def test_tamper_while_entry_delay(self):
        alarm._state = alarm.ENTRY_DELAY
        alarm._arm_mode = 'full'
        alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)


class TestNightModeIgnoresInterior(unittest.TestCase):
    """Test night mode ignores interior zones."""

    def setUp(self):
        _reset()
        alarm._zones['motion'] = {'type': 'instant', 'group': 'interior', 'last_event': 'ok'}
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}

    def test_interior_ignored_in_night(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'night'
        result = alarm.zone_trigger('motion', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('not active', result)

    def test_perimeter_active_in_night(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'night'
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)


class TestSensorCallbackIntegration(unittest.TestCase):
    """Test that DebouncedInput callback triggers zone_trigger correctly."""

    def setUp(self):
        _reset()

    def test_sensor_callback_triggers_zone(self):
        alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'

        # Simulate what DebouncedInput does on state change
        sensor = alarm._zones['door']['sensor']
        sensor.callback('door', 'triggered')

        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)

    def test_sensor_callback_publishes_and_triggers(self):
        alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'

        sensor = alarm._zones['door']['sensor']
        # Simulate _report_state which does both Notify and callback
        sensor._report_state(0)

        # Should have sensor notification
        sensor_notifs = _get_sensor_notifications()
        self.assertTrue(any(n.get('door') == 'triggered' for n in sensor_notifs))

        # Should have triggered entry delay
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)


class TestForceArmIntegration(unittest.TestCase):
    """Test force arm with open zones in full flow."""

    def setUp(self):
        _reset()
        alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')

    def test_cannot_arm_with_open_door(self):
        alarm._zones['door']['last_event'] = 'triggered'
        result = alarm.arm(mode='full')
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Cannot arm', result)

    def test_force_arm_with_open_door(self):
        alarm._zones['door']['last_event'] = 'triggered'
        result = alarm.arm(mode='full', force=True)
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertIn('bypassed', result)

    def test_force_arm_then_door_still_triggers(self):
        """Even after force arm, the open door should trigger when armed."""
        alarm._zones['door']['last_event'] = 'triggered'
        alarm.arm(mode='full', force=True)
        alarm._transition_to(alarm.ARMED)  # simulate exit delay expiry

        # Door is still triggered → zone_trigger
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)


class TestStateNotifications(unittest.TestCase):
    """Test that state transitions produce correct MQTT notifications."""

    def setUp(self):
        _reset()

    def test_full_cycle_state_notifications(self):
        alarm.arm(mode='full')
        alarm._transition_to(alarm.ARMED)
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        alarm._transition_to(alarm.ALARM)
        alarm.disarm()

        states = _get_state_notifications()
        state_sequence = [s['state'] for s in states]
        self.assertIn('ARMING', state_sequence)
        self.assertIn('ARMED', state_sequence)
        self.assertIn('ENTRY_DELAY', state_sequence)
        self.assertIn('ALARM', state_sequence)
        self.assertIn('DISARMED', state_sequence)


class TestDisarmFromAnyState(unittest.TestCase):
    """Test disarm works from any state."""

    def setUp(self):
        _reset()

    def test_disarm_from_arming(self):
        alarm._state = alarm.ARMING
        alarm._arm_mode = 'full'
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_from_armed(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_from_entry_delay(self):
        alarm._state = alarm.ENTRY_DELAY
        alarm._arm_mode = 'full'
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_from_alarm(self):
        alarm._state = alarm.ALARM
        alarm._arm_mode = 'full'
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_always_sends_all_stop(self):
        alarm._state = alarm.ALARM
        alarm._arm_mode = 'full'
        alarm.disarm()
        actions = _get_actions()
        self.assertIn({"action": "all_stop"}, actions)


if __name__ == "__main__":
    unittest.main(verbosity=2)
