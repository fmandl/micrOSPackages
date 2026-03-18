# micrOS Application: keychaindemo

Short description about the application...

## Installation

```
pacman install "github:BxNxM/micrOSPackages/keychaindemo"
```

> Uninstall:

```
pacman uninstall "<package-name>"
```

> Everything will be installed under `/lib/keychaindemo/*` and `/modules/LM_*`

## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## micrOS Project

[Project Docs](https://github.com/BxNxM/micrOS/tree/master)
[Coding Docs](https://github.com/BxNxM/micrOS/blob/master/micrOS/MODULE_GUIDE.md)

## Usage

### **load** function - load the app into memory

```commandline
keychain load
```

### **do** function - run example function

```commandline
keychain do
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html)

## Dependencies

```commandline
LM_oled
LM_ds18
LM_system

LM_gameOfLife
```
