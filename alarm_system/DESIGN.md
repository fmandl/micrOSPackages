# Alarm System - Architecture Design

## Overview

Distributed alarm system running on micrOS (ESP32-C6) with SIM800C GSM modem.
Modular design inspired by traditional alarm panels: a central controller manages
zones, state, and actions, while sensors are independent modules that report events.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            ESP32-C6 (micrOS)                                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                    LM_alarm_system.py                                │  │
│  │                    (Alarm Panel / Controller)                        │  │
│  │                                                                     │  │
│  │  ┌─────────────┐  ┌─────────────────────┐  ┌──────────────────────────┐│  │
│  │  │ State       │  │ Zone Manager        │  │ Action Dispatcher        ││  │
│  │  │ Machine     │  │                     │  │                          ││  │
│  │  │             │  │ door    [del] [per] │  │ _on_arming()    → MQTT   ││  │
│  │  │ DISARMED    │  │ tamper  [24h] [alw] │  │ _on_armed()     → MQTT   ││  │
│  │  │ ARMING      │  │ window  [ins] [per] │  │ _on_entry_delay()→ MQTT  ││  │
│  │  │ ARMED       │  │ motion  [ins] [int] │  │ _on_alarm()     → MQTT   ││  │
│  │  │ ENTRY_DELAY │  │                     │  │                   + SMS  ││  │
│  │  │ ALARM       │  │ Types:              │  │                   + Call ││  │
│  │  │             │  │  [del] delayed     │  │ _on_disarmed()  → MQTT   ││  │
│  │  │ Arm modes:  │  │  [ins] instant     │  │                          ││  │
│  │  │  full       │  │  [24h] 24-hour     │  └──────────────────────────┘│  │
│  │  │  night      │  │ Groups:             │                               │  │
│  │  │             │  │  [per] perimeter   │                               │  │
│  │  │             │  │  [int] interior    │                               │  │
│  │  │             │  │  [alw] always      │                               │  │
│  │  └─────────────┘  └─────────────────────┘                               │  │
│  │         ▲                  ▲                                         │  │
│  │         │                  │ zone_trigger(zone_id, event)            │  │
│  └─────────┼──────────────────┼─────────────────────────────────────────┘  │
│            │                  │                                             │
│            │         ┌────────┴────────┐                                   │
│            │         │                 │                                   │
│  ┌──────────────────────────┐ ┌─────────────────────┐                      │
│  │ alarm_system/            │ │  Future sensors      │                      │
│  │   door_sensor.py         │ │  alarm_system/       │                      │
│  │                          │ │   motion_sensor.py   │                      │
│  │  door (DebouncedInput)   │ │   window_sensor.py   │                      │
│  │  tamper (DebouncedInput) │ │   smoke_sensor.py    │                      │
│  │                          │ │   ...                │                      │
│  │  IRQ + debounce + confirm│ └─────────────────────┘                      │
│  │  + rescue polling        │                                              │
│  │  + MQTT publish (always) │                                              │
│  └──────────────────────────┘                                              │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                                 │
│  │    SIM800C      │  │  phone_manager  │                                 │
│  │  (SMS/Call)     │  │  (who can arm/  │                                 │
│  │                 │  │   disarm)       │                                 │
│  └─────────────────┘  └─────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
         │                              │
         │ MQTT                         │ MQTT
         ▼                              ▼
