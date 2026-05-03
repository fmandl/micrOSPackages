# micrOS Application: sim800

SIM800C GSM modem interface for micrOS devices. Provides voice call handling, SMS send/receive (PDU mode with multipart support), USSD queries, signal monitoring, event-driven subscriber system, and SMS notification integration with the micrOS Notify framework.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/sim800"
```

```bash
pacman upgrade "sim800"
pacman uninstall "sim800"
```

## Package Structure

```
sim800/package/
├── __init__.py       # Package loader
├── LM_sim800.py      # micrOS shell interface
├── modem.py          # Sim800 class: UART, AT commands, SMS, calls, USSD
├── codec.py          # GSM7/UCS2/PDU encode/decode
└── notify.py         # SMS Notify subscriber
```

| File | Responsibility |
|------|---------------|
| `LM_sim800.py` | Thin micrOS command interface, event system, load/reset |
| `modem.py` | Hardware communication (UART/AT), SMS queue, call/USSD |
| `codec.py` | Pure data transforms — GSM7, UCS2, PDU build/parse |
| `notify.py` | Notify subscriber — sends SMS only when explicitly requested |

## Hardware

- **Module**: SIM800C (or compatible SIM800L/SIM800)
- **Interface**: UART (default TX=16, RX=17)
- **RI pin**: GPIO 23 (Ring Indicator for interrupt-driven data reading)
- **Tested on**: Seeed Studio ESP32-C6

## Pin Configuration

| Function | Default GPIO | Description |
|----------|-------------|-------------|
| TX | 16 | UART TX to SIM800 RX |
| RX | 17 | UART RX from SIM800 TX |
| RI | 23 | Ring Indicator (falling edge interrupt) |

## Usage

```commandline
sim800 load pin_code=1234 tx_pin=16 rx_pin=17 ri_pin=23 notify_numbers="+36201234567,+36207654321"
sim800 set_notify_numbers numbers="+36201234567,+36207654321"
sim800 subscribe event_type="call" callback=<func>
sim800 unsubscribe event_type="call" callback=<func>
sim800 reset
sim800 reject_call busy=False
sim800 is_connected
sim800 get_signal_quality
sim800 get_network_info
sim800 read_uart
sim800 make_call number="+36201234567" ring_time=15
sim800 send_sms number="+36201234567" text="Hello"
sim800 send_ussd code="*102#"
sim800 get_balance code="*102#"
sim800 send_command "AT+CPIN?" timeout=1000
sim800 clear_sms target="ALL"
sim800 get_sms target="ALL"
sim800 pinmap
```

## SMS Notify Integration

The sim800 package registers as a Notify subscriber on `load()`. SMS is **only sent when explicitly requested** — it does NOT fire on every `Notify.notify()` call.

### Trigger SMS notification

```python
from Notify import Notify

# Send to default numbers (set at load or via set_notify_numbers)
Notify.notify("ALARM: door opened!", channels="SMS")

# Send to specific number
Notify.notify("ALARM!", sms_to="+36201234567")

# Send to multiple specific numbers
Notify.notify("ALARM!", sms_to=["+36201234567", "+36307654321"])

# SMS + Telegram together
Notify.notify("ALARM!", channels=("SMS", "Telegram"))

# SMS to specific number + Telegram
Notify.notify("ALARM!", sms_to="+36209999999", channels=("SMS", "Telegram"))

# Without channels or sms_to → only Telegram + MQTT, NO SMS
Notify.notify("debug info")
```

### When does SMS send?

| Call | SMS sent? |
|------|-----------|
| `Notify.notify("text")` | ❌ No |
| `Notify.notify("text", channels="SMS")` | ✅ Yes (default numbers) |
| `Notify.notify("text", sms_to="+36...")` | ✅ Yes (specified number) |
| `Notify.notify("text", channels=("SMS", "Telegram"))` | ✅ Yes |
| `Notify.notify("text", channels="Telegram")` | ❌ No |

## Event Subscriber System

Subscribe to modem events with callbacks:

```python
import LM_sim800 as sim

def on_call(call_params):
    print(f"Incoming call from {call_params['caller_number']}")

def on_sms(sms):
    print(f"SMS from {sms['sender']}: {sms['text']}")

sim.load(pin_code=1234)
sim.subscribe('call', on_call)
sim.subscribe('sms', on_sms)
```

### Event types

| Event | Callback signature | Description |
|-------|-------------------|-------------|
| `call` | `callback(call_params_dict)` | Incoming call with CLIP data |
| `sms` | `callback(sms_dict)` | Received SMS (auto-reassembled multipart) |
| `signal` | `callback(uart_lines_list)` | Unhandled UART messages |

## Features

- **RI interrupt-driven**: No polling — reads UART only when SIM800 signals data via RI pin
- **PDU mode SMS**: Full GSM7, UCS2, and 8-bit encoding/decoding
- **Multipart SMS**: Automatic reassembly of concatenated messages (8-bit and 16-bit references)
- **Hungarian GSM7 post-processing**: Corrects carrier-specific character substitutions (à→á, ò→ó, ù→ú)
- **Async SMS queue**: Messages sent sequentially without blocking
- **USSD support**: Balance queries with UCS2 and GSM7 decoding
- **Notify integration**: SMS as explicit-only notification channel

## Tests

```bash
cd sim800
python3 -m pytest tests/test_sim800.py -v
```

## Author

Flórián Mandl ([@fmandl](https://github.com/fmandl))
