"""
SIM800 Load Module — micrOS shell interface.
Modem logic: sim800.modem | Codec: sim800.codec | Notify: sim800.notify
"""

from Common import console, micro_task
from microIO import pinmap_search
from Types import resolve
from sim800.modem import Sim800
from sim800.notify import SMS

# Event subscribers: {'call': [cb, ...], 'sms': [cb, ...], 'signal': [cb, ...]}
_subscribers = {'call': [], 'sms': [], 'signal': []}


# ─── Public API ───────────────────────────────────────────────────

def load(pin_code=None, tx_pin=16, rx_pin=17, ri_pin=23, notify_numbers=None):
    """
    Initialize and connect the SIM800 module.
    :param pin_code int: SIM PIN code
    :param tx_pin int: UART TX GPIO pin (default: 16)
    :param rx_pin int: UART RX GPIO pin (default: 17)
    :param ri_pin int: Ring Indicator GPIO pin (default: 23)
    :param notify_numbers str: comma-separated SMS notify numbers (e.g. "+36201234567,+36207654321")
    :return str: status message
    """
    if Sim800.INSTANCE is None:
        Sim800.INSTANCE = Sim800(pin_code, tx_pin, rx_pin, ri_pin)
        if Sim800.INSTANCE.connect():
            if SMS.INSTANCE is None:
                nums = [n.strip() for n in notify_numbers.split(',') if n.strip()] if notify_numbers else SMS._load_cache()
                if nums:
                    SMS(nums)
                    SMS._save_cache()
            return 'Sim800 started.'
        else:
            Sim800.INSTANCE = None
            return 'Sim800 failed.'
    return 'Sim800 already running.'


def reset():
    """Hard reset the SIM800 module and clear the instance."""
    _inst().reset()
    Sim800.INSTANCE = None
    return "Sim800 reset finished."


def is_connected():
    """Check network registration and signal quality."""
    return _inst().is_connected()


def get_signal_quality():
    """Query signal quality (RSSI and BER)."""
    return _inst().get_signal_quality()


def get_network_info():
    """Query network registration status and operator name."""
    return _inst().get_network_info()


def reject_call(busy=False):
    """Reject an incoming call."""
    return _inst().reject_call(busy)


def make_call(number, ring_time=None):
    """Initiate a voice call."""
    return micro_task(tag='sim800.make_call', task=_inst().make_call(number, ring_time))


def send_sms(number, text, callback=None):
    """Queue an SMS for sending."""
    _inst().queue_sms(number, text, callback)
    return f'SMS queued to {number}'


def send_ussd(code, timeout=10000):
    """Send a USSD request."""
    return _inst().send_ussd(code, timeout)


def get_balance(code='*102#', timeout=10000):
    """Query prepaid balance via USSD."""
    return _inst().get_balance(code, timeout)


def receive_sms(index, delete=True):
    """Read, parse and reassemble a (possibly multipart) SMS by SIM index."""
    return _inst().receive_sms(index, delete)


def clear_sms(mode=6):
    """Delete all SMS messages."""
    return _inst().clear_sms(mode)


def delete_sms(index):
    """Delete a single SMS by index."""
    return _inst().delete_sms(index)


def get_sms(option=4):
    """List SMS messages from SIM memory."""
    return _inst().get_sms(option)


def read_uart():
    """Read and decode pending UART data."""
    return _inst().read_uart()


def send_command(command, timeout=1000):
    """Send an AT command and return the raw response bytes."""
    return _inst().send_command(command, timeout)


def set_notify_numbers(numbers):
    """
    Update SMS notify destination numbers.
    :param numbers str: comma-separated phone numbers
    """
    nums = [n.strip() for n in numbers.split(',') if n.strip()]
    SMS._NUMBERS = nums
    SMS._save_cache()
    return f"SMS notify numbers: {nums}"


# ─── Event system ─────────────────────────────────────────────────

def subscribe(event_type, callback):
    """
    Subscribe to SIM800 events. Starts listener on first subscriber.
    :param event_type str: 'call', 'sms', or 'signal'
    :param callback func: called with event data
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
    """Unsubscribe from SIM800 events."""
    if event_type in _subscribers and callback in _subscribers[event_type]:
        _subscribers[event_type].remove(callback)
    return f"Unsubscribed from {event_type}"


# ─── Internal ─────────────────────────────────────────────────────

def _inst():
    """Get loaded instance or raise."""
    if Sim800.INSTANCE is None:
        raise Exception('Not loaded. Call sim800 load first.')
    return Sim800.INSTANCE


def _has_subscribers():
    return any(_subscribers[k] for k in _subscribers)


def _dispatch(event_type, data):
    for cb in _subscribers.get(event_type, []):
        try:
            cb(data)
        except Exception as e:
            console(f"Subscriber error ({event_type}): {e}")


def _poll_uart():
    result = _inst().read_uart()
    if not result:
        return False
    uart_lines, raw_bytes = result
    if uart_lines is None:
        return False
    dispatched = False
    for value in uart_lines:
        if '+CLIP' in value:
            _dispatch('call', _inst().parse_call_params(value))
            dispatched = True
        elif '+CMTI' in value:
            try:
                index = int(value.split(',')[1].strip())
            except (IndexError, ValueError):
                continue
            sms = receive_sms(index)
            if sms is None:
                console("Multipart SMS part received, waiting for more...")
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
    micro_task(tag='sim800.listener', task=_run_listener())


# ─── LM helpers ───────────────────────────────────────────────────

def pinmap():
    """Shows logical pins used by this Load module."""
    return pinmap_search(['sim800_tx', 'sim800_rx', 'sim800_ri'])


def help(widgets=False):
    """[i] micrOS LM naming convention - built-in help message"""
    return resolve(('load pin_code=1234 tx_pin=16 rx_pin=17 ri_pin=23 notify_numbers="+36201234567"',
                    'set_notify_numbers numbers="+36201234567,+36207654321"',
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
