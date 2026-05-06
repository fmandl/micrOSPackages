"""
alarm_system/mqtt_watcher.py unit tests.

Run:
  cd /home/ealfnmo/smarthome/riaszto
  python3 -m pytest tests/test_mqtt_watcher.py -v
"""

import unittest
import sys
import types
import json
from unittest import mock
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package" / "alarm_system"


def _install_stubs():
    if "Common" not in sys.modules:
        stub = types.ModuleType("Common")
        stub.console = lambda *a, **kw: None
        stub.micro_task = mock.MagicMock()
        stub.data_dir = lambda f: f
        sys.modules["Common"] = stub

    if "LM_mqtt_client" not in sys.modules:
        stub = types.ModuleType("LM_mqtt_client")
        stub.subscribe = mock.MagicMock()
        stub.unsubscribe = mock.MagicMock()
        sys.modules["LM_mqtt_client"] = stub


def _load_module():
    _install_stubs()
    import importlib.util
    spec = importlib.util.spec_from_file_location("mqtt_watcher_test", str(PACKAGE_DIR / "mqtt_watcher.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mqtt_watcher_test"] = mod
    spec.loader.exec_module(mod)
    return mod


watcher = _load_module()
mqtt_stub = sys.modules["LM_mqtt_client"]


def _reset():
    watcher._watches.clear()
    watcher._zone_trigger_cb = None
    watcher._mqtt = mqtt_stub
    mqtt_stub.subscribe.reset_mock()
    mqtt_stub.unsubscribe.reset_mock()


class TestEvaluate(unittest.TestCase):
    """Test payload evaluation logic."""

    def test_raw_string_trigger(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_value': 'open'}
        self.assertEqual(watcher._evaluate(watch, 'open'), 'triggered')

    def test_raw_string_reset(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_value': 'open', 'reset_value': 'closed'}
        self.assertEqual(watcher._evaluate(watch, 'closed'), 'reset')

    def test_raw_string_no_match(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_value': 'open'}
        self.assertIsNone(watcher._evaluate(watch, 'something'))

    def test_json_field_trigger(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_field': 'contact', 'trigger_value': False}
        payload = json.dumps({"contact": False, "battery": 100})
        self.assertEqual(watcher._evaluate(watch, payload), 'triggered')

    def test_json_field_reset(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_field': 'contact',
                 'trigger_value': False, 'reset_value': True}
        payload = json.dumps({"contact": True, "battery": 100})
        self.assertEqual(watcher._evaluate(watch, payload), 'reset')

    def test_json_field_no_match(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_field': 'contact', 'trigger_value': False}
        payload = json.dumps({"contact": True})
        self.assertIsNone(watcher._evaluate(watch, payload))

    def test_json_field_missing(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_field': 'smoke', 'trigger_value': True}
        payload = json.dumps({"contact": False})
        self.assertIsNone(watcher._evaluate(watch, payload))

    def test_bool_trigger_value(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_field': 'tamper', 'trigger_value': True}
        payload = json.dumps({"tamper": True})
        self.assertEqual(watcher._evaluate(watch, payload), 'triggered')

    def test_raw_json_bool(self):
        """Raw payload that is a JSON bool."""
        watch = {'topic': 't', 'zone': 'z', 'trigger_value': True}
        self.assertEqual(watcher._evaluate(watch, 'true'), 'triggered')

    def test_invalid_json_falls_back_to_string(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_value': 'ON'}
        self.assertEqual(watcher._evaluate(watch, 'ON'), 'triggered')

    def test_malformed_json_with_field_returns_none(self):
        watch = {'topic': 't', 'zone': 'z', 'trigger_field': 'x', 'trigger_value': True}
        self.assertIsNone(watcher._evaluate(watch, 'not json'))


class TestOnMessage(unittest.TestCase):
    """Test message dispatch to zone_trigger."""

    def setUp(self):
        _reset()
        self.cb = mock.MagicMock()
        watcher._zone_trigger_cb = self.cb

    def test_matching_topic_triggers(self):
        watcher._watches.append({'topic': 'home/door', 'zone': 'door',
                                  'trigger_value': 'open'})
        watcher._on_message('home/door', 'open')
        self.cb.assert_called_once_with('door', 'triggered')

    def test_non_matching_topic_ignored(self):
        watcher._watches.append({'topic': 'home/door', 'zone': 'door',
                                  'trigger_value': 'open'})
        watcher._on_message('home/window', 'open')
        self.cb.assert_not_called()

    def test_multiple_watches_same_topic(self):
        watcher._watches.append({'topic': 'zigbee/sensor', 'zone': 'window',
                                  'trigger_field': 'contact', 'trigger_value': False})
        watcher._watches.append({'topic': 'zigbee/sensor', 'zone': 'tamper',
                                  'trigger_field': 'tamper', 'trigger_value': True})
        payload = json.dumps({"contact": False, "tamper": False})
        watcher._on_message('zigbee/sensor', payload)
        # Only contact matches, tamper doesn't
        self.cb.assert_called_once_with('window', 'triggered')

    def test_both_watches_trigger(self):
        watcher._watches.append({'topic': 'zigbee/sensor', 'zone': 'window',
                                  'trigger_field': 'contact', 'trigger_value': False})
        watcher._watches.append({'topic': 'zigbee/sensor', 'zone': 'tamper',
                                  'trigger_field': 'tamper', 'trigger_value': True})
        payload = json.dumps({"contact": False, "tamper": True})
        watcher._on_message('zigbee/sensor', payload)
        self.assertEqual(self.cb.call_count, 2)
        calls = [c[0] for c in self.cb.call_args_list]
        self.assertIn(('window', 'triggered'), calls)
        self.assertIn(('tamper', 'triggered'), calls)

    def test_no_callback_no_error(self):
        watcher._zone_trigger_cb = None
        watcher._watches.append({'topic': 'x', 'zone': 'z', 'trigger_value': 'y'})
        watcher._on_message('x', 'y')  # should not raise


class TestAddRemoveWatch(unittest.TestCase):
    """Test add/remove watch operations."""

    def setUp(self):
        _reset()
        watcher._zone_trigger_cb = mock.MagicMock()

    def test_add_watch(self):
        result = watcher.add_watch('home/door', 'door', 'open', 'closed')
        self.assertEqual(len(watcher._watches), 1)
        self.assertIn('added', result)

    def test_add_watch_subscribes(self):
        watcher.add_watch('home/door', 'door', 'open')
        mqtt_stub.subscribe.assert_called_once()

    def test_remove_watch(self):
        watcher.add_watch('home/door', 'door', 'open')
        result = watcher.remove_watch('home/door')
        self.assertEqual(len(watcher._watches), 0)
        self.assertIn('Removed', result)

    def test_remove_watch_unsubscribes(self):
        watcher.add_watch('home/door', 'door', 'open')
        watcher.remove_watch('home/door')
        mqtt_stub.unsubscribe.assert_called_once_with('home/door')

    def test_remove_nonexistent(self):
        result = watcher.remove_watch('bogus')
        self.assertIn('No watches', result)

    def test_list_watches(self):
        watcher.add_watch('home/door', 'door', 'open', 'closed')
        watcher.add_watch('home/window', 'window', 'open')
        watches = watcher.list_watches()
        self.assertEqual(len(watches), 2)

    def test_remove_only_matching_topic(self):
        watcher.add_watch('home/door', 'door', 'open')
        watcher.add_watch('home/window', 'window', 'open')
        watcher.remove_watch('home/door')
        self.assertEqual(len(watcher._watches), 1)
        self.assertEqual(watcher._watches[0]['zone'], 'window')


class TestLoadWatches(unittest.TestCase):
    """Test loading watches from config."""

    def setUp(self):
        _reset()
        watcher._zone_trigger_cb = mock.MagicMock()

    def test_load_watches_from_config(self):
        config = [
            {'topic': 'home/door', 'zone': 'door', 'trigger_value': 'open', 'reset_value': 'closed'},
            {'topic': 'home/window', 'zone': 'window', 'trigger_value': 'open'}
        ]
        watcher.load_watches(config)
        self.assertEqual(len(watcher._watches), 2)

    def test_load_watches_subscribes(self):
        config = [
            {'topic': 'home/door', 'zone': 'door', 'trigger_value': 'open'},
            {'topic': 'home/window', 'zone': 'window', 'trigger_value': 'open'}
        ]
        watcher.load_watches(config)
        self.assertEqual(mqtt_stub.subscribe.call_count, 2)

    def test_load_watches_deduplicates_subscribe(self):
        """Same topic twice should only subscribe once."""
        config = [
            {'topic': 'zigbee/sensor', 'zone': 'window', 'trigger_field': 'contact', 'trigger_value': False},
            {'topic': 'zigbee/sensor', 'zone': 'tamper', 'trigger_field': 'tamper', 'trigger_value': True}
        ]
        watcher.load_watches(config)
        # Only one subscribe call for the same topic
        mqtt_stub.subscribe.assert_called_once()


class TestUnload(unittest.TestCase):
    """Test unload clears everything."""

    def setUp(self):
        _reset()
        watcher._zone_trigger_cb = mock.MagicMock()

    def test_unload_clears_watches(self):
        watcher.add_watch('home/door', 'door', 'open')
        watcher.unload()
        self.assertEqual(len(watcher._watches), 0)

    def test_unload_unsubscribes(self):
        watcher.add_watch('home/door', 'door', 'open')
        mqtt_stub.unsubscribe.reset_mock()
        watcher.unload()
        mqtt_stub.unsubscribe.assert_called_once_with('home/door')


class TestGetWatchesConfig(unittest.TestCase):
    """Test config export."""

    def setUp(self):
        _reset()
        watcher._zone_trigger_cb = mock.MagicMock()

    def test_export_format(self):
        watcher.add_watch('home/door', 'door', 'open', 'closed', trigger_field=None)
        cfg = watcher.get_watches_config()
        self.assertEqual(len(cfg), 1)
        self.assertEqual(cfg[0]['topic'], 'home/door')
        self.assertEqual(cfg[0]['zone'], 'door')
        self.assertEqual(cfg[0]['trigger_value'], 'open')
        self.assertEqual(cfg[0]['reset_value'], 'closed')

    def test_export_without_reset(self):
        watcher.add_watch('home/light', 'light', 'ON')
        cfg = watcher.get_watches_config()
        self.assertNotIn('reset_value', cfg[0])

    def test_export_with_field(self):
        watcher.add_watch('zigbee/s', 'z', False, True, trigger_field='contact')
        cfg = watcher.get_watches_config()
        self.assertEqual(cfg[0]['trigger_field'], 'contact')


if __name__ == "__main__":
    unittest.main(verbosity=2)
