"""
Aqua irrigation load module for micrOS.

Public command + web endpoint glue only. Run lifecycle lives in
irrigation_system.state_machine (IDLE/RUNNING/PAUSED), pump + watcher task in
irrigation_system.actuators (PumpController), calculations in
irrigation_system.monitoring.

Public run commands: start / pause / resume / stop / status
(the legacy `water` command has been replaced by `start`).
"""

try:
    import ujson as json
except Exception:
    import json

from Common import web_endpoint
from microIO import pinmap_search
from Types import resolve
from irrigation_system import actuators, monitoring, state_machine, status_led, button as button_mod, scheduler_cfg


# --- module-level state machine wiring (singleton) ---
_CTRL = None
_FSM = None
_LED = None
_BTN = None


def _fsm():
    """Lazily build and wire the PumpController <-> AquaStateMachine (+ StatusLed + Button)."""
    global _CTRL, _FSM, _LED, _BTN
    if _FSM is None:
        _CTRL = actuators.PumpController(monitoring.CONFIG)
        _LED = status_led.StatusLed(monitoring.CONFIG)
        _FSM = state_machine.AquaStateMachine(_CTRL, led=_LED)
        _CTRL.bind_state_machine(_FSM)
        _BTN = button_mod.Button(state_machine=_FSM, config=monitoring.CONFIG)
    return _FSM


def _json(data):
    return "application/json", json.dumps(data)


def _settings_get(*_):
    return _json(status())


def _settings_post(_, body):
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception as e:
        return _json({"state": False, "error": "invalid_json", "detail": str(e)})

    config = payload.get("config", payload) if isinstance(payload, dict) else {}
    if not isinstance(config, dict):
        return _json({"state": False, "error": "invalid_config"})
    return _json(configure(**config))


def _register_web():
    web_endpoint("aqua", "irrigation_system/aqua.html")
    web_endpoint("aqua/settings", _settings_get)
    web_endpoint("aqua/settings", _settings_post, "POST")
    return True


def _dashboard_state(measure=False):
    monitor = monitoring.status(measure=measure)
    pump = actuators.status()
    snap = _fsm().snapshot()
    runtime = dict(pump["runtime"])
    runtime["last_level"] = monitor["level_sensor"]
    return {
        "state": snap["state"],            # IDLE | RUNNING | PAUSED
        "pump_on": pump["pump_on"],
        "run": snap["run"],                # active/last run plan (mode, elapsed, duration, ...)
        "fault": snap["fault"],            # {"reason": "low_water", ...} or None
        "now": _node_clock(),              # node local clock (what the scheduler works against)
        "config": monitor["config"],
        "tank": monitor["tank"],
        "flow": monitor["flow"],
        "soil": monitor["soil"],
        "ready": monitor["ready"],
        "runtime": runtime,
        "level_sensor": monitor["level_sensor"],
        "task": pump["task"],
        "endpoints": {
            "ui": "/aqua",
            "api": "/rest/aqua",
            "settings": "/aqua/settings",
        },
    }


def load(web=True, pump_pin=None):
    """
    Register the Aqua dashboard, book the pump pin, and restore run state.
    """
    if web:
        _register_web()
    # Restore persisted configuration from /data (tank sizes, level_module, pins, ...)
    # BEFORE building the controller/sensors, so pin binding uses the saved values.
    monitoring.load_config()
    # (Re)build the state machine; its constructor restores a persisted run
    # (timed -> PAUSED, manual -> IDLE) per the reboot-safety policy.
    global _CTRL, _FSM, _LED, _BTN
    _CTRL = actuators.PumpController(monitoring.CONFIG)
    _LED = status_led.StatusLed(monitoring.CONFIG)
    try:
        actuators.load(monitoring.CONFIG, pump_pin=pump_pin)
    except Exception as e:
        _FSM = state_machine.AquaStateMachine(_CTRL, led=_LED)
        _CTRL.bind_state_machine(_FSM)
        _wire_button()
        if not web:
            raise
        return "Aqua irrigation system loaded. Pump init failed: {}. UI: /aqua API: /rest/aqua Settings: /aqua/settings".format(e)
    _FSM = state_machine.AquaStateMachine(_CTRL, led=_LED)
    _CTRL.bind_state_machine(_FSM)
    _wire_button()
    return "Aqua irrigation system loaded. UI: /aqua API: /rest/aqua Settings: /aqua/settings"


def _wire_button():
    """Create and attach the physical button IRQ (best-effort)."""
    global _BTN
    _BTN = button_mod.Button(state_machine=_FSM, config=monitoring.CONFIG)
    try:
        _BTN.load()
    except Exception:
        pass


