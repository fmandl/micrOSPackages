import time
from machine import Pin, UART
from Common import console, micro_task
from microIO import bind_pin, pinmap_search
from Types import resolve

# Event subscribers: {'call': [cb, ...], 'sms': [cb, ...], 'signal': [cb, ...]}
_subscribers = {'call': [], 'sms': [], 'signal': []}


class Sim800:
    INSTANCE = None
    SMS_STATUS = {'0': 'REC UNREAD', '1': 'REC READ', '2': 'STO UNSENT', '3': 'STO SENT', '4': 'ALL'}
    GSM7_BASIC = {
        0x00: '@', 0x01: '£', 0x02: '$', 0x03: '¥', 0x04: 'è', 0x05: 'é', 0x06: 'ù', 0x07: 'ì',
        0x08: 'ò', 0x09: 'Ç', 0x0A: '\n', 0x0B: 'Ø', 0x0C: 'ø', 0x0D: '\r', 0x0E: 'Å', 0x0F: 'å',
        0x10: 'Δ', 0x11: '_', 0x12: 'Φ', 0x13: 'Γ', 0x14: 'Λ', 0x15: 'Ω', 0x16: 'Π', 0x17: 'Ψ',
        0x18: 'Σ', 0x19: 'Θ', 0x1A: 'Ξ', 0x1B: None,
        0x1C: 'Æ', 0x1D: 'æ', 0x1E: 'ß', 0x1F: 'É',
        0x20: ' ', 0x21: '!', 0x22: '"', 0x23: '#', 0x24: '¤', 0x25: '%', 0x26: '&', 0x27: "'",
        0x28: '(', 0x29: ')', 0x2A: '*', 0x2B: '+', 0x2C: ',', 0x2D: '-', 0x2E: '.', 0x2F: '/',
        0x30: '0', 0x31: '1', 0x32: '2', 0x33: '3', 0x34: '4', 0x35: '5', 0x36: '6', 0x37: '7',
        0x38: '8', 0x39: '9', 0x3A: ':', 0x3B: ';', 0x3C: '<', 0x3D: '=', 0x3E: '>', 0x3F: '?',
        0x40: '¡', 0x41: 'A', 0x42: 'B', 0x43: 'C', 0x44: 'D', 0x45: 'E', 0x46: 'F', 0x47: 'G',
        0x48: 'H', 0x49: 'I', 0x4A: 'J', 0x4B: 'K', 0x4C: 'L', 0x4D: 'M', 0x4E: 'N', 0x4F: 'O',
        0x50: 'P', 0x51: 'Q', 0x52: 'R', 0x53: 'S', 0x54: 'T', 0x55: 'U', 0x56: 'V', 0x57: 'W',
        0x58: 'X', 0x59: 'Y', 0x5A: 'Z', 0x5B: 'Ä', 0x5C: 'Ö', 0x5D: 'Ñ', 0x5E: 'Ü', 0x5F: '§',
        0x60: '¿', 0x61: 'a', 0x62: 'b', 0x63: 'c', 0x64: 'd', 0x65: 'e', 0x66: 'f', 0x67: 'g',
        0x68: 'h', 0x69: 'i', 0x6A: 'j', 0x6B: 'k', 0x6C: 'l', 0x6D: 'm', 0x6E: 'n', 0x6F: 'o',
        0x70: 'p', 0x71: 'q', 0x72: 'r', 0x73: 's', 0x74: 't', 0x75: 'u', 0x76: 'v', 0x77: 'w',
        0x78: 'x', 0x79: 'y', 0x7A: 'z', 0x7B: 'ä', 0x7C: 'ö', 0x7D: 'ñ', 0x7E: 'ü', 0x7F: 'à'
    }
    GSM7_EXT = {
        0x0A: '\f', 0x14: '^', 0x28: '{', 0x29: '}', 0x2F: '\\', 0x3C: '[', 0x3D: '~',
        0x3E: ']', 0x40: '|', 0x65: '€'
    }

    # GSM7 does not include á,ó,ú,ő,ű — carriers substitute the closest GSM7 char.
    # This map reverses common substitutions for Hungarian text.
    GSM7_HU_POST = {
        'à': 'á', 'ò': 'ó', 'ù': 'ú',
        'À': 'Á', 'Ò': 'Ó', 'Ù': 'Ú',
    }

    def __init__(self, pin_code, tx_pin, rx_pin, ri_pin):
        self.uart_no = 1
        self.sim_pin_code = str(pin_code)
        self.baudrate = 115200
        self.tx_pin = Pin(bind_pin("sim800_tx", tx_pin))
        self.rx_pin = Pin(bind_pin("sim800_rx", rx_pin))
        self.ri_pin = Pin(bind_pin("sim800_ri", ri_pin), Pin.IN, Pin.PULL_UP)
        self._ri_triggered = False
        self.ri_pin.irq(trigger=Pin.IRQ_FALLING, handler=self._ri_handler)
        self._concat_buffer = {}  # {ref: {total, sender, meta, parts: {part_no: text}}}
        self._sms_queue = []       # [(number, text, callback), ...]
        self._sms_sending = False

    def _ri_handler(self, pin):
        """RI interrupt handler — called on falling edge when SIM800 has data."""
        self._ri_triggered = True

    def _unlock_sim(self, responses):
        """Unlock SIM card with PIN code."""
        responses.append(self.send_command('AT+CPIN?'))                                 # Check PIN status
        if b'READY' not in responses[-1]:
            responses.append(self.send_command(f'AT+CPIN="{self.sim_pin_code}"'))       # Set PIN
            time.sleep(5)                                                               # Waiting delay for reconnection after PIN entry
            responses.append(self.send_command('AT+CPIN?'))                             # Check PIN status
            if b'READY' not in responses[-1]:
                raise Exception("SIM PIN not accepted")

    def _init_modem(self, responses):
        """Initialize modem settings (echo, CLIP, PDU mode, etc)."""
        responses.append(self.send_command('ATE0'))                                     # Turn off command echoing
        responses.append(self.send_command('AT+CFUN=1'))                                # Set full functionality mode
        responses.append(self.send_command('AT+CLIP=1'))                                # Enable Calling Line Identification Presentation (CLIP)
        responses.append(self.send_command('AT+CLIR=2'))                                # CLIR: use network default (show caller ID)
        responses.append(self.send_command('AT+CMGF=0'))                                # Select SMS message format (0=PDU mode, 1=Text mode)
        responses.append(self.send_command('AT+CPMS="SM"'))                             # Store SMS in SIM memory
        responses.append(self.send_command('AT+CREG?'))                                 # Check if sim800 is registered to the mobile network
        responses.append(self.send_command('AT+CSQ'))                                   # Check RSSI
        responses.append(self.send_command('AT+CFGRI=1'))                               # Enable RI pin for incoming data

    def connect(self, retries=5, retry_delay=2):
        """Connect to modem, unlock SIM and initialize.
        :param retries int: number of AT retries
        :param retry_delay int: seconds between retries
        :return bool: True on success
        """
        responses = []
        try:
            self.uart = UART(self.uart_no, baudrate=self.baudrate, tx=self.tx_pin, rx=self.rx_pin)
            for attempt in range(retries):
                resp = self.send_command('AT')
                responses.append(resp)
                if b'OK' in resp:
                    break
                console(f"SIM800 not ready, retry {attempt + 1}/{retries}")
                time.sleep(retry_delay)
            else:
                raise Exception("SIM800 not responding after retries")
            responses.append(self.send_command('AT+CMEE=2'))
            self._unlock_sim(responses)
            self._init_modem(responses)
            for resp in responses:
                console(resp)
            return True
        except Exception as e:
            responses.append(f"exception: {e}")
            for resp in responses:
                console(resp)
            return False

    def send_command(self, command, timeout=1000):
        """
        Send an AT command and return the raw response bytes.
        :param command str: AT command to send
        :param timeout int: response timeout in ms
        :return bytes: raw response
        """
        self.uart.write(command + '\r')
        time.sleep(0.1)  # Delay to allow command processing
        return self.read_response(timeout)

    def _read_raw(self, timeout=1000):
        """Read raw bytes from UART until OK/ERROR or timeout.
        :param timeout int: timeout in ms
        :return bytes: raw response
        """
        start_time = time.ticks_ms()
        response = bytearray()
        while time.ticks_diff(time.ticks_ms(), start_time) < timeout:
            if self.uart.any():
                chunk = self.uart.read(self.uart.any())
                if chunk:
                    response.extend(chunk)
                    if b'OK' in response or b'ERROR' in response:
                        break
            time.sleep(0.1)
        return bytes(response)

    def read_response(self, timeout=1000):
        """
        Read raw bytes from UART with timeout.
        :param timeout int: timeout in ms
        :return bytes: raw response
        """
        return self._read_raw(timeout)

    def read_uart(self):
        """
        Read and decode pending UART data into a list of lines.
        :return tuple|False: (lines_list, raw_bytes) or False if no data
        """
        if not self.uart.any():
            return False
        data = self._read_raw(timeout=300)
        if not data:
            return False
        try:
            return data.decode().strip().split('\r\n'), data
        except (UnicodeError, ValueError):
            return None, data

    def reset(self):
        """
        Hard reset the SIM800 module via AT+CFUN=1,1.
        """
        console(self.send_command('AT+CFUN=1,1'))               # Reset the module
        time.sleep(10)

    def get_sms(self, option):
        """
        List SMS messages from SIM memory.
        :param option int: message status filter (e.g. 4 = ALL)
        :return bytes: raw response
        """
        return self.send_command(f'AT+CMGL={option}')

    def read_sms(self, index):
        """
        Read a single SMS by index.
        :param index int: SIM memory index
        :return bytes: raw PDU response
        """
        return self.send_command(f'AT+CMGR={index}')

    def delete_sms(self, index):
        """
        Delete a single SMS by index.
        :param index int: SIM memory index
        :return bytes: raw response
        """
        return self.send_command(f'AT+CMGD={index}')

    def clear_sms(self, mode):
        """
        Delete all SMS messages by mode.
        :param mode int: delete mode (e.g. 6 = delete all)
        :return bytes: raw response
        """
        return self.send_command(f'AT+CMGDA={mode}')

    @staticmethod
    def _number_to_semi_octet(number):
        """Encode phone number to semi-octet PDU format."""
        digits = number.lstrip('+')
        if len(digits) % 2:
            digits += 'F'
        return ''.join(digits[i+1] + digits[i] for i in range(0, len(digits), 2))

    @staticmethod
    def _encode_gsm7(text):
        """Encode text to GSM7 septets and packed bytes.
        :return tuple: (septet list, packed bytearray)
        """
        GSM7_REV = {v: k for k, v in Sim800.GSM7_BASIC.items() if v is not None}
        GSM7_EXT_REV = {v: k for k, v in Sim800.GSM7_EXT.items()}
        septets = []
        for ch in text:
            if ch in GSM7_EXT_REV:
                septets.append(0x1B)
                septets.append(GSM7_EXT_REV[ch])
            else:
                septets.append(GSM7_REV.get(ch, 0x3F))  # '?' for unknown
        bit_acc = 0
        num_bits = 0
        result = bytearray()
        for s in septets:
            bit_acc |= s << num_bits
            num_bits += 7
            while num_bits >= 8:
                result.append(bit_acc & 0xFF)
                bit_acc >>= 8
                num_bits -= 8
        if num_bits > 0:
            result.append(bit_acc & 0xFF)
        return septets, result

    @staticmethod
    def _is_gsm7_encodable(text):
        """Check if text can be encoded in GSM7 default alphabet."""
        GSM7_REV = {v for v in Sim800.GSM7_BASIC.values() if v is not None}
        GSM7_EXT_REV = set(Sim800.GSM7_EXT.values())
        return all(ch in GSM7_REV or ch in GSM7_EXT_REV for ch in text)

    def _build_submit_pdu(self, number, text):
        """Build SMS-SUBMIT PDU for sending.
        :param number str: destination phone number
        :param text str: message text
        :return tuple: (pdu_hex_string, tpdu_length_in_bytes)
        """
        smsc = '00'  # use default SMSC
        tp_mti = 0x11  # SMS-SUBMIT, TP-VPF=relative
        tp_mr = '00'  # message reference
        toa = '91' if number.startswith('+') else '81'
        addr_digits = number.lstrip('+')
        addr_len = '%02X' % len(addr_digits)
        addr_val = self._number_to_semi_octet(number)
        tp_pid = '00'
        tp_vp = 'AA'  # validity period: 4 days
        if self._is_gsm7_encodable(text):
            tp_dcs = '00'
            septets, packed = self._encode_gsm7(text)
            tp_udl = '%02X' % len(septets)
            ud = packed.hex().upper()
        else:
            tp_dcs = '08'  # UCS2
            encoded = bytearray()
            for ch in text:
                cp = ord(ch)
                if cp > 0xFFFF:
                    high = 0xD800 + ((cp - 0x10000) >> 10)
                    low = 0xDC00 + ((cp - 0x10000) & 0x3FF)
                    encoded.append(high >> 8); encoded.append(high & 0xFF)
                    encoded.append(low >> 8); encoded.append(low & 0xFF)
                else:
                    encoded.append(cp >> 8); encoded.append(cp & 0xFF)
            tp_udl = '%02X' % len(encoded)
            ud = encoded.hex().upper()
        tpdu = '%02X' % tp_mti + tp_mr + addr_len + toa + addr_val + tp_pid + tp_dcs + tp_vp + tp_udl + ud
        return smsc + tpdu, len(tpdu) // 2

    def _wait_for_prompt(self, prompt=b'>', timeout=3000):
        """Wait for a specific prompt byte sequence from UART.
        :param prompt bytes: prompt to wait for
        :param timeout int: timeout in ms
        :return bytes: raw response
        """
        start_time = time.ticks_ms()
        response = bytearray()
        while time.ticks_diff(time.ticks_ms(), start_time) < timeout:
            if self.uart.any():
                chunk = self.uart.read(self.uart.any())
                if chunk:
                    response.extend(chunk)
                    if prompt in response or b'ERROR' in response:
                        break
            time.sleep(0.1)
        return bytes(response)

    def queue_sms(self, number, text, callback=None):
        """
        Add SMS to send queue. Starts processing if not already running.
        :param number str: destination phone number
        :param text str: message text
        :param callback func|None: called with (bool success, str detail) when done
        """
        self._sms_queue.append((number, text, callback))
        if not self._sms_sending:
            micro_task(tag='sim800.sms_queue', task=self._process_sms_queue())

    async def _process_sms_queue(self):
        """Process queued SMS messages one by one (async)."""
        with micro_task(tag='sim800.sms_queue') as my_task:
            self._sms_sending = True
            try:
                while self._sms_queue:
                    number, text, callback = self._sms_queue.pop(0)
                    await self._send_sms_inner(my_task, number, text, callback)
            finally:
                self._sms_sending = False

    async def _send_sms_inner(self, my_task, number, text, callback=None):
        """Send a single SMS in PDU mode.
        :param my_task: micro_task context for async yield
        :param number str: destination phone number
        :param text str: message text
        :param callback func|None: called with (bool success, str detail)
        :return bytes: raw response
        """
        pdu, tpdu_len = self._build_submit_pdu(number, text)
        self.uart.write(f'AT+CMGS={tpdu_len}\r')
        prompt = self._wait_for_prompt()
        if b'>' not in prompt:
            console(f"send_sms: no prompt, got: {prompt}")
            if callback:
                callback(False, str(prompt).strip())
            return prompt
        await my_task.feed(sleep_ms=100)
        self.uart.write(pdu + '\x1a')
        resp = self.read_response(timeout=10000)
        if callback:
            ok = b'+CMGS' in resp
            callback(ok, str(resp).strip())
        return resp

    def send_ussd(self, code, timeout=10000):
        """
        Send a USSD request and return the parsed response.
        :param code str: USSD code (e.g. '*102#')
        :param timeout int: response timeout in ms
        :return dict: status (int), message (str), dcs (int) or error string
        """
        self.send_command('AT+CUSD=1', timeout=500)
        self.uart.write(f'AT+CUSD=1,"{code}",15\r')
        resp = self._wait_for_cusd(timeout=timeout)
        try:
            text = ''.join(chr(b) for b in resp)
            if '+CUSD' not in text:
                return {'status': -1, 'message': text.strip()}
            cusd_line = text[text.index('+CUSD'):]
            cusd_line = cusd_line.split('\r')[0].split('\n')[0]
            inner = cusd_line[cusd_line.index(':') + 1:].strip()
            parts = inner.split(',', 2)
            status = int(parts[0].strip())
            message = parts[1].strip().strip('"') if len(parts) > 1 else ''
            dcs = int(parts[2].strip()) if len(parts) > 2 else 0
            if dcs == 72:
                message = self._decode_ussd_ucs2(message)
            elif dcs == 15:
                message = ''.join(self.GSM7_HU_POST.get(c, c) for c in message)
            return {'status': status, 'message': message, 'dcs': dcs}
        except Exception as e:
            console(f"send_ussd parse error: {e}")
            return {'status': -1, 'message': str(resp).strip()}

    def _wait_for_cusd(self, timeout=10000):
        """Wait for +CUSD response from UART.
        :param timeout int: timeout in ms
        :return bytes: raw response
        """
        start_time = time.ticks_ms()
        response = bytearray()
        while time.ticks_diff(time.ticks_ms(), start_time) < timeout:
            if self.uart.any():
                chunk = self.uart.read(self.uart.any())
                if chunk:
                    response.extend(chunk)
                    if b'+CUSD' in response and (b'\r\n' in response[response.index(b'+CUSD')+5:]):
                        break
                    if b'ERROR' in response:
                        break
            time.sleep(0.1)
        return bytes(response)

    @staticmethod
    def _decode_ussd_ucs2(hex_str):
        """Decode UCS2 hex string from USSD response.
        :param hex_str str: hex-encoded UCS2 string
        :return str: decoded text
        """
        try:
            return bytes.fromhex(hex_str).decode('utf-16-be')
        except Exception:
            return hex_str

    def get_balance(self, code='*102#', timeout=10000):
        """
        Query prepaid balance via USSD.
        :param code str: USSD balance code (default: *102# for Telekom HU)
        :param timeout int: response timeout in ms
        :return dict: status, message, dcs
        """
        return self.send_ussd(code, timeout)

    @staticmethod
    def _semi_octet_to_number(hex_str):
        """Decode semi-octet PDU format to phone number string."""
        s = hex_str.strip().upper()
        swapped = ''.join(s[i+1] + s[i] for i in range(0, len(s)-1, 2))
        if len(s) % 2 == 1:
            swapped += s[-1]
        if swapped.endswith('F'):
            swapped = swapped[:-1]
        return swapped

    @staticmethod
    def _swap_pairs(hex_str):
        """Swap adjacent hex character pairs."""
        return ''.join(hex_str[i+1] + hex_str[i] for i in range(0, len(hex_str), 2))

    @staticmethod
    def _time_zone_offset(hex_str):
        """Parse timezone offset from PDU timestamp byte."""
        raw = int(hex_str, 16)
        sign = "-" if raw & 0x80 else "+"
        minutes = (int(Sim800._swap_pairs(hex_str), 16) & 0x7F) * 15
        return f"{sign}{minutes//60:02d}:{minutes%60:02d}"

    @staticmethod
    def _time_stamp_parse(hex_str):
        """Parse PDU timestamp to human-readable string."""
        swapped = Sim800._swap_pairs(hex_str)
        time_zone = Sim800._time_zone_offset(hex_str[12:14])
        return f"20{swapped[0:2]}-{swapped[2:4]}-{swapped[4:6]} {swapped[6:8]}:{swapped[8:10]}:{swapped[10:12]} {time_zone}"

    @staticmethod
    def _parse_udh(user_data_hex):
        """
        Parse User Data Header from hex string.
        :return tuple: (udh_dict, user_data_hex_without_udh) or (None, original_hex)
        """
        try:
            udh_len = int(user_data_hex[:2], 16)            # UDH length in bytes
            udh_bytes = bytes.fromhex(user_data_hex[2:2 + udh_len * 2])
            rest = user_data_hex[2 + udh_len * 2:]
            # find concatenated SMS IE (0x00 = 8-bit ref, 0x08 = 16-bit ref)
            i = 0
            while i < len(udh_bytes):
                ie_id = udh_bytes[i]
                ie_len = udh_bytes[i + 1]
                if ie_id == 0x00 and ie_len == 3:           # 8-bit reference
                    return {
                        'ref':   udh_bytes[i + 2],
                        'total': udh_bytes[i + 3],
                        'part':  udh_bytes[i + 4]
                    }, rest
                if ie_id == 0x08 and ie_len == 4:           # 16-bit reference
                    return {
                        'ref':   (udh_bytes[i + 2] << 8) | udh_bytes[i + 3],
                        'total': udh_bytes[i + 4],
                        'part':  udh_bytes[i + 5]
                    }, rest
                i += 2 + ie_len
        except Exception:
            pass
        return None, user_data_hex

    @staticmethod
    def _ceil_even_int(n):
        """Round up to nearest even integer."""
        return n + (n & 1)

    @staticmethod
    def _pad_hex(h):
        """Pad hex string to even length, strip spaces."""
        h2 = h.replace(" ", "")
        return h2 if len(h2) % 2 == 0 else "0" + h2

    def _decode_gsm7(self, user_data_hex, septet_len, fill_bits=0):
        """Decode GSM7 packed data to text.
        :param user_data_hex str: hex-encoded packed GSM7 data
        :param septet_len str: number of septets as hex string
        :param fill_bits int: UDH fill bits to skip
        :return str: decoded text
        """
        data = bytes.fromhex(self._pad_hex(user_data_hex))
        septet_len = int(septet_len, 16)
        bit_acc = 0
        bits_in_acc = 0
        out_chars = []
        byte_index = 0
        if fill_bits > 0:
            while bits_in_acc < fill_bits and byte_index < len(data):
                bit_acc |= data[byte_index] << bits_in_acc
                bits_in_acc += 8
                byte_index += 1
            bit_acc >>= fill_bits
            bits_in_acc -= fill_bits
        while len(out_chars) < septet_len:
            while bits_in_acc < 7 and byte_index < len(data):
                bit_acc |= data[byte_index] << bits_in_acc
                bits_in_acc += 8
                byte_index += 1
            if bits_in_acc == 0:
                break
            septet = bit_acc & 0x7F
            bit_acc >>= 7
            bits_in_acc -= 7
            if septet == 0x1B:
                while bits_in_acc < 7 and byte_index < len(data):
                    bit_acc |= data[byte_index] << bits_in_acc
                    bits_in_acc += 8
                    byte_index += 1
                if bits_in_acc == 0:
                    break
                ext_val = bit_acc & 0x7F
                bit_acc >>= 7
                bits_in_acc -= 7
                out_chars.append(self.GSM7_EXT.get(ext_val, '?'))
            else:
                out_chars.append(self.GSM7_BASIC.get(septet, '?'))
        return ''.join(out_chars)

    @staticmethod
    def _decode_utf16be_with_surrogates(b):
        """Decode UTF-16BE bytes with surrogate pair support.
        :param b bytes: UTF-16BE encoded bytes
        :return str: decoded text
        """
        chars = []
        i = 0
        while i < len(b):
            if i + 1 >= len(b):
                break
            code_unit = (b[i] << 8) | b[i+1]
            i += 2
            if 0xD800 <= code_unit <= 0xDBFF:
                if i + 1 >= len(b):
                    chars.append('?')
                    break
                next_code_unit = (b[i] << 8) | b[i+1]
                i += 2
                if 0xDC00 <= next_code_unit <= 0xDFFF:
                    code_point = ((code_unit - 0xD800) << 10) + (next_code_unit - 0xDC00) + 0x10000
                    chars.append(chr(code_point))
                else:
                    chars.append('?')
                    i -= 2
            else:
                chars.append(chr(code_unit))
        return ''.join(chars)

    @staticmethod
    def _decode_8bit_data(h, tp_udl=None):
        """Decode 8-bit data from hex string.
        :param h str: hex-encoded data
        :param tp_udl str|None: user data length as hex string
        :return bytes: decoded data
        """
        b = bytes.fromhex(Sim800._pad_hex(h.strip()))
        if tp_udl is not None:
            tp_udl = int(tp_udl, 16)
            b = b[:tp_udl] if tp_udl <= len(b) else b + b'\x00' * (tp_udl - len(b))
        return b

    def reject_call(self, busy=False):
        """
        Reject an incoming call.
        :param busy bool: True = send busy signal (AT+GSMBUSY=1), False = silent disconnect (ATH)
        :return bytes: raw response
        """
        if busy:
            return self.send_command('AT+GSMBUSY=1')
        return self.send_command('ATH')

    def get_signal_quality(self):
        """
        Query signal quality (RSSI and BER) from AT+CSQ.
        :return dict: rssi (int), ber (int), dbm (str) or None on parse error
        """
        resp = self.send_command('AT+CSQ')
        try:
            line = [l for l in resp.decode().split('\r\n') if '+CSQ' in l][0]
            rssi, ber = line.split(':')[1].strip().split(',')
            rssi, ber = int(rssi), int(ber)
            dbm = f"{-113 + rssi * 2} dBm" if rssi not in (0, 99) else 'unknown'
            return {'rssi': rssi, 'ber': ber, 'dbm': dbm}
        except Exception as e:
            console(f"get_signal_quality error: {e}")
            return None

    def get_network_info(self):
        """
        Query network registration status and operator name.
        :return dict: reg_status (str), operator (str) or None on parse error
        """
        reg_status_table = {
            '0': 'not registered',
            '1': 'registered home',
            '2': 'searching',
            '3': 'denied',
            '4': 'unknown',
            '5': 'registered roaming'
        }
        result = {}
        try:
            creg = self.send_command('AT+CREG?').decode()
            stat = [l for l in creg.split('\r\n') if '+CREG' in l][0]
            result['reg_status'] = reg_status_table.get(stat.split(',')[-1].strip(), 'unknown')
        except Exception as e:
            console(f"get_network_info CREG error: {e}")
            result['reg_status'] = 'unknown'
        try:
            cops = self.send_command('AT+COPS?').decode()
            stat = [l for l in cops.split('\r\n') if '+COPS' in l][0]
            parts = stat.split(':')[1].strip().split(',')
            operator = parts[2].strip().strip('"') if len(parts) > 2 else 'unknown'
            result['operator'] = operator
        except Exception as e:
            console(f"get_network_info COPS error: {e}")
            result['operator'] = 'unknown'
        return result

    def is_connected(self):
        """
        Check network registration and signal quality in one call.
        :return dict: connected (bool), reg_status (str), operator (str), rssi (int), ber (int), dbm (str)
        """
        network = self.get_network_info()
        signal = self.get_signal_quality()
        connected = network.get('reg_status') in ('registered home', 'registered roaming')
        result = {'connected': connected}
        result.update(network)
        if signal:
            result.update(signal)
        return result

    def parse_call_params(self, clip_line):
        """
        Parse a +CLIP UART line into a dict.
        :param clip_line str: the line containing +CLIP data
        :return dict: data_type, caller_number, type_of_address, caller_name, call_type, extra_info, status
        """
        try:
            result = {}
            parts = clip_line.split(',')
            data_type, _, caller_number = parts[0].partition(':')
            result['data_type'] = data_type.strip()
            result['caller_number'] = caller_number.strip().strip('"')
            result['type_of_address'] = parts[1].strip().strip('"')
            result['caller_name'] = parts[2].strip().strip('"') if len(parts) > 2 else ''
            result['call_type'] = parts[3].strip().strip('"') if len(parts) > 3 else ''
            result['extra_info'] = parts[4].strip().strip('"') if len(parts) > 4 else ''
            result['status'] = parts[5].strip().strip('"') if len(parts) > 5 else ''
            return result
        except Exception as e:
            console(f"parse_call_params error: {e}")
            return {}

    def parse_sms(self, raw_bytes):
        """
        Parse a raw PDU-mode SMS response into a dict.
        :param raw_bytes bytes: raw AT+CMGR response
        :return dict: sign, status, alpha, length, smsc, sender, time_stamp, TP-DCS, text, ...
        """
        result = {}
        try:
            msg = raw_bytes.decode('utf-8').strip()
            if msg.endswith('OK'):
                msg = msg[:-2].strip()
        except Exception as e:
            console(f"Error: {e}")
            return result
        try:
            result['sign'], rest = msg.split(':', 1)                                                # sign
            header, body = rest.strip().split('\r\n')
            status, alpha, length = header.split(',')
            result['status'] = self.SMS_STATUS[status]                                              # status
            result['alpha'] = alpha.strip('"')                                                      # alpha
            result['length'] = length
            smsc_length, toa, body = int(body[:2])-1, body[2:4], body[4:]
            smsc_type_of_number = '+' if ((int(toa, 16) >> 4) & 0x07) == 1 else ''                  # smsc type of number
            smsc_num, body = body[:2*smsc_length], body[2*smsc_length:]
            result['smsc'] = f"{smsc_type_of_number}{self._semi_octet_to_number(smsc_num)}"         # smsc
            tp_first_octet = int(body[:2], 16)
            result['TP-MTI'] = tp_first_octet & ~0x04                                               # TP-MTI    0 = SMS-DELIVER
            tp_udhi = bool(tp_first_octet & 0x40)                                                   # TP-UDHI bit
            rest = body[2:]
            tp_oa_length, toa, rest = self._ceil_even_int(int(rest[:2], 16)), rest[2:4], rest[4:]
            sender_type_of_number = '+' if ((int(toa, 16) >> 4) & 0x07) == 1 else ''                # sender type of number
            sender_num, rest = rest[:tp_oa_length], rest[tp_oa_length:]
            result['sender'] = f"{sender_type_of_number}{self._semi_octet_to_number(sender_num)}"   # sender
            result['TP-PID'], rest = rest[:2], rest[2:]                                             # TP-PID
            result['TP-DCS'], rest = (int(rest[:2], 16) >> 2) & 0x03, rest[2:]                      # TP-DCS    0 = GSM 7-bit, 1 = 8-bit data, 2 = USC2 (16-bit)
            time_stamp, rest = rest[:14], rest[14:]                                                 # time_stamp
            result['time_stamp'] = self._time_stamp_parse(time_stamp)
            result['TP-UDL'], rest = rest[:2], rest[2:]                                             # TP-UDL
            udh = None
            if tp_udhi:
                udh, rest = self._parse_udh(rest)
                result['udh'] = udh
                if result['TP-DCS'] == 0 and udh:                                                   # GSM7: UDH occupies ceil((udhl+1)*8/7) septets
                    udhl = 5 if udh.get('ref', 0) < 256 else 6                                      # 5 for 8-bit ref, 6 for 16-bit ref
                    udh_bits = (udhl + 1) * 8
                    udh_septets = (udh_bits + 6) // 7                                               # ceil(udh_bits/7)
                    result['TP-UDL'] = '%02X' % (int(result['TP-UDL'], 16) - udh_septets)
                    result['_fill_bits'] = (7 - (udh_bits % 7)) % 7
            fill_bits = result.pop('_fill_bits', 0)
            if result['TP-DCS'] == 0:
                text = self._decode_gsm7(rest, result['TP-UDL'], fill_bits)
                result['text'] = ''.join(self.GSM7_HU_POST.get(c, c) for c in text)
            elif result['TP-DCS'] == 1:
                result['text'] = self._decode_8bit_data(rest, result['TP-UDL'])
            elif result['TP-DCS'] == 2:
                result['text'] = self._decode_utf16be_with_surrogates(bytes.fromhex(rest))          # text (assuming UCS2 encoding)
        except Exception as e:
            console(f"Error: {e}")
        return result

    async def make_call(self, number, ring_time=None):
        """
        Initiate a voice call.
        :param number str: phone number to call
        :param ring_time int|None: seconds to ring before hanging up, None = no auto hangup
        :return bytes: raw response
        """
        with micro_task(tag='sim800.make_call') as my_task:
            resp = self.send_command(f'ATD{number};')
            if ring_time is not None:
                await my_task.feed(sleep_ms=ring_time * 1000)
                self.send_command('ATH')
            return resp

    def receive_sms(self, index, delete=True):
        """
        Read, parse and reassemble a (possibly multipart) SMS by SIM index.
        :param index: SIM memory index (str or int)
        :param delete bool: delete SMS from SIM after reading (default: True)
        :return dict|None: complete SMS dict when all parts received, None if still waiting for more parts
        """
        raw = self.read_sms(index)
        sms = self.parse_sms(raw)
        if not sms:
            return None
        udh = sms.pop('udh', None)
        if udh is None:
            if delete:
                self.delete_sms(index)
            return sms
        ref, total, part = udh['ref'], udh['total'], udh['part']
        if ref not in self._concat_buffer:
            self._concat_buffer[ref] = {'total': total, 'parts': {}, 'meta': sms, 'indices': []}
        self._concat_buffer[ref]['parts'][part] = sms.get('text', '')
        self._concat_buffer[ref]['indices'].append(index)
        if len(self._concat_buffer[ref]['parts']) < total:
            return None
        entry = self._concat_buffer.pop(ref)
        if delete:
            for idx in entry['indices']:
                self.delete_sms(idx)
        result = entry['meta']
        result['text'] = ''.join(entry['parts'][i] for i in sorted(entry['parts']))
        result['parts'] = total
        return result

