"""
SIM800 modem driver — UART communication, AT commands, SMS, calls, USSD.
"""

import time
from machine import Pin, UART
from Common import console, micro_task
from microIO import bind_pin
from sim800 import codec


SMS_STATUS = {'0': 'REC UNREAD', '1': 'REC READ', '2': 'STO UNSENT', '3': 'STO SENT', '4': 'ALL'}


class Sim800:
    INSTANCE = None

    def __init__(self, pin_code, tx_pin, rx_pin, ri_pin):
        self.uart_no = 1
        self.sim_pin_code = str(pin_code)
        self.baudrate = 115200
        self.tx_pin = Pin(bind_pin("sim800_tx", tx_pin))
        self.rx_pin = Pin(bind_pin("sim800_rx", rx_pin))
        self.ri_pin = Pin(bind_pin("sim800_ri", ri_pin), Pin.IN, Pin.PULL_UP)
        self._ri_triggered = False
        self.ri_pin.irq(trigger=Pin.IRQ_FALLING, handler=self._ri_handler)
        self._concat_buffer = {}
        self._sms_queue = []
        self._sms_sending = False

    def _ri_handler(self, pin):
        """RI interrupt handler — called on falling edge when SIM800 has data."""
        self._ri_triggered = True

    # ─── Connection ───────────────────────────────────────────────

    def _unlock_sim(self, responses):
        """Unlock SIM card with PIN code."""
        responses.append(self.send_command('AT+CPIN?'))
        if b'READY' not in responses[-1]:
            responses.append(self.send_command(f'AT+CPIN="{self.sim_pin_code}"'))
            time.sleep(5)
            responses.append(self.send_command('AT+CPIN?'))
            if b'READY' not in responses[-1]:
                raise Exception("SIM PIN not accepted")

    def _init_modem(self, responses):
        """Initialize modem settings."""
        responses.append(self.send_command('ATE0'))
        responses.append(self.send_command('AT+CFUN=1'))
        responses.append(self.send_command('AT+CLIP=1'))
        responses.append(self.send_command('AT+CLIR=2'))
        responses.append(self.send_command('AT+CMGF=0'))
        responses.append(self.send_command('AT+CPMS="SM"'))
        responses.append(self.send_command('AT+CREG?'))
        responses.append(self.send_command('AT+CSQ'))
        responses.append(self.send_command('AT+CFGRI=1'))

    def connect(self, retries=5, retry_delay=2):
        """Connect to modem, unlock SIM and initialize.
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

    # ─── UART I/O ─────────────────────────────────────────────────

    def send_command(self, command, timeout=1000):
        """Send an AT command and return the raw response bytes."""
        self.uart.write(command + '\r')
        time.sleep(0.1)
        return self.read_response(timeout)

    def _read_raw(self, timeout=1000):
        """Read raw bytes from UART until OK/ERROR or timeout."""
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
        """Read raw bytes from UART with timeout."""
        return self._read_raw(timeout)

    def read_uart(self):
        """Read and decode pending UART data into a list of lines.
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

    def _wait_for_prompt(self, prompt=b'>', timeout=3000):
        """Wait for a specific prompt byte sequence from UART."""
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

    def _wait_for_cusd(self, timeout=10000):
        """Wait for +CUSD response from UART."""
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

    def reset(self):
        """Hard reset the SIM800 module via AT+CFUN=1,1."""
        console(self.send_command('AT+CFUN=1,1'))
        time.sleep(10)

    # ─── SMS ──────────────────────────────────────────────────────

    def get_sms(self, option):
        """List SMS messages from SIM memory."""
        return self.send_command(f'AT+CMGL={option}')

    def read_sms(self, index):
        """Read a single SMS by index."""
        return self.send_command(f'AT+CMGR={index}')

    def delete_sms(self, index):
        """Delete a single SMS by index."""
        return self.send_command(f'AT+CMGD={index}')

    def clear_sms(self, mode):
        """Delete all SMS messages by mode."""
        return self.send_command(f'AT+CMGDA={mode}')

    def queue_sms(self, number, text, callback=None):
        """Add SMS to send queue. Starts processing if not already running."""
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
        """Send a single SMS in PDU mode."""
        pdu, tpdu_len = codec.build_submit_pdu(number, text)
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

    def parse_sms(self, raw_bytes):
        """Parse a raw PDU-mode SMS response into a dict."""
        result = {}
        try:
            msg = raw_bytes.decode('utf-8').strip()
            if msg.endswith('OK'):
                msg = msg[:-2].strip()
        except Exception as e:
            console(f"Error: {e}")
            return result
        try:
            result['sign'], rest = msg.split(':', 1)
            header, body = rest.strip().split('\r\n')
            status, alpha, length = header.split(',')
            result['status'] = SMS_STATUS[status]
            result['alpha'] = alpha.strip('"')
            result['length'] = length
            smsc_length, toa, body = int(body[:2])-1, body[2:4], body[4:]
            smsc_type_of_number = '+' if ((int(toa, 16) >> 4) & 0x07) == 1 else ''
            smsc_num, body = body[:2*smsc_length], body[2*smsc_length:]
            result['smsc'] = f"{smsc_type_of_number}{codec.semi_octet_to_number(smsc_num)}"
            tp_first_octet = int(body[:2], 16)
            result['TP-MTI'] = tp_first_octet & ~0x04
            tp_udhi = bool(tp_first_octet & 0x40)
            rest = body[2:]
            tp_oa_length, toa, rest = codec.ceil_even_int(int(rest[:2], 16)), rest[2:4], rest[4:]
            sender_type_of_number = '+' if ((int(toa, 16) >> 4) & 0x07) == 1 else ''
            sender_num, rest = rest[:tp_oa_length], rest[tp_oa_length:]
            result['sender'] = f"{sender_type_of_number}{codec.semi_octet_to_number(sender_num)}"
            result['TP-PID'], rest = rest[:2], rest[2:]
            result['TP-DCS'], rest = (int(rest[:2], 16) >> 2) & 0x03, rest[2:]
            time_stamp, rest = rest[:14], rest[14:]
            result['time_stamp'] = codec.time_stamp_parse(time_stamp)
            result['TP-UDL'], rest = rest[:2], rest[2:]
            udh = None
            if tp_udhi:
                udh, rest = codec.parse_udh(rest)
                result['udh'] = udh
                if result['TP-DCS'] == 0 and udh:
                    udhl = 5 if udh.get('ref', 0) < 256 else 6
                    udh_bits = (udhl + 1) * 8
                    udh_septets = (udh_bits + 6) // 7
                    result['TP-UDL'] = '%02X' % (int(result['TP-UDL'], 16) - udh_septets)
                    result['_fill_bits'] = (7 - (udh_bits % 7)) % 7
            fill_bits = result.pop('_fill_bits', 0)
            if result['TP-DCS'] == 0:
                text = codec.decode_gsm7(rest, result['TP-UDL'], fill_bits)
                result['text'] = ''.join(codec.GSM7_HU_POST.get(c, c) for c in text)
            elif result['TP-DCS'] == 1:
                result['text'] = codec.decode_8bit_data(rest, result['TP-UDL'])
            elif result['TP-DCS'] == 2:
                result['text'] = codec.decode_utf16be_with_surrogates(bytes.fromhex(rest))
        except Exception as e:
            console(f"Error: {e}")
        return result

    def receive_sms(self, index, delete=True):
        """Read, parse and reassemble a (possibly multipart) SMS by SIM index.
        :return dict|None: complete SMS dict or None if still waiting for more parts
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

    # ─── Calls ────────────────────────────────────────────────────

    def reject_call(self, busy=False):
        """Reject an incoming call."""
        if busy:
            return self.send_command('AT+GSMBUSY=1')
        return self.send_command('ATH')

    async def make_call(self, number, ring_time=None):
        """Initiate a voice call."""
        with micro_task(tag='sim800.make_call') as my_task:
            resp = self.send_command(f'ATD{number};')
            if ring_time is not None:
                await my_task.feed(sleep_ms=ring_time * 1000)
                self.send_command('ATH')
            return resp

    def parse_call_params(self, clip_line):
        """Parse a +CLIP UART line into a dict."""
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

    # ─── USSD ─────────────────────────────────────────────────────

    def send_ussd(self, code, timeout=10000):
        """Send a USSD request and return the parsed response."""
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
                message = codec.decode_ussd_ucs2(message)
            elif dcs == 15:
                message = ''.join(codec.GSM7_HU_POST.get(c, c) for c in message)
            return {'status': status, 'message': message, 'dcs': dcs}
        except Exception as e:
            console(f"send_ussd parse error: {e}")
            return {'status': -1, 'message': str(resp).strip()}

    def get_balance(self, code='*102#', timeout=10000):
        """Query prepaid balance via USSD."""
        return self.send_ussd(code, timeout)

    # ─── Network status ───────────────────────────────────────────

    def get_signal_quality(self):
        """Query signal quality (RSSI and BER) from AT+CSQ."""
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
        """Query network registration status and operator name."""
        reg_status_table = {
            '0': 'not registered', '1': 'registered home', '2': 'searching',
            '3': 'denied', '4': 'unknown', '5': 'registered roaming'
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
            result['operator'] = parts[2].strip().strip('"') if len(parts) > 2 else 'unknown'
        except Exception as e:
            console(f"get_network_info COPS error: {e}")
            result['operator'] = 'unknown'
        return result

    def is_connected(self):
        """Check network registration and signal quality in one call."""
        network = self.get_network_info()
        signal = self.get_signal_quality()
        connected = network.get('reg_status') in ('registered home', 'registered roaming')
        result = {'connected': connected}
        result.update(network)
        if signal:
            result.update(signal)
        return result
