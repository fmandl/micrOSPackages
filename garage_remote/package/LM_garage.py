import time
import re
import json
import LM_sim800 as sim
import LM_users as users
from machine import Pin
from Common import micro_task, console, exec_cmd
from Notify import Notify
from Types import resolve

# status: "A" as Allowed
# status: "B" as Blocked

# Alarm session management
MAX_ALARM_MINUTES = 60
ALARM_CHUNK_MINUTES = 7
_alarm_sessions = {}
_alarm_observer_task = None

def get_timestamp():
    """Return current local time as formatted string."""
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4])

def _logger(message, level="INFO", topic_suffix="log"):
    """Log message to MQTT notify and console.
    :param message str: log message
    :param level str: log level (INFO, WARN, ERROR)
    :param topic_suffix str: MQTT topic suffix
    """
    payload = json.dumps({"time": get_timestamp(), "level": level, "message": str(message)})
    console_entry = f"[{get_timestamp()}] [{level}] {message}"
    Notify.notify(payload, topic=topic_suffix)
    console(console_entry)

class RelayButton:
    """Single GPIO relay button with async push capability."""
    BUTTONS = {}

    def __init__(self, pin_num, tag, duration=2000):
        """Initialize relay button and register in BUTTONS.
        :param pin_num int: GPIO pin number
        :param tag str: unique identifier and micro_task tag
        :param duration int: button press duration in ms
        """
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.tag = tag
        self.duration = duration
        RelayButton.BUTTONS[tag] = self

    @staticmethod
    def get(tag):
        """Get relay button by tag.
        :param tag str: button tag
        :return RelayButton|None: button instance or None
        """
        return RelayButton.BUTTONS.get(tag)

    async def push(self):
        """Async button press: activate, wait, deactivate."""
        with micro_task(tag=self.tag) as my_task:
            self.pin.value(1)
            await my_task.feed(sleep_ms=self.duration)
            self.pin.value(0)


def _instantiate_relay():
    """Create relay button instances."""
    if not RelayButton.BUTTONS:
        RelayButton(18, 'relay.door')
        RelayButton(20, 'relay.alarm')
        return "Relays instantiated."
    return "Relays already instantiated."

def open_garage():
    """Open garage door by pressing the relay button.
    :return dict: status
    """
    door = RelayButton.get('relay.door')
    if door is None:
        return {"error": "relay.door not initialized, call load() first"}
    micro_task(tag=door.tag, task=door.push())
    _logger("Garage door opened")
    return {"garage":"open"}

def press_alarm_button():
    """Press the alarm remote button to toggle alarm state."""
    alarm_btn = RelayButton.get('relay.alarm')
    if alarm_btn is None:
        return {"error": "relay.alarm not initialized, call load() first"}
    micro_task(tag=alarm_btn.tag, task=alarm_btn.push())
    return {"alarm":"pressed"}


# --- Alarm session management ---


async def _alarm_observer():
    """Async observer that re-presses the alarm button at chunk boundaries.
    Checks every 10 seconds. Presses the button when remaining time hits a chunk boundary.
    When all sessions expire, the alarm reactivates automatically.
    """
    global _alarm_observer_task
    chunk_sec = ALARM_CHUNK_MINUTES * 60
    with micro_task(tag="garage_alarm_observer") as my_task:
        try:
            while _alarm_sessions:
                now = time.time()
                need_press = False
                for phone, end_time in list(_alarm_sessions.items()):
                    remaining = end_time - now
                    if remaining <= 0:
                        _alarm_sessions.pop(phone, None)
                        _logger(f"Alarm session expired for {phone}")
                    elif remaining >= chunk_sec and remaining % chunk_sec < 10:
                        need_press = True
                if not _alarm_sessions:
                    _logger("Garage alarm system reactivated")
                    break
                if need_press:
                    press_alarm_button()
                    _logger(f"Alarm button re-pressed, active sessions: {len(_alarm_sessions)}")
                await my_task.feed(sleep_ms=10_000)
        except Exception as e:
            _logger(f"Exception in observer: {e}", "ERROR")
        finally:
            _alarm_observer_task = None

def garage_alarm_off(minutes, phone='shell'):
    """Temporarily disable the garage alarm for a given duration.
    Starts the observer task if not already running.
    :param minutes int: duration in minutes (capped at MAX_ALARM_MINUTES)
    :param phone str: phone number of the requester (default: 'shell')
    :return str: status message
    """
    global _alarm_observer_task
    if minutes > MAX_ALARM_MINUTES:
        minutes = MAX_ALARM_MINUTES
    if minutes < ALARM_CHUNK_MINUTES:
        minutes = ALARM_CHUNK_MINUTES
    end_time = time.time() + minutes * 60
    _alarm_sessions[phone] = end_time
    _logger(f"Alarm off for {minutes} min by {phone}")
    press_alarm_button()
    if _alarm_observer_task is None:
        _alarm_observer_task = micro_task(tag="garage_alarm_observer", task=_alarm_observer())
    return f"Alarm off for {minutes} min"

