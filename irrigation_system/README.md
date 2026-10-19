![irrigation illustration](./media/irrigation.png?raw=true)

# micrOS Package: irrigation\_system - WIP (beta)

Architecture-first skeleton for a water-only garden irrigation dashboard.

The public load module is `aqua`. This first version does not drive real
hardware yet; it provides the package shape, web UI, dummy API endpoints, and
the core tank/flow/head calculations that the real pump and sensor logic can
replace later.

## Install

```bash
pacman install "github:BxNxM/micrOSPackages/irrigation_system"
```

```bash
pacman upgrade "irrigation_system"
pacman uninstall "irrigation_system"
```

## Device Layout

- Load module: `/modules/LM_aqua.py`
- Package metadata: `/lib/irrigation_system/pacman.json`
- Web UI: `/web/irrigation_system/aqua.html`

## Usage

```commandline
aqua load
aqua status
aqua configure tank_width_cm=40 tank_depth_cm=25 tank_height_cm=20 water_distance_cm=7 min_level_cm=2 level_module=manual pump_l_hour=300 head_count=4 soil_sensor_count=4
aqua configure level_module=rcwl1670
aqua pinmap
aqua sensor_distance
aqua plan volume_l=1
aqua plan per_head_l=0.25
aqua water volume_l=1
aqua start
task show aqua._watering_task
aqua stop
```

Open the dashboard after `aqua load`:

```text
http://<device>/aqua
```

## Skeleton API

The dashboard uses the shared micrOS `uapi.js` helper, which calls load-module
commands through `/rest`.

- `GET /rest/aqua/status/measure=True` returns the dummy dashboard state.
- `GET /rest/aqua/water/volume_l=1` starts a watering run.
- `GET /rest/aqua/start` starts the pump manually.
- `GET /rest/aqua/stop` stops watering.
- `GET /aqua/settings` returns the current dashboard config for sync.
- `POST /aqua/settings` accepts `{"config": {...}}` to update configuration fields.

The current model includes:

- tank dimensions and top-to-water distance measurement
- ultrasonic distance sensor integration through the `ultrasonic_distance` package
- default no-sensor/manual mode with `water_distance_cm` test input
- selectable real level modules: `rcwl1670` or `hcsr04`
- water-level distance pins exposed as shared `dist_trig` / `dist_echo` GPIOs
- minimum reserve height in cm
- pump flow in L/h
- real pump GPIO output on `pump_pin` with high/low control
- configurable number of irrigation heads
- configurable number of soil moisture sensors
- short-lived `aqua._watering_task` with `task.out` progress while watering
- calculated tank capacity, water height, current volume, usable volume, per-head flow, and run plan

## Dependencies

```text
ultrasonic_distance
```