def _inst():
    """Get loaded instance or raise."""
    if Sim800.INSTANCE is None:
        raise Exception('Not loaded. Call sim800 load first.')
    return Sim800.INSTANCE

def is_connected():
    """
    Check network registration and signal quality.
    :return dict: connected, reg_status, operator, rssi, ber, dbm
    """
    return _inst().is_connected()

def get_signal_quality():
    """
    Query signal quality (RSSI and BER).
    :return dict: rssi, ber, dbm
    """
    return _inst().get_signal_quality()

def get_network_info():
    """
    Query network registration status and operator name.
    :return dict: reg_status, operator
    """
    return _inst().get_network_info()

def reject_call(busy=False):
    """
    Reject an incoming call.
    :param busy bool: True = send busy signal, False = silent disconnect (default)
    :return bytes: raw response
    """
    return _inst().reject_call(busy)

def make_call(number, ring_time=None):
    """
    Initiate a voice call.
    :param number str: phone number to call
    :param ring_time int|None: seconds to ring before hanging up
    :return dict: task state
    """
    return micro_task(tag='sim800.make_call', task=_inst().make_call(number, ring_time))

def send_sms(number, text, callback=None):
    """
    Queue an SMS for sending. Messages are sent one by one.
    :param number str: destination phone number
    :param text str: message text
    :param callback func|None: called with (bool success, str detail) when done
    :return str: queued status
    """
    _inst().queue_sms(number, text, callback)
    return f'SMS queued to {number}'

