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
VALID_TYPES = ('delayed', 'instant', '24h', 'cross')
VALID_GROUPS = ('perimeter', 'interior', 'always')

# --- Module state ---
_state = DISARMED
_arm_mode = None
_delay_task = None
_zones = {}
_exit_delay = 30
_entry_delay = 15
_interval = 50
_max_log_entries = 100
_config_file = None
_state_file = None
_alarm_memory = []
_chime = False
_auto_arm_delay = None
_auto_arm_mode = 'full'
_auto_arm_task = None
_last_activity = 0
_bypassed = set()
_BOOK = 'alarm'


# --- Config persistence ---

def _save_config():
    """Persist current config (sensors + zones + watches + settings) to JSON file."""
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
            if z['type'] == 'cross':
                entry['cross_pair'] = z.get('cross_pair')
                entry['cross_window'] = z.get('cross_window', 30)
            if 'supervision' in z:
                entry['supervision'] = z['supervision']
            zones.append(entry)
    try:
        from alarm_system.mqtt_watcher import get_watches_config
        watches = get_watches_config()
    except Exception:
        watches = []
    config = {
        'exit_delay': _exit_delay,
        'entry_delay': _entry_delay,
        'interval': _interval,
        'max_log_entries': _max_log_entries,
        'sensors': sensors,
        'zones': zones,
        'watches': watches
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

from alarm_system.actions import on_arming as _on_arming
from alarm_system.actions import on_armed as _on_armed
from alarm_system.actions import on_entry_delay as _on_entry_delay
from alarm_system.actions import on_disarmed as _on_disarmed
from alarm_system.actions import on_silent_alert as _on_silent_alert


def _on_alarm_wrapper():
    """Wrapper to pass alarm_memory to on_alarm."""
    from alarm_system.actions import on_alarm
    on_alarm(_alarm_memory)

_ACTION_HOOKS = {
    ARMING: _on_arming,
    ARMED: _on_armed,
    ENTRY_DELAY: _on_entry_delay,
    ALARM: _on_alarm_wrapper,
    DISARMED: _on_disarmed,
}

def status():
    """Return current system status.
    :return dict: state, arm_mode, zones, open_zones, alarm_memory
    """
    return {
        'state': _state,
        'arm_mode': _arm_mode,
        'zones': {name: {
            'type': z['type'],
            'group': z['group'],
            'last_event': z.get('last_event', 'ok')
        } for name, z in _zones.items()},
        'open_zones': [name for name, z in _zones.items() if z.get('last_event') == 'triggered'],
        'alarm_memory': list(_alarm_memory),
        'bypassed': list(_bypassed),
        'trouble': _get_trouble_zones()
    }


# --- Public interface ---

def load(config='alarm_config.json'):
    """Initialize alarm system: load config, create sensors, restore state, start detection loop.
    :param config str: config filename in data_dir (default: alarm_config.json)
    :return str: status message
    """
    global _state, _arm_mode, _exit_delay, _entry_delay, _interval, _max_log_entries, _config_file, _state_file

    _config_file = data_dir(config)
    _state_file = data_dir('alarm_state.json')

    # Load config
    cfg = _load_config()
    if cfg:
        _exit_delay = cfg.get('exit_delay', 30)
        _entry_delay = cfg.get('entry_delay', 15)
        _interval = cfg.get('interval', 50)
        _max_log_entries = cfg.get('max_log_entries', 100)
        # Create sensors from config
        for s in cfg.get('sensors', []):
            _create_sensor(s['name'], s['pin'], s['type'], s['group'])
        # Register remote zones from config
        for z in cfg.get('zones', []):
            zone = {'type': z['type'], 'group': z['group'], 'last_event': 'ok'}
            if z['type'] == 'cross':
                zone['cross_pair'] = z.get('cross_pair')
                zone['cross_window'] = z.get('cross_window', 30)
            if 'supervision' in z:
                zone['supervision'] = z['supervision']
                zone['last_seen'] = time.time()
            _zones[z['name']] = zone
        # Load MQTT watches
        from alarm_system.mqtt_watcher import init as watcher_init, load_watches
        watcher_init(zone_trigger)
        load_watches(cfg.get('watches', []))

    # Init event log
    from alarm_system.event_log import init as log_init
    log_init(data_dir('alarm_log.json'), _max_log_entries)

    # Init phonebook
    phonebook_file = cfg.get('phonebook', 'alarm_users.json') if cfg else 'alarm_users.json'
    try:
        import LM_users as users
        users.load(json_file=phonebook_file, book=_BOOK)
    except Exception as e:
        console(f"alarm_system: phonebook init skipped: {e}")

    # Init SMS handler
    try:
        import LM_sim800 as sim
        from alarm_system.sms_handler import init as sms_init, handle_sms
        import sys
        sms_init(sys.modules[__name__])
        sim.subscribe('sms', handle_sms)
    except Exception as e:
        console(f"alarm_system: SMS subscribe skipped: {e}")

    # Restore state from file
    _state, _arm_mode = _load_state()

    # Start detection loop
    micro_task(tag="alarm_detection_task", task=_detection_loop(_interval))

    # Log system start
    from alarm_system.event_log import log as _elog
    _elog('system_start', {'state': _state, 'mode': _arm_mode, 'zones': len(_zones)})

    console(f"alarm_system: started, state={_state}, mode={_arm_mode}, zones={len(_zones)}")
    return f"Alarm system started. State: {_state}, zones: {len(_zones)}"


def unload():
    """Stop alarm system: disable sensor IRQs, unsubscribe watches, clear state.
    :return str: status message
    """
    global _delay_task
    try:
        from alarm_system.event_log import log as _elog
        _elog('system_stop')
    except Exception:
        pass
    # Unsubscribe SMS
    try:
        import LM_sim800 as sim
        from alarm_system.sms_handler import handle_sms
        sim.unsubscribe('sms', handle_sms)
    except Exception:
        pass
    for name, zone in _zones.items():
        sensor = zone.get('sensor')
        if sensor:
            sensor.pin.irq(handler=None)
    _zones.clear()
    _delay_task = None
    try:
        from alarm_system.mqtt_watcher import unload as watcher_unload
        watcher_unload()
    except Exception:
        pass
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

    # Check for trouble zones (supervision timeout)
    trouble_zones = _get_trouble_zones()
    if trouble_zones and not force:
        Notify.notify(json.dumps({"action": "arm_refused", "reason": "trouble",
                                  "zones": trouble_zones}), topic="alarm/action")
        return f"Cannot arm: trouble zones: {', '.join(trouble_zones)}"

    # Check for open zones in active groups
    open_zones = [name for name, z in _zones.items()
                  if z.get('last_event') == 'triggered'
                  and z['type'] != '24h'
                  and _is_group_active_for_mode(z['group'], mode)]
    if open_zones and not force:
        Notify.notify(json.dumps({"action": "arm_refused", "reason": "open_zones",
                                  "zones": open_zones}), topic="alarm/action")
        return f"Cannot arm: open zones: {', '.join(open_zones)}"

    global _alarm_memory
    _alarm_memory = []
    _arm_mode = mode
    _transition_to(ARMING)
    _delay_task = micro_task(tag="alarm_exit_delay", task=_exit_delay_task())
    from alarm_system.event_log import log as _elog
    _elog('arm', {'mode': mode, 'force': force, 'bypassed': open_zones if open_zones else None})
    if open_zones:
        return f"Arming ({mode}), exit delay {_exit_delay}s [bypassed: {', '.join(open_zones)}]"
    return f"Arming ({mode}), exit delay {_exit_delay}s"


def disarm():
    """Disarm the alarm system.
    :return str: status message
    """
    global _arm_mode, _delay_task
    prev_state = _state
    _arm_mode = None
    _delay_task = None
    _bypassed.clear()
    _transition_to(DISARMED)
    _reset_activity()
    from alarm_system.event_log import log as _elog
    _elog('disarm', {'from_state': prev_state})
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

    # Supervision: update last_seen on any event (triggered or reset)
    if 'supervision' in zone:
        zone['last_seen'] = time.time()

    if event != 'triggered':
        return f"Zone {name} reset"

    zone_type = zone['type']
    zone_group = zone['group']

    # Chime: beep on delayed zone while disarmed
    if _chime and _state == DISARMED and zone_type == 'delayed':
        Notify.notify(json.dumps({"action": "chime", "zone": name}), topic="alarm/action")

    # Auto-arm: reset activity timer on any trigger while disarmed
    if _state == DISARMED:
        _reset_activity()

    from alarm_system.event_log import log as _elog

    # 24h zones trigger in any state
    if zone_type == '24h':
        if _state in (ARMED, ENTRY_DELAY):
            _alarm_memory.append(name)
            _elog('alarm', {'zone': name, 'type': '24h'})
            _transition_to(ALARM)
            return f"ALARM: 24h zone {name} triggered"
        else:
            _elog('silent_alert', {'zone': name, 'state': _state})
            _on_silent_alert(name)
            return f"Silent alert: 24h zone {name} triggered while {_state}"

    # Other zones only matter when armed
    if _state != ARMED:
        return f"Ignored: zone {name} triggered while {_state}"

    # Bypassed zones are ignored
    if name in _bypassed:
        return f"Ignored: zone {name} is bypassed"

    # Check if zone group is active in current arm mode
    if not _is_group_active(zone_group):
        return f"Ignored: zone {name} group '{zone_group}' not active in mode '{_arm_mode}'"

    # Delayed zone → entry delay
    if zone_type == 'delayed':
        global _delay_task
        _alarm_memory.append(name)
        _elog('zone_trigger', {'zone': name, 'type': 'delayed', 'result': 'entry_delay'})
        _transition_to(ENTRY_DELAY)
        _delay_task = micro_task(tag="alarm_entry_delay", task=_entry_delay_task())
        return f"Entry delay: zone {name} triggered"

    # Instant zone → immediate alarm
    if zone_type == 'instant':
        _alarm_memory.append(name)
        _elog('alarm', {'zone': name, 'type': 'instant'})
        _transition_to(ALARM)
        return f"ALARM: instant zone {name} triggered"

    # Cross-zone → alarm only if pair triggered within window
    if zone_type == 'cross':
        pair_name = zone.get('cross_pair')
        window = zone.get('cross_window', 30)
        zone['last_trigger_time'] = time.time()
        pair = _zones.get(pair_name)
        if pair and pair.get('last_trigger_time'):
            elapsed = time.time() - pair['last_trigger_time']
            if elapsed <= window:
                _alarm_memory.append(name)
                _alarm_memory.append(pair_name)
                _elog('alarm', {'zone': name, 'type': 'cross', 'pair': pair_name, 'elapsed': int(elapsed)})
                _transition_to(ALARM)
                return f"ALARM: cross-zone {name}+{pair_name} triggered ({int(elapsed)}s apart)"
        _elog('zone_trigger', {'zone': name, 'type': 'cross', 'result': 'waiting_for_pair'})
        return f"Cross-zone: {name} triggered, waiting for pair '{pair_name}'"

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

def add_zone(name, type='instant', group='perimeter', cross_pair=None, cross_window=30):
    """Register a remote zone (triggered via MQTT/shell, no GPIO pin).
    :param name str: zone name
    :param type str: 'delayed', 'instant', '24h', or 'cross'
    :param group str: 'perimeter', 'interior', or 'always'
    :param cross_pair str|None: paired zone name (required for type='cross')
    :param cross_window int: seconds window for cross-zone (default: 30)
    :return str: status message
    """
    if name in _zones:
        return f"Zone '{name}' already exists. Remove it first."
    if type not in VALID_TYPES:
        return f"Invalid type '{type}'. Must be one of: {', '.join(VALID_TYPES)}"
    if group not in VALID_GROUPS:
        return f"Invalid group '{group}'. Must be one of: {', '.join(VALID_GROUPS)}"
    if type == 'cross' and not cross_pair:
        return "Cross-zone requires 'cross_pair' parameter."
    zone = {'type': type, 'group': group, 'last_event': 'ok'}
    if type == 'cross':
        zone['cross_pair'] = cross_pair
        zone['cross_window'] = cross_window
    _zones[name] = zone
    _save_config()
    if type == 'cross':
        return f"Zone '{name}' added: type={type}, group={group}, pair={cross_pair}, window={cross_window}s"
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


# --- MQTT Watch management ---

def add_watch(topic, zone, trigger_value, reset_value=None, trigger_field=None):
    """Add an MQTT topic watch. Auto-registers zone if not exists.
    :param topic str: MQTT topic to subscribe to
    :param zone str: zone name to trigger
    :param trigger_value: value that means 'triggered'
    :param reset_value: value that means 'reset' (optional)
    :param trigger_field str|None: JSON field to extract from payload
    :return str: status message
    """
    # Auto-register zone if not exists
    if zone not in _zones:
        _zones[zone] = {'type': 'instant', 'group': 'perimeter', 'last_event': 'ok'}
    from alarm_system.mqtt_watcher import add_watch as watcher_add
    result = watcher_add(topic, zone, trigger_value, reset_value, trigger_field)
    _save_config()
    return result


def remove_watch(topic):
    """Remove all watches for a topic.
    :param topic str: MQTT topic
    :return str: status message
    """
    from alarm_system.mqtt_watcher import remove_watch as watcher_remove
    result = watcher_remove(topic)
    _save_config()
    return result


def list_watches():
    """List all MQTT watches.
    :return list: watch configurations
    """
    from alarm_system.mqtt_watcher import list_watches as watcher_list
    return watcher_list()


# --- Event log ---

def event_log(count=20):
    """Return last N event log entries.
    :param count int: number of entries (default: 20)
    :return list: log entries [{ts, event, data}, ...]
    """
    from alarm_system.event_log import get
    return get(count)


def clear_log():
    """Clear the event log.
    :return str: status message
    """
    from alarm_system.event_log import clear
    clear()
    return 'Event log cleared.'


def alarm_memory():
    """Return zones that caused the last alarm. Cleared on next arm().
    :return list: zone names
    """
    return list(_alarm_memory)


def chime(state=None):
    """Get or set chime mode. When on, delayed zones beep while disarmed.
    :param state str|None: 'on', 'off', or None to query
    :return str: current chime state
    """
    global _chime
    if state is None:
        return f"Chime: {'on' if _chime else 'off'}"
    if state == 'on':
        _chime = True
        return 'Chime enabled.'
    elif state == 'off':
        _chime = False
        return 'Chime disabled.'
    return f"Invalid state '{state}'. Use 'on' or 'off'."


# --- Auto-arm ---

def auto_arm(delay=None, mode='full'):
    """Configure auto-arm. Arms automatically after inactivity.
    :param delay int|None: seconds of inactivity before arm. None or 0 to disable.
    :param mode str: arm mode to use ('full' or 'night')
    :return str: status message
    """
    global _auto_arm_delay, _auto_arm_mode
    if delay is None or delay == 0:
        _auto_arm_delay = None
        _stop_auto_arm_task()
        return 'Auto-arm disabled.'
    _auto_arm_delay = delay
    _auto_arm_mode = mode
    _reset_activity()
    return f"Auto-arm enabled: {delay}s inactivity → arm({mode})"


# --- Zone bypass ---

def bypass(name):
    """Bypass a zone. Bypassed zones are ignored while armed. Cleared on disarm.
    :param name str: zone name
    :return str: status message
    """
    if name not in _zones:
        return f"Zone '{name}' not found."
    if _zones[name]['type'] == '24h':
        return f"Cannot bypass 24h zone '{name}'."
    _bypassed.add(name)
    from alarm_system.event_log import log as _elog
    _elog('bypass', {'zone': name})
    return f"Zone '{name}' bypassed."


def unbypass(name):
    """Remove bypass from a zone.
    :param name str: zone name
    :return str: status message
    """
    if name not in _bypassed:
        return f"Zone '{name}' is not bypassed."
    _bypassed.discard(name)
    return f"Zone '{name}' unbypass."


# --- Supervision ---

def supervise(name, timeout=600):
    """Enable heartbeat supervision for a zone.
    :param name str: zone name
    :param timeout int: seconds without activity before trouble (default: 600)
    :return str: status message
    """
    if name not in _zones:
        return f"Zone '{name}' not found."
    if 'pin' in _zones[name]:
        return f"Cannot supervise local GPIO zone '{name}'."
    _zones[name]['supervision'] = timeout
    _zones[name]['last_seen'] = time.time()
    _save_config()
    return f"Zone '{name}' supervised: timeout={timeout}s"


def unsupervise(name):
    """Disable heartbeat supervision for a zone.
    :param name str: zone name
    :return str: status message
    """
    if name not in _zones:
        return f"Zone '{name}' not found."
    _zones[name].pop('supervision', None)
    _zones[name].pop('last_seen', None)
    _save_config()
    return f"Zone '{name}' supervision removed."


def _get_trouble_zones():
    """Return list of zones in trouble (supervision timeout exceeded)."""
    now = time.time()
    trouble = []
    for name, z in _zones.items():
        timeout = z.get('supervision')
        if timeout is None:
            continue
        last_seen = z.get('last_seen', 0)
        if (now - last_seen) > timeout:
            trouble.append(name)
    return trouble


def _reset_activity():
    """Reset auto-arm inactivity timer."""
    global _last_activity, _auto_arm_task
    _last_activity = time.time()
    # Restart task if auto-arm is enabled and we're disarmed
    if _auto_arm_delay and _state == DISARMED:
        _stop_auto_arm_task()
        _auto_arm_task = micro_task(tag="alarm_auto_arm", task=_auto_arm_timer())


def _stop_auto_arm_task():
    """Cancel auto-arm task."""
    global _auto_arm_task
    _auto_arm_task = None



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


async def _auto_arm_timer():
    """Wait for inactivity period then auto-arm."""
    with micro_task(tag="alarm_auto_arm") as my_task:
        await my_task.feed(sleep_ms=_auto_arm_delay * 1000)
        if _state == DISARMED and _auto_arm_delay:
            elapsed = time.time() - _last_activity
            if elapsed >= _auto_arm_delay - 1:
                from alarm_system.event_log import log as _elog
                _elog('auto_arm', {'delay': _auto_arm_delay, 'mode': _auto_arm_mode})
                arm(mode=_auto_arm_mode)


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
                    'add_watch topic="zigbee2mqtt/sensor" zone="window" trigger_field="contact" trigger_value=false reset_value=true',
                    'remove_watch topic="zigbee2mqtt/sensor"',
                    'list_watches',
                    'event_log count=20',
                    'clear_log',
                    'alarm_memory',
                    'chime state="on"',
                    'chime state="off"',
                    'auto_arm delay=3600 mode="night"',
                    'auto_arm delay=0',
                    'bypass name="window"',
                    'unbypass name="window"',
                    'supervise name="window" timeout=600',
                    'unsupervise name="window"',
                    'pinmap'), widgets=widgets)