┌─────────────────┐          ┌─────────────────────┐
│  MQTT Broker    │          │  Remote Devices      │
│  (Synology)     │          │                     │
│                 │          │  - Buzzer ESP        │
│  Topics:        │          │  - Siren ESP         │
│  Alarm/sensor   │          │  - LED indicator     │
│  Alarm/state    │          │  - Keypad ESP        │
│  Alarm/action   │          │  - Dashboard         │
│  Alarm/cmd      │          └─────────────────────┘
└─────────────────┘
```

## Module Separation

### LM_alarm_system.py (Load Module — alarm panel)
- **State Machine**: DISARMED / ARMING / ARMED / ENTRY_DELAY / ALARM
- **Zone Manager**: registers zones with types (instant, delayed, 24h, cross)
- **Sensor init**: instantiates DebouncedInput from door_sensor.py
- **Public interface**: load(), unload(), arm(), disarm(), status(), zone_trigger(), add_zone(), etc.
- This is the only `LM_` module — called from micrOS shell

### alarm_system/door_sensor.py (helper module)
- DebouncedInput class (IRQ + debounce + confirm + rescue)
- Pure sensor logic — no alarm state knowledge
- Reports state changes via callback (provided by LM_alarm_system)
- Also publishes raw sensor state via Notify (MQTT) always, regardless of alarm state

### alarm_system/actions.py (helper module)
- Action dispatcher hooks called on state transitions
- Sends MQTT notifications to remote devices (buzzer, siren, LED)
- Sends alarm SMS to admin users via SIM800

### alarm_system/sms_handler.py (helper module)
- SMS command parser with phonebook authorization
- Dispatches arm/disarm/status/bypass/auto_arm commands
- Role-based access: admin-only commands (bypass, auto_arm)

### alarm_system/event_log.py (helper module)
- Circular buffer event log with JSON persistence
- Configurable max entries

### alarm_system/mqtt_watcher.py (helper module)
- Subscribes to arbitrary MQTT topics
- Maps payloads to zone_trigger() calls

### alarm_system/__init__.py
- Package init loader

## File Layout (on device)

```
/modules/LM_alarm_system.py              ← micrOS Load Module
/lib/alarm_system/__init__.py            ← package init
/lib/alarm_system/door_sensor.py         ← DebouncedInput class
/lib/alarm_system/event_log.py           ← circular event log
/lib/alarm_system/mqtt_watcher.py        ← MQTT topic-to-zone mapper
/lib/alarm_system/actions.py             ← action hooks (MQTT notify + SMS alarm)
/lib/alarm_system/sms_handler.py         ← SMS command parsing + auth
```

## Package Layout (in repo)

```
alarm_system/
├── DESIGN.md
├── PROGRESS.md
├── README.md
├── package.json
├── package/
│   ├── __init__.py
│   ├── LM_alarm_system.py
│   ├── alarm_system/
│   │   ├── __init__.py
│   │   ├── door_sensor.py
│   │   ├── event_log.py
│   │   ├── mqtt_watcher.py
│   │   ├── actions.py
│   │   └── sms_handler.py
│   └── pacman.json
└── tests/
    ├── test_alarm_system.py
    ├── test_door_sensor.py
    ├── test_event_log.py
    ├── test_integration.py
    ├── test_mqtt_watcher.py
    └── test_sms_control.py
```

## State Machine

```
                    arm(mode)
    ┌──────────┐ ──────────▶ ┌──────────┐
    │ DISARMED │             │ ARMING   │ (exit delay, _on_arming)
    └──────────┘ ◀────────── └──────────┘
       ▲  disarm()               │ delay expires
       │                         ▼
       │                    ┌──────────┐
       │  disarm()          │  ARMED   │ (monitoring active groups, _on_armed)
       │ ◀───────────────── └──────────┘
       │         │                │
       │         │                │ active zone triggers
       │         │                ▼
       │         │          ┌─────────────┐
       │         └───────── │ ENTRY_DELAY │ (_on_entry_delay) [delayed zones only]
       │           disarm() └─────────────┘
       │                          │ delay expires
       │                          ▼
       │                    ┌──────────┐
       └─────────────────── │  ALARM   │ (_on_alarm: siren, SMS, call)
              disarm()      └──────────┘

    * 24h zone (group="always"): ANY state → ALARM (immediate, no delay)
    * instant zone (active group): ARMED → ALARM (no entry delay)
    * delayed zone (active group): ARMED → ENTRY_DELAY → ALARM
    * inactive group zone: ignored (logged only)
