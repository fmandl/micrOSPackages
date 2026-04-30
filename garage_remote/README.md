# micrOS Application: garage_remote

Smart garage remote control for micrOS devices. Controls a garage door opener and alarm system via optocoupler-driven RF remote (Mitto BFT2), triggered by phone calls and SMS commands. Authorized callers can open the garage door, while SMS commands control the alarm system with timed sessions.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/garage_remote"
```

```bash
pacman upgrade "garage_remote"
pacman uninstall "garage_remote"
```

## Device Layout

- Package files: `/lib/garage_remote`
- Load module: `/modules/LM_garage.py`

## Hardware

- **MCU**: Seeed Studio ESP32-C6
- **Remote**: Mitto BFT2 (2-channel RF remote)
- **Interface**: 2-channel optocoupler driving remote buttons
- **Channel 1**: Garage door open/close
- **Channel 2**: Alarm system temporary disable

## Pin Configuration

| Function | Default GPIO | Description |
|----------|-------------|-------------|
| relay.door | 18 | Optocoupler channel 1 — garage door button |
| relay.alarm | 20 | Optocoupler channel 2 — alarm disable button |

## Usage

```commandline
garage load pin_code=1234
garage unload
garage open_garage
garage press_alarm_button
garage garage_alarm_off minutes=10
garage garage_alarm_off minutes=10 phone="+36201234567"
garage garage_alarm_on
garage garage_alarm_on phone="+36201234567"
```

## Call-based Garage Door Control

An authorized caller (status "A" in phone_manager) can open the garage door by calling the device. The call is automatically rejected and the door opens.

## SMS-based Alarm Control

| Command | Description |
|---------|-------------|
| `alarm off <minutes>` | Disable alarm for N minutes (max 30, min 7) |
| `alarm on` | Re-enable alarm immediately |
| `cmd: <command>` | Execute micrOS command (admin only) |

## Alarm Session Logic

The physical alarm remote disables the alarm for exactly 7 minutes (chunk time) per button press. For longer durations, the system automatically re-presses the button at chunk boundaries:

- **7 min request**: 1 press at start, alarm reactivates after 7 min
- **15 min request**: press at 0 min, re-press at ~1 min (remainder), re-press at ~8 min
- **30 min request**: press at start, then re-press at each 7-min chunk boundary

The observer checks every 10 seconds and presses the button when `remaining % chunk_time` approaches 0.

## Dependencies

Dependencies are auto-installed by `mip` based on `package.json`:

```text
github:BxNxM/micrOSPackages/sim800
github:BxNxM/micrOSPackages/phone_manager
```

## Tests

```bash
cd garage_remote
python3 -m pytest tests/test_garage.py -v
```