def send_ussd(code, timeout=10000):
    """
    Send a USSD request.
    :param code str: USSD code (e.g. '*102#')
    :param timeout int: response timeout in ms
    :return dict: status, message, dcs
    """
    return _inst().send_ussd(code, timeout)

def get_balance(code='*102#', timeout=10000):
    """
    Query prepaid balance via USSD.
    :param code str: USSD balance code (default: *102# for Telekom HU)
    :param timeout int: response timeout in ms
    :return dict: status, message, dcs
    """
    return _inst().get_balance(code, timeout)

def receive_sms(index, delete=True):
    """
    Read, parse and reassemble a (possibly multipart) SMS by SIM index.
    :param index: SIM memory index
    :param delete bool: delete SMS from SIM after reading (default: True)
    :return dict|None: complete SMS dict or None if still waiting for more parts
    """
    return _inst().receive_sms(index, delete)

def clear_sms(mode=6):
    """
    Delete all SMS messages.
    :param mode int: delete mode (default: 6 = delete all)
    :return bytes: raw response
    """
    return _inst().clear_sms(mode)

def delete_sms(index):
    """
    Delete a single SMS by index.
    :param index int: SIM memory index
    :return bytes: raw response
    """
    return _inst().delete_sms(index)

def get_sms(option=4):
    """
    List SMS messages from SIM memory.
    :param option int: message status filter (default: 4 = ALL)
    :return bytes: raw response
    """
    return _inst().get_sms(option)