```

## Zone Types

| Type | Behavior | Example |
|------|----------|--------|
| `delayed` | Entry delay before alarm | Front door |
| `instant` | Immediate alarm when armed | Window, motion |
| `24h` | Always triggers alarm (any state) | Tamper, smoke |

## Zone Groups (Arm Modes)

Zones belong to groups that determine which arm mode activates them:

| Group | `arm full` | `arm night` | Description |
|-------|-----------|-------------|-------------|
| `perimeter` | ✓ | ✓ | Nyílászárók (ajtó, ablak) |
| `interior` | ✓ | ✗ | Belső érzékelők (mozgás, PIR) |
| `always` | ✓ | ✓ | Mindig aktív (tamper, füst) — 24h típusú zónák |

### Zone registration example
```
alarm_system add_zone name="door" type="delayed" group="perimeter"
alarm_system add_zone name="window" type="instant" group="perimeter"
alarm_system add_zone name="motion" type="instant" group="interior"
alarm_system add_zone name="tamper" type="24h" group="always"
alarm_system add_zone name="smoke" type="24h" group="always"
```

### Arm modes
```
alarm_system arm mode="full"      # minden zóna éles (perimeter + interior + always)
alarm_system arm mode="night"     # csak perimeter + always (belső mozgás nem riaszt)
```

When `zone_trigger` is called, the system checks:
1. Is the zone's group active in the current arm mode?
2. If yes → proceed with zone type logic (delayed/instant/24h)
3. If no → ignore (log only)

## MQTT Topics

| Topic | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `{devfid}/alarm/sensor` | OUT | `{"door": "triggered"}` | Raw sensor state (always) |
| `{devfid}/alarm/state` | OUT | `{"state": "armed", "prev": "arming"}` | State transitions |
| `{devfid}/alarm/action` | OUT | `{"action": "siren_on"}` | Commands to remote devices |
| `{devfid}/alarm/zone` | OUT | `{"zone": "door", "event": "triggered"}` | Zone events |

## Public Interface (LM_alarm_system.py)

```
alarm_system load config="alarm_config.json"
alarm_system unload
alarm_system arm mode="full"
alarm_system arm mode="night"
alarm_system disarm
alarm_system status
alarm_system add_sensor name="door" pin=19 type="delayed" group="perimeter"
alarm_system add_sensor name="window" pin=21 type="instant" group="perimeter"
alarm_system remove_sensor name="door"
alarm_system add_zone name="light_living" type="instant" group="interior"
alarm_system remove_zone name="light_living"
alarm_system list_zones
alarm_system zone_trigger name="door" event="triggered"
alarm_system show_config
alarm_system pinmap
```

## Configuration File

Stored in `/data/alarm_config.json`, loaded on `load()`, updated on `add_sensor`/`remove_sensor`/`add_zone`/`remove_zone`:

```json
{
    "exit_delay": 30,
    "entry_delay": 15,
    "interval": 50,
    "sensors": [
        {"name": "door", "pin": 19, "type": "delayed", "group": "perimeter"},
        {"name": "tamper", "pin": 20, "type": "24h", "group": "always"}
    ],
    "zones": [
        {"name": "light_living", "type": "instant", "group": "interior"}
    ]
}
```

- `sensors` — local GPIO sensors (DebouncedInput, have a pin)
- `zones` — remote zones (triggered via MQTT/shell, no pin)
- `show_config` — prints current config file content
- Config is auto-saved when sensors/zones are added or removed

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `exit_delay` | 30 | Seconds after arm() before armed |
| `entry_delay` | 15 | Seconds after delayed zone triggers before alarm |
| `interval` | 50 | Sensor detection loop interval in ms |

## State Persistence

Alarm state is saved to `/data/alarm_state.json` on every transition:

```json
{
    "state": "ARMED",
    "arm_mode": "full"
}
```

### Save behavior
- `_transition_to()` writes state to file after every change
- Only `state` and `arm_mode` are persisted (zones are re-registered on load)

### Load behavior (boot/restart)
| Saved state | Restored as | Reason |
|-------------|-------------|--------|
| `DISARMED` | DISARMED | Normal |
| `ARMING` | ARMED | Exit delay already expired during reboot |
| `ARMED` | ARMED | Continue monitoring |
| `ENTRY_DELAY` | ALARM | Suspicious — reboot during entry delay |
| `ALARM` | ALARM | Continue alarm (siren, SMS, etc.) |
| File missing/corrupt | DISARMED | Safe default (first boot) |

### Internal state variables

```python
_state = 'DISARMED'       # current state
_arm_mode = None          # 'full' / 'night' / None (when disarmed)
_delay_task = None        # reference to active delay task (for cancel)
_zones = {}               # {'door': {'type': 'delayed', 'group': 'perimeter'}, ...}
```

## Interaction Flow Example

```
1. alarm_system load door_pin=19 tamper_pin=20
   → creates DebouncedInput instances (from alarm_system.door_sensor)
   → passes zone_trigger as callback to each sensor
   → registers default zones: door=delayed, tamper=24h
   → starts detection loop (single async task)
   → state: DISARMED

2. User sends SMS "arm" (or MQTT or shell)
3. alarm_system.arm() called
4. State: DISARMED → ARMING
5. _on_arming() → MQTT: {"action": "buzzer_slow"}
6. async _exit_delay_task() starts (waits exit_delay seconds)
7. After exit_delay seconds:
8. State: ARMING → ARMED
9. _on_armed() → MQTT: {"action": "buzzer_stop", "action": "led_red"}

--- later ---

