# micrOS Application: neopixel\_matrix

NeoPixel Matrix (micrOS Package)
A lightweight micrOS package that adds X–Y addressable control and web-based
interaction to NeoPixel LED matrices. It provides pixel-level drawing, brightness control,
colormap import/export, and built-in animations (rainbow, snake, spiral, noise),
all accessible through micrOS’s auto-generated web UI and API endpoints—ideal for
quick IoT dashboards and creative LED projects.

## Installation

```
pacman install "github:BxNxM/micrOSPackages/neopixel_matrix"
```

> Everything will be installed under `/lib/neopixel_matrix/*` and `/modules/LM_*`

## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## micrOS Project

[Project Docs](https://github.com/BxNxM/micrOS/tree/master)
[Coding Docs](https://github.com/BxNxM/micrOS/blob/master/APPLICATION_GUIDE.md)

## Usage

### **load** function - load the app into memory

Start with **default** parameters:

```commandline
neomatrix load 
```

```commandline
neomatrix load width=8 height=8 neop=14 i2c_sda=11 i2c_scl=12
```

> Customization parameters

### **do** function - run example function

```commandline
 pixel x y color=(10, 3, 0) show=True
 clear
 color_fill r=<0-255-5> g=<0-255-5> b=<0-255-5>
 brightness br=<0-60-2>
 stop
 snake speed_ms=50 length=5
 rainbow
 spiral speed_ms=40
 noise speed_ms=85
 control speed_ms=<1-200> bt_draw=None
 draw_colormap bitmap=[(0,0,(10,2,0)),(x,y,color),...]
 get_colormap
 status
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#neomatrix)


## Dependencies

n/a
