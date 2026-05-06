# Alarm System - Progress Tracker

## Completed Steps

### 1. ✅ door_sensor.py (sensor module)
- DebouncedInput class with IRQ + debounce + confirm + rescue polling
- Callback support (`callback(name, event)` on state change)
- Notify publish (always sends sensor state via MQTT, regardless of alarm state)
- Active-low logic: 0 = triggered, 1 = reset
- 30 tests passing
- Location: `/home/ealfnmo/smarthome/riaszto/alarm_system/door_sensor.py`

### 2. ✅ LM_alarm_system.py (alarm panel base)
- State machine: DISARMED / ARMING / ARMED / ENTRY_DELAY / ALARM
- `_transition_to()` — state change + persist + notify
- State persistence: JSON save/load, reboot recovery (ARMING→ARMED, ENTRY_DELAY→ALARM)
- Config file: `/data/alarm_config.json` — stores sensors, zones, settings
- Sensor management: `add_sensor(name, pin, type, group)`, `remove_sensor(name)`
- Zone management: `add_zone(name, type, group)`, `remove_zone(name)`, `list_zones()`
- Zone trigger decision tree: type (delayed/instant/24h) + group (perimeter/interior/always) + arm mode
- Arm modes: `full` (perimeter + interior), `night` (perimeter only)
- `arm(mode)` / `disarm()` with exit/entry delay async tasks
- `load(config)` — loads config, creates sensors, restores state, starts detection loop
- `unload()` — disables IRQs, clears zones
- `status()` / `show_config()` — system info
- `help()` / `pinmap()` — micrOS conventions
- Validation: type/group checked on add
- 65 tests passing
- Location: `/home/ealfnmo/smarthome/riaszto/LM_alarm_system.py`

## Remaining Steps

### 3. ✅ Action dispatcher hooks
- `_on_arming()` — Notify: buzzer slow beep
- `_on_armed()` — Notify: buzzer stop, led red
- `_on_entry_delay()` — Notify: buzzer fast beep
- `_on_alarm()` — Notify: siren on (+ SMS/call TBD)
- `_on_disarmed()` — Notify: all stop, led green
- `_on_silent_alert(zone_name)` — Notify: alert (24h zone while disarmed)
- Wired into `_transition_to()` via `_ACTION_HOOKS` dict
- 7 tests for hooks
- Total: 71 tests in test_alarm_system.py

### 4. ✅ Force arm / open zone handling
- `arm()` refuses if active zones are open (returns message + Notify)
- `arm(force=True)` overrides and arms anyway (bypassed zones listed)
- Tamper open → always refuses, even with force=True
- Open zones in inactive groups (e.g. interior in night mode) don't block arm
- `arm_refused` action sent via Notify (MQTT) for dashboard/keypad feedback
- 7 new tests
- Total: 77 tests in test_alarm_system.py

### 5. ✅ Integration test
- Full arm → exit delay → armed → disarm cycle
- Door trigger → entry delay → alarm (and disarm during entry delay)
- Instant zone → immediate alarm
- Tamper (24h) triggers in any state (alarm when armed, silent when disarmed)
- Night mode ignores interior zones
- Sensor callback → zone_trigger → state machine → action hooks
- Force arm with open zones
- State notifications sequence verification
- Disarm from any state
- 24 integration tests passing

### 6. ✅ Package creation (micrOSPackages)
- Package pushed to https://github.com/fmandl/micrOSPackages/tree/main/alarm_system
- package.json with deps (sim800, phone_manager)
- pacman.json with layout (/modules/LM_alarm_system.py + /lib/alarm_system/)
- README.md with full documentation
- All 131 tests passing from package location

### 7. ✅ SMS control integration
- `_handle_sms(sms)` — SMS command handler with phonebook authorization
- Saját phonebook: `book='alarm'` (izolált a garázstól)
- Config: `phonebook` mező az alarm_config.json-ban (default: `alarm_users.json`)
- Parancsok:
  - `arm` / `arm full` — admin only
  - `arm night` — admin only
  - `disarm` — admin + user
  - `status` — admin + user (SMS választ küld)
- Alarm notification: `_on_alarm()` SMS-t küld minden admin-nak az alarm_memory tartalommal
- Blocked/inactive userek ignorálva
- SIM800 subscribe/unsubscribe a load/unload-ban
- Graceful fallback: ha nincs SIM800 vagy phonebook, a rendszer tovább működik
- 17 tests passing
- Location: integrated in `LM_alarm_system.py`

### 8. ✅ Remote MQTT sensor support
- `alarm_system/mqtt_watcher.py` — topic-to-zone mapper
- Subscribes to arbitrary MQTT topics, evaluates payload, calls zone_trigger
- Supports raw string and JSON field extraction
- Multiple watches on same topic (e.g. contact + tamper from one Zigbee sensor)
- `add_watch`, `remove_watch`, `list_watches` public functions
- Auto-registers zone on add_watch if not exists
- Watches saved to config file, loaded on startup
- Graceful fallback if MQTT not available (local sensors still work)
- 31 tests passing
- Location: `/home/ealfnmo/smarthome/riaszto/alarm_system/mqtt_watcher.py`