def read_uart():
    """
    Read and decode pending UART data.
    :return tuple|False: (lines_list, raw_bytes) or False if no data
    """
    return _inst().read_uart()

def send_command(command, timeout=1000):
    """
    Send an AT command and return the raw response bytes.
    :param command str: AT command to send
    :param timeout int: response timeout in ms
    :return bytes: raw response
    """
    return _inst().send_command(command, timeout)

def reset():
    """
    Hard reset the SIM800 module and clear the instance.
    :return str: status message
    """
    _inst().reset()
    Sim800.INSTANCE = None
    return "Sim800 reset finished."

def load(pin_code=None, tx_pin=16, rx_pin=17, ri_pin=23):
    """
    Initialize and connect the SIM800 module.
    :param pin_code int: SIM PIN code
    :param tx_pin int: UART TX GPIO pin (default: 16)
    :param rx_pin int: UART RX GPIO pin (default: 17)
    :param ri_pin int: Ring Indicator GPIO pin (default: 23)
    :return str: status message
    """
    if Sim800.INSTANCE is None:
        Sim800.INSTANCE = Sim800(pin_code, tx_pin, rx_pin, ri_pin)
        if Sim800.INSTANCE.connect():
            return 'Sim800 started.'
        else:
            Sim800.INSTANCE = None
            return 'Sim800 failed.'
    return 'Sim800 already running.'