10. Door opens
11. DebouncedInput detects (in detection loop)
12. DebouncedInput publishes MQTT: {"door": "triggered"} (always)
13. DebouncedInput calls callback → zone_trigger("door", "triggered")
14. zone_trigger checks: zone "door" is type "delayed", group "perimeter", group is active
15. State: ARMED → ENTRY_DELAY
16. _on_entry_delay() → MQTT: {"action": "buzzer_fast"}
17. async _entry_delay_task() starts (waits entry_delay seconds)
18. If user disarms within entry_delay → task cancelled, DISARMED, all stops
19. If not → State: ENTRY_DELAY → ALARM
20. _on_alarm() → MQTT: {"action": "siren_on"} + SMS + Call
```

## Execution Model

```
┌───────────────────────────────────────────────────────────────────┐
│                     Async Tasks                                    │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Detection Loop (always running)                              │  │
│  │                                                               │  │
│  │  while True:                                                  │  │
│  │      door.process_if_needed()                                 │  │
│  │      tamper.process_if_needed()                               │  │
│  │      door.poll()                                              │  │
│  │      tamper.poll()                                            │  │
│  │      sleep(interval)                                          │  │
│  │                                                               │  │
│  │  On state change → callback → zone_trigger() [synchronous]    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Exit Delay Task (temporary, started by arm())               │  │
│  │                                                               │  │
│  │  await sleep(exit_delay)                                      │  │
│  │  _transition_to(ARMED)                                        │  │
│  │  [task ends]                                                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Entry Delay Task (temporary, started by zone_trigger())     │  │
│  │                                                               │  │
│  │  await sleep(entry_delay)                                     │  │
│  │  _transition_to(ALARM)                                        │  │
│  │  [task ends]                                                  │  │
│  │  * cancelled if disarm() called during delay                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                     │
│  No loop in LM_alarm_system.py — only:                              │
│    - zone_trigger(): synchronous decision tree                      │
│    - arm()/disarm(): synchronous state change + starts delay task   │
│    - _transition_to(): synchronous action dispatch                  │
└───────────────────────────────────────────────────────────────────┘
```

## Action Hooks (dummy implementations, send MQTT)

```python
def _on_arming():
    """Exit delay started. Buzzer: slow beep."""
    Notify.notify(json.dumps({"action": "buzzer_slow"}), topic="alarm/action")

def _on_armed():
    """System armed. Buzzer: stop, LED: red."""
    Notify.notify(json.dumps({"action": "buzzer_stop"}), topic="alarm/action")
    Notify.notify(json.dumps({"action": "led_red"}), topic="alarm/action")

def _on_entry_delay():
    """Entry delay started. Buzzer: fast beep."""
    Notify.notify(json.dumps({"action": "buzzer_fast"}), topic="alarm/action")

def _on_alarm():
    """Alarm triggered. Siren + SMS + Call."""
    Notify.notify(json.dumps({"action": "siren_on"}), topic="alarm/action")
    # sim800.send_sms(owner, "ALARM: door opened!")
    # sim800.make_call(owner, ring_time=20)

def _on_disarmed():
    """System disarmed. Everything stops."""
    Notify.notify(json.dumps({"action": "all_stop"}), topic="alarm/action")
    Notify.notify(json.dumps({"action": "led_green"}), topic="alarm/action")
```

## SMS/Call Control (TBD)

SMS-based arm/disarm control will be implemented later.
For now, the system is controlled via MQTT or micrOS shell.

Future SMS commands (planned):
- `arm full` / `arm night`
- `disarm`
- `status`
- Authorization via phone_manager (who can arm/disarm)
- Alarm notification: who to call/SMS when alarm triggers

## MQTT Control

The micrOS `async_mqtt` module interprets 3-part topics as command execution:

```
Topic: {devfid}/alarm_system/arm
Payload: {"mode": "full"}
→ calls: alarm_system.arm(mode="full")

Topic: {devfid}/alarm_system/disarm
Payload: {}
→ calls: alarm_system.disarm()

Topic: {devfid}/alarm_system/status
Payload: {}
→ calls: alarm_system.status()
```

No custom MQTT subscribe needed — the micrOS MQTT client handles this natively.

## Tamper Handling in DISARMED State

24h zones (tamper, smoke) trigger in ANY state, but behavior differs:

| State | 24h zone triggers | Action |
|-------|-------------------|--------|
| ARMED / ENTRY_DELAY | Full alarm (siren + SMS + call) | _on_alarm() |
| DISARMED / ARMING | Silent alert (Notify only, no siren) | _on_silent_alert() |

```python
def _on_silent_alert(zone_name):
    """24h zone triggered while disarmed. Notify only, no siren."""
    Notify.notify(json.dumps({"alert": zone_name, "state": _state}), topic="alarm/alert")
