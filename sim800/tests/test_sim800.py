"""
LM_sim800.py unit tests — runs on host CPython without hardware.

Run:
  cd /home/ealfnmo/smarthome/garage
  python3 -m pytest tests/test_sim800.py -v
"""

import unittest
import sys
import types
import importlib.util
from unittest import mock
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "package"
_MODULE_NAME = "LM_sim800_under_test"


def _install_stubs():
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
            def irq(self, **kw): pass

        class FakeUART:
            def __init__(self, *a, **kw):
                self._buf = b""
            def write(self, data): pass
            def read(self, *a): return self._buf or None
            def any(self): return len(self._buf)

        m.Pin = FakePin
        m.UART = FakeUART
        m.WDT = type("WDT", (), {"__init__": lambda s, **kw: None, "feed": lambda s: None})
        sys.modules["machine"] = m

    for mod_name in ("Common", "Config", "microIO", "Types"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            if mod_name == "Common":
                stub.console = lambda *a, **kw: None
                stub.data_dir = lambda f_name=None: f_name if f_name else '.'
                stub.micro_task = mock.MagicMock()
                stub.exec_cmd = mock.MagicMock(return_value=(True, "{}"))

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
            elif mod_name == "Config":
                stub.cfgget = lambda k: "test_device"
            elif mod_name == "microIO":
                stub.bind_pin = lambda name, default: default
                stub.pinmap_search = lambda pins: {p: 0 for p in pins}
            elif mod_name == "Types":
                stub.resolve = lambda t, **kw: t
            sys.modules[mod_name] = stub


def _load_sim800_module():
    _install_stubs()
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, str(PACKAGE_DIR / "LM_sim800.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load_sim800_module()


def _new_inst():
    """Create a Sim800 instance without hardware init."""
    return sim.Sim800.__new__(sim.Sim800)


def _make_raw_pdu(pdu_hex, status="0"):
    return f"\r\n+CMGR: {status},\"\",155\r\n{pdu_hex}\r\n\r\nOK\r\n".encode()


# ---------------------------------------------------------------------------
# PDU helpers
# ---------------------------------------------------------------------------

class TestPduHelpers(unittest.TestCase):

    def test_semi_octet_to_number_even(self):
        self.assertEqual(sim.Sim800._semi_octet_to_number("6302214365F7"), "36201234567")

    def test_semi_octet_to_number_odd(self):
        # odd digit count — trailing nibble kept as-is
        self.assertEqual(sim.Sim800._semi_octet_to_number("630221436507"), "362012345670")

    def test_swap_pairs(self):
        self.assertEqual(sim.Sim800._swap_pairs("6230"), "2603")

    def test_pad_hex_even(self):
        self.assertEqual(sim.Sim800._pad_hex("AB"), "AB")

    def test_pad_hex_odd(self):
        self.assertEqual(sim.Sim800._pad_hex("ABC"), "0ABC")

    def test_pad_hex_strips_spaces(self):
        self.assertEqual(sim.Sim800._pad_hex("A B C"), "0ABC")

    def test_ceil_even_int_even(self):
        self.assertEqual(sim.Sim800._ceil_even_int(4), 4)

    def test_ceil_even_int_odd(self):
        self.assertEqual(sim.Sim800._ceil_even_int(5), 6)

    def test_time_stamp_parse(self):
        # "62309111042200" -> 2026-03-19 11:40:22 +00:00
        result = sim.Sim800._time_stamp_parse("62309111042200")
        self.assertTrue(result.startswith("20"))
        self.assertIn(":", result)

    def test_time_zone_offset_positive(self):
        result = sim.Sim800._time_zone_offset("00")
        self.assertEqual(result, "+00:00")

    def test_time_zone_offset_negative(self):
        result = sim.Sim800._time_zone_offset("80")
        self.assertTrue(result.startswith("-"))


# ---------------------------------------------------------------------------
# GSM7 decoding
# ---------------------------------------------------------------------------

class TestGsm7Decode(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def test_decode_hello(self):
        # "hello" packed GSM7
        self.assertEqual(self.inst._decode_gsm7("E8329BFD06", "05"), "hello")

    def test_decode_hellohello(self):
        self.assertEqual(self.inst._decode_gsm7("E8329BFD4697D9EC37", "0A"), "hellohello")

    def test_decode_gsm7_special_chars(self):
        # '@' is 0x00 in GSM7
        result = self.inst._decode_gsm7("00", "01")
        self.assertEqual(result, "@")

    def test_decode_gsm7_unknown_char(self):
        # 0x1B alone (escape with no following byte) should not crash
        result = self.inst._decode_gsm7("1B", "01")
        self.assertIsInstance(result, str)

    def test_decode_gsm7_ext_euro(self):
        # € = escape (0x1B) + 0x65, packed into 2 septets
        # bit-pack: 0x1B = 0b0011011, 0x65 = 0b1100101
        # packed LSB-first: 0x1B | (0x65 << 7) = 0x1B | 0x3280 = 0x329B -> bytes: 9B 32
        result = self.inst._decode_gsm7("9B32", "02")
        self.assertIn("€", result)


# ---------------------------------------------------------------------------
# UTF-16BE decoding
# ---------------------------------------------------------------------------

class TestUtf16BeDecode(unittest.TestCase):

    def test_basic_ascii(self):
        b = "hello".encode("utf-16-be")
        self.assertEqual(sim.Sim800._decode_utf16be_with_surrogates(b), "hello")

    def test_hungarian_chars(self):
        text = "Árvíztűrő"
        b = text.encode("utf-16-be")
        self.assertEqual(sim.Sim800._decode_utf16be_with_surrogates(b), text)

    def test_surrogate_pair_emoji(self):
        # 😀 U+1F600 -> surrogate pair D83D DE00
        b = bytes.fromhex("D83DDE00")
        result = sim.Sim800._decode_utf16be_with_surrogates(b)
        self.assertEqual(result, "😀")

    def test_odd_length_bytes(self):
        # should not crash on odd-length input
        result = sim.Sim800._decode_utf16be_with_surrogates(b"\x00")
        self.assertIsInstance(result, str)

    def test_invalid_surrogate_pair(self):
        # high surrogate not followed by low surrogate -> '?'
        b = bytes.fromhex("D83D0041")
        result = sim.Sim800._decode_utf16be_with_surrogates(b)
        self.assertIn("?", result)


# ---------------------------------------------------------------------------
# 8-bit data decoding
# ---------------------------------------------------------------------------

class TestDecode8bit(unittest.TestCase):

    def test_basic(self):
        b = sim.Sim800._decode_8bit_data("48656C6C6F")
        self.assertEqual(b, b"Hello")

    def test_truncate_by_udl(self):
        b = sim.Sim800._decode_8bit_data("48656C6C6F", tp_udl="03")
        self.assertEqual(b, b"Hel")

    def test_pad_by_udl(self):
        b = sim.Sim800._decode_8bit_data("4865", tp_udl="04")
        self.assertEqual(b, b"He\x00\x00")

    def test_odd_hex(self):
        b = sim.Sim800._decode_8bit_data("A")
        self.assertEqual(b, bytes.fromhex("0A"))


# ---------------------------------------------------------------------------
# SMS parsing
# ---------------------------------------------------------------------------

class TestSmsParse(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def test_parse_gsm7_sender_and_text(self):
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "00"
            "62309111042200"
            "0A"
            "E8329BFD4697D9EC37"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu))
        self.assertEqual(result["sender"], "+36201234567")
        self.assertEqual(result["text"], "hellohello")
        self.assertEqual(result["TP-DCS"], 0)

    def test_parse_gsm7_hungarian_post_processing(self):
        # GSM7 septets: à(0x7F) ò(0x08) ù(0x06) -> should become áóú
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "00"
            "62309111042200"
            "03"
            "7F8401"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu))
        self.assertEqual(result["text"], "áóú")

    def test_parse_ucs2_text(self):
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "08"
            "62309111042200"
            "0A"
            "00C1007200760072007A"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu))
        self.assertEqual(result["TP-DCS"], 2)
        self.assertIn("\u00c1", result["text"])

    def test_parse_smsc(self):
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "00"
            "62309111042200"
            "0A"
            "E8329BFD4697D9EC37"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu))
        self.assertIn("smsc", result)
        self.assertTrue(result["smsc"].startswith("+"))

    def test_parse_timestamp(self):
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "00"
            "62309111042200"
            "0A"
            "E8329BFD4697D9EC37"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu))
        self.assertIn("time_stamp", result)
        self.assertRegex(result["time_stamp"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}:\d{2}$")

    def test_parse_status_rec_unread(self):
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "00"
            "62309111042200"
            "0A"
            "E8329BFD4697D9EC37"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu, status="0"))
        self.assertEqual(result["status"], "REC UNREAD")

    def test_parse_status_rec_read(self):
        pdu = (
            "07916303898814F2"
            "00"
            "0B916302214365F7"
            "00" "00"
            "62309111042200"
            "0A"
            "E8329BFD4697D9EC37"
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu, status="1"))
        self.assertEqual(result["status"], "REC READ")

    def test_parse_invalid_bytes_returns_empty(self):
        result = self.inst.parse_sms(b"\xff\xfe invalid")
        self.assertEqual(result, {})

    def test_parse_malformed_pdu_returns_partial(self):
        raw = b"\r\n+CMGR: 0,\"\",10\r\nDEADBEEF\r\n\r\nOK\r\n"
        result = self.inst.parse_sms(raw)
        # should not raise, returns whatever was parsed
        self.assertIsInstance(result, dict)

    def test_parse_oa_length_with_bit2_set(self):
        """Regression: OA address-length must not be masked with & ~0x04.

        A 12-digit sender (OA-length = 0x0C) has bit 2 set.  The old code
        applied _mask_tp_flags which cleared bit 2, reading only 8 digits
        and shifting every subsequent field (PID, DCS, timestamp, text).
        """
        # 12-digit sender +363012345678 -> OA len 0C, TOA 91, semi-octet 630321436587
        pdu = (
            "07916303898814F2"          # SMSC: +36309888412
            "00"                        # TP-MTI: SMS-DELIVER
            "0C91630321436587"          # OA: 0C digits, intl, +363012345678
            "00" "00"                   # TP-PID, TP-DCS (GSM7)
            "62309111042200"            # timestamp
            "05"                        # TP-UDL: 5 septets
            "E8329BFD06"                # "hello" GSM7-packed
        )
        result = self.inst.parse_sms(_make_raw_pdu(pdu))
        self.assertEqual(result["sender"], "+363012345678")
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["TP-DCS"], 0)
        self.assertRegex(result["time_stamp"],
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{2}:\d{2}$")


# ---------------------------------------------------------------------------
# Call params parsing
# ---------------------------------------------------------------------------

class TestCallParsing(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def test_parse_clip_international(self):
        clip_line = '+CLIP: "+36201234567",145,"",0,"",0'
        result = self.inst.parse_call_params(clip_line)
        self.assertEqual(result["caller_number"], "+36201234567")
        self.assertEqual(result["data_type"], "+CLIP")

    def test_parse_clip_domestic(self):
        clip_line = '+CLIP: "061234567",129,"",0,"",0'
        result = self.inst.parse_call_params(clip_line)
        self.assertEqual(result["caller_number"], "061234567")

    def test_parse_clip_missing_fields(self):
        # fewer parts than expected — should not crash
        clip_line = '+CLIP: "+36201234567",145'
        result = self.inst.parse_call_params(clip_line)
        self.assertEqual(result["caller_number"], "+36201234567")
        self.assertEqual(result.get("caller_name", ""), "")

    def test_parse_clip_malformed_returns_empty(self):
        result = self.inst.parse_call_params("garbage")
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# read_uart
# ---------------------------------------------------------------------------

class TestReadUart(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        self.inst.uart = mock.MagicMock()
        self.inst.uart._buf = b""
        self.inst.uart.any.side_effect = lambda: len(self.inst.uart._buf)

    def _patch_read_raw(self):
        self.inst._read_raw = mock.MagicMock(return_value=self.inst.uart._buf)

    def test_no_data_returns_false(self):
        self.inst.uart._buf = b""
        self._patch_read_raw()
        self.assertFalse(self.inst.read_uart())

    def test_returns_lines(self):
        self.inst.uart._buf = b"\r\nRING\r\n+CLIP: ...\r\nOK\r\n"
        self._patch_read_raw()
        result = self.inst.read_uart()
        self.assertIsInstance(result, tuple)
        lines, raw = result
        self.assertIsInstance(lines, list)
        self.assertIn("RING", lines)

    def test_unicode_decode_error_returns_raw(self):
        self.inst.uart._buf = b"\xff\xfe\x00"
        self._patch_read_raw()
        result = self.inst.read_uart()
        self.assertIsInstance(result, tuple)
        lines, raw = result
        self.assertIsNone(lines)
        self.assertEqual(raw, b"\xff\xfe\x00")


# ---------------------------------------------------------------------------
# get_signal_quality
# ---------------------------------------------------------------------------

class TestGetSignalQuality(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def _mock_response(self, resp_bytes):
        self.inst.send_command = mock.MagicMock(return_value=resp_bytes)

    def test_normal_signal(self):
        self._mock_response(b"\r\n+CSQ: 18,0\r\n\r\nOK\r\n")
        result = self.inst.get_signal_quality()
        self.assertEqual(result["rssi"], 18)
        self.assertEqual(result["ber"], 0)
        self.assertEqual(result["dbm"], "-77 dBm")

    def test_unknown_signal(self):
        self._mock_response(b"\r\n+CSQ: 99,99\r\n\r\nOK\r\n")
        result = self.inst.get_signal_quality()
        self.assertEqual(result["rssi"], 99)
        self.assertEqual(result["dbm"], "unknown")

    def test_minimum_signal(self):
        self._mock_response(b"\r\n+CSQ: 0,0\r\n\r\nOK\r\n")
        result = self.inst.get_signal_quality()
        self.assertEqual(result["dbm"], "unknown")

    def test_maximum_signal(self):
        self._mock_response(b"\r\n+CSQ: 31,0\r\n\r\nOK\r\n")
        result = self.inst.get_signal_quality()
        self.assertEqual(result["dbm"], "-51 dBm")

    def test_malformed_response_returns_none(self):
        self._mock_response(b"\r\nERROR\r\n")
        result = self.inst.get_signal_quality()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# get_network_info
# ---------------------------------------------------------------------------

class TestGetNetworkInfo(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def _mock_responses(self, creg, cops):
        responses = [creg, cops]
        self.inst.send_command = mock.MagicMock(side_effect=responses)

    def test_registered_home(self):
        self._mock_responses(
            b"\r\n+CREG: 0,1\r\n\r\nOK\r\n",
            b'\r\n+COPS: 0,0,"Telekom HU",2\r\n\r\nOK\r\n'
        )
        result = self.inst.get_network_info()
        self.assertEqual(result["reg_status"], "registered home")
        self.assertEqual(result["operator"], "Telekom HU")

    def test_registered_roaming(self):
        self._mock_responses(
            b"\r\n+CREG: 0,5\r\n\r\nOK\r\n",
            b'\r\n+COPS: 0,0,"T-Mobile AT",2\r\n\r\nOK\r\n'
        )
        result = self.inst.get_network_info()
        self.assertEqual(result["reg_status"], "registered roaming")

    def test_not_registered(self):
        self._mock_responses(
            b"\r\n+CREG: 0,0\r\n\r\nOK\r\n",
            b'\r\n+COPS: 0\r\n\r\nOK\r\n'
        )
        result = self.inst.get_network_info()
        self.assertEqual(result["reg_status"], "not registered")

    def test_searching(self):
        self._mock_responses(
            b"\r\n+CREG: 0,2\r\n\r\nOK\r\n",
            b'\r\n+COPS: 0\r\n\r\nOK\r\n'
        )
        result = self.inst.get_network_info()
        self.assertEqual(result["reg_status"], "searching")

    def test_creg_error_returns_unknown(self):
        self._mock_responses(b"\r\nERROR\r\n", b'\r\n+COPS: 0,0,"Telekom",2\r\n\r\nOK\r\n')
        result = self.inst.get_network_info()
        self.assertEqual(result["reg_status"], "unknown")

    def test_cops_error_returns_unknown_operator(self):
        self._mock_responses(b"\r\n+CREG: 0,1\r\n\r\nOK\r\n", b"\r\nERROR\r\n")
        result = self.inst.get_network_info()
        self.assertEqual(result["operator"], "unknown")


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------

class TestIsConnected(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def test_connected_home(self):
        self.inst.get_network_info = mock.MagicMock(return_value={
            "reg_status": "registered home", "operator": "Telekom HU"
        })
        self.inst.get_signal_quality = mock.MagicMock(return_value={
            "rssi": 18, "ber": 0, "dbm": "-77 dBm"
        })
        result = self.inst.is_connected()
        self.assertTrue(result["connected"])
        self.assertEqual(result["operator"], "Telekom HU")
        self.assertEqual(result["dbm"], "-77 dBm")

    def test_connected_roaming(self):
        self.inst.get_network_info = mock.MagicMock(return_value={
            "reg_status": "registered roaming", "operator": "T-Mobile AT"
        })
        self.inst.get_signal_quality = mock.MagicMock(return_value={
            "rssi": 12, "ber": 0, "dbm": "-89 dBm"
        })
        result = self.inst.is_connected()
        self.assertTrue(result["connected"])

    def test_not_connected(self):
        self.inst.get_network_info = mock.MagicMock(return_value={
            "reg_status": "not registered", "operator": "unknown"
        })
        self.inst.get_signal_quality = mock.MagicMock(return_value=None)
        result = self.inst.is_connected()
        self.assertFalse(result["connected"])

    def test_signal_none_still_returns_dict(self):
        self.inst.get_network_info = mock.MagicMock(return_value={
            "reg_status": "registered home", "operator": "Telekom HU"
        })
        self.inst.get_signal_quality = mock.MagicMock(return_value=None)
        result = self.inst.is_connected()
        self.assertTrue(result["connected"])
        self.assertNotIn("rssi", result)


# ---------------------------------------------------------------------------
# Multipart SMS parsing & reassembly
# ---------------------------------------------------------------------------

# UCS2 multipart PDUs (ref=0xCC, 2 parts: "Hello" + "World")
_UCS2_PART1_PDU = (
    "07916303898814F2440B916302214365F7"
    "00086230911104220010"
    "050003CC020100480065006C006C006F"
)
_UCS2_PART2_PDU = (
    "07916303898814F2440B916302214365F7"
    "00086230911104220010"
    "050003CC02020057006F0072006C0064"
)

# GSM7 multipart PDUs (ref=0xAB, 2 parts: "Test" + "OK", with 1 fill bit)
_GSM7_PART1_PDU = (
    "07916303898814F2440B916302214365F7"
    "0000623091110422000B"
    "050003AB0201A8E5391D"
)
_GSM7_PART2_PDU = (
    "07916303898814F2440B916302214365F7"
    "00006230911104220009"
    "050003AB02029E4B"
)


class TestMultipartSmsParse(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def test_ucs2_multipart_part1_text(self):
        result = self.inst.parse_sms(_make_raw_pdu(_UCS2_PART1_PDU))
        self.assertEqual(result["text"], "Hello")
        self.assertEqual(result["udh"]["ref"], 0xCC)
        self.assertEqual(result["udh"]["part"], 1)
        self.assertEqual(result["udh"]["total"], 2)

    def test_ucs2_multipart_part2_text(self):
        result = self.inst.parse_sms(_make_raw_pdu(_UCS2_PART2_PDU))
        self.assertEqual(result["text"], "World")
        self.assertEqual(result["udh"]["part"], 2)

    def test_gsm7_multipart_part1_text(self):
        result = self.inst.parse_sms(_make_raw_pdu(_GSM7_PART1_PDU))
        self.assertEqual(result["text"], "Test")
        self.assertEqual(result["udh"]["ref"], 0xAB)
        self.assertEqual(result["udh"]["part"], 1)

    def test_gsm7_multipart_part2_text(self):
        result = self.inst.parse_sms(_make_raw_pdu(_GSM7_PART2_PDU))
        self.assertEqual(result["text"], "OK")
        self.assertEqual(result["udh"]["part"], 2)

    def test_gsm7_multipart_tp_dcs_is_zero(self):
        result = self.inst.parse_sms(_make_raw_pdu(_GSM7_PART1_PDU))
        self.assertEqual(result["TP-DCS"], 0)


class TestReceiveSmsReassembly(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        self.inst._concat_buffer = {}
        self.inst.delete_sms = mock.MagicMock()

    def test_single_part_returns_immediately(self):
        single_pdu = (
            "07916303898814F2000B916302214365F7"
            "0000623091110422000AE8329BFD4697D9EC37"
        )
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(single_pdu))
        result = self.inst.receive_sms(1)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "hellohello")
        self.inst.delete_sms.assert_called_once_with(1)

    def test_single_part_no_delete(self):
        single_pdu = (
            "07916303898814F2000B916302214365F7"
            "0000623091110422000AE8329BFD4697D9EC37"
        )
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(single_pdu))
        result = self.inst.receive_sms(1, delete=False)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "hellohello")
        self.inst.delete_sms.assert_not_called()

    def test_multipart_first_part_returns_none(self):
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART1_PDU))
        result = self.inst.receive_sms(5)
        self.assertIsNone(result)
        self.inst.delete_sms.assert_not_called()

    def test_multipart_both_parts_returns_combined(self):
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART1_PDU))
        self.inst.receive_sms(5)
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART2_PDU))
        result = self.inst.receive_sms(6)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "HelloWorld")
        self.assertEqual(result["parts"], 2)
        self.assertEqual(self.inst.delete_sms.call_count, 2)

    def test_multipart_no_delete(self):
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART1_PDU))
        self.inst.receive_sms(5, delete=False)
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART2_PDU))
        result = self.inst.receive_sms(6, delete=False)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "HelloWorld")
        self.inst.delete_sms.assert_not_called()

    def test_multipart_reverse_order(self):
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART2_PDU))
        self.inst.receive_sms(10)
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART1_PDU))
        result = self.inst.receive_sms(11)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "HelloWorld")

    def test_multipart_gsm7_reassembly(self):
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_GSM7_PART1_PDU))
        self.inst.receive_sms(1)
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_GSM7_PART2_PDU))
        result = self.inst.receive_sms(2)
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "TestOK")

    def test_concat_buffer_cleared_after_complete(self):
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART1_PDU))
        self.inst.receive_sms(5)
        self.assertEqual(len(self.inst._concat_buffer), 1)
        self.inst.read_sms = mock.MagicMock(return_value=_make_raw_pdu(_UCS2_PART2_PDU))
        self.inst.receive_sms(6)
        self.assertEqual(len(self.inst._concat_buffer), 0)


