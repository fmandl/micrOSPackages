"""
LM_alarm_system.py unit tests — runs on host CPython without hardware.

Run:
  cd /home/ealfnmo/smarthome/riaszto
  python3 -m pytest tests/test_alarm_system.py -v
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
_MODULE_NAME = "LM_alarm_system_under_test"


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

    # Ensure alarm_system package is importable
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


def _reset_module():
    """Reset module state between tests."""
    alarm._state = alarm.DISARMED
    alarm._arm_mode = None
    alarm._delay_task = None
    alarm._zones.clear()
    alarm._exit_delay = 30
    alarm._entry_delay = 15
    alarm._interval = 50
    alarm._max_log_entries = 100
    alarm._config_file = None
    alarm._state_file = None
    alarm._alarm_memory = []
    alarm._chime = False
    alarm._auto_arm_delay = None
    alarm._auto_arm_mode = 'full'
    alarm._auto_arm_task = None
    alarm._last_activity = 0
    alarm._bypassed = set()
    Notify.notify.reset_mock()


class TestStateMachine(unittest.TestCase):
    """Test state transitions."""

    def setUp(self):
        _reset_module()

    def test_initial_state_is_disarmed(self):
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_transition_updates_state(self):
        alarm._transition_to(alarm.ARMED)
        self.assertEqual(alarm._state, alarm.ARMED)

    def test_transition_notifies(self):
        alarm._transition_to(alarm.ARMED)
        # First call is state notification, subsequent calls are action hooks
        state_call = Notify.notify.call_args_list[0]
        payload = json.loads(state_call[0][0])
        self.assertEqual(payload['state'], 'ARMED')
        self.assertEqual(payload['prev'], 'DISARMED')

    def test_transition_topic(self):
        alarm._transition_to(alarm.ARMED)
        state_call = Notify.notify.call_args_list[0]
        self.assertEqual(state_call[1]['topic'], 'alarm/state')


class TestPersistence(unittest.TestCase):
    """Test state save/load."""

    def setUp(self):
        _reset_module()
        self.tmpfile = os.path.join(tempfile.gettempdir(), 'test_alarm_state.json')
        alarm._state_file = self.tmpfile
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_save_creates_file(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._save_state()
        self.assertTrue(os.path.exists(self.tmpfile))

    def test_save_load_roundtrip(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'night'
        alarm._save_state()
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.ARMED)
        self.assertEqual(mode, 'night')

    def test_load_missing_file_returns_disarmed(self):
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.DISARMED)
        self.assertIsNone(mode)

    def test_load_corrupt_file_returns_disarmed(self):
        with open(self.tmpfile, 'w') as f:
            f.write("not json")
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.DISARMED)
        self.assertIsNone(mode)

    def test_load_arming_becomes_armed(self):
        with open(self.tmpfile, 'w') as f:
            json.dump({'state': 'ARMING', 'arm_mode': 'full'}, f)
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.ARMED)

    def test_load_entry_delay_becomes_alarm(self):
        with open(self.tmpfile, 'w') as f:
            json.dump({'state': 'ENTRY_DELAY', 'arm_mode': 'full'}, f)
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.ALARM)

    def test_load_alarm_stays_alarm(self):
        with open(self.tmpfile, 'w') as f:
            json.dump({'state': 'ALARM', 'arm_mode': 'full'}, f)
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.ALARM)

    def test_load_invalid_state_returns_disarmed(self):
        with open(self.tmpfile, 'w') as f:
            json.dump({'state': 'BOGUS', 'arm_mode': 'full'}, f)
        state, mode = alarm._load_state()
        self.assertEqual(state, alarm.DISARMED)

    def test_transition_saves_state(self):
        alarm._state_file = self.tmpfile
        alarm._transition_to(alarm.ARMED)
        with open(self.tmpfile, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['state'], 'ARMED')


class TestArmDisarm(unittest.TestCase):
    """Test arm/disarm commands."""

    def setUp(self):
        _reset_module()

    def test_arm_from_disarmed(self):
        result = alarm.arm(mode='full')
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertEqual(alarm._arm_mode, 'full')
        self.assertIn('Arming', result)

    def test_arm_night_mode(self):
        alarm.arm(mode='night')
        self.assertEqual(alarm._arm_mode, 'night')

    def test_arm_refuses_when_not_disarmed(self):
        alarm._state = alarm.ARMED
        result = alarm.arm()
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('Cannot arm', result)

    def test_arm_refuses_with_open_zones(self):
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'triggered'}
        result = alarm.arm(mode='full')
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Cannot arm', result)
        self.assertIn('door', result)

    def test_arm_force_with_open_zones(self):
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'triggered'}
        result = alarm.arm(mode='full', force=True)
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertIn('bypassed', result)
        self.assertIn('door', result)

    def test_arm_refuses_with_open_tamper_even_force(self):
        alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'triggered'}
        result = alarm.arm(mode='full', force=True)
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Cannot arm', result)
        self.assertIn('tamper', result)

    def test_arm_refused_notifies(self):
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'triggered'}
        alarm.arm(mode='full')
        actions = [json.loads(c[0][0]) for c in Notify.notify.call_args_list
                   if c[1].get('topic') == 'alarm/action']
        self.assertTrue(any(a.get('action') == 'arm_refused' for a in actions))

    def test_arm_ok_when_open_zone_not_in_active_group(self):
        alarm._zones['motion'] = {'type': 'instant', 'group': 'interior', 'last_event': 'triggered'}
        result = alarm.arm(mode='night')  # interior not active in night
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertNotIn('Cannot', result)

    def test_arm_ok_when_zones_closed(self):
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        result = alarm.arm(mode='full')
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertNotIn('bypassed', result)

    def test_disarm_from_armed(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        result = alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIsNone(alarm._arm_mode)
        self.assertIn('Disarmed', result)

    def test_disarm_from_alarm(self):
        alarm._state = alarm.ALARM
        alarm._arm_mode = 'full'
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_from_entry_delay(self):
        alarm._state = alarm.ENTRY_DELAY
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_from_arming(self):
        alarm._state = alarm.ARMING
        alarm.disarm()
        self.assertEqual(alarm._state, alarm.DISARMED)


class TestZoneManagement(unittest.TestCase):
    """Test zone add/remove/list."""

    def setUp(self):
        _reset_module()

    def test_add_zone(self):
        result = alarm.add_zone('light', type='instant', group='interior')
        self.assertIn('light', alarm._zones)
        self.assertIn('added', result)

    def test_add_zone_defaults(self):
        alarm.add_zone('test')
        self.assertEqual(alarm._zones['test']['type'], 'instant')
        self.assertEqual(alarm._zones['test']['group'], 'perimeter')

    def test_add_zone_duplicate_refused(self):
        alarm.add_zone('light')
        result = alarm.add_zone('light')
        self.assertIn('already exists', result)

    def test_add_zone_invalid_type(self):
        result = alarm.add_zone('test', type='bogus')
        self.assertIn('Invalid type', result)
        self.assertNotIn('test', alarm._zones)

    def test_add_zone_invalid_group(self):
        result = alarm.add_zone('test', group='bogus')
        self.assertIn('Invalid group', result)
        self.assertNotIn('test', alarm._zones)

    def test_remove_zone(self):
        alarm.add_zone('light')
        result = alarm.remove_zone('light')
        self.assertNotIn('light', alarm._zones)
        self.assertIn('removed', result)

    def test_remove_nonexistent_zone(self):
        result = alarm.remove_zone('bogus')
        self.assertIn('not found', result)

    def test_remove_sensor_via_remove_zone_refused(self):
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'sensor': mock.MagicMock(), 'pin': 19}
        result = alarm.remove_zone('door')
        self.assertIn('local sensor', result)
        self.assertIn('door', alarm._zones)

    def test_list_zones(self):
        alarm.add_zone('light', type='instant', group='interior')
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'pin': 19, 'last_event': 'ok'}
        zones = alarm.list_zones()
        self.assertEqual(len(zones), 2)
        self.assertEqual(zones['light']['type'], 'instant')
        self.assertIsNone(zones['light']['pin'])
        self.assertEqual(zones['door']['pin'], 19)


class TestSensorManagement(unittest.TestCase):
    """Test add_sensor/remove_sensor."""

    def setUp(self):
        _reset_module()

    def test_add_sensor(self):
        result = alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')
        self.assertIn('door', alarm._zones)
        self.assertIn('added', result)
        self.assertEqual(alarm._zones['door']['pin'], 19)
        self.assertIsNotNone(alarm._zones['door'].get('sensor'))

    def test_add_sensor_duplicate_refused(self):
        alarm.add_sensor('door', pin=19)
        result = alarm.add_sensor('door', pin=20)
        self.assertIn('already exists', result)

    def test_add_sensor_invalid_type(self):
        result = alarm.add_sensor('door', pin=19, type='bogus')
        self.assertIn('Invalid type', result)

    def test_add_sensor_invalid_group(self):
        result = alarm.add_sensor('door', pin=19, group='bogus')
        self.assertIn('Invalid group', result)

    def test_remove_sensor(self):
        alarm.add_sensor('door', pin=19)
        result = alarm.remove_sensor('door')
        self.assertNotIn('door', alarm._zones)
        self.assertIn('removed', result)

    def test_remove_sensor_not_found(self):
        result = alarm.remove_sensor('bogus')
        self.assertIn('not found', result)

    def test_remove_zone_via_remove_sensor_refused(self):
        alarm.add_zone('light')
        result = alarm.remove_sensor('light')
        self.assertIn('remote zone', result)
        self.assertIn('light', alarm._zones)


class TestZoneTrigger(unittest.TestCase):
    """Test zone_trigger decision logic."""

    def setUp(self):
        _reset_module()
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['motion'] = {'type': 'instant', 'group': 'interior', 'last_event': 'ok'}
        alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'ok'}

    def test_trigger_when_disarmed_ignored(self):
        alarm._state = alarm.DISARMED
        result = alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Ignored', result)

    def test_trigger_24h_when_disarmed_silent_alert(self):
        alarm._state = alarm.DISARMED
        result = alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Silent alert', result)

    def test_trigger_24h_when_armed_alarm(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)

    def test_trigger_delayed_when_armed_entry_delay(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)

    def test_trigger_instant_when_armed_alarm(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('window', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)

    def test_trigger_interior_ignored_in_night_mode(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'night'
        result = alarm.zone_trigger('motion', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('not active', result)

    def test_trigger_perimeter_active_in_night_mode(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'night'
        alarm.zone_trigger('window', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)

    def test_trigger_reset_event_no_alarm(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        result = alarm.zone_trigger('door', 'reset')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('reset', result)

    def test_trigger_unknown_zone(self):
        result = alarm.zone_trigger('bogus', 'triggered')
        self.assertIn('Unknown zone', result)

    def test_trigger_stores_last_event(self):
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._zones['door']['last_event'], 'triggered')


class TestGroupActive(unittest.TestCase):
    """Test _is_group_active logic."""

    def setUp(self):
        _reset_module()

    def test_always_active_in_full(self):
        alarm._arm_mode = 'full'
        self.assertTrue(alarm._is_group_active('always'))

    def test_always_active_in_night(self):
        alarm._arm_mode = 'night'
        self.assertTrue(alarm._is_group_active('always'))

    def test_perimeter_active_in_full(self):
        alarm._arm_mode = 'full'
        self.assertTrue(alarm._is_group_active('perimeter'))

    def test_perimeter_active_in_night(self):
        alarm._arm_mode = 'night'
        self.assertTrue(alarm._is_group_active('perimeter'))

    def test_interior_active_in_full(self):
        alarm._arm_mode = 'full'
        self.assertTrue(alarm._is_group_active('interior'))

    def test_interior_not_active_in_night(self):
        alarm._arm_mode = 'night'
        self.assertFalse(alarm._is_group_active('interior'))

    def test_unknown_group_not_active(self):
        alarm._arm_mode = 'full'
        self.assertFalse(alarm._is_group_active('bogus'))


class TestStatus(unittest.TestCase):
    """Test status() output."""

    def setUp(self):
        _reset_module()

    def test_status_returns_state(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'night'
        s = alarm.status()
        self.assertEqual(s['state'], 'ARMED')
        self.assertEqual(s['arm_mode'], 'night')

    def test_status_shows_zones(self):
        alarm.add_zone('door', type='delayed', group='perimeter')
        s = alarm.status()
        self.assertIn('door', s['zones'])

    def test_status_shows_open_zones(self):
        alarm.add_zone('door', type='delayed', group='perimeter')
        alarm._zones['door']['last_event'] = 'triggered'
        s = alarm.status()
        self.assertIn('door', s['open_zones'])

    def test_status_no_open_zones(self):
        alarm.add_zone('door', type='delayed', group='perimeter')
        s = alarm.status()
        self.assertEqual(s['open_zones'], [])


class TestConfig(unittest.TestCase):
    """Test config save/load and show_config."""

    def setUp(self):
        _reset_module()
        self.tmpfile = os.path.join(tempfile.gettempdir(), 'test_alarm_config.json')
        alarm._config_file = self.tmpfile
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_save_config_creates_file(self):
        alarm.add_zone('light', type='instant', group='interior')
        self.assertTrue(os.path.exists(self.tmpfile))

    def test_save_load_roundtrip_zones(self):
        alarm.add_zone('light', type='instant', group='interior')
        cfg = alarm._load_config()
        self.assertEqual(len(cfg['zones']), 1)
        self.assertEqual(cfg['zones'][0]['name'], 'light')

    def test_save_load_roundtrip_sensors(self):
        alarm.add_sensor('door', pin=19, type='delayed', group='perimeter')
        cfg = alarm._load_config()
        self.assertEqual(len(cfg['sensors']), 1)
        self.assertEqual(cfg['sensors'][0]['pin'], 19)

    def test_save_preserves_settings(self):
        alarm._exit_delay = 45
        alarm._entry_delay = 20
        alarm._interval = 100
        alarm._save_config()
        cfg = alarm._load_config()
        self.assertEqual(cfg['exit_delay'], 45)
        self.assertEqual(cfg['entry_delay'], 20)
        self.assertEqual(cfg['interval'], 100)

    def test_show_config_returns_dict(self):
        alarm._save_config()
        result = alarm.show_config()
        self.assertIsInstance(result, dict)
        self.assertIn('exit_delay', result)

    def test_show_config_no_file(self):
        alarm._config_file = '/tmp/nonexistent_alarm_cfg.json'
        result = alarm.show_config()
        self.assertEqual(result, "No config file found.")


class TestUnload(unittest.TestCase):
    """Test unload."""

    def setUp(self):
        _reset_module()

    def test_unload_clears_zones(self):
        alarm.add_zone('door')
        alarm.unload()
        self.assertEqual(len(alarm._zones), 0)

    def test_unload_returns_message(self):
        result = alarm.unload()
        self.assertIn('stopped', result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestUnload(unittest.TestCase):
    """Test unload."""

    def setUp(self):
        _reset_module()

    def test_unload_clears_zones(self):
        alarm.add_zone('light')
        alarm.unload()
        self.assertEqual(len(alarm._zones), 0)

    def test_unload_returns_message(self):
        result = alarm.unload()
        self.assertIn('stopped', result)


class TestActionHooks(unittest.TestCase):
    """Test action dispatcher hooks are called on state transitions."""

    def setUp(self):
        _reset_module()

    def _get_action_payloads(self):
        """Extract action payloads from Notify calls."""
        actions = []
        for call in Notify.notify.call_args_list:
            if call[1].get('topic') == 'alarm/action':
                actions.append(json.loads(call[0][0]))
        return actions

    def test_arming_sends_buzzer_slow(self):
        alarm._transition_to(alarm.ARMING)
        actions = self._get_action_payloads()
        self.assertIn({"action": "buzzer_slow"}, actions)

    def test_armed_sends_buzzer_stop_and_led_red(self):
        alarm._transition_to(alarm.ARMED)
        actions = self._get_action_payloads()
        self.assertIn({"action": "buzzer_stop"}, actions)
        self.assertIn({"action": "led_red"}, actions)

    def test_entry_delay_sends_buzzer_fast(self):
        alarm._transition_to(alarm.ENTRY_DELAY)
        actions = self._get_action_payloads()
        self.assertIn({"action": "buzzer_fast"}, actions)

    def test_alarm_sends_siren_on(self):
        alarm._transition_to(alarm.ALARM)
        actions = self._get_action_payloads()
        self.assertIn({"action": "siren_on"}, actions)

    def test_disarmed_sends_all_stop_and_led_green(self):
        alarm._state = alarm.ARMED
        alarm._transition_to(alarm.DISARMED)
        actions = self._get_action_payloads()
        self.assertIn({"action": "all_stop"}, actions)
        self.assertIn({"action": "led_green"}, actions)

    def test_silent_alert_on_24h_zone_disarmed(self):
        alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'ok'}
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('tamper', 'triggered')
        actions = self._get_action_payloads()
        self.assertTrue(any('alert' in a for a in actions))


class TestAlarmMemory(unittest.TestCase):
    """Test alarm_memory tracking."""

    def setUp(self):
        _reset_module()
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'ok'}

    def test_memory_empty_initially(self):
        self.assertEqual(alarm.alarm_memory(), [])

    def test_instant_trigger_adds_to_memory(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('window', 'triggered')
        self.assertEqual(alarm.alarm_memory(), ['window'])

    def test_delayed_trigger_adds_to_memory(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        self.assertIn('door', alarm.alarm_memory())

    def test_24h_trigger_when_armed_adds_to_memory(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('tamper', 'triggered')
        self.assertIn('tamper', alarm.alarm_memory())

    def test_24h_trigger_when_disarmed_not_in_memory(self):
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm.alarm_memory(), [])

    def test_multiple_triggers_accumulate(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        # State is now ENTRY_DELAY, tamper (24h) still triggers
        alarm.zone_trigger('tamper', 'triggered')
        mem = alarm.alarm_memory()
        self.assertIn('door', mem)
        self.assertIn('tamper', mem)

    def test_arm_clears_memory(self):
        alarm._alarm_memory = ['door', 'window']
        alarm.arm(mode='full')
        self.assertEqual(alarm.alarm_memory(), [])

    def test_status_includes_memory(self):
        alarm._alarm_memory = ['door']
        s = alarm.status()
        self.assertEqual(s['alarm_memory'], ['door'])

    def test_disarm_does_not_clear_memory(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('window', 'triggered')
        alarm.disarm()
        self.assertEqual(alarm.alarm_memory(), ['window'])


class TestChimeMode(unittest.TestCase):
    """Test chime mode."""

    def setUp(self):
        _reset_module()
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}

    def test_chime_off_by_default(self):
        self.assertFalse(alarm._chime)

    def test_chime_on(self):
        result = alarm.chime('on')
        self.assertTrue(alarm._chime)
        self.assertIn('enabled', result)

    def test_chime_off(self):
        alarm._chime = True
        result = alarm.chime('off')
        self.assertFalse(alarm._chime)
        self.assertIn('disabled', result)

    def test_chime_query(self):
        alarm._chime = True
        result = alarm.chime()
        self.assertIn('on', result)

    def test_chime_invalid_state(self):
        result = alarm.chime('bogus')
        self.assertIn('Invalid', result)

    def test_chime_beeps_on_delayed_zone_disarmed(self):
        alarm._chime = True
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('door', 'triggered')
        actions = [json.loads(c[0][0]) for c in Notify.notify.call_args_list
                   if c[1].get('topic') == 'alarm/action']
        self.assertTrue(any(a.get('action') == 'chime' for a in actions))

    def test_chime_no_beep_on_instant_zone(self):
        alarm._chime = True
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('window', 'triggered')
        actions = [json.loads(c[0][0]) for c in Notify.notify.call_args_list
                   if c[1].get('topic') == 'alarm/action']
        self.assertFalse(any(a.get('action') == 'chime' for a in actions))

    def test_chime_no_beep_when_armed(self):
        alarm._chime = True
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('door', 'triggered')
        actions = [json.loads(c[0][0]) for c in Notify.notify.call_args_list
                   if c[1].get('topic') == 'alarm/action']
        self.assertFalse(any(a.get('action') == 'chime' for a in actions))

    def test_chime_no_beep_when_off(self):
        alarm._chime = False
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('door', 'triggered')
        actions = [json.loads(c[0][0]) for c in Notify.notify.call_args_list
                   if c[1].get('topic') == 'alarm/action']
        self.assertFalse(any(a.get('action') == 'chime' for a in actions))


class TestAutoArm(unittest.TestCase):
    """Test auto-arm feature."""

    def setUp(self):
        _reset_module()

    def test_auto_arm_enable(self):
        result = alarm.auto_arm(delay=3600, mode='night')
        self.assertEqual(alarm._auto_arm_delay, 3600)
        self.assertEqual(alarm._auto_arm_mode, 'night')
        self.assertIn('enabled', result)

    def test_auto_arm_disable_with_zero(self):
        alarm._auto_arm_delay = 3600
        result = alarm.auto_arm(delay=0)
        self.assertIsNone(alarm._auto_arm_delay)
        self.assertIn('disabled', result)

    def test_auto_arm_disable_with_none(self):
        alarm._auto_arm_delay = 3600
        result = alarm.auto_arm()
        self.assertIsNone(alarm._auto_arm_delay)
        self.assertIn('disabled', result)

    def test_reset_activity_updates_timestamp(self):
        alarm._auto_arm_delay = 3600
        alarm._state = alarm.DISARMED
        before = time.time()
        alarm._reset_activity()
        self.assertGreaterEqual(alarm._last_activity, before)

    def test_disarm_resets_activity(self):
        alarm._auto_arm_delay = 3600
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._last_activity = 0
        alarm.disarm()
        self.assertGreater(alarm._last_activity, 0)

    def test_zone_trigger_resets_activity_when_disarmed(self):
        alarm._auto_arm_delay = 3600
        alarm._state = alarm.DISARMED
        alarm._last_activity = 0
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        alarm.zone_trigger('door', 'triggered')
        self.assertGreater(alarm._last_activity, 0)

    def test_zone_trigger_no_reset_when_armed(self):
        alarm._auto_arm_delay = 3600
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._last_activity = 0
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
        alarm.zone_trigger('window', 'triggered')
        # Activity not reset when armed (state changes to ALARM)
        self.assertEqual(alarm._last_activity, 0)

    def test_auto_arm_starts_task_on_enable(self):
        alarm._state = alarm.DISARMED
        alarm.auto_arm(delay=60, mode='full')
        self.assertIsNotNone(alarm._auto_arm_task)

    def test_auto_arm_no_task_when_not_disarmed(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._auto_arm_delay = 60
        alarm._reset_activity()
        # Task not started because not DISARMED
        self.assertIsNone(alarm._auto_arm_task)


class TestZoneBypass(unittest.TestCase):
    """Test zone bypass feature."""

    def setUp(self):
        _reset_module()
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'ok'}

    def test_bypass_zone(self):
        result = alarm.bypass('window')
        self.assertIn('window', alarm._bypassed)
        self.assertIn('bypassed', result)

    def test_bypass_nonexistent_zone(self):
        result = alarm.bypass('bogus')
        self.assertIn('not found', result)

    def test_bypass_24h_refused(self):
        result = alarm.bypass('tamper')
        self.assertNotIn('tamper', alarm._bypassed)
        self.assertIn('Cannot', result)

    def test_bypassed_zone_ignored_when_armed(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._bypassed.add('window')
        result = alarm.zone_trigger('window', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('bypassed', result)

    def test_non_bypassed_zone_still_triggers(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._bypassed.add('window')
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(alarm._state, alarm.ENTRY_DELAY)

    def test_disarm_clears_bypass(self):
        alarm._bypassed.add('window')
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.disarm()
        self.assertEqual(alarm._bypassed, set())

    def test_unbypass(self):
        alarm._bypassed.add('window')
        result = alarm.unbypass('window')
        self.assertNotIn('window', alarm._bypassed)
        self.assertIn('unbypass', result)

    def test_unbypass_not_bypassed(self):
        result = alarm.unbypass('window')
        self.assertIn('not bypassed', result)

    def test_status_shows_bypassed(self):
        alarm._bypassed.add('window')
        s = alarm.status()
        self.assertIn('window', s['bypassed'])

    def test_24h_zone_not_affected_by_bypass(self):
        # 24h zones can't be bypassed, but verify trigger still works
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm.zone_trigger('tamper', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)


class TestCrossZone(unittest.TestCase):
    """Test cross-zone (dual trigger) feature."""

    def setUp(self):
        _reset_module()
        alarm._zones['motion_hall'] = {
            'type': 'cross', 'group': 'interior', 'last_event': 'ok',
            'cross_pair': 'motion_kitchen', 'cross_window': 30
        }
        alarm._zones['motion_kitchen'] = {
            'type': 'cross', 'group': 'interior', 'last_event': 'ok',
            'cross_pair': 'motion_hall', 'cross_window': 30
        }
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'

    def test_single_cross_zone_no_alarm(self):
        result = alarm.zone_trigger('motion_hall', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('waiting for pair', result)

    def test_both_cross_zones_within_window_alarm(self):
        alarm.zone_trigger('motion_hall', 'triggered')
        result = alarm.zone_trigger('motion_kitchen', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)
        self.assertIn('ALARM', result)
        self.assertIn('motion_hall', result)
        self.assertIn('motion_kitchen', result)

    def test_both_cross_zones_outside_window_no_alarm(self):
        alarm._zones['motion_hall']['last_trigger_time'] = time.time() - 60
        result = alarm.zone_trigger('motion_kitchen', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('waiting for pair', result)

    def test_cross_zone_adds_both_to_memory(self):
        alarm.zone_trigger('motion_hall', 'triggered')
        alarm.zone_trigger('motion_kitchen', 'triggered')
        mem = alarm.alarm_memory()
        self.assertIn('motion_hall', mem)
        self.assertIn('motion_kitchen', mem)

    def test_cross_zone_ignored_when_disarmed(self):
        alarm._state = alarm.DISARMED
        result = alarm.zone_trigger('motion_hall', 'triggered')
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('Ignored', result)

    def test_cross_zone_ignored_in_inactive_group(self):
        alarm._arm_mode = 'night'  # interior not active
        result = alarm.zone_trigger('motion_hall', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('not active', result)

    def test_cross_zone_bypassed(self):
        alarm._bypassed.add('motion_hall')
        result = alarm.zone_trigger('motion_hall', 'triggered')
        self.assertEqual(alarm._state, alarm.ARMED)
        self.assertIn('bypassed', result)

    def test_add_cross_zone(self):
        result = alarm.add_zone('pir1', type='cross', group='interior',
                                cross_pair='pir2', cross_window=20)
        self.assertIn('pir1', alarm._zones)
        self.assertEqual(alarm._zones['pir1']['cross_pair'], 'pir2')
        self.assertEqual(alarm._zones['pir1']['cross_window'], 20)
        self.assertIn('pair=pir2', result)

    def test_add_cross_zone_without_pair_refused(self):
        result = alarm.add_zone('pir1', type='cross', group='interior')
        self.assertNotIn('pir1', alarm._zones)
        self.assertIn('cross_pair', result)

    def test_reverse_trigger_order(self):
        alarm.zone_trigger('motion_kitchen', 'triggered')
        result = alarm.zone_trigger('motion_hall', 'triggered')
        self.assertEqual(alarm._state, alarm.ALARM)
        self.assertIn('ALARM', result)


class TestSupervision(unittest.TestCase):
    """Test sensor supervision (heartbeat)."""

    def setUp(self):
        _reset_module()
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
        alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok', 'pin': 19, 'sensor': mock.MagicMock()}

    def test_supervise_zone(self):
        result = alarm.supervise('window', timeout=300)
        self.assertEqual(alarm._zones['window']['supervision'], 300)
        self.assertIn('supervised', result)

    def test_supervise_nonexistent(self):
        result = alarm.supervise('bogus')
        self.assertIn('not found', result)

    def test_supervise_gpio_refused(self):
        result = alarm.supervise('door')
        self.assertIn('Cannot', result)
        self.assertNotIn('supervision', alarm._zones['door'])

    def test_unsupervise(self):
        alarm._zones['window']['supervision'] = 300
        result = alarm.unsupervise('window')
        self.assertNotIn('supervision', alarm._zones['window'])
        self.assertIn('removed', result)

    def test_zone_trigger_updates_last_seen(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = 0
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('window', 'triggered')
        self.assertGreater(alarm._zones['window']['last_seen'], 0)

    def test_trouble_when_timeout_exceeded(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = time.time() - 600
        trouble = alarm._get_trouble_zones()
        self.assertIn('window', trouble)

    def test_no_trouble_when_recent(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = time.time()
        trouble = alarm._get_trouble_zones()
        self.assertEqual(trouble, [])

    def test_arm_refused_with_trouble(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = time.time() - 600
        result = alarm.arm(mode='full')
        self.assertEqual(alarm._state, alarm.DISARMED)
        self.assertIn('trouble', result)

    def test_arm_force_with_trouble(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = time.time() - 600
        result = alarm.arm(mode='full', force=True)
        self.assertEqual(alarm._state, alarm.ARMING)

    def test_status_shows_trouble(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = time.time() - 600
        s = alarm.status()
        self.assertIn('window', s['trouble'])

    def test_reset_event_also_updates_last_seen(self):
        alarm._zones['window']['supervision'] = 300
        alarm._zones['window']['last_seen'] = 0
        alarm._state = alarm.DISARMED
        alarm.zone_trigger('window', 'reset')
        self.assertGreater(alarm._zones['window']['last_seen'], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
