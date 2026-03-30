# micrOS Application: neopixel_matrix

NeoPixel matrix package with pixel addressing, brightness control, animation helpers, and a small web drawing UI.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/neopixel_matrix"
pacman upgrade "neopixel_matrix"
pacman uninstall "neopixel_matrix"
```

## Device Layout

- Package files: `/lib/neopixel_matrix`
- Load module: `/modules/LM_neomatrix.py`
- Web asset: `/web/matrix_draw.html`

## Usage

```commandline
neomatrix load width=8 height=8 neop=14 i2c_sda=11 i2c_scl=12
pixel x y color=(10, 3, 0) show=True
clear
color_fill r=<0-255-5> g=<0-255-5> b=<0-255-5>
brightness br=<0-100>
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

## Dependencies

n/a
