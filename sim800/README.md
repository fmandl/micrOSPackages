# micrOS Application: sim800

SIM800C GSM modem interface for micrOS devices. Provides voice call handling, SMS send/receive (PDU mode with multipart support), USSD queries, signal monitoring, and an event-driven subscriber system with RI (Ring Indicator) interrupt-based UART reading.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/sim800"
```

```bash
pacman upgrade "sim800"
pacman uninstall "sim800"
```

## Device Layout

- Package files: `/lib/sim800`
- Load module: `/modules/LM_sim800.py`

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
sim800 load pin_code=1234 tx_pin=16 rx_pin=17 ri_pin=23
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

## Tests

```bash
cd sim800
python3 -m pytest tests/test_sim800.py -v
```