def _has_subscribers():
    """Check if any event type has subscribers."""
    return any(_subscribers[k] for k in _subscribers)

def subscribe(event_type, callback):
    """
    Subscribe to SIM800 events. Starts listener automatically on first subscriber.
    :param event_type str: 'call', 'sms', or 'signal'
    :param callback func: called with event data when event occurs
        - call: callback(call_params_dict)
        - sms: callback(sms_dict)
        - signal: callback(uart_message_list)
    :return str: status message
    """
    if event_type not in _subscribers:
        return f"Unknown event type: {event_type}. Use: {', '.join(_subscribers.keys())}"
    was_empty = not _has_subscribers()
    if callback not in _subscribers[event_type]:
        _subscribers[event_type].append(callback)
        if was_empty:
            _ensure_listener()
    return f"Subscribed to {event_type}"

def unsubscribe(event_type, callback):
    """
    Unsubscribe from SIM800 events. Stops listener when no subscribers remain.
    :param event_type str: 'call', 'sms', or 'signal'
    :param callback func: previously subscribed callback
    :return str: status message
    """
    if event_type in _subscribers and callback in _subscribers[event_type]:
        _subscribers[event_type].remove(callback)
    return f"Unsubscribed from {event_type}"

def _dispatch(event_type, data):
    """Dispatch event to all subscribers.
    :param event_type str: event type
    :param data: event data passed to callbacks
    """
    for cb in _subscribers.get(event_type, []):
        try:
            cb(data)
        except Exception as e:
            console(f"Subscriber error ({event_type}): {e}")

