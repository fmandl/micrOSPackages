# micrOS Application: alarm_system

Distributed alarm system for micrOS devices. Manages zones, state machine, and action dispatch via MQTT. Supports local GPIO sensors, remote MQTT zones, topic watchers, event logging, supervision, and more. Inspired by professional alarm panels (Ajax, Paradox).

## Install

```bash
pacman install "github:fmandl/micrOSPackages/alarm_system"
```

```bash
pacman upgrade "alarm_system"
pacman uninstall "alarm_system"
```

## Device Layout

- Package files: `/lib/alarm_system`
- Load module: `/modules/LM_alarm_system.py`
- Config file: `/data/alarm_config.json`
- State file: `/data/alarm_state.json`
- Event log: `/data/alarm_log.json`

## Usage

```commandline
alarm_system load config="alarm_config.json"
alarm_system unload
alarm_system arm mode="full"
alarm_system arm mode="full" force=True
alarm_system arm mode="night"
alarm_system disarm
alarm_system status
alarm_system add_sensor name="door" pin=19 type="delayed" group="perimeter"
alarm_system remove_sensor name="door"
alarm_system add_zone name="light" type="instant" group="interior"
alarm_system add_zone name="pir1" type="cross" group="interior" cross_pair="pir2" cross_window=30
alarm_system remove_zone name="light"
alarm_system list_zones
alarm_system zone_trigger name="door" event="triggered"
alarm_system show_config
alarm_system add_watch topic="zigbee2mqtt/sensor" zone="window" trigger_field="contact" trigger_value=false reset_value=true
alarm_system remove_watch topic="zigbee2mqtt/sensor"
alarm_system list_watches
alarm_system event_log count=20
alarm_system clear_log
alarm_system alarm_memory
alarm_system chime state="on"
alarm_system chime state="off"
alarm_system auto_arm delay=3600 mode="night"
alarm_system auto_arm delay=0
alarm_system bypass name="window"
alarm_system unbypass name="window"
alarm_system supervise name="window" timeout=600
alarm_system unsupervise name="window"
alarm_system pinmap
```

## State Machine

```
                arm(mode)
  DISARMED ──────────────▶ ARMING (exit delay, buzzer slow)
     ▲                        │ delay expires
     │                        ▼
     │  disarm()          ARMED (monitoring active groups)
     │ ◀─────────────────    │
     │         │              │ active zone triggers
     │         │              ▼
     │         └────────  ENTRY_DELAY (buzzer fast)
     │           disarm()    │ delay expires
     │                       ▼
     └────────────────── ALARM (siren, SMS, call)
            disarm()

  * 24h zone (tamper): ANY state → ALARM (immediate)
  * instant zone: ARMED → ALARM (no entry delay)
  * delayed zone: ARMED → ENTRY_DELAY → ALARM
  * cross zone: ARMED → ALARM only if pair also triggers within window
```

## Zone Types

| Type      | Behavior                                    | Example              |
|-----------|---------------------------------------------|----------------------|
| `delayed` | Entry delay before alarm                    | Front door           |
| `instant` | Immediate alarm when armed                  | Window, motion       |
| `24h`     | Always triggers (any state)                 | Tamper, smoke        |
| `cross`   | Alarm only if paired zone triggers within X sec | Dual PIR         |

## Zone Groups (Arm Modes)

| Group       | `arm full` | `arm night` | Description                    |
|-------------|-----------|-------------|--------------------------------|
| `perimeter` | ✓         | ✓           | Doors, windows                 |
| `interior`  | ✓         | ✗           | Motion sensors                 |
| `always`    | ✓         | ✓           | Tamper, smoke (24h zones)      |

## SMS Control

SMS-based arm/disarm with phonebook authorization. Uses its own isolated phonebook (`book='alarm'`).

### SMS Commands

| SMS text | admin | user | Description |
|----------|-------|------|-------------|
| `arm` / `arm full` | ✓ | ✓ | Arm full mode |
| `arm night` | ✓ | ✓ | Arm night mode |
| `disarm` | ✓ | ✓ | Disarm |
| `status` | ✓ | ✓ | Reply SMS with current state |
| `bypass <zone>` | ✓ | ✗ | Bypass a zone (admin only) |
| `unbypass <zone>` | ✓ | ✗ | Remove bypass (admin only) |
| `auto_arm <sec> [mode]` | ✓ | ✗ | Configure auto-arm (admin only) |

### Alarm Notification

When alarm triggers, SMS is sent to all admin users:
```
ALARM! Zones: door, window
```

### Phonebook Config

In `alarm_config.json`:
```json
{
    "phonebook": "alarm_users.json"
}
```

Manage users:
```commandline
users load json_file="alarm_users.json" book="alarm"
users add_user phone="+36201234567" name="Owner" role="admin" book="alarm"
users add_user phone="+36209876543" name="Cleaner" role="user" book="alarm"
```

## Features

- **Event log**: Circular buffer with configurable max entries, persisted to JSON
- **Alarm memory**: Tracks which zones caused the last alarm (cleared on next arm)
- **Chime mode**: Beep on delayed zone open while disarmed
- **Auto-arm**: Automatic arming after inactivity (resets on zone_trigger + disarm)
- **Zone bypass**: Temporarily ignore a zone while armed (clears on disarm)
- **Cross-zone**: Dual trigger — alarm only if paired zone also triggers within time window
- **Sensor supervision**: Heartbeat monitoring for remote zones (trouble blocks arm)
- **MQTT watcher**: Subscribe to arbitrary topics, map payloads to zone triggers
- **Force arm**: Override open zones (except tamper)
- **State persistence**: Survives reboot

## MQTT Topic Watcher

Subscribe to non-micrOS devices (Zigbee2MQTT, Shelly, Tasmota):

```commandline
alarm_system add_watch topic="zigbee2mqtt/window" zone="window" trigger_field="contact" trigger_value=false reset_value=true
alarm_system add_watch topic="shelly/door/state" zone="door" trigger_value="open" reset_value="close"
```

## Config File

```json
{
    "exit_delay": 30,
    "entry_delay": 15,
    "interval": 50,
    "max_log_entries": 100,
    "sensors": [
        {"name": "door", "pin": 19, "type": "delayed", "group": "perimeter"}
    ],
    "zones": [
        {"name": "window", "type": "instant", "group": "perimeter", "supervision": 600}
    ],
    "watches": [
        {"topic": "zigbee2mqtt/window", "zone": "window", "trigger_field": "contact", "trigger_value": false, "reset_value": true}
    ]
}
```

## Dependencies

Auto-installed via `mip` based on `package.json`:
```
github:fmandl/micrOSPackages/sim800
github:fmandl/micrOSPackages/phone_manager
```

## Tests

```bash
cd alarm_system
python3 -m pytest tests/ -v
```

246 tests (alarm_system + door_sensor + integration + event_log + mqtt_watcher).

## Author

Flórián Mandl ([@fmandl](https://github.com/fmandl))
