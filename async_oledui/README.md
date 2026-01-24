# micrOS Application: async\_oledui

micrOS Multitask OLED UI is a lightweight, asynchronous user interface framework for
MicroPython-based devices that turns small OLED screens into fully interactive,
multi-page dashboards. It enables dynamic page generation, real-time system monitoring,
and direct execution of load module commands using simple controls like a trackball
and optional haptic feedback, making embedded systems easier to explore,
manage, and interact with in real time.

## Installation

```
pacman install "github:BxNxM/micrOSPackages/async_oledui"
```

> Uninstall:

```
pacman uninstall "async_oledui"
```


> Everything will be installed under `/lib/async_oledui/*` and `/modules/LM_*`

## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## Usage

### **load** function - load and configure the application

```
oledui load
```

> Default values: width=128 height=64 oled_type="sh1106" control='trackball' poweroff=None haptic=False

Options:

```
oledui load width=128 height=64
            oled_type='sh1106/ssd1306'
            control='trackball'
            poweroff=None/sec
            haptic=False/True
```

> poweroff=None/sec: if sec set to integer like: 30, display will turn off after 30 sec,
> otherwise (None) display is always on.

### features

```commandline
oledui control cmd="<prev,press,next,on,off>"
oledui cursor x y
oledui popup msg='text'
oledui cancel_popup
oledui genpage cmd='system clock'
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#oledui)

## Dependencies

### micrOS built-ins:

```
LM_system
LM_oled
LM_oled_sh1106

LM_trackball
LM_haptic
LM_gameOfLife
LM_esp32
```

### External dependency:

```
n/a
```