```

## Alarm Timeout (TBD)

The alarm system starts and stops actions (siren, buzzer, etc.) via MQTT.
The remote device (siren ESP) decides its own timeout behavior.

- `_on_alarm()` → sends `{"action": "siren_on"}`
- `disarm()` → sends `{"action": "all_stop"}`
- If the siren has a built-in 10-minute timeout, that's its responsibility
- The alarm_system only sends start/stop commands

## Notification & Retry (TBD)

All notifications go through `Notify.notify()` which is transport-agnostic.
When SMS support is added to Notify, it will automatically be available.

Retry/escalation logic (planned for later):
- Retry failed notifications
- Escalation if no disarm within X minutes
- Multiple contact numbers

## Status Query

Inspired by professional alarm panels (Ajax, Paradox):

```python
def status():
    """Return current system status."""
    return {
        'state': _state,
        'arm_mode': _arm_mode,
        'zones': {name: {
            'type': z['type'],
            'group': z['group'],
            'status': z.get('last_event', 'ok')  # ok / triggered / tamper
        } for name, z in _zones.items()},
        'open_zones': [name for name, z in _zones.items() if z.get('last_event') == 'triggered']
    }
```

### Arm with open zones (Ajax/Paradox behavior)

| Scenario | Ajax behavior | Our implementation |
|----------|--------------|-------------------|
| Arm with door open | Warns, allows force arm | arm() returns warning, arm(force=True) overrides |
| Arm with tamper open | Refuses | arm() refuses, must fix tamper first |

```
alarm_system arm mode="full"              # refuses if zones open
alarm_system arm mode="full" force=True   # arms anyway, bypasses open zones
```

## Remote Sensor Support (MQTT Zone Trigger)

For sensors on other ESP devices (or any MQTT source), a zone can be triggered
via the standard micrOS MQTT command mechanism:

```
Topic: {devfid}/alarm_system/zone_trigger
Payload: {"name": "window_kitchen", "event": "triggered"}
→ calls: alarm_system.zone_trigger(name="window_kitchen", event="triggered")
```

This enables:
- Remote ESP sensors (window, motion, smoke on different devices)
- Smart switches (light turned on while armed → trigger)
- Any MQTT-capable device to act as a zone input

### Remote sensor registration

Remote zones are registered the same way as local ones:
```
alarm_system add_zone name="window_kitchen" type="instant" group="perimeter"
alarm_system add_zone name="light_living" type="instant" group="interior"
```

The alarm_system doesn't care if the trigger comes from a local DebouncedInput
callback or from an MQTT command — `zone_trigger()` handles both identically.

## Dependencies

- `sim800` package — SMS/call for alarm notification (TBD)
- `phone_manager` package — authorization, who can arm/disarm (multi-phonebook: `book='alarm'`)
- `async_mqtt` package — MQTT communication + remote control

## Future Sensors (same interface)

Any new sensor can be added as `alarm_system/<sensor_name>.py` and call
`zone_trigger(zone_name, event)` — the alarm_system handles the rest:
- Window sensor (reed contact)
- PIR motion sensor
- Smoke detector
- Glass break sensor
- Water leak sensor
- Remote MQTT sensors (any device publishing to zone_trigger topic)


## Professional Alarm System Comparison & Future Development

### Current coverage vs Ajax/Paradox

| Feature                              | Ajax/Paradox | Our system | Status                  |
|--------------------------------------|--------------|------------|-------------------------|
| State machine (arm/disarm/alarm)     | ✅           | ✅         | Done                    |
| Zone types (delayed/instant/24h)     | ✅           | ✅         | Done                    |
| Exit/entry delay                     | ✅           | ✅         | Done                    |
| Partial arm (night/stay mode)        | ✅           | ✅         | Done                    |
| Tamper handling (24h, always active) | ✅           | ✅         | Done                    |
| State persistence (survives reboot)  | ✅           | ✅         | Done                    |
| Action dispatch (siren, buzzer, LED) | ✅           | ✅         | Done (MQTT)             |
| Config file (sensors/zones)          | ✅           | ✅         | Done                    |
| Multiple partitions                  | ✅           | ❌         | Not needed (separate ESP per area) |
| Zone bypass                          | ✅           | ✅         | Done                    |
| Alarm memory (which zone triggered)  | ✅           | ✅         | Done                    |
| Event log                            | ✅           | ✅         | Done                    |
| User PIN codes                       | ✅           | ❌         | Not in alarm panel (see note) |
| Auto-arm (timed arming)              | ✅           | ✅         | Done                    |
| Bell/siren timeout                   | ✅           | ❌         | Siren device responsibility |
| Sensor supervision (heartbeat)       | ✅           | ✅         | Done                    |
| Cross-zone (dual trigger)            | ✅ (Paradox) | ✅         | Done                    |
| Chime mode                           | ✅           | ✅         | Done                    |
| PGM outputs (relay control)          | ✅           | ✅         | Done (MQTT actions + local GPIO) |

### Our advantages over traditional systems

| Feature                    | Traditional                    | Our system                          |
|----------------------------|--------------------------------|-------------------------------------|
| Distributed architecture   | ❌ (closed, proprietary)       | ✅ MQTT, any device can connect     |
| Remote zones via MQTT      | ❌ (expensive radio sensors)   | ✅ any ESP/MQTT device              |
| SMS/call fallback          | ✅ (GSM module addon)          | ✅ built-in SIM800                  |
| Open source / customizable | ❌                             | ✅                                  |
| No cloud dependency        | ❌ (Ajax needs cloud)          | ✅ local MQTT broker                |
| Cost per zone              | €€€ (proprietary sensors)     | € (ESP + reed switch)              |

### Planned future features (priority order)

#### 1. ✅ Zone bypass (Implemented)
Temporarily disable a zone without removing it. Useful when a window is left open.
```
alarm_system bypass name="window_kitchen"
alarm_system unbypass name="window_kitchen"
```
- Bypassed zones are ignored during armed state (zone_trigger returns "bypassed")
- Bypass clears automatically on disarm
- 24h zones (tamper, smoke) cannot be bypassed
- Bypass state shown in `status()` output
- Logged as `bypass` event in event log

#### 2. ✅ Event log (Implemented)
Record all events with timestamp for audit trail.
```
alarm_system event_log              # show last 20 events
alarm_system event_log count=50     # show last 50
alarm_system clear_log              # clear all entries
```
Events logged:
- `system_start` — `{state, mode, zones}`
- `system_stop`
- `arm` — `{mode, force, bypassed}`
- `disarm` — `{from_state}`
- `zone_trigger` — `{zone, type, result}`
- `alarm` — `{zone, type}`
- `silent_alert` — `{zone, state}`

Storage: circular buffer in `/data/alarm_log.json`.
Max entries configurable via `max_log_entries` in alarm config (default: 100).
Helper module: `alarm_system/event_log.py`.

#### 3. ✅ Chime mode (Implemented)
When disarmed, optionally notify (beep) when a delayed zone opens. Useful to know when someone enters.
```
alarm_system chime state="on"
alarm_system chime state="off"
alarm_system chime                  # query current state
```
- Only affects delayed zones (door) while DISARMED
- Sends `{"action": "chime", "zone": "<name>"}` via Notify to `alarm/action` topic
- Does NOT trigger alarm
- Instant and 24h zones are not affected

#### 4. ✅ Alarm memory (Implemented)
After alarm, remember which zone(s) caused it. Cleared on next arm.
```
alarm_system alarm_memory           # show alarm cause
```
- `_alarm_memory` list populated when zone_trigger leads to ALARM or ENTRY_DELAY
- Cleared automatically on next `arm()` call
- `disarm()` does NOT clear it (so you can check after disarming)
- Included in `status()` output as `alarm_memory` field
- Ready for SMS sending: `", ".join(alarm_memory())`

#### 5. ✅ Sensor supervision (Implemented)
Remote MQTT sensors should periodically report they're alive. If no heartbeat for X minutes, mark zone as "trouble".
```
alarm_system supervise name="window_kitchen" timeout=600   # expect activity every 10 min
alarm_system unsupervise name="window_kitchen"             # disable
```
- Only for remote zones (not local GPIO — refused for pin-based sensors)
- `last_seen` updated on ANY event (triggered or reset)
- If `time.time() - last_seen > timeout` → zone is in "trouble"
- Trouble zones block `arm()` (like tamper) — `force=True` overrides
- `status()` shows `trouble` list
- Supervision timeout saved in config, `last_seen` initialized on load
- Works with mqtt_watcher: any payload from watched topic updates last_seen via zone_trigger

#### 6. ✅ Auto-arm (Implemented)
Automatically arm after a configurable time of inactivity.
```
alarm_system auto_arm delay=3600 mode="night"   # auto arm after 1h inactivity
alarm_system auto_arm delay=0                   # disable
alarm_system auto_arm                           # disable (same as delay=0)
```
- Inactivity timer resets on: `zone_trigger` (while DISARMED) + `disarm()`
- Only counts while DISARMED (no point when already armed)
- When timer expires → calls `arm(mode=_auto_arm_mode)`
- Logged as `auto_arm` event in event log
- Task-based: new async task started on each activity reset

#### 7. ~~Multiple partitions~~ (Not implementing)
Split zones into independent partitions that can be armed/disarmed separately.
- **Decision**: Not needed — separate ESP per area (garage, apartment) achieves the same
  with better isolation, independent reboot, and shared sensors/sirens via MQTT.
- Each ESP runs its own `alarm_system` instance with its own config.
- Shared resources (siren, buzzer) are MQTT-controlled — both partitions can trigger them.

#### 8. ~~User PIN codes~~ (Not in alarm panel)
Authentication/authorization is handled at the interface level, not in the alarm panel:

| Interface | Auth method | Responsibility |
|-----------|-------------|----------------|
| MQTT | MQTT broker auth (user/pass, ACL) | Broker config |
| SMS | Phone number → phone_manager phonebook | `phone_manager` package |
| Keypad | PIN code → `alarm_system/keypad.py` | Future keypad module |

The alarm panel (`LM_alarm_system.py`) trusts whoever calls its functions —
the caller is responsible for verifying authorization before invoking arm/disarm.


## Remote MQTT Sensor Support — Topic Watcher (Step 8)

### Problem

The native micrOS 3-part topic mechanism only works with other micrOS devices.
Non-micrOS devices (Zigbee gateways, Shelly, Tasmota, ESPHome, etc.) publish
to their own topics in their own formats.

### Solution: MQTT Topic Watcher

A configurable topic-to-zone mapper that:
1. Subscribes to arbitrary MQTT topics
2. Evaluates payload against trigger conditions
3. Calls `zone_trigger(zone_name, event)` when condition matches

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MQTT Broker                               │
│                                                                  │
│  Topics:                                                         │
│    home/window_kitchen/state    → "open" / "closed"              │
│    zigbee/motion_hallway        → {"occupancy": true}            │
│    shelly/switch1/relay/0       → "on" / "off"                   │
│    tasmota/smoke/SENSOR         → {"smoke": "detected"}          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ subscribe
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              alarm_system/mqtt_watcher.py                         │
│                                                                  │
│  Watches = [                                                     │
│    {                                                             │
│      "topic": "home/window_kitchen/state",                       │
│      "zone": "window_kitchen",                                   │
│      "trigger_value": "open",                                    │
│      "reset_value": "closed"                                     │
│    },                                                            │
│    {                                                             │
│      "topic": "zigbee/motion_hallway",                           │
│      "zone": "motion_hallway",                                   │
│      "trigger_field": "occupancy",                               │
│      "trigger_value": true,                                      │
│      "reset_value": false                                        │
│    },                                                            │
│    {                                                             │
│      "topic": "shelly/switch1/relay/0",                          │
│      "zone": "light_living",                                     │
│      "trigger_value": "on"                                       │
│    }                                                             │
│  ]                                                               │
│                                                                  │
│  On message received:                                            │
│    1. Match topic to watch entry                                 │
│    2. Extract value (raw payload or JSON field)                   │
│    3. Compare to trigger_value / reset_value                     │
│    4. Call zone_trigger(zone, "triggered" or "reset")            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ zone_trigger()
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              LM_alarm_system.py (state machine)                   │
└─────────────────────────────────────────────────────────────────┘
```

