# micrOS Application: blinky/_example

Minimal micrOS example package for controlling a single LED from the shell or web UI.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/blinky_example"
```

```bash
pacman upgrade "blinky_example"
pacman uninstall "blinky_example"
```

## Device Layout

- Package files: `/lib/blinky_example`
- Load module: `/modules/LM_blinky.py`

## Usage

```commandline
blinky load pin_number=26
blinky on
blinky off
blinky toggle
blinky blink count=10 delay_ms=200
```

> Blink every 100ms with Task

```commandline
blinky toggle &&100
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#blinky)

## Dependencies

Dependencies are auto installed by `mip` based on `package.json`

```text
n/a
```