def garage_alarm_on(phone='shell'):
    """Immediately reactivate the garage alarm for a given phone session.
    :param phone str: phone number of the requester (default: 'shell')
    :return str: status message
    """
    _alarm_sessions.pop(phone, None)
    _logger(f"Alarm on by {phone}")
    return "Alarm on"

def _handle_alarm_command(command, phone):
    """Parse and execute alarm SMS command.
    :param command str: SMS text (e.g. 'alarm on', 'alarm off 15')
    :param phone str: sender phone number
    :return str: status message
    """
    if re.search(r'^alarm\son$', command.lower()):
        return garage_alarm_on(phone)
    elif re.search(r'^alarm\soff\s+\d+$', command.lower()):
        minutes = int(command.split()[2])
        return garage_alarm_off(minutes, phone)
    return f"Unknown command: {command}"


# --- Call / SMS handlers ---

def _handle_call(call_params):
    """Handle incoming call: reject, check user, open garage if allowed.
    :param call_params dict: parsed call parameters from SIM800
    """
    sim.reject_call()
    caller = call_params.get('caller_number', '')
    result = users.get_user(phone=caller)
    if not result:
        _logger(f"Unknown caller: {caller}")
        return
    user = result[0]
    if user["status"] == "A":
        if users.check_access(user['phone']):
            _logger(f"Inactive caller: {user['name']} ({user['phone']})")
            return
        _logger(f"Allowed caller: {user['name']} ({user['phone']})")
        res = open_garage()
        if "error" in res:
            _logger(f"Failed to open garage: {res['error']}", "ERROR")
    elif user["status"] == "B":
        _logger(f"Blocked caller: {user['name']} ({user['phone']}) - {user.get('info', '')}")

def _handle_sms(sms):
    """Handle incoming SMS: check user, process command.
    :param sms dict: parsed SMS from SIM800 (sender, text, etc.)
    """
    sender = sms.get('sender', '')
    text = sms.get('text', '').strip()
    if not sender:
        _logger("SMS without sender field")
        return
    result = users.get_user(phone=sender)
    if not result:
        _logger(f"Unknown SMS sender: {sender}")
        return
    user = result[0]
    if user["status"] == "B":
        _logger(f"Blocked SMS sender: {user['name']} ({user['phone']}) - {user.get('info', '')}")
        return
    if user["status"] != "A":
        _logger(f"SMS sender with unexpected status '{user['status']}': {user['name']} ({user['phone']})")
        return
    if users.check_access(user['phone']):
        _logger(f"Inactive SMS sender: {user['name']} ({user['phone']})")
        return
    if user["role"] == "admin" and re.search(r'^[cC][mM][dD]:.*', text):
        cmd = text[4:].strip().split()
        state, output_json = exec_cmd(cmd, jsonify=True)
        _logger(f"Admin CMD by {user['name']} ({user['phone']}): {text} - state: {state}")
        _logger(f"Admin CMD output: {output_json}")
    else:
        _logger(f"Alarm CMD by {user['name']} ({user['phone']}): {text}")
        _handle_alarm_command(text, user["phone"])

def load(pin_code):
    """Initialize garage module: relay, users, SIM800, subscribe to events.
    :param pin_code int: SIM card PIN code
    :return str: status message
    """
    _instantiate_relay()
    users.load()
    sim.load(pin_code=pin_code)
    # Flush stale UART data before subscribing
    sim.read_uart()
    sim.subscribe('call', _handle_call)
    sim.subscribe('sms', _handle_sms)
    _logger("Garage module started", "INFO")
    return 'Garage module started.'

def unload():
    """Gracefully stop garage module: unsubscribe events, clear alarm sessions.
    :return str: status message
    """
    global _alarm_observer_task
    sim.unsubscribe('call', _handle_call)
    sim.unsubscribe('sms', _handle_sms)
    _alarm_sessions.clear()
    _alarm_observer_task = None
    _logger("Garage module stopped", "INFO")
    return 'Garage module stopped.'


#######################
# LM helper functions #
#######################

def help(widgets=False):
    """
    [i] micrOS LM naming convention - built-in help message
    :return tuple:
        (widgets=False) list of functions implemented by this application
        (widgets=True) list of widget json for UI generation
    """
    return resolve(('load pin_code=1234',
                    'unload',
                    'open_garage',
                    'press_alarm_button',
                    'garage_alarm_off minutes=10',
                    'garage_alarm_off minutes=10 phone="+36201234567"',
                    'garage_alarm_on',
                    'garage_alarm_on phone="+36201234567"'), widgets=widgets)
