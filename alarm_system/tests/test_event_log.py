"""
tests/test_event_log.py — Event log unit tests.

Run:
  cd /home/ealfnmo/smarthome/riaszto
  python3 -m pytest tests/test_event_log.py -v
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

# --- Stubs ---

def _install_stubs():
    if not hasattr(time, 'ticks_ms'):
        time.ticks_ms = lambda: int(time.time() * 1000)
        time.ticks_diff = lambda a, b: a - b

    if "machine" not in sys.modules:
        m = types.ModuleType("machine")

        class FakePin:
            IN = 0; OUT = 1; PULL_UP = 2; PULL_DOWN = 3
            IRQ_FALLING = 1; IRQ_RISING = 2
            def __init__(self, *a, **kw): self._value = 1
            def value(self, v=None):
                if v is not None: self._value = v
                return self._value
            def irq(self, **kw): pass

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
                if hasattr(task, 'close'): task.close()
                return {'tag': tag, 'state': 'created'}
            return FakeTaskCtx()

        stub.micro_task = mock.MagicMock(side_effect=_micro_task_side_effect)
        stub.data_dir = lambda f: os.path.join(tempfile.gettempdir(), f)
        sys.modules["Common"] = stub

    if "Notify" not in sys.modules:
        stub = types.ModuleType("Notify")
        stub.Notify = type("Notify", (), {"notify": staticmethod(mock.MagicMock())})
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


_install_stubs()

from alarm_system.event_log import init, log, get, clear, _log, _log_file


def _reset_log():
    """Reset event_log module state."""
    import alarm_system.event_log as el
    el._log = []
    el._max_entries = 100
    el._log_file = None


class TestEventLogInit(unittest.TestCase):
    """Test init and file loading."""

    def setUp(self):
        _reset_log()
        self.tmpfile = os.path.join(tempfile.gettempdir(), 'test_event_log.json')
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_init_sets_file(self):
        import alarm_system.event_log as el
        init(self.tmpfile, 50)
        self.assertEqual(el._log_file, self.tmpfile)
        self.assertEqual(el._max_entries, 50)

    def test_init_empty_when_no_file(self):
        init(self.tmpfile)
        self.assertEqual(get(), [])

    def test_init_loads_existing_file(self):
        entries = [{'ts': 1000, 'event': 'arm', 'data': {'mode': 'full'}}]
        with open(self.tmpfile, 'w') as f:
            json.dump(entries, f)
        init(self.tmpfile)
        result = get()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['event'], 'arm')

    def test_init_corrupt_file_returns_empty(self):
        with open(self.tmpfile, 'w') as f:
            f.write("not json")
        init(self.tmpfile)
        self.assertEqual(get(), [])

    def test_init_trims_to_max_entries(self):
        entries = [{'ts': i, 'event': 'test'} for i in range(200)]
        with open(self.tmpfile, 'w') as f:
            json.dump(entries, f)
        init(self.tmpfile, max_entries=50)
        self.assertEqual(len(get(999)), 50)


class TestEventLogWrite(unittest.TestCase):
    """Test log() writing."""

    def setUp(self):
        _reset_log()
        self.tmpfile = os.path.join(tempfile.gettempdir(), 'test_event_log.json')
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)
        init(self.tmpfile, 100)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_log_appends_entry(self):
        log('arm', {'mode': 'full'})
        entries = get()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['event'], 'arm')
        self.assertEqual(entries[0]['data'], {'mode': 'full'})

    def test_log_has_timestamp(self):
        before = int(time.time())
        log('disarm')
        after = int(time.time())
        ts = get()[0]['ts']
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)

    def test_log_without_data(self):
        log('system_start')
        entry = get()[0]
        self.assertEqual(entry['event'], 'system_start')
        self.assertNotIn('data', entry)

    def test_log_persists_to_file(self):
        log('alarm', {'zone': 'door'})
        with open(self.tmpfile, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['event'], 'alarm')

    def test_log_circular_buffer(self):
        _reset_log()
        init(self.tmpfile, max_entries=5)
        for i in range(10):
            log(f'event_{i}')
        entries = get(999)
        self.assertEqual(len(entries), 5)
        # Should keep last 5
        self.assertEqual(entries[0]['event'], 'event_5')
        self.assertEqual(entries[4]['event'], 'event_9')

    def test_log_multiple_entries(self):
        log('arm', {'mode': 'full'})
        log('zone_trigger', {'zone': 'door'})
        log('alarm', {'zone': 'door'})
        entries = get()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['event'], 'arm')
        self.assertEqual(entries[2]['event'], 'alarm')


class TestEventLogGet(unittest.TestCase):
    """Test get() retrieval."""

    def setUp(self):
        _reset_log()
        self.tmpfile = os.path.join(tempfile.gettempdir(), 'test_event_log.json')
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)
        init(self.tmpfile, 100)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_get_default_count(self):
        for i in range(30):
            log(f'event_{i}')
        entries = get()  # default 20
        self.assertEqual(len(entries), 20)
        # Should be last 20
        self.assertEqual(entries[0]['event'], 'event_10')

    def test_get_custom_count(self):
        for i in range(10):
            log(f'event_{i}')
        entries = get(count=5)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]['event'], 'event_5')

    def test_get_more_than_available(self):
        log('one')
        log('two')
        entries = get(count=50)
        self.assertEqual(len(entries), 2)

    def test_get_empty_log(self):
        self.assertEqual(get(), [])


class TestEventLogClear(unittest.TestCase):
    """Test clear()."""

    def setUp(self):
        _reset_log()
        self.tmpfile = os.path.join(tempfile.gettempdir(), 'test_event_log.json')
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)
        init(self.tmpfile, 100)

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.remove(self.tmpfile)

    def test_clear_empties_log(self):
        log('arm')
        log('disarm')
        clear()
        self.assertEqual(get(), [])

    def test_clear_persists_empty(self):
        log('arm')
        clear()
        with open(self.tmpfile, 'r') as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_clear_then_log_works(self):
        log('arm')
        clear()
        log('disarm')
        entries = get()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['event'], 'disarm')


class TestEventLogIntegration(unittest.TestCase):
    """Test event_log integration with LM_alarm_system."""

    def setUp(self):
        _reset_log()
        self.tmpdir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.tmpdir, 'alarm_config.json')
        self.state_file = os.path.join(self.tmpdir, 'alarm_state.json')
        self.log_file = os.path.join(self.tmpdir, 'alarm_log.json')

        # Patch data_dir to use tmpdir
        import Common
        Common.data_dir = lambda f: os.path.join(self.tmpdir, f)

        # Load LM module fresh
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "LM_alarm_test_log", str(PACKAGE_DIR / "LM_alarm_system.py"))
        self.alarm = importlib.util.module_from_spec(spec)
        sys.modules["LM_alarm_test_log"] = self.alarm
        spec.loader.exec_module(self.alarm)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        sys.modules.pop("LM_alarm_test_log", None)

    def _reset_alarm(self):
        self.alarm._state = self.alarm.DISARMED
        self.alarm._arm_mode = None
        self.alarm._delay_task = None
        self.alarm._zones.clear()
        self.alarm._config_file = self.config_file
        self.alarm._state_file = self.state_file

    def test_arm_logs_event(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        self.alarm.arm(mode='full')
        entries = el.get(999)
        arm_events = [e for e in entries if e['event'] == 'arm']
        self.assertEqual(len(arm_events), 1)
        self.assertEqual(arm_events[0]['data']['mode'], 'full')

    def test_disarm_logs_event(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        self.alarm._state = self.alarm.ARMED
        self.alarm._arm_mode = 'full'
        self.alarm.disarm()
        entries = el.get(999)
        disarm_events = [e for e in entries if e['event'] == 'disarm']
        self.assertEqual(len(disarm_events), 1)
        self.assertEqual(disarm_events[0]['data']['from_state'], 'ARMED')

    def test_zone_trigger_logs_alarm(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        self.alarm._state = self.alarm.ARMED
        self.alarm._arm_mode = 'full'
        self.alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
        self.alarm.zone_trigger('window', 'triggered')
        entries = el.get(999)
        alarm_events = [e for e in entries if e['event'] == 'alarm']
        self.assertEqual(len(alarm_events), 1)
        self.assertEqual(alarm_events[0]['data']['zone'], 'window')

    def test_zone_trigger_logs_entry_delay(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        self.alarm._state = self.alarm.ARMED
        self.alarm._arm_mode = 'full'
        self.alarm._zones['door'] = {'type': 'delayed', 'group': 'perimeter', 'last_event': 'ok'}
        self.alarm.zone_trigger('door', 'triggered')
        entries = el.get(999)
        zt_events = [e for e in entries if e['event'] == 'zone_trigger']
        self.assertEqual(len(zt_events), 1)
        self.assertEqual(zt_events[0]['data']['result'], 'entry_delay')

    def test_silent_alert_logged(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        self.alarm._state = self.alarm.DISARMED
        self.alarm._zones['tamper'] = {'type': '24h', 'group': 'always', 'last_event': 'ok'}
        self.alarm.zone_trigger('tamper', 'triggered')
        entries = el.get(999)
        sa_events = [e for e in entries if e['event'] == 'silent_alert']
        self.assertEqual(len(sa_events), 1)
        self.assertEqual(sa_events[0]['data']['zone'], 'tamper')

    def test_event_log_public_function(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        el.log('test_event', {'foo': 'bar'})
        result = self.alarm.event_log(count=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['event'], 'test_event')

    def test_clear_log_public_function(self):
        self._reset_alarm()
        import alarm_system.event_log as el
        el.init(self.log_file, 100)
        el.log('test_event')
        result = self.alarm.clear_log()
        self.assertIn('cleared', result)
        self.assertEqual(el.get(), [])

    def test_config_saves_max_log_entries(self):
        self._reset_alarm()
        self.alarm._max_log_entries = 200
        self.alarm._save_config()
        cfg = self.alarm._load_config()
        self.assertEqual(cfg['max_log_entries'], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
