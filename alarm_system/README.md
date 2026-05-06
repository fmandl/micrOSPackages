# micrOS Application: alarm_system

Distributed alarm system for micrOS devices. Manages zones, state machine, and action dispatch via MQTT. Supports local GPIO sensors (door, tamper) and remote MQTT zones. Inspired by professional alarm panels (Ajax, Paradox).

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

## Hardware

- **Door sensor**: Reed contact (normally open, active-low with pull-up)
- **Tamper sensor**: Tamper switch (normally closed)
- **Interface**: GPIO with IRQ + debounce + confirm + rescue polling

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
alarm_system add_sensor name="tamper" pin=20 type="24h" group="always"
alarm_system remove_sensor name="door"
alarm_system add_zone name="light_living" type="instant" group="interior"
alarm_system remove_zone name="light_living"
alarm_system list_zones
alarm_system zone_trigger name="door" event="triggered"
alarm_system show_config
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
```

## Zone Types

| Type      | Behavior                        | Example              |
|-----------|---------------------------------|----------------------|
| `delayed` | Entry delay before alarm        | Front door           |
| `instant` | Immediate alarm when armed      | Window, motion       |
| `24h`     | Always triggers (any state)     | Tamper, smoke        |

## Zone Groups (Arm Modes)

| Group       | `arm full` | `arm night` | Description                    |
|-------------|-----------|-------------|--------------------------------|
| `perimeter` | ✓         | ✓           | Doors, windows                 |
| `interior`  | ✓         | ✗           | Motion sensors                 |
| `always`    | ✓         | ✓           | Tamper, smoke (24h zones)      |

## Action Hooks (MQTT notifications to remote devices)

| State transition | MQTT action sent              | Remote device response |
|-----------------|-------------------------------|----------------------|
| → ARMING        | `{"action": "buzzer_slow"}`   | Buzzer slow beep     |
| → ARMED         | `{"action": "buzzer_stop"}`   | Buzzer stops         |
|                 | `{"action": "led_red"}`       | LED turns red        |
| → ENTRY_DELAY   | `{"action": "buzzer_fast"}`   | Buzzer fast beep     |
| → ALARM         | `{"action": "siren_on"}`      | Siren activates      |
| → DISARMED      | `{"action": "all_stop"}`      | Everything stops     |
|                 | `{"action": "led_green"}`     | LED turns green      |

## Force Arm

- `arm()` refuses if zones are open in active groups
- `arm(force=True)` overrides (bypasses open zones)
- Tamper open → always refuses, even with force

## Config File

Stored in `/data/alarm_config.json`, auto-saved on sensor/zone changes:

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

## State Persistence

State survives reboot via `/data/alarm_state.json`:
- ARMED → stays ARMED
- ARMING → becomes ARMED (delay expired during reboot)
- ENTRY_DELAY → becomes ALARM (suspicious reboot)
- ALARM → stays ALARM

## MQTT Control

Uses native micrOS 3-part topic command execution:
```
Topic: {devfid}/alarm_system/arm     Payload: {"mode": "full"}
Topic: {devfid}/alarm_system/disarm  Payload: {}
Topic: {devfid}/alarm_system/status  Payload: {}
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

## Author

Flórián Mandl ([@fmandl](https://github.com/fmandl))