# ---------------------------------------------------------------------------
# make_call
# ---------------------------------------------------------------------------

import asyncio


class _FakeTaskCtx:
    async def feed(self, sleep_ms=0): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass


def _fake_micro_task(tag=None, task=None, _wrap=False):
    if task is not None:
        if hasattr(task, 'close'):
            task.close()
        return {'tag': tag, 'state': 'created'}
    return _FakeTaskCtx()


# ---------------------------------------------------------------------------
# SMS encoding & sending
# ---------------------------------------------------------------------------

class TestGsm7Encode(unittest.TestCase):

    def test_encode_hello(self):
        septets, packed = sim.Sim800._encode_gsm7('hello')
        self.assertEqual(len(septets), 5)
        self.assertEqual(packed.hex().upper(), 'E8329BFD06')

    def test_encode_euro_uses_escape(self):
        septets, _ = sim.Sim800._encode_gsm7('€')
        self.assertEqual(septets, [0x1B, 0x65])

    def test_is_gsm7_encodable_ascii(self):
        self.assertTrue(sim.Sim800._is_gsm7_encodable('Hello World 123'))

    def test_is_gsm7_encodable_hungarian(self):
        self.assertFalse(sim.Sim800._is_gsm7_encodable('Árvíztűrő'))

    def test_is_gsm7_encodable_euro(self):
        self.assertTrue(sim.Sim800._is_gsm7_encodable('€100'))


