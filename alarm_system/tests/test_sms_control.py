"""
tests/test_sms_control.py — SMS control integration tests.

Run:
  cd alarm_system
  python3 -m pytest tests/test_sms_control.py -v
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

    # Stub LM_users with multi-book support
    if "LM_users" not in sys.modules:
        users_stub = types.ModuleType("LM_users")
        users_stub._books = {}

        def _load(json_file='users.json', book='default'):
            users_stub._books[book] = []
            return f"UserManagement '{book}' started."

        def _add_user(phone, name, status='A', role='user', book='default', **kw):
            users_stub._books.setdefault(book, []).append(
                {'phone': phone, 'name': name, 'status': status, 'role': role})
            return f"User {name} added."

        def _get_user(phone=None, book='default', **kw):
            for u in users_stub._books.get(book, []):
                if phone and u['phone'] == phone:
                    return [u]
            return None

        def _get_all_users(book='default'):
            return users_stub._books.get(book, [])

        def _check_access(phone, book='default'):
            return False  # default: access OK

        users_stub.load = _load
        users_stub.add_user = _add_user
        users_stub.get_user = _get_user
        users_stub.get_all_users = _get_all_users
        users_stub.check_access = _check_access
        sys.modules["LM_users"] = users_stub

    # Stub LM_sim800
    if "LM_sim800" not in sys.modules:
        sim_stub = types.ModuleType("LM_sim800")
        sim_stub.subscribe = mock.MagicMock()
        sim_stub.unsubscribe = mock.MagicMock()
        sim_stub.send_sms = mock.MagicMock()
        sys.modules["LM_sim800"] = sim_stub

    if str(PACKAGE_DIR) not in sys.path:
        sys.path.insert(0, str(PACKAGE_DIR))


def _load_module():
    _install_stubs()
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "LM_alarm_sms_test", str(PACKAGE_DIR / "LM_alarm_system.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["LM_alarm_sms_test"] = mod
    spec.loader.exec_module(mod)
    return mod


alarm = _load_module()
sim = sys.modules["LM_sim800"]
users = sys.modules["LM_users"]
Notify = sys.modules["Notify"].Notify

# Init SMS handler with alarm module reference
from alarm_system.sms_handler import init as sms_init, handle_sms
sms_init(alarm)


def _reset():
    alarm._state = alarm.DISARMED
    alarm._arm_mode = None
    alarm._delay_task = None
    alarm._zones.clear()
    alarm._exit_delay = 30
    alarm._entry_delay = 15
    alarm._alarm_memory = []
    alarm._bypassed = set()
    alarm._chime = False
    alarm._auto_arm_delay = None
    alarm._auto_arm_task = None
    alarm._last_activity = 0
    alarm._config_file = None
    alarm._state_file = None
    users._books = {'alarm': [
        {'phone': '+36201111111', 'name': 'Admin', 'status': 'A', 'role': 'admin'},
        {'phone': '+36202222222', 'name': 'User', 'status': 'A', 'role': 'user'},
        {'phone': '+36203333333', 'name': 'Blocked', 'status': 'B', 'role': 'user'},
    ]}
    sim.send_sms.reset_mock()
    Notify.notify.reset_mock()


class TestSmsArm(unittest.TestCase):
    """Test SMS arm commands."""

    def setUp(self):
        _reset()

    def test_admin_arm_full(self):
        handle_sms({'sender': '+36201111111', 'text': 'arm full'})
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertEqual(alarm._arm_mode, 'full')

    def test_admin_arm_short(self):
        handle_sms({'sender': '+36201111111', 'text': 'arm'})
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertEqual(alarm._arm_mode, 'full')

    def test_admin_arm_night(self):
        handle_sms({'sender': '+36201111111', 'text': 'arm night'})
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertEqual(alarm._arm_mode, 'night')

    def test_user_can_arm(self):
        handle_sms({'sender': '+36202222222', 'text': 'arm full'})
        self.assertEqual(alarm._state, alarm.ARMING)

    def test_user_can_arm_night(self):
        handle_sms({'sender': '+36202222222', 'text': 'arm night'})
        self.assertEqual(alarm._state, alarm.ARMING)
        self.assertEqual(alarm._arm_mode, 'night')


class TestSmsDisarm(unittest.TestCase):
    """Test SMS disarm commands."""

    def setUp(self):
        _reset()
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'

    def test_admin_disarm(self):
        handle_sms({'sender': '+36201111111', 'text': 'disarm'})
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_user_disarm(self):
        handle_sms({'sender': '+36202222222', 'text': 'disarm'})
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_disarm_case_insensitive(self):
        handle_sms({'sender': '+36201111111', 'text': 'DISARM'})
        self.assertEqual(alarm._state, alarm.DISARMED)


class TestSmsAuth(unittest.TestCase):
    """Test SMS authorization."""

    def setUp(self):
        _reset()

    def test_unknown_sender_ignored(self):
        handle_sms({'sender': '+36209999999', 'text': 'disarm'})
        self.assertEqual(alarm._state, alarm.DISARMED)  # no change

    def test_blocked_user_ignored(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        handle_sms({'sender': '+36203333333', 'text': 'disarm'})
        self.assertEqual(alarm._state, alarm.ARMED)  # no change

    def test_empty_sender_ignored(self):
        handle_sms({'sender': '', 'text': 'disarm'})
        self.assertEqual(alarm._state, alarm.DISARMED)

    def test_empty_text_ignored(self):
        handle_sms({'sender': '+36201111111', 'text': ''})
        self.assertEqual(alarm._state, alarm.DISARMED)


class TestSmsStatus(unittest.TestCase):
    """Test SMS status query."""

    def setUp(self):
        _reset()

    def test_status_sends_sms(self):
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        handle_sms({'sender': '+36201111111', 'text': 'status'})
        sim.send_sms.assert_called_once()
        call_args = sim.send_sms.call_args
        self.assertEqual(call_args[0][0], '+36201111111')
        self.assertIn('ARMED', call_args[0][1])

    def test_user_can_query_status(self):
        handle_sms({'sender': '+36202222222', 'text': 'status'})
        sim.send_sms.assert_called_once()


class TestAlarmNotification(unittest.TestCase):
    """Test alarm SMS notification to admins."""

    def setUp(self):
        _reset()
        alarm._state = alarm.ARMED
        alarm._arm_mode = 'full'
        alarm._zones['door'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}

    def test_alarm_sends_sms_to_admins(self):
        alarm.zone_trigger('door', 'triggered')
        sim.send_sms.assert_called_once()
        call_args = sim.send_sms.call_args
        self.assertEqual(call_args[0][0], '+36201111111')
        self.assertIn('ALARM', call_args[0][1])
        self.assertIn('door', call_args[0][1])

    def test_alarm_sms_not_sent_to_users(self):
        alarm.zone_trigger('door', 'triggered')
        self.assertEqual(sim.send_sms.call_count, 1)

    def test_alarm_sms_includes_memory(self):
        alarm.zone_trigger('door', 'triggered')
        msg = sim.send_sms.call_args[0][1]
        self.assertIn('door', msg)


class TestSmsAdminCommands(unittest.TestCase):
    """Test admin-only SMS commands."""

    def setUp(self):
        _reset()
        alarm._zones['window'] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}

    def test_admin_bypass(self):
        handle_sms({'sender': '+36201111111', 'text': 'bypass window'})
        self.assertIn('window', alarm._bypassed)

    def test_user_cannot_bypass(self):
        handle_sms({'sender': '+36202222222', 'text': 'bypass window'})
        self.assertNotIn('window', alarm._bypassed)

    def test_admin_unbypass(self):
        alarm._bypassed.add('window')
        handle_sms({'sender': '+36201111111', 'text': 'unbypass window'})
        self.assertNotIn('window', alarm._bypassed)

    def test_user_cannot_unbypass(self):
        alarm._bypassed.add('window')
        handle_sms({'sender': '+36202222222', 'text': 'unbypass window'})
        self.assertIn('window', alarm._bypassed)

    def test_admin_auto_arm(self):
        handle_sms({'sender': '+36201111111', 'text': 'auto_arm 3600 night'})
        self.assertEqual(alarm._auto_arm_delay, 3600)
        self.assertEqual(alarm._auto_arm_mode, 'night')

    def test_admin_auto_arm_disable(self):
        alarm._auto_arm_delay = 3600
        handle_sms({'sender': '+36201111111', 'text': 'auto_arm 0'})
        self.assertIsNone(alarm._auto_arm_delay)

    def test_user_cannot_auto_arm(self):
        handle_sms({'sender': '+36202222222', 'text': 'auto_arm 3600 night'})
        self.assertIsNone(alarm._auto_arm_delay)


if __name__ == "__main__":
    unittest.main(verbosity=2)