def configure(tank_width_cm=None, tank_depth_cm=None, tank_height_cm=None,
              water_distance_cm=None, min_level_cm=None, pump_l_hour=None,
              soil_sensor_count=None, pump_pin=None, heads=None,
              tank_mode=None, tank_calibration=None,
              level_module=None, checkpoint_interval_s=None, max_runtime_s=None,
              led_pin=None, led_count=None, led_brightness=None, led_blink_ms=None,
              btn_pin=None, btn_long_ms=None, btn_debounce_ms=None, **_):
    """
    Update dashboard configuration values.
    """
    was_manual = monitoring.is_manual_level_module()
    monitoring.update_config({
        "tank_width_cm": tank_width_cm,
        "tank_depth_cm": tank_depth_cm,
        "tank_height_cm": tank_height_cm,
        "tank_mode": tank_mode,
        "tank_calibration": tank_calibration,
        "water_distance_cm": water_distance_cm,
        "min_level_cm": min_level_cm,
        "pump_l_hour": pump_l_hour,
        "soil_sensor_count": soil_sensor_count,
        "pump_pin": pump_pin,
        "heads": heads,
        "level_module": level_module,
        "checkpoint_interval_s": checkpoint_interval_s,
        "max_runtime_s": max_runtime_s,
        "led_pin": led_pin,
        "led_count": led_count,
        "led_brightness": led_brightness,
        "led_blink_ms": led_blink_ms,
        "btn_pin": btn_pin,
        "btn_long_ms": btn_long_ms,
        "btn_debounce_ms": btn_debounce_ms,
    })
    monitoring.configure_level(was_manual, water_distance_cm=water_distance_cm)
    try:
        actuators.load(monitoring.CONFIG, pump_pin=pump_pin)
    except Exception:
        actuators.set_last_action("configure_pump_failed")
        return status()
    actuators.set_last_action("configure")
    return status()


def tank():
    """
    Return tank level and volume.
    """
    return monitoring.tank()


def flow():
    """
    Return pump and irrigation-head flow calculations.
    """
    return monitoring.flow()


def pinmap():
    """
    Shows logical pins used by this Load Module.
    """
    pins = actuators.pinmap(monitoring.CONFIG)
    if not monitoring.is_manual_level_module():
        pins.update(pinmap_search(["dist_trig", "dist_echo"]))
    return pins


def soil():
    """
    Return soil moisture sensor readings.
    """
    return monitoring.soil()


def plan(volume_l=None, per_head_l=None):
    """
    Preview a watering run from total or per-head volume.
    """
    return monitoring.plan(volume_l=volume_l, per_head_l=per_head_l)


def ready(volume_l=None):
    """
    Return readiness based on tank level and requested volume.
    """
    return monitoring.ready(required_l=volume_l)


# ---- run lifecycle (state machine) ----

def start(volume_l=None, per_head_l=None, max_runtime_s=0, **_):
    """
    Start a run from IDLE.
    - timed: pass volume_l or per_head_l -> auto-stops when the volume is dispensed.
    - manual: no volume -> runs until pause/stop (max_runtime_s=0 means infinite;
      >0 sets a safety hard cap in seconds).
    """
    return _fsm().transition("start", volume_l=volume_l, per_head_l=per_head_l,
                             max_runtime_s=max_runtime_s)


def pause():
    """
    Pause an active run: pump off, remaining state saved, watcher task killed.
    """
    return _fsm().transition("pause")


def resume():
    """
    Resume a paused run with the saved remaining time (re-checks water level).
    """
    return _fsm().transition("resume")


def stop():
    """
    Stop: pump off, watcher task killed, saved run state cleared.
    """
    return _fsm().transition("stop")


# ---- scheduling (built-in Scheduler via crontasks; timed runs only) ----

def _node_clock():
    """Node local time as {'iso','hour','minute','second','weekday'} (best-effort).

    weekday: 0=Mon..6=Sun (same convention as the scheduler weekday field).
    """
    try:
        from time import localtime
        t = localtime()                 # (year, month, mday, hour, minute, second, weekday, yearday)
        return {
            "iso": "%04d-%02d-%02d %02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5]),
            "hour": t[3], "minute": t[4], "second": t[5], "weekday": t[6],
        }
    except Exception:
        return None