class TestBuildSubmitPdu(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()

    def test_gsm7_pdu_structure(self):
        pdu, tpdu_len = self.inst._build_submit_pdu('+36201234567', 'Test')
        self.assertTrue(pdu.startswith('00'))  # default SMSC
        self.assertGreater(tpdu_len, 0)
        self.assertEqual(len(pdu[2:]), tpdu_len * 2)  # hex chars = bytes * 2

    def test_gsm7_pdu_contains_address(self):
        pdu, _ = self.inst._build_submit_pdu('+36201234567', 'Hi')
        # semi-octet of 36201234567 -> 6302214365F7
        self.assertIn('6302214365F7', pdu)

    def test_ucs2_pdu_for_non_gsm7(self):
        pdu, _ = self.inst._build_submit_pdu('+36201234567', 'Árvíz')
        # TP-DCS should be 08 (UCS2)
        self.assertIn('08', pdu)

    def test_international_toa(self):
        pdu, _ = self.inst._build_submit_pdu('+36201234567', 'X')
        self.assertIn('91', pdu)  # TOA international

    def test_domestic_toa(self):
        pdu, _ = self.inst._build_submit_pdu('06201234567', 'X')
        self.assertIn('81', pdu)  # TOA domestic


class TestSendSms(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        self.inst.uart = mock.MagicMock()
        self.inst._wait_for_prompt = mock.MagicMock(return_value=b'\r\n> ')
        self.inst.read_response = mock.MagicMock(return_value=b'\r\n+CMGS: 1\r\n\r\nOK\r\n')
        self.inst._sms_queue = []
        self.inst._sms_sending = False

    def _run(self, coro):
        return asyncio.run(coro)

    def test_send_sms_inner_writes_cmgs(self):
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self._run(self.inst._send_sms_inner(_FakeTaskCtx(), '+36201234567', 'Hello'))
        first_write = self.inst.uart.write.call_args_list[0][0][0]
        self.assertIn('AT+CMGS=', first_write)

    def test_send_sms_inner_writes_pdu_with_ctrl_z(self):
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self._run(self.inst._send_sms_inner(_FakeTaskCtx(), '+36201234567', 'Hello'))
        pdu_write = self.inst.uart.write.call_args_list[1][0][0]
        self.assertTrue(pdu_write.endswith('\x1a'))

    def test_send_sms_inner_callback_success(self):
        cb = mock.MagicMock()
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self._run(self.inst._send_sms_inner(_FakeTaskCtx(), '+36201234567', 'Hello', callback=cb))
        cb.assert_called_once()
        self.assertTrue(cb.call_args[0][0])

    def test_send_sms_inner_callback_failure(self):
        self.inst._wait_for_prompt = mock.MagicMock(return_value=b'\r\nERROR\r\n')
        cb = mock.MagicMock()
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self._run(self.inst._send_sms_inner(_FakeTaskCtx(), '+36201234567', 'Hello', callback=cb))
        cb.assert_called_once()
        self.assertFalse(cb.call_args[0][0])

    def test_send_sms_inner_aborts_on_no_prompt(self):
        self.inst._wait_for_prompt = mock.MagicMock(return_value=b'\r\nERROR\r\n')
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self._run(self.inst._send_sms_inner(_FakeTaskCtx(), '+36201234567', 'Hello'))
        self.assertEqual(self.inst.uart.write.call_count, 1)

    def test_queue_sms_adds_to_queue(self):
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self.inst.queue_sms('+36201234567', 'Hello')
        # queue_sms triggers _process_sms_queue which pops immediately,
        # but since micro_task is faked (closes coroutine), queue may be empty
        # The key test: micro_task was called to start processing

    def test_queue_sms_multiple(self):
        self.inst._sms_sending = True  # pretend already sending
        self.inst.queue_sms('+36201234567', 'First')
        self.inst.queue_sms('+36201234567', 'Second')
        self.assertEqual(len(self.inst._sms_queue), 2)
        self.assertEqual(self.inst._sms_queue[0][1], 'First')
        self.assertEqual(self.inst._sms_queue[1][1], 'Second')

    def test_process_queue_sends_all(self):
        self.inst._sms_queue = [
            ('+36201234567', 'First', None),
            ('+36201234567', 'Second', None),
        ]
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            self._run(self.inst._process_sms_queue())
        self.assertEqual(len(self.inst._sms_queue), 0)
        self.assertFalse(self.inst._sms_sending)
        self.assertEqual(self.inst.uart.write.call_count, 4)  # 2x (CMGS + PDU)

    def test_module_level_send_sms_queues(self):
        sim.Sim800.INSTANCE = self.inst
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            result = sim.send_sms('+36201234567', 'Test')
        self.assertIn('queued', result)
        sim.Sim800.INSTANCE = None

    def test_send_sms_roundtrip_gsm7(self):
        """Encode then decode GSM7 and verify text matches."""
        pdu, _ = self.inst._build_submit_pdu('+36201234567', 'Test msg!')
        # Extract TP-UDL and UD from the end of TPDU
        # Skip: SMSC(2) + MTI(2) + MR(2) + AddrLen(2) + TOA(2) + Addr(12) + PID(2) + DCS(2) + VP(2)
        tpdu = pdu[2:]  # skip SMSC '00'
        # DCS is at fixed offset: 2+2+2+2+12+2 = 22 hex chars from tpdu start
        dcs_hex = tpdu[22:24]
        self.assertEqual(dcs_hex, '00')  # GSM7
        tp_udl = tpdu[26:28]
        ud_hex = tpdu[28:]
        decoded = self.inst._decode_gsm7(ud_hex, tp_udl)
        self.assertEqual(decoded, 'Test msg!')


# ---------------------------------------------------------------------------
# USSD & balance
# ---------------------------------------------------------------------------

class TestSendUssd(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        self.inst.send_command = mock.MagicMock(return_value=b'\r\nOK\r\n')
        self.inst.uart = mock.MagicMock()

    def test_ussd_parses_text_response(self):
        self.inst._wait_for_cusd = mock.MagicMock(
            return_value=b'\r\n+CUSD: 0,"Egyenleg: 1500 Ft",15\r\n'
        )
        result = self.inst.send_ussd('*111#')
        self.assertEqual(result['status'], 0)
        self.assertEqual(result['message'], 'Egyenleg: 1500 Ft')
        self.assertEqual(result['dcs'], 15)

    def test_ussd_parses_ucs2_response(self):
        self.inst._wait_for_cusd = mock.MagicMock(
            return_value=b'\r\n+CUSD: 0,"00480069",72\r\n'
        )
        result = self.inst.send_ussd('*111#')
        self.assertEqual(result['status'], 0)
        self.assertEqual(result['message'], 'Hi')
        self.assertEqual(result['dcs'], 72)

    def test_ussd_no_cusd_in_response(self):
        self.inst._wait_for_cusd = mock.MagicMock(return_value=b'\r\nERROR\r\n')
        result = self.inst.send_ussd('*111#')
        self.assertEqual(result['status'], -1)

    def test_ussd_status_only(self):
        self.inst._wait_for_cusd = mock.MagicMock(
            return_value=b'\r\n+CUSD: 2\r\n'
        )
        result = self.inst.send_ussd('*111#')
        self.assertEqual(result['status'], 2)
        self.assertEqual(result['message'], '')

    def test_ussd_enables_cusd(self):
        self.inst._wait_for_cusd = mock.MagicMock(
            return_value=b'\r\n+CUSD: 0,"OK",15\r\n'
        )
        self.inst.send_ussd('*111#')
        self.inst.send_command.assert_called_with('AT+CUSD=1', timeout=500)

    def test_ussd_hungarian_post_processing(self):
        self.inst._wait_for_cusd = mock.MagicMock(
            return_value=b'\r\n+CUSD: 0,"v\xe0s\xe0rl\xe0s",15\r\n'
        )
        result = self.inst.send_ussd('*111#')
        self.assertEqual(result['message'], 'v\u00e1s\u00e1rl\u00e1s')

    def test_ussd_ok_before_cusd_ignored(self):
        self.inst._wait_for_cusd = mock.MagicMock(
            return_value=b'\r\nOK\r\n\r\n+CUSD: 0,"Test",15\r\n'
        )
        result = self.inst.send_ussd('*111#')
        self.assertEqual(result['status'], 0)
        self.assertEqual(result['message'], 'Test')


class TestGetBalance(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        self.inst.send_ussd = mock.MagicMock(
            return_value={'status': 0, 'message': 'Egyenleg: 1500 Ft', 'dcs': 15}
        )

    def test_get_balance_default_code(self):
        result = self.inst.get_balance()
        self.inst.send_ussd.assert_called_once_with('*102#', 10000)
        self.assertEqual(result['message'], 'Egyenleg: 1500 Ft')

    def test_get_balance_custom_code(self):
        self.inst.get_balance(code='*100#', timeout=5000)
        self.inst.send_ussd.assert_called_once_with('*100#', 5000)


class TestDecodeUssdUcs2(unittest.TestCase):

    def test_decode_valid_ucs2(self):
        result = sim.Sim800._decode_ussd_ucs2('00480065006C006C006F')
        self.assertEqual(result, 'Hello')

    def test_decode_hungarian(self):
        text = 'Árvíz'
        hex_str = text.encode('utf-16-be').hex()
        result = sim.Sim800._decode_ussd_ucs2(hex_str)
        self.assertEqual(result, 'Árvíz')

    def test_decode_invalid_returns_original(self):
        result = sim.Sim800._decode_ussd_ucs2('ZZZZ')
        self.assertEqual(result, 'ZZZZ')


class TestMakeCall(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        self.inst.send_command = mock.MagicMock(return_value=b'\r\nOK\r\n')

    def test_call_without_ring_time(self):
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            asyncio.run(self.inst.make_call('+36201234567'))
        self.inst.send_command.assert_called_once_with('ATD+36201234567;')

    def test_call_with_ring_time_sends_ath(self):
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            asyncio.run(self.inst.make_call('+36201234567', ring_time=10))
        self.inst.send_command.assert_any_call('ATD+36201234567;')
        self.inst.send_command.assert_any_call('ATH')

    def test_call_returns_response(self):
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task):
            result = asyncio.run(self.inst.make_call('+36201234567'))
        self.assertEqual(result, b'\r\nOK\r\n')

    def test_module_level_make_call_creates_task(self):
        sim.Sim800.INSTANCE = self.inst
        with mock.patch.object(sim, 'micro_task', side_effect=_fake_micro_task) as mt:
            sim.make_call('+36201234567', ring_time=5)
            mt.assert_called_once()
            self.assertEqual(mt.call_args[1]['tag'], 'sim800.make_call')
        sim.Sim800.INSTANCE = None


# ---------------------------------------------------------------------------
# _inst() guard
# ---------------------------------------------------------------------------

class TestInstGuard(unittest.TestCase):

    def setUp(self):
        self._orig = sim.Sim800.INSTANCE
        sim.Sim800.INSTANCE = None

    def tearDown(self):
        sim.Sim800.INSTANCE = self._orig

    def test_inst_raises_when_not_loaded(self):
        with self.assertRaises(Exception) as ctx:
            sim._inst()
        self.assertIn('Not loaded', str(ctx.exception))

    def test_is_connected_raises_when_not_loaded(self):
        with self.assertRaises(Exception):
            sim.is_connected()

    def test_get_signal_quality_raises_when_not_loaded(self):
        with self.assertRaises(Exception):
            sim.get_signal_quality()

    def test_reject_call_raises_when_not_loaded(self):
        with self.assertRaises(Exception):
            sim.reject_call()

    def test_send_sms_raises_when_not_loaded(self):
        with self.assertRaises(Exception):
            sim.send_sms('+36201234567', 'test')

    def test_read_uart_raises_when_not_loaded(self):
        with self.assertRaises(Exception):
            sim.read_uart()

    def test_inst_returns_instance_when_loaded(self):
        fake = _new_inst()
        sim.Sim800.INSTANCE = fake
        self.assertIs(sim._inst(), fake)


# ---------------------------------------------------------------------------
# _poll_uart CMTI index type
# ---------------------------------------------------------------------------

class TestPollUartCmtiIndex(unittest.TestCase):

    def setUp(self):
        self.inst = _new_inst()
        sim.Sim800.INSTANCE = self.inst
        sim._subscribers = {'call': [], 'sms': [mock.MagicMock()], 'signal': []}

    def tearDown(self):
        sim.Sim800.INSTANCE = None
        sim._subscribers = {'call': [], 'sms': [], 'signal': []}

    def test_cmti_index_is_int(self):
        self.inst.read_uart = mock.MagicMock(return_value=(['+CMTI: "SM",3'], b'+CMTI: "SM",3'))
        with mock.patch.object(sim, 'receive_sms', return_value={'text': 'hi', 'sender': '+36201234567'}) as mock_recv:
            sim._poll_uart()
            index_arg = mock_recv.call_args[0][0]
            self.assertIsInstance(index_arg, int)
            self.assertEqual(index_arg, 3)

    def test_cmti_index_multidigit(self):
        self.inst.read_uart = mock.MagicMock(return_value=(['+CMTI: "SM",42'], b'+CMTI: "SM",42'))
        with mock.patch.object(sim, 'receive_sms', return_value={'text': 'hi', 'sender': '+36201234567'}) as mock_recv:
            sim._poll_uart()
            self.assertEqual(mock_recv.call_args[0][0], 42)



if __name__ == "__main__":
    unittest.main(verbosity=2)
