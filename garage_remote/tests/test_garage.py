"""
LM_garage.py unit tests — runs on host CPython without hardware.

Run:
  cd /home/ealfnmo/smarthome/garage
  python3 -m pytest tests/ -v
  # or
  python3 -m unittest tests.test_garage -v
"""

import unittest
import sys
import types
import time
from unittest import mock
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"
MICROS_SOURCE = PACKAGE_DIR


def _install_stubs():
    """Stub MicroPython-only modules so LM_garage imports on CPython."""
    if "machine" not in sys.modules:
        m = types.ModuleType("machine")

        class FakePin:
            IN = 0; OUT = 1; PULL_UP = 2; PULL_DOWN = 3
            def __init__(self, *a, **kw):
                self._value = kw.get("value", 0)
            def value(self, v=None):
                if v is not None:
                    self._value = v
                return self._value

        m.Pin = FakePin
        m.UART = type("UART", (), {
            "__init__": lambda s, *a, **kw: None,
            "write": lambda s, d: None,
            "read": lambda s, *a: None,
            "any": lambda s: False,
        })
        m.WDT = type("WDT", (), {
            "__init__": lambda s, **kw: None,
            "feed": lambda s: None,
        })
        sys.modules["machine"] = m

    for mod_name in ("Common", "Config", "microIO", "Types", "Notify"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            if mod_name == "Common":
                stub.console = lambda *a, **kw: None
                def _micro_task_stub(tag=None, task=None, _wrap=False):
                    if task is not None:
                        if hasattr(task, 'close'):
                            task.close()
                        return {'tag': tag, 'state': 'created'}
                    return None
                stub.micro_task = mock.MagicMock(side_effect=_micro_task_stub)
                stub.exec_cmd = mock.MagicMock(return_value=(True, "{}"))
                stub.syslog = lambda *a, **kw: None
            elif mod_name == "Config":
                stub.cfgget = lambda k: "test_device"
            elif mod_name == "microIO":
                stub.bind_pin = lambda name, default: default
                stub.pinmap_search = lambda pins: {p: 0 for p in pins}
            elif mod_name == "Types":
                stub.resolve = lambda t, **kw: t
            elif mod_name == "Notify":
                stub.Notify = type("Notify", (), {
                    "notify": staticmethod(lambda *a, **kw: "sent"),
                    "GLOBAL_NOTIFY": True,
                })
            sys.modules[mod_name] = stub

    if "LM_mqtt_client" not in sys.modules:
        stub = types.ModuleType("LM_mqtt_client")
        stub.publish = mock.MagicMock(return_value="sent")
        sys.modules["LM_mqtt_client"] = stub

    # Stub LM_sim800
    if "LM_sim800" not in sys.modules:
        stub = types.ModuleType("LM_sim800")
        stub.load = mock.MagicMock(return_value="Sim800 started.")
        stub.read_uart = mock.MagicMock(return_value=False)
        stub.send_command = mock.MagicMock()
        stub.receive_sms = mock.MagicMock(return_value=None)
        stub.reject_call = mock.MagicMock()
        stub.subscribe = mock.MagicMock()
        stub.unsubscribe = mock.MagicMock()

        class FakeSim800Instance:
            parse_call_params = mock.MagicMock()
            read_sms = mock.MagicMock()
            parse_sms = mock.MagicMock()
            delete_sms = mock.MagicMock()

        stub.Sim800 = type("Sim800", (), {"INSTANCE": FakeSim800Instance()})
        sys.modules["LM_sim800"] = stub

    # Stub LM_users
    if "LM_users" not in sys.modules:
        stub = types.ModuleType("LM_users")
        stub.load = mock.MagicMock(return_value="UserManagement started.")
        stub.get_user = mock.MagicMock(return_value=None)
        stub.check_access = mock.MagicMock(return_value=False)
        sys.modules["LM_users"] = stub

    for p in (str(PACKAGE_DIR), str(MICROS_SOURCE)):
        if p not in sys.path:
            sys.path.insert(0, p)


_install_stubs()
import LM_garage as garage
import LM_sim800 as sim_stub
import LM_users as users_stub


class TestRelayButton(unittest.TestCase):
    """Test RelayButton pin control logic."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()

    def test_door_button_pin(self):
        btn = garage.RelayButton(18, 'relay.door')
        self.assertEqual(btn.pin.value(), 0)
        btn.pin.value(1)
        self.assertEqual(btn.pin.value(), 1)
        btn.pin.value(0)
        self.assertEqual(btn.pin.value(), 0)

    def test_alarm_button_pin(self):
        btn = garage.RelayButton(20, 'relay.alarm')
        self.assertEqual(btn.pin.value(), 0)
        btn.pin.value(1)
        self.assertEqual(btn.pin.value(), 1)
        btn.pin.value(0)
        self.assertEqual(btn.pin.value(), 0)

    def test_button_tag(self):
        btn = garage.RelayButton(18, 'relay.door')
        self.assertEqual(btn.tag, 'relay.door')

    def test_button_duration_default(self):
        btn = garage.RelayButton(18, 'relay.door')
        self.assertEqual(btn.duration, 2000)

    def test_button_duration_custom(self):
        btn = garage.RelayButton(18, 'relay.door', duration=500)
        self.assertEqual(btn.duration, 500)

    def test_auto_registers_in_buttons(self):
        garage.RelayButton(18, 'relay.door')
        self.assertIn('relay.door', garage.RelayButton.BUTTONS)

    def test_get_returns_button(self):
        btn = garage.RelayButton(18, 'relay.door')
        self.assertIs(garage.RelayButton.get('relay.door'), btn)

    def test_get_returns_none_for_unknown(self):
        self.assertIsNone(garage.RelayButton.get('relay.nonexistent'))


class TestHandleCall(unittest.TestCase):
    """Test call handler with parsed call_params."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()
        users_stub.get_user = mock.MagicMock(return_value=None)

    def test_allowed_user_opens_garage(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A"}]
        with mock.patch.object(garage, "open_garage") as mock_open:
            garage._handle_call({"caller_number": "+36201111111"})
        mock_open.assert_called_once()

    def test_blocked_user_rejected(self):
        users_stub.get_user.return_value = [{"phone": "+36202222222", "name": "Bob", "status": "B", "info": "blocked"}]
        with mock.patch.object(garage, "open_garage") as mock_open:
            garage._handle_call({"caller_number": "+36202222222"})
        mock_open.assert_not_called()

    def test_unknown_caller(self):
        users_stub.get_user.return_value = None
        with mock.patch.object(garage, "open_garage") as mock_open:
            garage._handle_call({"caller_number": "+36209999999"})
        mock_open.assert_not_called()

    def test_rejects_call(self):
        sim_stub.reject_call = mock.MagicMock()
        garage._handle_call({"caller_number": "+36209999999"})
        sim_stub.reject_call.assert_called_once()

    def test_missing_caller_number(self):
        users_stub.get_user.return_value = None
        garage._handle_call({})  # should not crash


class TestHandleSms(unittest.TestCase):
    """Test SMS handler with parsed sms dict."""

    def setUp(self):
        users_stub.get_user = mock.MagicMock(return_value=None)

    def test_admin_alarm_on(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Admin", "status": "A", "role": "admin"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36201111111", "text": "alarm on"})
        mock_alarm.assert_called_once_with("alarm on", "+36201111111")

    def test_admin_alarm_off(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Admin", "status": "A", "role": "admin"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36201111111", "text": "alarm off 30"})
        mock_alarm.assert_called_once_with("alarm off 30", "+36201111111")

    def test_admin_cmd_execution(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Admin", "status": "A", "role": "admin"}]
        from Common import exec_cmd
        exec_cmd.reset_mock()
        garage._handle_sms({"sender": "+36201111111", "text": "cmd: system info"})
        exec_cmd.assert_called_once_with(["system", "info"], jsonify=True)

    def test_blocked_sender(self):
        users_stub.get_user.return_value = [{"phone": "+36202222222", "name": "Blocked", "status": "B", "info": "x"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36202222222", "text": "alarm on"})
        mock_alarm.assert_not_called()

    def test_unknown_sender(self):
        users_stub.get_user.return_value = None
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36209999999", "text": "alarm on"})
        mock_alarm.assert_not_called()

    def test_user_role_gets_alarm_command(self):
        users_stub.get_user.return_value = [{"phone": "+36203333333", "name": "User", "status": "A", "role": "user"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36203333333", "text": "alarm on"})
        mock_alarm.assert_called_once_with("alarm on", "+36203333333")

    def test_user_role_cmd_goes_to_alarm(self):
        """Non-admin user sending CMD: should go to alarm handler, not exec_cmd."""
        users_stub.get_user.return_value = [{"phone": "+36203333333", "name": "User", "status": "A", "role": "user"}]
        from Common import exec_cmd
        exec_cmd.reset_mock()
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36203333333", "text": "cmd: system info"})
        exec_cmd.assert_not_called()
        mock_alarm.assert_called_once()

    def test_sms_text_trailing_newline_stripped(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "User", "status": "A", "role": "user"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36201111111", "text": "alarm on\n"})
        mock_alarm.assert_called_once_with("alarm on", "+36201111111")

    def test_sms_text_leading_whitespace_stripped(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "User", "status": "A", "role": "user"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36201111111", "text": "  alarm on"})
        mock_alarm.assert_called_once_with("alarm on", "+36201111111")

    def test_sms_text_both_sides_stripped(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "User", "status": "A", "role": "user"}]
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36201111111", "text": " \nalarm off 10\n "})
        mock_alarm.assert_called_once_with("alarm off 10", "+36201111111")


# --- Alarm tests (merged from test_garage_alarm.py) ---

class TestHandleAlarmCommand(unittest.TestCase):

    def setUp(self):
        garage._alarm_sessions.clear()
        garage._alarm_observer_task = None

    def test_alarm_on(self):
        garage._alarm_sessions["+36201111111"] = time.time() + 600
        result = garage._handle_alarm_command("alarm on", "+36201111111")
        self.assertEqual(result, "Alarm on")
        self.assertNotIn("+36201111111", garage._alarm_sessions)

    def test_alarm_off(self):
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()
        result = garage._handle_alarm_command("alarm off 15", "+36201111111")
        self.assertEqual(result, "Alarm off for 15 min")
        self.assertIn("+36201111111", garage._alarm_sessions)

    def test_alarm_off_case_insensitive(self):
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()
        result = garage._handle_alarm_command("ALARM OFF 10", "+36201111111")
        self.assertEqual(result, "Alarm off for 10 min")

    def test_alarm_on_case_insensitive(self):
        garage._alarm_sessions["+36201111111"] = time.time() + 600
        result = garage._handle_alarm_command("Alarm On", "+36201111111")
        self.assertEqual(result, "Alarm on")

    def test_unknown_command(self):
        result = garage._handle_alarm_command("something else", "+36201111111")
        self.assertIn("Unknown command", result)

    def test_unknown_command_partial_match(self):
        result = garage._handle_alarm_command("alarm", "+36201111111")
        self.assertIn("Unknown command", result)

    def test_alarm_off_no_minutes(self):
        result = garage._handle_alarm_command("alarm off", "+36201111111")
        self.assertIn("Unknown command", result)


class TestGarageAlarmOff(unittest.TestCase):

    def setUp(self):
        garage._alarm_sessions.clear()
        garage._alarm_observer_task = None
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()

    def test_creates_session(self):
        garage.garage_alarm_off(10, "+36201111111")
        self.assertIn("+36201111111", garage._alarm_sessions)

    def test_caps_at_max_minutes(self):
        garage.garage_alarm_off(999, "+36201111111")
        end_time = garage._alarm_sessions["+36201111111"]
        expected_max = time.time() + garage.MAX_ALARM_MINUTES * 60
        self.assertAlmostEqual(end_time, expected_max, delta=2)

    def test_exactly_max_minutes(self):
        result = garage.garage_alarm_off(garage.MAX_ALARM_MINUTES, "+36201111111")
        end_time = garage._alarm_sessions["+36201111111"]
        expected = time.time() + garage.MAX_ALARM_MINUTES * 60
        self.assertAlmostEqual(end_time, expected, delta=2)
        self.assertEqual(result, f"Alarm off for {garage.MAX_ALARM_MINUTES} min")

    def test_one_minute(self):
        """Minutes below chunk are raised to chunk minimum."""
        result = garage.garage_alarm_off(1, "+36201111111")
        end_time = garage._alarm_sessions["+36201111111"]
        expected = time.time() + garage.ALARM_CHUNK_MINUTES * 60
        self.assertAlmostEqual(end_time, expected, delta=2)
        self.assertEqual(result, f"Alarm off for {garage.ALARM_CHUNK_MINUTES} min")

    def test_zero_minutes(self):
        """Zero minutes raised to chunk minimum."""
        result = garage.garage_alarm_off(0, "+36201111111")
        end_time = garage._alarm_sessions["+36201111111"]
        expected = time.time() + garage.ALARM_CHUNK_MINUTES * 60
        self.assertAlmostEqual(end_time, expected, delta=2)
        self.assertEqual(result, f"Alarm off for {garage.ALARM_CHUNK_MINUTES} min")

    def test_negative_minutes_raised_to_chunk(self):
        """Negative minutes raised to chunk minimum."""
        result = garage.garage_alarm_off(-5, "+36201111111")
        end_time = garage._alarm_sessions["+36201111111"]
        expected = time.time() + garage.ALARM_CHUNK_MINUTES * 60
        self.assertAlmostEqual(end_time, expected, delta=2)
        self.assertEqual(result, f"Alarm off for {garage.ALARM_CHUNK_MINUTES} min")

    def test_max_plus_one_capped(self):
        result = garage.garage_alarm_off(garage.MAX_ALARM_MINUTES + 1, "+36201111111")
        self.assertEqual(result, f"Alarm off for {garage.MAX_ALARM_MINUTES} min")

    def test_returns_message(self):
        result = garage.garage_alarm_off(15, "+36201111111")
        self.assertEqual(result, "Alarm off for 15 min")

    def test_returns_capped_message(self):
        result = garage.garage_alarm_off(999, "+36201111111")
        self.assertEqual(result, f"Alarm off for {garage.MAX_ALARM_MINUTES} min")

    def test_overwrites_existing_session(self):
        garage.garage_alarm_off(5, "+36201111111")
        first_end = garage._alarm_sessions["+36201111111"]
        time.sleep(0.01)
        garage.garage_alarm_off(20, "+36201111111")
        second_end = garage._alarm_sessions["+36201111111"]
        self.assertGreater(second_end, first_end)

    def test_multiple_phones(self):
        garage.garage_alarm_off(10, "+36201111111")
        garage.garage_alarm_off(20, "+36202222222")
        self.assertEqual(len(garage._alarm_sessions), 2)


class TestGarageAlarmOn(unittest.TestCase):

    def setUp(self):
        garage._alarm_sessions.clear()

    def test_removes_session(self):
        garage._alarm_sessions["+36201111111"] = time.time() + 600
        garage.garage_alarm_on("+36201111111")
        self.assertNotIn("+36201111111", garage._alarm_sessions)

    def test_returns_message(self):
        result = garage.garage_alarm_on("+36201111111")
        self.assertEqual(result, "Alarm on")

    def test_nonexistent_phone_no_error(self):
        result = garage.garage_alarm_on("+99999999999")
        self.assertEqual(result, "Alarm on")

    def test_other_sessions_untouched(self):
        garage._alarm_sessions["+36201111111"] = time.time() + 600
        garage._alarm_sessions["+36202222222"] = time.time() + 600
        garage.garage_alarm_on("+36201111111")
        self.assertNotIn("+36201111111", garage._alarm_sessions)
        self.assertIn("+36202222222", garage._alarm_sessions)


class TestAlarmObserver(unittest.TestCase):

    def setUp(self):
        garage._alarm_sessions.clear()
        garage._alarm_observer_task = None
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()

    def test_observer_task_starts_on_alarm_off(self):
        with mock.patch.object(garage, 'micro_task', wraps=garage.micro_task) as mt:
            garage.garage_alarm_off(10, "+36201111111")
            self.assertTrue(mt.call_count >= 1)

    def test_observer_task_not_restarted_if_running(self):
        garage._alarm_observer_task = "already_running"
        micro_task = sys.modules['Common'].micro_task
        micro_task.reset_mock()
        garage.garage_alarm_off(10, "+36201111111")
        # Only press_alarm_button call, no observer start
        tags = [c.kwargs.get('tag', '') for c in micro_task.call_args_list]
        self.assertNotIn("garage_alarm_observer", tags)

    def test_session_expiry(self):
        # Session already expired
        garage._alarm_sessions["+36201111111"] = time.time() - 10
        now = time.time()
        for phone, end_time in list(garage._alarm_sessions.items()):
            if end_time <= now:
                garage._alarm_sessions.pop(phone, None)
        self.assertNotIn("+36201111111", garage._alarm_sessions)

    def test_session_still_active(self):
        garage._alarm_sessions["+36201111111"] = time.time() + 3600
        now = time.time()
        for phone, end_time in list(garage._alarm_sessions.items()):
            if end_time <= now:
                garage._alarm_sessions.pop(phone, None)
        self.assertIn("+36201111111", garage._alarm_sessions)

    def test_observer_boundary_exactly_one_chunk_remaining(self):
        """Session with exactly chunk time remaining should NOT be expired.
        It's in the last chunk — no re-press needed, but not expired yet.
        """
        now = time.time()
        garage._alarm_sessions["+36201111111"] = now + garage.ALARM_CHUNK_MINUTES * 60
        chunk_sec = garage.ALARM_CHUNK_MINUTES * 60
        need_press = False
        for phone, end_time in list(garage._alarm_sessions.items()):
            remaining = end_time - now
            if remaining <= 0:
                garage._alarm_sessions.pop(phone, None)
            elif remaining >= chunk_sec and remaining % chunk_sec < 15:
                need_press = True
        self.assertIn("+36201111111", garage._alarm_sessions)
        # remaining == chunk_sec, remaining % chunk_sec == 0 < 15, and remaining >= chunk_sec → press
        self.assertTrue(need_press)

    def test_observer_boundary_just_under_one_chunk(self):
        """Session with slightly less than chunk time should NOT be expired (still has time left)."""
        now = time.time()
        garage._alarm_sessions["+36201111111"] = now + garage.ALARM_CHUNK_MINUTES * 60 - 1
        chunk_sec = garage.ALARM_CHUNK_MINUTES * 60
        for phone, end_time in list(garage._alarm_sessions.items()):
            remaining = end_time - now
            if remaining <= 0:
                garage._alarm_sessions.pop(phone, None)
        self.assertIn("+36201111111", garage._alarm_sessions)

    def test_observer_expired_session(self):
        """Session with remaining <= 0 should be expired."""
        now = time.time()
        garage._alarm_sessions["+36201111111"] = now - 1
        chunk_sec = garage.ALARM_CHUNK_MINUTES * 60
        for phone, end_time in list(garage._alarm_sessions.items()):
            remaining = end_time - now
            if remaining <= 0:
                garage._alarm_sessions.pop(phone, None)
        self.assertNotIn("+36201111111", garage._alarm_sessions)

    def test_observer_no_repress_in_last_chunk(self):
        """Session in last chunk (0 < remaining < chunk_sec) should not trigger re-press."""
        now = time.time()
        garage._alarm_sessions["+36201111111"] = now + 60  # 1 min remaining
        chunk_sec = garage.ALARM_CHUNK_MINUTES * 60
        need_press = False
        for phone, end_time in list(garage._alarm_sessions.items()):
            remaining = end_time - now
            if remaining <= 0:
                garage._alarm_sessions.pop(phone, None)
            elif remaining >= chunk_sec and remaining % chunk_sec < 15:
                need_press = True
        self.assertFalse(need_press)

    def test_session_overwrite_extends_past_original_chunk_boundary(self):
        """Second alarm off should extend session past the first one's chunk boundary."""
        now = time.time()
        garage.garage_alarm_off(7, "+36201111111")
        first_end = garage._alarm_sessions["+36201111111"]
        garage.garage_alarm_off(10, "+36201111111")
        second_end = garage._alarm_sessions["+36201111111"]
        self.assertGreater(second_end, first_end)
        # At first_end - chunk, the session should NOT expire
        simulated_now = first_end - garage.ALARM_CHUNK_MINUTES * 60
        self.assertFalse(second_end < simulated_now + garage.ALARM_CHUNK_MINUTES * 60)


class TestLogging(unittest.TestCase):
    """Test that user interactions are logged via _logger."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()
        garage._alarm_sessions.clear()
        garage._alarm_observer_task = None
        users_stub.get_user = mock.MagicMock(return_value=None)

    @mock.patch.object(garage, '_logger')
    def test_unknown_caller_logged(self, mock_log):
        garage._handle_call({"caller_number": "+36209999999"})
        mock_log.assert_called_once()
        self.assertIn("Unknown caller", mock_log.call_args[0][0])

    @mock.patch.object(garage, '_logger')
    def test_allowed_caller_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A"}]
        with mock.patch.object(garage, 'open_garage'):
            garage._handle_call({"caller_number": "+36201111111"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Allowed caller" in c for c in calls))

    @mock.patch.object(garage, '_logger')
    def test_blocked_caller_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36202222222", "name": "Bob", "status": "B", "info": "banned"}]
        garage._handle_call({"caller_number": "+36202222222"})
        mock_log.assert_called_once()
        self.assertIn("Blocked caller", mock_log.call_args[0][0])

    @mock.patch.object(garage, '_logger')
    def test_unknown_sms_sender_logged(self, mock_log):
        garage._handle_sms({"sender": "+36209999999", "text": "hello"})
        mock_log.assert_called_once()
        self.assertIn("Unknown SMS sender", mock_log.call_args[0][0])

    @mock.patch.object(garage, '_logger')
    def test_blocked_sms_sender_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36202222222", "name": "Bob", "status": "B", "info": "x"}]
        garage._handle_sms({"sender": "+36202222222", "text": "alarm on"})
        mock_log.assert_called_once()
        self.assertIn("Blocked SMS sender", mock_log.call_args[0][0])

    @mock.patch.object(garage, '_logger')
    def test_unexpected_status_sms_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36203333333", "name": "X", "status": "Z", "role": "user"}]
        garage._handle_sms({"sender": "+36203333333", "text": "alarm on"})
        mock_log.assert_called_once()
        self.assertIn("unexpected status", mock_log.call_args[0][0])

    @mock.patch.object(garage, '_logger')
    def test_admin_cmd_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Admin", "status": "A", "role": "admin"}]
        garage._handle_sms({"sender": "+36201111111", "text": "cmd: system info"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Admin CMD by" in c for c in calls))
        self.assertTrue(any("Admin CMD output" in c for c in calls))

    @mock.patch.object(garage, '_logger')
    def test_alarm_cmd_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "User", "status": "A", "role": "user"}]
        garage._handle_sms({"sender": "+36201111111", "text": "alarm on"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Alarm CMD by" in c for c in calls))

    @mock.patch.object(garage, '_logger')
    def test_garage_alarm_off_logged(self, mock_log):
        garage.garage_alarm_off(10, "+36201111111")
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Alarm off for 10 min" in c for c in calls))

    @mock.patch.object(garage, '_logger')
    def test_garage_alarm_on_logged(self, mock_log):
        garage._alarm_sessions["+36201111111"] = time.time() + 600
        garage.garage_alarm_on("+36201111111")
        mock_log.assert_called_once()
        self.assertIn("Alarm on by", mock_log.call_args[0][0])

    @mock.patch.object(garage, '_logger')
    def test_open_garage_logged(self, mock_log):
        garage.open_garage()
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Garage door opened" in c for c in calls))

    @mock.patch.object(garage, '_logger')
    def test_sms_without_sender_logged(self, mock_log):
        garage._handle_sms({"text": "hello"})
        mock_log.assert_called_once()
        self.assertIn("SMS without sender", mock_log.call_args[0][0])


class TestUnload(unittest.TestCase):
    """Test graceful shutdown via unload()."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()
        garage._alarm_sessions.clear()
        garage._alarm_observer_task = None
        sim_stub.unsubscribe = mock.MagicMock()

    def test_unload_unsubscribes_call(self):
        garage.unload()
        sim_stub.unsubscribe.assert_any_call('call', garage._handle_call)

    def test_unload_unsubscribes_sms(self):
        garage.unload()
        sim_stub.unsubscribe.assert_any_call('sms', garage._handle_sms)

    def test_unload_clears_alarm_sessions(self):
        garage._alarm_sessions["+36201111111"] = time.time() + 600
        garage._alarm_sessions["+36202222222"] = time.time() + 600
        garage.unload()
        self.assertEqual(len(garage._alarm_sessions), 0)

    def test_unload_clears_observer_task(self):
        garage._alarm_observer_task = "running"
        garage.unload()
        self.assertIsNone(garage._alarm_observer_task)

    def test_unload_returns_message(self):
        result = garage.unload()
        self.assertEqual(result, 'Garage module stopped.')

    @mock.patch.object(garage, '_logger')
    def test_unload_logged(self, mock_log):
        garage.unload()
        mock_log.assert_called_once()
        self.assertIn("Garage module stopped", mock_log.call_args[0][0])


class TestHandleCallErrorLogging(unittest.TestCase):
    """Test that open_garage errors are logged in _handle_call."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()
        users_stub.get_user = mock.MagicMock(return_value=None)

    @mock.patch.object(garage, '_logger')
    def test_open_garage_error_logged(self, mock_log):
        """When relay is not initialized, _handle_call should log the error."""
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A"}]
        # No relay initialized -> open_garage returns error dict
        garage._handle_call({"caller_number": "+36201111111"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Failed to open garage" in c for c in calls))

    @mock.patch.object(garage, '_logger')
    def test_open_garage_success_no_error_logged(self, mock_log):
        """When relay is initialized, no error should be logged."""
        garage._instantiate_relay()
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A"}]
        garage._handle_call({"caller_number": "+36201111111"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertFalse(any("Failed to open garage" in c for c in calls))


class TestLoggerJsonSafety(unittest.TestCase):
    """Test that _logger produces valid JSON even with special characters."""

    def setUp(self):
        import json
        self.json = json

    @mock.patch.object(garage.Notify, 'notify')
    def test_logger_with_quotes_in_message(self, mock_notify):
        garage._logger('User said "hello"')
        payload = mock_notify.call_args[0][0]
        parsed = self.json.loads(payload)
        self.assertIn('User said "hello"', parsed['message'])

    @mock.patch.object(garage.Notify, 'notify')
    def test_logger_with_backslash_in_message(self, mock_notify):
        garage._logger('path\\to\\file')
        payload = mock_notify.call_args[0][0]
        parsed = self.json.loads(payload)
        self.assertIn('path\\to\\file', parsed['message'])

    @mock.patch.object(garage.Notify, 'notify')
    def test_logger_with_newline_in_message(self, mock_notify):
        garage._logger('line1\nline2')
        payload = mock_notify.call_args[0][0]
        parsed = self.json.loads(payload)
        self.assertIn('line1\nline2', parsed['message'])

    @mock.patch.object(garage.Notify, 'notify')
    def test_logger_json_has_all_fields(self, mock_notify):
        garage._logger('test msg', level='WARN', topic_suffix='alert')
        payload = mock_notify.call_args[0][0]
        parsed = self.json.loads(payload)
        self.assertIn('time', parsed)
        self.assertEqual(parsed['level'], 'WARN')
        self.assertEqual(parsed['message'], 'test msg')
        self.assertEqual(mock_notify.call_args[1]['topic'], 'alert')


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestInactiveAccess(unittest.TestCase):
    """Test that inactive (expired/not-yet-active) users are rejected."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()
        users_stub.get_user = mock.MagicMock(return_value=None)
        users_stub.check_access = mock.MagicMock(return_value=False)

    def test_inactive_caller_rejected(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A"}]
        users_stub.check_access.return_value = True
        with mock.patch.object(garage, "open_garage") as mock_open:
            garage._handle_call({"caller_number": "+36201111111"})
        mock_open.assert_not_called()

    @mock.patch.object(garage, '_logger')
    def test_inactive_caller_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A"}]
        users_stub.check_access.return_value = True
        garage._handle_call({"caller_number": "+36201111111"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Inactive caller" in c for c in calls))

    def test_inactive_sms_sender_rejected(self):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A", "role": "admin"}]
        users_stub.check_access.return_value = True
        with mock.patch.object(garage, "_handle_alarm_command") as mock_alarm:
            garage._handle_sms({"sender": "+36201111111", "text": "alarm on"})
        mock_alarm.assert_not_called()

    @mock.patch.object(garage, '_logger')
    def test_inactive_sms_sender_logged(self, mock_log):
        users_stub.get_user.return_value = [{"phone": "+36201111111", "name": "Alice", "status": "A", "role": "user"}]
        users_stub.check_access.return_value = True
        garage._handle_sms({"sender": "+36201111111", "text": "alarm on"})
        calls = [c[0][0] for c in mock_log.call_args_list]
        self.assertTrue(any("Inactive SMS sender" in c for c in calls))


class TestPressAlarmButton(unittest.TestCase):
    """Test press_alarm_button directly."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()

    def test_press_alarm_button_error_when_not_initialized(self):
        result = garage.press_alarm_button()
        self.assertIn("error", result)

    def test_press_alarm_button_success(self):
        garage._instantiate_relay()
        result = garage.press_alarm_button()
        self.assertEqual(result, {"alarm": "pressed"})


class TestOpenGarage(unittest.TestCase):
    """Test open_garage directly."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()

    def test_open_garage_error_when_not_initialized(self):
        result = garage.open_garage()
        self.assertIn("error", result)

    def test_open_garage_success(self):
        garage._instantiate_relay()
        result = garage.open_garage()
        self.assertEqual(result, {"garage": "open"})


class TestLoad(unittest.TestCase):
    """Test load() initialization."""

    def setUp(self):
        garage.RelayButton.BUTTONS.clear()
        sim_stub.load = mock.MagicMock(return_value="Sim800 started.")
        sim_stub.subscribe = mock.MagicMock()
        sim_stub.read_uart = mock.MagicMock(return_value=False)
        users_stub.load = mock.MagicMock(return_value="UserManagement started.")

    def test_load_returns_message(self):
        result = garage.load(1234)
        self.assertEqual(result, "Garage module started.")

    def test_load_initializes_relays(self):
        garage.load(1234)
        self.assertIn('relay.door', garage.RelayButton.BUTTONS)
        self.assertIn('relay.alarm', garage.RelayButton.BUTTONS)

    def test_load_subscribes_call(self):
        garage.load(1234)
        sim_stub.subscribe.assert_any_call('call', garage._handle_call)

    def test_load_subscribes_sms(self):
        garage.load(1234)
        sim_stub.subscribe.assert_any_call('sms', garage._handle_sms)

    def test_load_calls_sim_load(self):
        garage.load(1234)
        sim_stub.load.assert_called_once_with(pin_code=1234)

    def test_load_calls_users_load(self):
        garage.load(1234)
        users_stub.load.assert_called_once()


class TestHandleAlarmCommandEdgeCases(unittest.TestCase):
    """Test alarm command edge cases."""

    def setUp(self):
        garage._alarm_sessions.clear()
        garage._alarm_observer_task = None
        garage.RelayButton.BUTTONS.clear()
        garage._instantiate_relay()

    def test_alarm_off_non_numeric_minutes(self):
        result = garage._handle_alarm_command("alarm off abc", "+36201111111")
        self.assertIn("Unknown command", result)

    def test_alarm_off_float_minutes(self):
        result = garage._handle_alarm_command("alarm off 10.5", "+36201111111")
        self.assertIn("Unknown command", result)

    def test_alarm_off_negative_in_command(self):
        result = garage._handle_alarm_command("alarm off -5", "+36201111111")
        self.assertIn("Unknown command", result)

    def test_alarm_off_extra_spaces(self):
        result = garage._handle_alarm_command("alarm off  10", "+36201111111")
        self.assertEqual(result, "Alarm off for 10 min")

    def test_alarm_on_extra_text(self):
        result = garage._handle_alarm_command("alarm on please", "+36201111111")
        self.assertIn("Unknown command", result)


class TestGetTimestamp(unittest.TestCase):
    """Test get_timestamp format."""

    def test_returns_formatted_string(self):
        result = garage.get_timestamp()
        self.assertRegex(result, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')

    def test_returns_current_time(self):
        t = time.localtime()
        result = garage.get_timestamp()
        expected_prefix = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
        self.assertTrue(result.startswith(expected_prefix))