def _ensure_cron():
    """Make sure the built-in cron (Timer1) runs against the current crontasks.

    The micrOS scheduler Timer1 is normally created only at boot, and only if
    `crontasks != 'n/a'` at that moment. So a schedule added at runtime would not
    fire until the next reboot. We fix that by:
      1) turning the `cron` config flag on (persistent), and
      2) (re)initialising the cron timer now via Interrupts.enableCron().
    Best-effort: never raises (e.g. on the CPython test host where machine/
    Interrupts are unavailable). Returns True if the timer was (re)armed.
    """
    try:
        from Config import cfgget, cfgput
        if not cfgget("cron"):
            cfgput("cron", True)                 # persist so it also survives reboots
        if str(cfgget("crontasks")).lower() == "n/a":
            return False                         # nothing to run; timer stays as-is
        from Interrupts import enableCron        # idempotent: Timer(1).init re-arms
        enableCron()
        return True
    except Exception:
        return False


def schedule_list():
    """
    List irrigation schedules parsed from the node's crontasks.
    Each: {id, days, hour, minute, volume_l, timestamp}. Only `aqua start`
    (timed) blocks are shown; other crontasks are ignored here.
    `now` carries the node's local clock so the UI can show what the scheduler
    works against.
    """
    return {"schedules": scheduler_cfg.list_schedules(), "now": _node_clock(),
            "cron_enabled": _cron_enabled()}


def _cron_enabled():
    """Whether the built-in cron flag is on (scheduler can run). Best-effort."""
    try:
        from Config import cfgget
        return bool(cfgget("cron"))
    except Exception:
        return None


def schedule_add(days="*", hour=6, minute=0, volume_l=1):
    """
    Add a timed irrigation schedule.
    - days: '*' (every day), a single 0..6 (0=Mon), or a range like '0-4'
    - hour/minute: time of day; volume_l: Total litres to dispense
    Writes the crontasks config (persistent); the built-in Scheduler runs it.
    Future: sun-tag timestamps (sunrise/sunset+/-min) and manual/time-capped runs.
    """
    new_cron = scheduler_cfg.add_schedule(days=days, hour=hour, minute=minute, volume_l=volume_l)
    ok = scheduler_cfg.set_crontasks(new_cron)
    armed = _ensure_cron()
    return {"state": bool(ok), "crontasks": new_cron, "cron_armed": armed,
            "schedules": scheduler_cfg.list_schedules(new_cron)}


def schedule_remove(index=0):
    """
    Remove the Nth irrigation schedule (0-based over irrigation blocks only).
    Other crontasks are left untouched.
    """
    new_cron = scheduler_cfg.remove_schedule(int(index))
    ok = scheduler_cfg.set_crontasks(new_cron)
    armed = _ensure_cron()
    return {"state": bool(ok), "crontasks": new_cron, "cron_armed": armed,
            "schedules": scheduler_cfg.list_schedules(new_cron)}


def sensor_distance(module=None):
    """
    Read top-to-water distance from the configured ultrasonic distance module.
    """
    return monitoring.sensor_distance(module=module)


def set_level(distance_cm=None, distance_mm=None, measure=False, module=None, clear=False, **_):
    """
    Update top-to-water distance in manual mode or by sensor measurement.
    """
    result = monitoring.set_level(
        distance_cm=distance_cm,
        distance_mm=distance_mm,
        measure=measure,
        module=module,
        clear=clear,
    )
    if isinstance(result, dict) and result.get("state") is False and result.get("source") != "manual":
        actuators.set_last_action("set_level_failed")
        return result
    actuators.set_last_action("set_level")
    return result


def status(measure=False):
    """
    Return the complete dashboard state (FSM state, run, fault, tank, etc.).
    """
    return _dashboard_state(measure=measure)


def help(widgets=False):
    """
    micrOS LM help.
    """
    return resolve((
        "load web=True pump_pin=None",
        "status",
        "tank",
        "flow",
        "pinmap",
        "soil",
        "sensor_distance module=None",
        "plan volume_l=1 per_head_l=None",
        "start volume_l=None per_head_l=None max_runtime_s=0",
        "BUTTON pause",
        "BUTTON resume",
        "BUTTON stop",
        "configure tank_width_cm=40 tank_depth_cm=25 tank_height_cm=20 water_distance_cm=7 min_level_cm=2 level_module=manual pump_l_hour=300 soil_sensor_count=4 pump_pin=3 checkpoint_interval_s=0 max_runtime_s=0 led_pin=6 led_count=1 led_brightness=100 led_blink_ms=400 btn_pin=45 btn_long_ms=1500 btn_debounce_ms=50",
        "set_level distance_cm=7 distance_mm=None measure=False module=None clear=False",
        "ready volume_l=None",
        "schedule_list",
        "schedule_add days=* hour=6 minute=0 volume_l=1",
        "schedule_remove index=0",
    ), widgets=widgets)
