# micrOS Application: keychaindemo

Compact demo package for an ESP32-C3 keychain device with OLED status display, DS18 temperature readout, screen saver logic, and NeoPixel control.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/keychaindemo"
```

```bash
pacman upgrade "keychaindemo"
pacman uninstall "keychaindemo"
```

## Device Layout

- Package files: `/lib/keychaindemo`
- Load module: `/modules/LM_keychain.py`

## Usage

```commandline
keychain load width=64 height=32 bootmsg="micrOS"
keychain display period=1000 tts=30
keychain temperature
keychain button
keychain display_toggle
keychain neopixel_toggle
keychain color_wheel br=20
keychain pinmap
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#keychain)

## Dependencies

Dependencies are auto installed by `mip` based on `package.json`

### built-ins

```text
LM_oled
LM_ds18
LM_system
LM_gameOfLife
```
