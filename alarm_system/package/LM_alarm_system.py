"""
LM_alarm_system.py — Alarm panel controller for micrOS.
State machine, zone management, and action dispatch.
"""

from Common import micro_task, console, data_dir
from Notify import Notify
from microIO import bind_pin, pinmap_search
from Types import resolve
import time
import json

# --- States ---
DISARMED = 'DISARMED'
ARMING = 'ARMING'
ARMED = 'ARMED'
ENTRY_DELAY = 'ENTRY_DELAY'
ALARM = 'ALARM'

VALID_STATES = (DISARMED, ARMING, ARMED, ENTRY_DELAY, ALARM)
VALID_TYPES = ('delayed', 'instant', '24h')
VALID_GROUPS = ('perimeter', 'interior', 'always')

# --- Module state ---
_state = DISARMED
_arm_mode = None
_delay_task = None
_zones = {}
_exit_delay = 30
_entry_delay = 15
_interval = 50
_config_file = None
_state_file = None


# --- Config persistence ---

def _save_config():
    """Persist current config (sensors + zones + settings) to JSON file."""
    if _config_file is None:
        return
    sensors = []
    zones = []
    for name, z in _zones.items():
        entry = {'name': name, 'type': z['type'], 'group': z['group']}
        if 'pin' in z:
            entry['pin'] = z['pin']
            sensors.append(entry)
        else:
            zones.append(entry)
    config = {
        'exit_delay': _exit_delay,
        'entry_delay': _entry_delay,
        'interval': _interval,
        'sensors': sensors,
        'zones': zones
    }
    try:
        with open(_config_file, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        console(f"alarm_system: save config error: {e}")


def _load_config():
    """Load config from JSON file. Returns config dict or defaults."""
    if _config_file is None:
        return None
    try:
        with open(_config_file, 'r') as f:
            return json.load(f)
    except (OSError, ValueError, Exception):
        return None


# --- State persistence ---

def _save_state():
    """Persist current state and arm_mode to JSON file."""
    if _state_file is None:
        return
    try:
        with open(_state_file, 'w') as f:
            json.dump({'state': _state, 'arm_mode': _arm_mode}, f)
    except Exception as e:
        console(f"alarm_system: save state error: {e}")


def _load_state():
    """Load state from JSON file. Returns (state, arm_mode) or defaults."""
    if _state_file is None:
        return DISARMED, None
    try:
        with open(_state_file, 'r') as f:
            data = json.load(f)
        saved_state = data.get('state', DISARMED)
        saved_mode = data.get('arm_mode', None)
        if saved_state == ARMING:
            saved_state = ARMED
        elif saved_state == ENTRY_DELAY:
            saved_state = ALARM
        elif saved_state not in VALID_STATES:
            saved_state = DISARMED
        return saved_state, saved_mode
    except (OSError, ValueError, Exception):
        return DISARMED, None


# --- State machine ---

def _transition_to(new_state):
    """Transition to a new state: save, notify, dispatch action.
    :param new_state str: target state
    """
    global _state
    prev = _state
    _state = new_state
    _save_state()
    console(f"alarm_system: {prev} → {new_state}")
    Notify.notify(json.dumps({"state": new_state, "prev": prev, "mode": _arm_mode}), topic="alarm/state")
    # Dispatch action hook
    _ACTION_HOOKS.get(new_state, lambda: None)()



# --- Action dispatcher hooks ---

def _on_arming():
    """Exit delay started. Notify remote devices: buzzer slow beep."""
    Notify.notify(json.dumps({"action": "buzzer_slow"}), topic="alarm/action")


def _on_armed():
    """System armed. Notify remote devices: buzzer stop, LED red."""
    Notify.notify(json.dumps({"action": "buzzer_stop"}), topic="alarm/action")
    Notify.notify(json.dumps({"action": "led_red"}), topic="alarm/action")


def _on_entry_delay():
    """Entry delay started. Notify remote devices: buzzer fast beep."""
    Notify.notify(json.dumps({"action": "buzzer_fast"}), topic="alarm/action")


def _on_alarm():
    """Alarm triggered. Notify remote devices: siren on."""
    Notify.notify(json.dumps({"action": "siren_on"}), topic="alarm/action")
    # TBD: sim800.send_sms(owner, "ALARM triggered!")
    # TBD: sim800.make_call(owner, ring_time=20)


def _on_disarmed():
    """System disarmed. Notify remote devices: all stop, LED green."""
    Notify.notify(json.dumps({"action": "all_stop"}), topic="alarm/action")
    Notify.notify(json.dumps({"action": "led_green"}), topic="alarm/action")


def _on_silent_alert(zone_name):
    """24h zone triggered while disarmed. Notify only, no siren."""
    Notify.notify(json.dumps({"alert": zone_name, "type": "silent"}), topic="alarm/action")

_ACTION_HOOKS = {
    ARMING: _on_arming,
    ARMED: _on_armed,
    ENTRY_DELAY: _on_entry_delay,
    ALARM: _on_alarm,
    DISARMED: _on_disarmed,
}

def status():
    """Return current system status.
    :return dict: state, arm_mode, zones, open_zones
    """
    return {
        'state': _state,
        'arm_mode': _arm_mode,
        'zones': {name: {
            'type': z['type'],
            'group': z['group'],
            'last_event': z.get('last_event', 'ok')
        } for name, z in _zones.items()},
        'open_zones': [name for name, z in _zones.items() if z.get('last_event') == 'triggered']
    }


# --- Public interface ---

def load(config='alarm_config.json'):
    """Initialize alarm system: load config, create sensors, restore state, start detection loop.
    :param config str: config filename in data_dir (default: alarm_config.json)
    :return str: status message
    """
    global _state, _arm_mode, _exit_delay, _entry_delay, _interval, _config_file, _state_file

    _config_file = data_dir(config)
    _state_file = data_dir('alarm_state.json')

    # Load config
    cfg = _load_config()
    if cfg:
        _exit_delay = cfg.get('exit_delay', 30)
        _entry_delay = cfg.get('entry_delay', 15)
        _interval = cfg.get('interval', 50)
        # Create sensors from config
        for s in cfg.get('sensors', []):
            _create_sensor(s['name'], s['pin'], s['type'], s['group'])
        # Register remote zones from config
        for z in cfg.get('zones', []):
            _zones[z['name']] = {'type': z['type'], 'group': z['group'], 'last_event': 'ok'}

    # Restore state from file
    _state, _arm_mode = _load_state()

    # Start detection loop
    micro_task(tag="alarm_detection_task", task=_detection_loop(_interval))

    console(f"alarm_system: started, state={_state}, mode={_arm_mode}, zones={len(_zones)}")
    return f"Alarm system started. State: {_state}, zones: {len(_zones)}"


def unload():
    """Stop alarm system: disable sensor IRQs, clear state.
    :return str: status message
    """
    global _delay_task
    for name, zone in _zones.items():
        sensor = zone.get('sensor')
        if sensor:
            sensor.pin.irq(handler=None)
    _zones.clear()
    _delay_task = None
    console("alarm_system: stopped")
    return 'Alarm system stopped.'


def arm(mode='full', force=False):
    """Arm the alarm system.
    :param mode str: 'full' or 'night' (default: 'full')
    :param force bool: arm even if zones are open (default: False)
    :return str: status message
    """
    global _arm_mode, _delay_task
    if _state not in (DISARMED,):
        return f"Cannot arm: current state is {_state}"

    # Check for open tamper zones (cannot be forced)
    open_tamper = [name for name, z in _zones.items()
                   if z['type'] == '24h' and z.get('last_event') == 'triggered']
    if open_tamper:
        Notify.notify(json.dumps({"action": "arm_refused", "reason": "tamper_open",
                                  "zones": open_tamper}), topic="alarm/action")
        return f"Cannot arm: tamper zone open: {', '.join(open_tamper)}"

    # Check for open zones in active groups
    open_zones = [name for name, z in _zones.items()
                  if z.get('last_event') == 'triggered'
                  and z['type'] != '24h'
                  and _is_group_active_for_mode(z['group'], mode)]
    if open_zones and not force:
        Notify.notify(json.dumps({"action": "arm_refused", "reason": "open_zones",
                                  "zones": open_zones}), topic="alarm/action")
        return f"Cannot arm: open zones: {', '.join(open_zones)}"

    _arm_mode = mode
    _transition_to(ARMING)
    _delay_task = micro_task(tag="alarm_exit_delay", task=_exit_delay_task())
    if open_zones:
        return f"Arming ({mode}), exit delay {_exit_delay}s [bypassed: {', '.join(open_zones)}]"
    return f"Arming ({mode}), exit delay {_exit_delay}s"


def disarm():
    """Disarm the alarm system.
    :return str: status message
    """
    global _arm_mode, _delay_task
    _arm_mode = None
    _delay_task = None
    _transition_to(DISARMED)
    return "Disarmed"


def zone_trigger(name, event):
    """Handle a zone trigger event. Called by sensors or MQTT.
    :param name str: zone name
    :param event str: 'triggered' or 'reset'
    :return str: action taken
    """
    if name not in _zones:
        return f"Unknown zone: {name}"

    zone = _zones[name]
    zone['last_event'] = event

    if event != 'triggered':
        return f"Zone {name} reset"

    zone_type = zone['type']
    zone_group = zone['group']

    # 24h zones trigger in any state
    if zone_type == '24h':
        if _state in (ARMED, ENTRY_DELAY):
            _transition_to(ALARM)
            return f"ALARM: 24h zone {name} triggered"
        else:
            _on_silent_alert(name)
            return f"Silent alert: 24h zone {name} triggered while {_state}"

    # Other zones only matter when armed
    if _state != ARMED:
        return f"Ignored: zone {name} triggered while {_state}"

    # Check if zone group is active in current arm mode
    if not _is_group_active(zone_group):
        return f"Ignored: zone {name} group '{zone_group}' not active in mode '{_arm_mode}'"

    # Delayed zone → entry delay
    if zone_type == 'delayed':
        global _delay_task
        _transition_to(ENTRY_DELAY)
        _delay_task = micro_task(tag="alarm_entry_delay", task=_entry_delay_task())
        return f"Entry delay: zone {name} triggered"

    # Instant zone → immediate alarm
    if zone_type == 'instant':
        _transition_to(ALARM)
        return f"ALARM: instant zone {name} triggered"

    return f"Unknown zone type: {zone_type}"


# --- Sensor management ---

def _create_sensor(name, pin, type, group):
    """Create a DebouncedInput sensor and register as zone.
    :param name str: sensor/zone name
    :param pin int: GPIO pin number
    :param type str: 'delayed', 'instant', or '24h'
    :param group str: 'perimeter', 'interior', or 'always'
    """
    from alarm_system.door_sensor import DebouncedInput
    sensor = DebouncedInput(pin, name, callback=zone_trigger)
    _zones[name] = {'type': type, 'group': group, 'last_event': 'ok', 'pin': pin, 'sensor': sensor}


def add_sensor(name, pin, type='delayed', group='perimeter'):
    """Add a local GPIO sensor. Creates DebouncedInput and saves to config.
    :param name str: sensor name
    :param pin int: GPIO pin number
    :param type str: 'delayed', 'instant', or '24h'
    :param group str: 'perimeter', 'interior', or 'always'
    :return str: status message
    """
    if name in _zones:
        return f"Zone '{name}' already exists. Remove it first."
    if type not in VALID_TYPES:
        return f"Invalid type '{type}'. Must be one of: {', '.join(VALID_TYPES)}"
    if group not in VALID_GROUPS:
        return f"Invalid group '{group}'. Must be one of: {', '.join(VALID_GROUPS)}"
    _create_sensor(name, pin, type, group)
    _save_config()
    return f"Sensor '{name}' added: pin={pin}, type={type}, group={group}"


def remove_sensor(name):
    """Remove a local GPIO sensor. Disables IRQ and saves config.
    :param name str: sensor name
    :return str: status message
    """
    if name not in _zones:
        return f"Sensor '{name}' not found."
    zone = _zones[name]
    if 'sensor' not in zone:
        return f"'{name}' is a remote zone, use remove_zone."
    zone['sensor'].pin.irq(handler=None)
    del _zones[name]
    _save_config()
    return f"Sensor '{name}' removed."


# --- Remote zone management ---

def add_zone(name, type='instant', group='perimeter'):
    """Register a remote zone (triggered via MQTT/shell, no GPIO pin).
    :param name str: zone name
    :param type str: 'delayed', 'instant', or '24h'
    :param group str: 'perimeter', 'interior', or 'always'
    :return str: status message
    """
    if name in _zones:
        return f"Zone '{name}' already exists. Remove it first."
    if type not in VALID_TYPES:
        return f"Invalid type '{type}'. Must be one of: {', '.join(VALID_TYPES)}"
    if group not in VALID_GROUPS:
        return f"Invalid group '{group}'. Must be one of: {', '.join(VALID_GROUPS)}"
    _zones[name] = {'type': type, 'group': group, 'last_event': 'ok'}
    _save_config()
    return f"Zone '{name}' added: type={type}, group={group}"


def remove_zone(name):
    """Remove a remote zone. Saves config.
    :param name str: zone name
    :return str: status message
    """
    if name not in _zones:
        return f"Zone '{name}' not found."
    if 'sensor' in _zones[name]:
        return f"'{name}' is a local sensor, use remove_sensor."
    del _zones[name]
    _save_config()
    return f"Zone '{name}' removed."


def list_zones():
    """List all registered zones and sensors.
    :return dict: zone configurations
    """
    return {name: {
        'type': z['type'],
        'group': z['group'],
        'pin': z.get('pin'),
        'last_event': z.get('last_event', 'ok')
    } for name, z in _zones.items()}


def show_config():
    """Display current config file content.
    :return dict: config data
    """
    cfg = _load_config()
    if cfg is None:
        return "No config file found."
    return cfg


# --- Helpers ---

def _is_group_active(group):
    """Check if a zone group is active in the current arm mode.
    :param group str: zone group name
    :return bool: True if active
    """
    return _is_group_active_for_mode(group, _arm_mode)


def _is_group_active_for_mode(group, mode):
    """Check if a zone group is active for a given arm mode.
    :param group str: zone group name
    :param mode str: arm mode ('full' or 'night')
    :return bool: True if active
    """
    if group == 'always':
        return True
    if mode == 'full' and group in ('perimeter', 'interior'):
        return True
    if mode == 'night' and group == 'perimeter':
        return True
    return False


# --- Async tasks ---

async def _detection_loop(interval):
    """Async detection loop: processes sensor events.
    :param interval int: loop sleep interval in ms
    """
    with micro_task(tag="alarm_detection_task") as my_task:
        while True:
            for zone in _zones.values():
                sensor = zone.get('sensor')
                if sensor:
                    sensor.process_if_needed()
                    sensor.poll()
            await my_task.feed(sleep_ms=interval)


async def _exit_delay_task():
    """Wait for exit delay then transition to ARMED."""
    with micro_task(tag="alarm_exit_delay") as my_task:
        await my_task.feed(sleep_ms=_exit_delay * 1000)
        if _state == ARMING:
            _transition_to(ARMED)


async def _entry_delay_task():
    """Wait for entry delay then transition to ALARM."""
    with micro_task(tag="alarm_entry_delay") as my_task:
        await my_task.feed(sleep_ms=_entry_delay * 1000)
        if _state == ENTRY_DELAY:
            _transition_to(ALARM)


#######################
# LM helper functions #
#######################

def pinmap():
    """
    [i] micrOS LM naming convention
    Shows logical pins - pin number(s) used by this Load module
    :return dict: pin name (str) - pin value (int) pairs
    """
    pins = [f"alarm_{name}" for name, z in _zones.items() if 'pin' in z]
    return pinmap_search(pins) if pins else {}


def help(widgets=False):
    """
    [i] micrOS LM naming convention - built-in help message
    :return tuple:
        (widgets=False) list of functions implemented by this application
        (widgets=True) list of widget json for UI generation
    """
    return resolve(('load config="alarm_config.json"',
                    'unload',
                    'arm mode="full"',
                    'arm mode="full" force=True',
                    'arm mode="night"',
                    'disarm',
                    'status',
                    'add_sensor name="door" pin=19 type="delayed" group="perimeter"',
                    'remove_sensor name="door"',
                    'add_zone name="light" type="instant" group="interior"',
                    'remove_zone name="light"',
                    'list_zones',
                    'zone_trigger name="door" event="triggered"',
                    'show_config',
                    'pinmap'), widgets=widgets)