### Watch Entry Configuration

Each watch entry maps one MQTT topic to one zone:

```json
{
    "topic": "home/window_kitchen/state",
    "zone": "window_kitchen",
    "trigger_value": "open",
    "reset_value": "closed",
    "trigger_field": null
}
```

| Field           | Required | Description                                          |
|-----------------|----------|------------------------------------------------------|
| `topic`         | yes      | MQTT topic to subscribe to                           |
| `zone`          | yes      | Zone name to trigger (must be registered in alarm)   |
| `trigger_value` | yes      | Value that means "triggered"                         |
| `reset_value`   | no       | Value that means "reset" (if absent, no reset sent)  |
| `trigger_field` | no       | JSON field to extract from payload (if payload is JSON) |

### Payload Matching Logic

```python
def _evaluate_message(watch, payload):
    """Evaluate incoming MQTT message against watch entry.
    :param watch dict: watch configuration
    :param payload str: raw MQTT payload
    :return str|None: 'triggered', 'reset', or None (no match)
    """
    # Extract value
    field = watch.get('trigger_field')
    if field:
        # JSON payload — extract field
        data = json.loads(payload)
        value = data.get(field)
    else:
        # Raw string payload
        value = payload.strip()

    # Compare
    if value == watch['trigger_value']:
        return 'triggered'
    if 'reset_value' in watch and value == watch['reset_value']:
        return 'reset'
    return None
```