### 9. ✅ Event log
- `alarm_system/event_log.py` — circular buffer with JSON persistence
- Configurable `max_log_entries` in alarm config (default: 100)
- Events logged: arm, disarm, zone_trigger, alarm, silent_alert, system_start, system_stop
- `event_log(count=20)` — return last N entries
- `clear_log()` — clear all entries
- Persisted to `/data/alarm_log.json`
- Loaded on startup, trimmed to max_entries
- 26 tests passing
- Location: `/home/ealfnmo/smarthome/riaszto/alarm_system/event_log.py`

### 10. ✅ Alarm memory
- `_alarm_memory` list — tracks which zones caused the last alarm
- Populated on zone_trigger when it leads to ALARM or ENTRY_DELAY
- Cleared on next `arm()` call
- `alarm_memory()` — returns zone list (ready for SMS sending later)
- Included in `status()` output
- 9 tests passing
- Location: integrated in `LM_alarm_system.py`

### 11. ✅ Chime mode
- `_chime` flag — when on, delayed zones send beep notification while disarmed
- `chime('on')` / `chime('off')` / `chime()` (query)
- Only triggers on delayed zones + DISARMED state
- Sends `{"action": "chime", "zone": name}` via Notify
- 9 tests passing
- Location: integrated in `LM_alarm_system.py`

### 12. ✅ Auto-arm
- Inactivity-based automatic arming while DISARMED
- `auto_arm(delay=3600, mode='night')` — enable with delay in seconds
- `auto_arm(delay=0)` or `auto_arm()` — disable
- Timer resets on: `zone_trigger` (while DISARMED) + `disarm()`
- Async task waits for delay, then calls `arm(mode)`
- Logged as `auto_arm` event in event log
- 9 tests passing
- Location: integrated in `LM_alarm_system.py`

### 13. ✅ Zone bypass
- `bypass(name)` — ignore zone while armed
- `unbypass(name)` — re-enable zone
- 24h zones cannot be bypassed (tamper, smoke)
- Bypass clears automatically on `disarm()`
- Shown in `status()` output
- Logged as `bypass` event in event log
- 10 tests passing
- Location: integrated in `LM_alarm_system.py`

### 14. ✅ Cross-zone (dual trigger)
- New zone type: `cross` — only alarms if paired zone also triggers within time window
- `add_zone name="pir1" type="cross" group="interior" cross_pair="pir2" cross_window=30`
- First trigger: records timestamp, no alarm
- Second trigger (pair): checks if first was within window → ALARM
- Both zones added to alarm_memory
- Reduces false alarms from single PIR sensors
- Config persistence: `cross_pair` and `cross_window` saved/loaded
- 10 tests passing
- Location: integrated in `LM_alarm_system.py`

### 15. ✅ Sensor supervision (heartbeat)
- `supervise(name, timeout=600)` — enable heartbeat monitoring
- `unsupervise(name)` — disable
- Only for remote zones (GPIO refused)
- `last_seen` updated on any zone_trigger event (triggered or reset)
- Trouble zones block `arm()` unless `force=True`
- Shown in `status()` as `trouble` list
- Supervision timeout persisted in config
- 11 tests passing
- Location: integrated in `LM_alarm_system.py`

## File Structure

```
/home/ealfnmo/smarthome/garage/final_version/micrOS_fork/micrOS/packages/alarm_system/
├── DESIGN.md                   ← architecture & design document
├── PROGRESS.md                 ← this file
├── README.md                   ← package documentation
├── package.json                ← package metadata & dependencies
├── package/
│   ├── LM_alarm_system.py      ← main Load Module (public interface + state machine)
│   ├── __init__.py
│   ├── alarm_system/
│   │   ├── __init__.py
│   │   ├── door_sensor.py      ← DebouncedInput class (30 tests)
│   │   ├── event_log.py        ← circular event log (26 tests)
│   │   ├── mqtt_watcher.py     ← MQTT topic-to-zone mapper (31 tests)
│   │   ├── actions.py          ← action hooks (MQTT notify + SMS alarm)
│   │   └── sms_handler.py      ← SMS command parsing + auth (24 tests)
│   └── pacman.json             ← device file layout
└── tests/
    ├── test_alarm_system.py    ← LM_alarm_system tests (135 tests)
    ├── test_door_sensor.py     ← door_sensor tests (30 tests)
    ├── test_event_log.py       ← event_log tests (26 tests)
    ├── test_integration.py     ← integration tests (24 tests)
    ├── test_mqtt_watcher.py    ← mqtt_watcher tests (31 tests)
    └── test_sms_control.py     ← SMS control tests (24 tests)
```

## Test Summary

| Module | Tests | Status |
|--------|-------|--------|
| door_sensor.py      | 30  | ✅ passing |
| LM_alarm_system.py  | 135 | ✅ passing |
| integration         | 24  | ✅ passing |
| mqtt_watcher.py     | 31  | ✅ passing |
| event_log.py        | 26  | ✅ passing |
| sms_control.py      | 24  | ✅ passing |
| **Total**           | **270** | **✅ all passing** |

## Notes

- The old `LM_alarm.py` and `tests/test_alarm.py` can be removed once migration is complete
- Action hooks are the next priority — they make the system actually DO something on state changes
- SMS/call integration depends on how Notify evolves (TBD)
- Remote MQTT sensors will use the native micrOS 3-part topic → command mechanism
