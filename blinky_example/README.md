# micrOS Application: blinky\_example

LM_Blinky is a simple micrOS load module that provides basic,
remote-controllable LED management for MicroPython devices.
It lets users initialize a GPIO pin and turn an LED on, off, toggle its state,
or run timed blink sequences through the micrOS shell or web interface,
making it ideal for hardware testing, demos, and quick feedback in embedded projects.

## Installation

```
pacman install "github:BxNxM/micrOSPackages/blinky_example"
```

> Uninstall:

```
pacman uninstall "blinky_example"
```

> Everything will be installed under `/lib/blinky_example/*` and `/modules/LM_*`

## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## Usage

### **load** function - load the app into memory

```commandline
blinky load
```

### **Commands** function - run example function

```commandline
blinky load pin_number=26
blinky on,
blinky off
blinky toggle
blinky blink count=10 delay_ms=200
```

## Dependencies

n/a