### Config File Extension

The watches are stored in the alarm config file:

```json
{
    "exit_delay": 30,
    "entry_delay": 15,
    "interval": 50,
    "sensors": [...],
    "zones": [...],
    "watches": [
        {
            "topic": "home/window_kitchen/state",
            "zone": "window_kitchen",
            "trigger_value": "open",
            "reset_value": "closed"
        },
        {
            "topic": "zigbee/motion_hallway",
            "zone": "motion_hallway",
            "trigger_field": "occupancy",
            "trigger_value": true,
            "reset_value": false
        },
        {
            "topic": "shelly/switch1/relay/0",
            "zone": "light_living",
            "trigger_value": "on"
        }
    ]
}
```

### Public Interface

```
alarm_system add_watch topic="home/window/state" zone="window" trigger_value="open" reset_value="closed"
alarm_system add_watch topic="zigbee/motion" zone="motion" trigger_field="occupancy" trigger_value=true reset_value=false
alarm_system remove_watch topic="home/window/state"
alarm_system list_watches
```

### Implementation Notes

- The watcher uses the micrOS MQTT client's subscribe mechanism
- Each watch entry subscribes to one topic
- On `load()`, all watches from config are subscribed
- On `unload()`, all watches are unsubscribed
- `add_watch` also auto-registers the zone via `add_zone()` if not exists
- The watcher is a helper module: `alarm_system/mqtt_watcher.py`

