# micrOS Application: async\_oledui

Short description about the application...

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

### **load** function - load the app into memory

```commandline
oledui load
```

### features

```commandline
oledui control cmd=<prev,press,next,on,off>
oledui cursor x y
oledui popup msg='text'
oledui cancel_popup
oledui genpage cmd='system clock'
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#oledui)

## Dependencies

```
LM_system
LM_oled
LM_oled_sh1106

LM_trackball
LM_haptic
LM_gameOfLife
LM_esp32
```
