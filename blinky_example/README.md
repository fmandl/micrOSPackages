# micrOS Application: blinky\_example

Short description about the application...

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