def _poll_uart():
    """Poll UART and dispatch events to subscribers.
    :return bool: True if an event was dispatched
    """
    result = _inst().read_uart()
    if not result:
        return False
    uart_lines, raw_bytes = result
    if uart_lines is None:
        return False
    dispatched = False
    for value in uart_lines:
        if '+CLIP' in value:
            call_params = _inst().parse_call_params(value)
            _dispatch('call', call_params)
            dispatched = True
        elif '+CMTI' in value:
            try:
                index = int(value.split(',')[1].strip())
            except (IndexError, ValueError):
                continue
            sms = receive_sms(index)
            if sms is None:
                console(f"Multipart SMS part received, waiting for more...")
            else:
                _dispatch('sms', sms)
                dispatched = True
        elif 'NO CARRIER' in value:
            continue
    if not dispatched and uart_lines:
        at_parts = [v for v in uart_lines if v]
        if at_parts:
            _dispatch('signal', at_parts)
    return dispatched


async def _run_listener():
    """Async UART listener loop. Reads UART when RI interrupt signals data."""
    with micro_task(tag='sim800.listener') as my_task:
        inst = Sim800.INSTANCE
        while _has_subscribers():
            try:
                if inst._ri_triggered:
                    inst._ri_triggered = False
                    await my_task.feed(sleep_ms=50)
                    _poll_uart()
                await my_task.feed(sleep_ms=100)
            except Exception as e:
                console(f"Listener error: {e}")
                await my_task.feed(sleep_ms=100)
        console("SIM800 listener stopped - no subscribers")

