# micrOS Application: async_oledui

Async OLED UI framework for micrOS. It provides page rendering, cursor control, popups, and trackball-driven navigation for SSD1306 and SH1106 displays.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/async_oledui"
```

```bash
pacman upgrade "async_oledui"
pacman uninstall "async_oledui"
```

## Device Layout

- Package files: `/lib/async_oledui`
- Load module: `/modules/LM_oledui.py`

## Usage

```commandline
oledui load
oledui load width=128 height=64 oled_type='sh1106' control='trackball' poweroff=None haptic=False
oledui control cmd="<prev,press,next,on,off>"
oledui cursor x y
oledui popup msg='text'
oledui cancel_popup
oledui genpage cmd='system clock'
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#oledui)

## Dependency

Dependencies are auto installed by `mip` based on `package.json`

### built-ins

```text
LM_system
LM_oled / LM_oled_sh1106
LM_trackball
LM_haptic
LM_gameOfLife
LM_esp32
```
