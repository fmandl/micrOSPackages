# Alarm System — User Guide

## Quick Start

### 1. Install the package

```commandline
pacman install "github:fmandl/micrOSPackages/alarm_system"
```

### 2. Start the system

```commandline
alarm_system load
```

### 3. Add your first sensor

```commandline
alarm_system add_sensor name="front_door" pin=19 type="delayed" group="perimeter"
```

### 4. Arm and test

```commandline
alarm_system arm mode="full"
```

---

## Concepts

### States

| State | Meaning | What happens |
|-------|---------|--------------|
| DISARMED | System off | Sensors report but don't trigger alarm |
| ARMING | Exit delay running | You have time to leave |
| ARMED | Monitoring active | Zone triggers lead to alarm |
| ENTRY_DELAY | Entry delay running | You have time to disarm |
| ALARM | Alarm active | Siren + SMS + notifications |

### Zone Types

| Type | When it triggers | Use case |
|------|-----------------|----------|
| `delayed` | After entry delay | Front door — gives you time to disarm |
| `instant` | Immediately | Windows, motion — no delay needed |
| `24h` | Always (even disarmed) | Tamper, smoke — always critical |
| `cross` | Only if pair also triggers | Dual PIR — reduces false alarms |

### Zone Groups

| Group | Active in `full` | Active in `night` | Use case |
|-------|-----------------|-------------------|----------|
| `perimeter` | ✓ | ✓ | Doors, windows (shell of the building) |
| `interior` | ✓ | ✗ | Motion sensors (you're inside at night) |
| `always` | ✓ | ✓ | Tamper, smoke (always critical) |

### Arm Modes

| Mode | What's monitored | When to use |
|------|-----------------|-------------|
| `full` | Everything (perimeter + interior + always) | Leaving the house |
| `night` | Perimeter + always (interior ignored) | Sleeping — you can move inside |

---

## Scenarios

### Scenario 1: Basic Home Setup

**Situation**: Apartment with front door, 2 windows, 1 motion sensor, 1 tamper switch.

```commandline
alarm_system load

# Local GPIO sensors
alarm_system add_sensor name="front_door" pin=19 type="delayed" group="perimeter"
alarm_system add_sensor name="tamper" pin=20 type="24h" group="always"

# Remote zones (Zigbee sensors via MQTT)
alarm_system add_zone name="window_kitchen" type="instant" group="perimeter"
alarm_system add_zone name="window_bedroom" type="instant" group="perimeter"
alarm_system add_zone name="motion_hallway" type="instant" group="interior"

# MQTT watches for Zigbee2MQTT sensors
alarm_system add_watch topic="zigbee2mqtt/window_kitchen" zone="window_kitchen" trigger_field="contact" trigger_value=false reset_value=true
alarm_system add_watch topic="zigbee2mqtt/window_bedroom" zone="window_bedroom" trigger_field="contact" trigger_value=false reset_value=true
alarm_system add_watch topic="zigbee2mqtt/motion_hallway" zone="motion_hallway" trigger_field="occupancy" trigger_value=true reset_value=false
```

**Daily use:**
```commandline
# Leaving home
alarm_system arm mode="full"
# → 30s exit delay → buzzer beeps slowly → you leave → system armed

# Coming home
# → open front door → entry delay starts → buzzer beeps fast
alarm_system disarm
# → everything stops, LED green

# Going to sleep
alarm_system arm mode="night"
# → windows and doors monitored, but you can walk to the bathroom
```

---

### Scenario 2: Garage with SIM800 SMS Control

**Situation**: Garage with door sensor, controlled via SMS (no WiFi dashboard).

```commandline
alarm_system load

# Garage door sensor (local GPIO)
alarm_system add_sensor name="garage_door" pin=19 type="delayed" group="perimeter"

# SMS phonebook setup
users load json_file="alarm_users.json" book="alarm"
users add_user phone="+36201234567" name="Owner" role="admin" book="alarm"
users add_user phone="+36209876543" name="Wife" role="user" book="alarm"
```

**SMS commands (send from your phone):**
```
arm              → arms in full mode
arm night        → arms in night mode
disarm           → disarms
status           → replies with current state
```

**What happens on alarm:**
```
1. Garage door opens while armed
2. Entry delay starts (15s)
3. Nobody disarms
4. ALARM state → siren on
5. SMS sent to Owner: "ALARM! Zones: garage_door"
```

---

### Scenario 3: Shop with Auto-Arm

**Situation**: Shop closes at 18:00. If nobody arms by 19:00, auto-arm kicks in.

```commandline
alarm_system load

# Sensors
alarm_system add_sensor name="shop_door" pin=19 type="delayed" group="perimeter"
alarm_system add_zone name="motion_shop" type="instant" group="interior"
alarm_system add_watch topic="zigbee2mqtt/motion_shop" zone="motion_shop" trigger_field="occupancy" trigger_value=true reset_value=false

# Auto-arm: if no activity for 1 hour → arm full
alarm_system auto_arm delay=3600 mode="full"

# Chime: beep when someone enters (while disarmed)
alarm_system chime state="on"
```

**How it works:**
```
18:00 — Last person leaves, door closes
18:00 — Activity timer resets (door triggered)
19:00 — 1 hour of no activity → system auto-arms in full mode
19:00 — Event log: "auto_arm"

Next morning:
08:00 — Owner arrives, opens door → entry delay
08:00 — Owner sends SMS: "disarm" → system disarmed
08:00 — Chime beeps (door opened while disarmed) — nice confirmation
```

---

### Scenario 4: Zigbee Sensor with Tamper Detection

**Situation**: Sonoff window sensor that reports both `contact` and `tamper` in one payload.

```
Zigbee2MQTT publishes:
Topic: zigbee2mqtt/sonoff_living_window
Payload: {"battery":100,"contact":false,"tamper":false,"linkquality":200}
```

```commandline
# Window zone (instant, perimeter)
alarm_system add_zone name="living_window" type="instant" group="perimeter"
alarm_system add_watch topic="zigbee2mqtt/sonoff_living_window" zone="living_window" trigger_field="contact" trigger_value=false reset_value=true

# Tamper zone (24h, always — triggers even when disarmed)
alarm_system add_zone name="living_window_tamper" type="24h" group="always"
alarm_system add_watch topic="zigbee2mqtt/sonoff_living_window" zone="living_window_tamper" trigger_field="tamper" trigger_value=true reset_value=false

# Supervise: alert if sensor goes silent for 10 minutes
alarm_system supervise name="living_window" timeout=600
alarm_system supervise name="living_window_tamper" timeout=600
```

**What happens:**
- Window opens while armed → ALARM (instant zone)
- Someone removes the sensor cover (tamper) while disarmed → silent alert (MQTT notification, no siren)
- Sensor battery dies / Zigbee network drops → after 10 min, zone shows "trouble" → can't arm until fixed

---

### Scenario 5: Dual PIR (Cross-Zone) to Reduce False Alarms

**Situation**: Two PIR motion sensors in hallway. Single PIR can false-trigger (cat, heat). Only alarm if BOTH trigger within 30 seconds.

```commandline
alarm_system add_zone name="pir_hallway_1" type="cross" group="interior" cross_pair="pir_hallway_2" cross_window=30
alarm_system add_zone name="pir_hallway_2" type="cross" group="interior" cross_pair="pir_hallway_1" cross_window=30

alarm_system add_watch topic="zigbee2mqtt/pir_hallway_1" zone="pir_hallway_1" trigger_field="occupancy" trigger_value=true
alarm_system add_watch topic="zigbee2mqtt/pir_hallway_2" zone="pir_hallway_2" trigger_field="occupancy" trigger_value=true
```

**What happens:**
```
Cat walks past PIR 1:
  → "Cross-zone: pir_hallway_1 triggered, waiting for pair"
  → PIR 2 doesn't trigger within 30s → nothing happens ✓

Intruder walks through hallway:
  → PIR 1 triggers
  → 5 seconds later PIR 2 triggers
  → "ALARM: cross-zone pir_hallway_1+pir_hallway_2 triggered (5s apart)"
```

---

### Scenario 6: Bypass a Zone Temporarily

**Situation**: You want to leave the kitchen window open for ventilation but still arm the system.

```commandline
# Try to arm — refused because window is open
alarm_system arm mode="full"
# → "Cannot arm: open zones: window_kitchen"

# Option 1: Force arm (zone still monitored — if it closes then opens again, alarm)
alarm_system arm mode="full" force=True

# Option 2: Bypass (zone completely ignored until disarm)
alarm_system bypass name="window_kitchen"
alarm_system arm mode="full"
# → Arms successfully, window_kitchen is ignored

# When you come home and disarm:
alarm_system disarm
# → Bypass automatically cleared, window_kitchen monitored again
```

**Via SMS (admin only):**
```
bypass window_kitchen
arm
```

---

### Scenario 7: Night Mode

**Situation**: Going to sleep. You want doors/windows monitored but motion sensors off (you walk to bathroom at night).

```commandline
alarm_system arm mode="night"
```

**What's monitored:**
- ✓ front_door (perimeter) — if someone opens the door → entry delay → alarm
- ✓ window_kitchen (perimeter) — if window opens → instant alarm
- ✓ tamper (always) — if someone tampers → alarm
- ✗ motion_hallway (interior) — ignored, you can walk freely

**What happens at night:**
```
You walk to bathroom:
  → motion_hallway triggers
  → "Ignored: zone motion_hallway group 'interior' not active in mode 'night'"
  → No alarm ✓

Someone breaks window:
  → window_kitchen triggers
  → ALARM (instant zone, perimeter group, active in night mode)
```

---

### Scenario 8: Multiple Users with Different Permissions

**Situation**: Home with owner (full control) and cleaner (can only disarm during work hours).

```commandline
# Setup phonebook
users load json_file="alarm_users.json" book="alarm"
users add_user phone="+36201111111" name="Owner" role="admin" book="alarm"
users add_user phone="+36202222222" name="Cleaner" role="user" valid_from="2025-01-01T08:00" expires="2025-12-31T17:00" book="alarm"
```

**Owner can (via SMS):**
- `arm`, `arm night`, `disarm`, `status`
- `bypass window_kitchen`
- `auto_arm 3600 night`

**Cleaner can (via SMS):**
- `arm`, `disarm`, `status`
- Cannot: `bypass`, `auto_arm`
- Access only valid 08:00-17:00 (outside hours → ignored)

---

### Scenario 9: Shelly Door Sensor (non-Zigbee)

**Situation**: Shelly door sensor that publishes simple string payloads.

```
Topic: shellies/door1/sensor/state
Payload: "open" or "close"
```

```commandline
alarm_system add_zone name="back_door" type="delayed" group="perimeter"
alarm_system add_watch topic="shellies/door1/sensor/state" zone="back_door" trigger_value="open" reset_value="close"
alarm_system supervise name="back_door" timeout=300
```

---

### Scenario 10: Checking What Happened (Event Log + Alarm Memory)

**After an alarm event:**

```commandline
# What zones caused the alarm?
alarm_system alarm_memory
# → ["front_door", "motion_hallway"]

# Full event history
alarm_system event_log count=10
# → [
#   {"ts": 1706000000, "event": "arm", "data": {"mode": "full"}},
#   {"ts": 1706003600, "event": "zone_trigger", "data": {"zone": "front_door", "type": "delayed", "result": "entry_delay"}},
#   {"ts": 1706003615, "event": "alarm", "data": {"zone": "front_door", "type": "delayed"}},
#   {"ts": 1706003620, "event": "alarm", "data": {"zone": "motion_hallway", "type": "instant"}},
#   {"ts": 1706004000, "event": "disarm", "data": {"from_state": "ALARM"}}
# ]

# Current system status
alarm_system status
# → {
#   "state": "DISARMED",
#   "arm_mode": null,
#   "zones": {...},
#   "open_zones": [],
#   "alarm_memory": ["front_door", "motion_hallway"],
#   "bypassed": [],
#   "trouble": []
# }
```

---

## Configuration Reference

### alarm_config.json (full example)

```json
{
    "exit_delay": 30,
    "entry_delay": 15,
    "interval": 50,
    "max_log_entries": 100,
    "phonebook": "alarm_users.json",
    "sensors": [
        {"name": "front_door", "pin": 19, "type": "delayed", "group": "perimeter"},
        {"name": "tamper", "pin": 20, "type": "24h", "group": "always"}
    ],
    "zones": [
        {"name": "window_kitchen", "type": "instant", "group": "perimeter", "supervision": 600},
        {"name": "window_bedroom", "type": "instant", "group": "perimeter", "supervision": 600},
        {"name": "motion_hallway", "type": "instant", "group": "interior"},
        {"name": "pir_1", "type": "cross", "group": "interior", "cross_pair": "pir_2", "cross_window": 30},
        {"name": "pir_2", "type": "cross", "group": "interior", "cross_pair": "pir_1", "cross_window": 30}
    ],
    "watches": [
        {"topic": "zigbee2mqtt/window_kitchen", "zone": "window_kitchen", "trigger_field": "contact", "trigger_value": false, "reset_value": true},
        {"topic": "zigbee2mqtt/window_bedroom", "zone": "window_bedroom", "trigger_field": "contact", "trigger_value": false, "reset_value": true},
        {"topic": "zigbee2mqtt/motion_hallway", "zone": "motion_hallway", "trigger_field": "occupancy", "trigger_value": true, "reset_value": false},
        {"topic": "zigbee2mqtt/pir_1", "zone": "pir_1", "trigger_field": "occupancy", "trigger_value": true},
        {"topic": "zigbee2mqtt/pir_2", "zone": "pir_2", "trigger_field": "occupancy", "trigger_value": true}
    ]
}
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `exit_delay` | 30 | Seconds to leave after arming |
| `entry_delay` | 15 | Seconds to disarm after delayed zone triggers |
| `interval` | 50 | Sensor polling interval in ms |
| `max_log_entries` | 100 | Max event log entries (circular buffer) |
| `phonebook` | `alarm_users.json` | Phonebook file for SMS authorization |

---

## SMS Command Reference

| Command | admin | user | Response |
|---------|-------|------|----------|
| `arm` / `arm full` | ✓ | ✓ | Arms in full mode |
| `arm night` | ✓ | ✓ | Arms in night mode |
| `disarm` | ✓ | ✓ | Disarms the system |
| `status` | ✓ | ✓ | SMS reply with state |
| `bypass <zone>` | ✓ | ✗ | Bypass a zone |
| `unbypass <zone>` | ✓ | ✗ | Remove bypass |
| `auto_arm <sec> [mode]` | ✓ | ✗ | Configure auto-arm |

---

## Troubleshooting

### "Cannot arm: open zones: window_kitchen"
The window is open. Options:
1. Close the window, then arm
2. `alarm_system bypass name="window_kitchen"` then arm
3. `alarm_system arm mode="full" force=True` (zone still monitored)

### "Cannot arm: tamper zone open: tamper"
A tamper switch is triggered. This cannot be bypassed or forced. Fix the physical tamper issue first.

### "Cannot arm: trouble zones: window_kitchen"
The sensor hasn't reported in a while (supervision timeout). Options:
1. Check the sensor (battery? Zigbee connection?)
2. `alarm_system arm mode="full" force=True` (overrides trouble)

### Zone triggers but no alarm
Check:
- Is the system armed? (`alarm_system status`)
- Is the zone's group active in the current arm mode? (interior ignored in night mode)
- Is the zone bypassed? (`status` shows bypassed list)

### SMS commands not working
Check:
- Is the phone number in the phonebook? (`users get_all_users book="alarm"`)
- Is the user status "A"? (not "B" blocked)
- Is the user within valid_from/expires window?
- Is SIM800 module loaded?

---

## MQTT Integration with Home Assistant

### Arm/disarm from HA

```yaml
# configuration.yaml
mqtt:
  alarm_control_panel:
    - name: "House Alarm"
      state_topic: "devfid/alarm/state"
      command_topic: "devfid/alarm_system/arm"
      payload_arm_away: '{"mode": "full"}'
      payload_arm_night: '{"mode": "night"}'
      payload_disarm: '{}'
      value_template: "{{ value_json.state }}"
```

### Sensor states in HA

```yaml
mqtt:
  sensor:
    - name: "Alarm State"
      state_topic: "devfid/alarm/state"
      value_template: "{{ value_json.state }}"
    - name: "Alarm Mode"
      state_topic: "devfid/alarm/state"
      value_template: "{{ value_json.mode }}"
```

### Automation: notify on alarm

```yaml
automation:
  - alias: "Alarm notification"
    trigger:
      - platform: mqtt
        topic: "devfid/alarm/state"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.state == 'ALARM' }}"
    action:
      - service: notify.mobile_app
        data:
          message: "ALARM triggered!"
```