def _ensure_listener():
    """Start listener if not already running."""
    micro_task(tag='sim800.listener', task=_run_listener())


#######################
# LM helper functions #
#######################

def pinmap():
    """
    [i] micrOS LM naming convention
    Shows logical pins - pin number(s) used by this Load module
    - info which pins to use for this application
    :return dict: pin name (str) - pin value (int) pairs
    """
    return pinmap_search(['sim800_tx', 'sim800_rx', 'sim800_ri'])


def help(widgets=False):
    """
    [i] micrOS LM naming convention - built-in help message
    :return tuple:
        (widgets=False) list of functions implemented by this application
        (widgets=True) list of widget json for UI generation
    """
    return resolve(('load pin_code=1234 tx_pin=16 rx_pin=17 ri_pin=23',
                    'subscribe event_type="call" callback=<func>',
                    'unsubscribe event_type="call" callback=<func>',
                    'reset',
                    'reject_call busy=False',
                    'is_connected',
                    'get_signal_quality',
                    'get_network_info',
                    'read_uart',
                    'make_call number="+36201234567" ring_time=15',
                    'send_sms number="+36201234567" text="Hello"',
                    'send_ussd code="*102#"',
                    'get_balance code="*102#"',
                    'send_command "AT+CPIN?" timeout=1000',
                    'clear_sms target="ALL"',
                    'get_sms target="ALL"',
                    'pinmap'), widgets=widgets)