### File Layout (on device)

```
/modules/LM_alarm_system.py
/lib/alarm_system/__init__.py
/lib/alarm_system/door_sensor.py
/lib/alarm_system/event_log.py
/lib/alarm_system/mqtt_watcher.py
/lib/alarm_system/actions.py
/lib/alarm_system/sms_handler.py
```

### Example Scenarios

#### Zigbee window sensor (via Zigbee2MQTT)
```
alarm_system add_zone name="window_kitchen" type="instant" group="perimeter"
alarm_system add_watch topic="zigbee2mqtt/window_kitchen" zone="window_kitchen" trigger_field="contact" trigger_value=false reset_value=true
```
(Zigbee2MQTT: `contact: false` = open, `contact: true` = closed)

#### Shelly door sensor
```
alarm_system add_zone name="front_door" type="delayed" group="perimeter"
alarm_system add_watch topic="shellies/door1/sensor/state" zone="front_door" trigger_value="open" reset_value="close"
```

#### Smart light as trip wire (armed + light turns on = intruder)
```
alarm_system add_zone name="light_hallway" type="instant" group="interior"
alarm_system add_watch topic="tasmota/light_hallway/POWER" zone="light_hallway" trigger_value="ON"
```

#### Smoke detector (always active, 24h zone)
```
alarm_system add_zone name="smoke_kitchen" type="24h" group="always"
alarm_system add_watch topic="zigbee2mqtt/smoke_kitchen" zone="smoke_kitchen" trigger_field="smoke" trigger_value=true reset_value=false
```

#### Multiple watches on same topic (Sonoff window sensor with tamper)

One Zigbee device publishes both `contact` and `tamper` in the same payload:
```
Topic: zigbee2mqtt/sonoff_living_room_window_sensor
Payload: {"battery":100,"battery_low":false,"contact":false,"linkquality":200,"tamper":false,"voltage":3000}
```

Two watch entries on the same topic, each watching a different field:
```
alarm_system add_zone name="living_window" type="instant" group="perimeter"
alarm_system add_watch topic="zigbee2mqtt/sonoff_living_room_window_sensor" zone="living_window" trigger_field="contact" trigger_value=false reset_value=true

alarm_system add_zone name="living_window_tamper" type="24h" group="always"
alarm_system add_watch topic="zigbee2mqtt/sonoff_living_room_window_sensor" zone="living_window_tamper" trigger_field="tamper" trigger_value=true reset_value=false
```

Resulting config:
```json
{
    "exit_delay": 30,
    "entry_delay": 15,
    "interval": 50,
    "sensors": [
        {"name": "door", "pin": 19, "type": "delayed", "group": "perimeter"},
        {"name": "tamper", "pin": 20, "type": "24h", "group": "always"}
    ],
    "zones": [
        {"name": "living_window", "type": "instant", "group": "perimeter"},
        {"name": "living_window_tamper", "type": "24h", "group": "always"}
    ],
    "watches": [
        {
            "topic": "zigbee2mqtt/sonoff_living_room_window_sensor",
            "zone": "living_window",
            "trigger_field": "contact",
            "trigger_value": false,
            "reset_value": true
        },
        {
            "topic": "zigbee2mqtt/sonoff_living_room_window_sensor",
            "zone": "living_window_tamper",
            "trigger_field": "tamper",
            "trigger_value": true,
            "reset_value": false
        }
    ]
}
```

Note: Multiple watch entries can reference the same MQTT topic. When a message
arrives, the watcher evaluates ALL matching entries and triggers each zone independently.

### Dependencies

- `async_mqtt` package must be loaded for MQTT subscribe to work
- If MQTT is not available, watches are silently skipped (local sensors still work)
